#!/usr/bin/env python3
"""Deterministic scheduler and AWS CLI adapter regression checks (no live AWS)."""
if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
import tempfile
import io
import shutil
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from model_design import markdown_for, stack_model

SPEC = importlib.util.spec_from_file_location("controller", Path(__file__).with_name("cloudformation-deploy.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
ROOT = Path(__file__).resolve().parents[2]
TARGET = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}


def units(*orders):
    return [{"name": chr(65 + i), "template": "app.yaml", "parameters": chr(97 + i) + ".json", "deployOrder": str(order)}
            for i, order in enumerate(orders)]


def states(units):
    return {unit["name"]: {"status": "NOT_STARTED"} for unit in units}


def rejects(call, text):
    try:
        call()
    except (ValueError, M.Blocked) as error:
        assert text in str(error), error
    else:
        raise AssertionError("accepted invalid input: " + text)


class Fake:
    def __init__(self, completions=None, blocked=()):
        self.events, self.running, self.peak = [], set(), 0
        self.completions = {key: list(values) for key, values in (completions or {}).items()}
        self.blocked = set(blocked)

    def prepare(self, unit, state):
        self.events.append(("prepare", unit["name"], unit["template"], unit["parameters"]))
        state["changeSetId"] = "cs-" + unit["name"]
        return "BLOCKED" if unit["name"] in self.blocked else "READY"

    def execute(self, unit, state):
        name = unit["name"]
        self.running.add(name)
        self.peak = max(self.peak, len(self.running))
        self.events.append(("start", name, state["changeSetId"]))

    def poll(self, unit, state):
        name = unit["name"]
        sequence = self.completions.get(name, ["CREATE_COMPLETE"])
        result = sequence.pop(0) if len(sequence) > 1 else sequence[0]
        if result in M.SUCCESS | M.FAILED:
            self.running.remove(name)
        self.events.append(("poll", name, result))
        return result


def starts(fake):
    return [event[1] for event in fake.events if event[0] == "start"]


def finish(units, limit, state, fake):
    for _ in range(10):
        outcome = M.run_group(units, limit, state, fake, sleep=lambda _: None)
        if outcome != "GROUP_COMPLETE":
            return outcome
    raise AssertionError("groups did not complete")


def check_scheduler():
    # Cases 1 and 4: order barrier, including an early A completion.
    scoped = units(10, 20, 30)
    state, fake = states(scoped), Fake()
    assert finish(scoped, 3, state, fake) == "COMPLETE"
    assert starts(fake) == ["A", "B", "C"]
    for previous, following in (("A", "B"), ("B", "C")):
        assert fake.events.index(("poll", previous, "CREATE_COMPLETE")) < next(i for i, e in enumerate(fake.events) if e[:2] == ("start", following))
    scoped = units(10, 10, 20)
    state, fake = states(scoped), Fake({"B": ["CREATE_IN_PROGRESS"] * 3 + ["CREATE_COMPLETE"]})
    assert M.run_group(scoped, 2, state, fake, sleep=lambda _: None) == "GROUP_COMPLETE"
    assert starts(fake) == ["A", "B"]
    assert state["C"]["status"] == "NOT_STARTED"
    assert finish(scoped, 2, state, fake) == "COMPLETE"
    assert fake.events.index(("poll", "B", "CREATE_COMPLETE")) < next(i for i, e in enumerate(fake.events) if e[:2] == ("start", "C"))
    # Cases 2 and 3: slot reuse before B finishes, no template deduplication.
    scoped = units(10, 10, 10)
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"],
                                        "B": ["CREATE_IN_PROGRESS"] * 4 + ["CREATE_COMPLETE"]})
    assert finish(scoped, 2, state, fake) == "COMPLETE"
    assert fake.peak == 2 and starts(fake) == ["A", "B", "C"]
    assert next(i for i, e in enumerate(fake.events) if e[:2] == ("start", "C")) < fake.events.index(("poll", "B", "CREATE_COMPLETE"))
    assert state["A"]["changeSetId"] != state["B"]["changeSetId"]
    assert ("prepare", "A", "app.yaml", "a.json") in fake.events
    assert ("prepare", "B", "app.yaml", "b.json") in fake.events
    # Case 5: detect failure while B runs, drain B, keep C/D unstarted.
    scoped = units(10, 10, 10, 20)
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "ROLLBACK_IN_PROGRESS", "ROLLBACK_COMPLETE"],
                                        "B": ["CREATE_IN_PROGRESS"] * 3 + ["CREATE_COMPLETE"]})
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert [s["status"] for s in state.values()] == ["FAILED", "SUCCESS", "NOT_STARTED", "NOT_STARTED"]
    assert starts(fake) == ["A", "B"] and not fake.running
    assert M.run_group(scoped, 2, state, fake) == "STOPPED"
    # Restart after a failure was saved but another execution was still running.
    state = states(scoped)
    state["A"]["status"], state["B"]["status"] = "FAILED", "RUNNING"
    fake = Fake({"B": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    fake.running = {"B"}
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert state["B"]["status"] == "SUCCESS" and not fake.running and not starts(fake)
    # A blocker during B preparation stops queueing and drains A.
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]}, blocked={"B"})
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert [s["status"] for s in state.values()] == ["SUCCESS", "BLOCKED", "NOT_STARTED", "NOT_STARTED"]
    assert starts(fake) == ["A"] and not fake.running
    # Read errors stop queueing but do not claim terminal failure.
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    poll, failed = fake.poll, [False]
    def transient(unit, state):
        if not failed[0]:
            failed[0] = True
            raise M.Blocked("read access temporarily unavailable")
        return poll(unit, state)
    fake.poll = transient
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert starts(fake) == ["A"] and state["A"]["status"] == "SUCCESS"


class StubAws(M.AwsBackend):
    def __init__(self, exports=(), destructive=False):
        super().__init__(ROOT, "dev", "123456789012", TARGET)
        self.exports, self.calls = list(exports), []
        self.change = {"Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "Changes": [
            {"ResourceChange": {"LogicalResourceId": "App", "ResourceType": "AWS::S3::Bucket",
                                "Action": "Remove" if destructive else "Add"}}]}

    def aws(self, operation, *arguments):
        self.calls.append((operation, arguments))
        if operation == "list-exports":
            return {"Exports": [{"Name": name} for name in self.exports]}
        if operation == "describe-stacks":
            raise M.Blocked("Stack does not exist")
        if operation == "create-change-set":
            return {"Id": "cs-" + arguments[1]}
        if operation == "describe-change-set":
            return json.loads(json.dumps(self.change))
        if operation == "execute-change-set":
            return {}
        raise AssertionError(operation)


def check_aws_adapter():
    # Case 3: distinct AWS requests with the shared template and separate inputs.
    backend = StubAws()
    scoped = units(10, 10)
    for unit in scoped:
        backend.templates[unit["name"]] = ({}, {})
        state = {"status": "NOT_STARTED", "clientToken": "token-" + unit["name"]}
        assert backend.prepare(unit, state) == "READY"
        backend.execute(unit, state)
    creates = [args for operation, args in backend.calls if operation == "create-change-set"]
    assert len(creates) == 2 and creates[0][1] == "A" and creates[1][1] == "B"
    assert creates[0][creates[0].index("--template-body") + 1] == creates[1][creates[1].index("--template-body") + 1]
    assert creates[0][creates[0].index("--parameters") + 1].endswith("a.json")
    assert creates[1][creates[1].index("--parameters") + 1].endswith("b.json")
    executes = [args for operation, args in backend.calls if operation == "execute-change-set"]
    assert executes[0][3] == "cs-A" and executes[1][3] == "cs-B"
    # Cases 6/7: producer succeeds before real list-exports and consumer change set.
    backend = StubAws()
    scoped = units(10, 20)
    state = states(scoped)
    backend.templates = {"A": ({}, {}), "B": ({"Resources": {"Imported": {"Fn::ImportValue": "NetworkVpcId"}}}, {})}
    def execute(unit, entry):
        backend.calls.append(("executed", unit["name"]))
    backend.execute = execute
    def poll(unit, entry):
        if unit["name"] == "A":
            backend.exports = ["NetworkVpcId"]
        backend.calls.append(("terminal", unit["name"]))
        return "CREATE_COMPLETE"
    backend.poll = poll
    assert finish(scoped, 3, state, backend) == "COMPLETE"
    consumer_cs = next(i for i, (op, args) in enumerate(backend.calls) if op == "create-change-set" and args[1] == "B")
    assert backend.calls.index(("terminal", "A")) < next(i for i, (op, _) in enumerate(backend.calls) if op == "list-exports") < consumer_cs
    for exports, expected in ((["NetworkVpcId"], "COMPLETE"), ([], "STOPPED")):
        backend = StubAws(exports)
        backend.templates["B"] = ({"Fn::ImportValue": "NetworkVpcId"}, {})
        backend.execute, backend.poll = lambda *args: None, lambda *args: "CREATE_COMPLETE"
        partial = [scoped[1]]
        state = states(partial)
        assert finish(partial, 2, state, backend) == expected
        creates = [args[1] for op, args in backend.calls if op == "create-change-set"]
        assert creates == (["B"] if exports else []) and "A" not in state
    # Missing export after a successful producer still blocks consumer.
    backend = StubAws()
    backend.templates["B"] = ({"Fn::ImportValue": "NetworkVpcId"}, {})
    state = states([scoped[1]])
    assert finish([scoped[1]], 2, state, backend) == "STOPPED"
    assert state["B"]["status"] == "BLOCKED"
    assert "DeployOrder conflicts" in state["B"]["reason"]
    assert not any(op == "create-change-set" for op, _ in backend.calls)
    backend = StubAws()
    backend.templates = {"A": ({}, {}), "B": ({"Fn::ImportValue": "NetworkVpcId"}, {})}
    backend.execute, backend.poll = lambda *args: None, lambda *args: "CREATE_COMPLETE"
    state = states(scoped)
    assert finish(scoped, 2, state, backend) == "STOPPED"
    assert [entry["status"] for entry in state.values()] == ["SUCCESS", "BLOCKED"]
    assert [args[1] for op, args in backend.calls if op == "create-change-set"] == ["A"]
    # Existing Export cannot bypass an unfinished in-scope producer in the same group.
    backend = StubAws()
    backend.templates["B"] = ({"Fn::ImportValue": "NetworkVpcId"}, {})
    backend.states = {"A": {"status": "RUNNING"}}
    backend.aws = lambda *args: {"Exports": [{"Name": "NetworkVpcId", "ExportingStackId": "arn:aws:cloudformation:region:account:stack/A/id"}]}
    rejects(lambda: backend.check_imports(scoped[1]), "producer A has not succeeded")
    # Destructive change blocks. Human approval reuses and re-fetches exact ID/content.
    backend = StubAws(destructive=True)
    unit, state = scoped[0], {"status": "NOT_STARTED", "clientToken": "approved"}
    backend.templates["A"] = ({}, {})
    assert backend.prepare(unit, state) == "BLOCKED"
    assert not any(op == "execute-change-set" for op, _ in backend.calls)
    backend.approvals = {state["changeSetId"]}
    assert backend.prepare(unit, state) == "READY"
    backend.execute(unit, state)
    assert sum(op == "create-change-set" for op, _ in backend.calls) == 1
    backend.change["Changes"][0]["ResourceChange"]["PolicyAction"] = "Retain"
    rejects(lambda: backend.prepare(unit, state), "approval invalid")
    rejects(lambda: backend.execute(unit, state), "approval invalid")
    backend.change["ExecutionStatus"] = "OBSOLETE"
    rejects(lambda: backend.prepare(unit, state), "AVAILABLE")
    for replacement in ("True", "Conditional"):
        backend = StubAws()
        backend.change["Changes"][0]["ResourceChange"].update(Action="Modify", Replacement=replacement)
        backend.templates["A"] = ({}, {})
        assert backend.prepare(unit, {"status": "NOT_STARTED"}) == "BLOCKED"
    backend.change["Changes"][0]["ResourceChange"]["Replacement"] = "Unknown"
    rejects(lambda: backend.prepare(unit, {"status": "NOT_STARTED"}), "unknown change set replacement")
    # A matching operation token and actual terminal stack status are both required.
    backend = M.AwsBackend(ROOT, "dev", "123456789012", TARGET)
    event = {"ResourceType": "AWS::CloudFormation::Stack", "ClientRequestToken": "current", "ResourceStatus": "CREATE_FAILED"}
    actual = ["ROLLBACK_IN_PROGRESS"]
    backend.aws = lambda operation, *args: ({"StackEvents": [event]} if operation == "describe-stack-events" else {"Stacks": [{"StackStatus": actual[0]}]})
    state = {"status": "RUNNING", "clientToken": "current", "changeSetId": "cs-A"}
    assert backend.poll(unit, state) == "ROLLBACK_IN_PROGRESS" and state["failureDetected"]
    actual[0], event["ResourceStatus"] = "ROLLBACK_COMPLETE", "ROLLBACK_COMPLETE"
    assert backend.poll(unit, state) == "ROLLBACK_COMPLETE"
    actual[0], event["ResourceStatus"] = "UPDATE_COMPLETE", "UPDATE_IN_PROGRESS"
    assert backend.poll(unit, state) == "UPDATE_IN_PROGRESS"  # Do not mistake old success for new success.
    backend.aws = lambda operation, *args: ({"StackEvents": []} if operation == "describe-stack-events" else {"ExecutionStatus": "EXECUTE_IN_PROGRESS"})
    assert backend.poll(unit, state) == "UPDATE_IN_PROGRESS"


def check_template_validation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        backend = M.AwsBackend(root, "dev", "123456789012", TARGET)
        unit = units(10)[0]
        template, params = backend.paths(unit)
        template.parent.mkdir(parents=True)
        params.parent.mkdir(parents=True)
        template.write_text("Resources: {}\n")
        params.write_text('[{"ParameterKey":"Prefix","ParameterValue":"Network"}]')
        document = {"Parameters": {"Prefix": {"Default": "Default"}}, "Fn::ImportValue": {"Fn::Join": ["", [{"Ref": "Prefix"}, "VpcId"]]}}
        calls = []
        backend.aws = lambda operation, *args: calls.append((operation, args)) or {}
        with patch.dict(sys.modules, {"cfnlint.decode": SimpleNamespace(decode=lambda path: (document, []))}), \
                patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run:
            backend.validate(unit)
            assert backend.templates["A"][1] == {"Prefix": "Network"}
            assert run.call_args.args[0] == ["cfn-lint", "--regions", "ap-northeast-1", "--template", str(template)]
            assert calls == [("validate-template", ("--template-body", "file://" + str(template)))]
            document["Transform"] = "AWS::Serverless-2016-10-31"
            rejects(lambda: backend.validate(unit), "transform template")


def check_inputs():
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for i, unit in enumerate(units(20, 10, 10), 1):
        values.update({f"desired.stack.{i:03}.{key}": value for key, value in unit.items()})
        values[f"display.stack.{i:03}.comment"] = "アプリケーションを配置するstack"
    for field, invalid in (("desired.deployment.maxConcurrentStacks", "0"), ("desired.deployment.maxConcurrentStacks", "-1"),
                           ("desired.deployment.maxConcurrentStacks", "abc"), ("desired.stack.001.deployOrder", "0"),
                           ("desired.stack.001.deployOrder", "-1"), ("desired.stack.001.deployOrder", "abc")):
        rejects(lambda: stack_model(values | {field: invalid}), "integer >= 1")
    missing = dict(values)
    del missing["desired.stack.001.deployOrder"]
    rejects(lambda: stack_model(missing), "migration required")
    missing = dict(values)
    del missing["desired.deployment.maxConcurrentStacks"]
    assert stack_model(missing)[0] == 1
    for field in ("dependsOn", "AfterStack", "DependsOnStack", "Dependencies"):
        rejects(lambda: stack_model(values | {"desired.stack.001." + field: "A"}), "requires only")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        path.parent.mkdir(parents=True)
        # Naming rules need only the established file; no alternative schema.
        (root / "framework/rules").mkdir(parents=True)
        (root / "framework/rules/aws-resource-naming.md").write_text(
            "| CloudFormation | Stack | `CloudFormation.Stack` | StackName | `.*` |\n")
        path.write_text(markdown_for(path, values, root))
        source = root / "model/dev/123456789012/cloudformation-stacks.properties"
        source.parent.mkdir(parents=True)
        source.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
        limit, scoped = M.load_units(root, "dev", "123456789012", ["A", "C"])
        assert limit == 2 and [unit["name"] for unit in scoped] == ["C", "A"]
        rejects(lambda: M.load_units(root, "dev", "123456789012", ["unknown"]), "Deployment scope")
        path.write_text(path.read_text().replace("| MaxConcurrentStacks | 2 |", "| MaxConcurrentStacks | 3 |"))
        rejects(lambda: M.load_units(root, "dev", "123456789012", ["A"]), "mismatch")
        (root / "tasks").mkdir()
        contract = root / "tasks/active.md"
        contract.write_text("- Task type: `governance`\n")
        rejects(lambda: M.active_scope(root, ["A"], "dev", TARGET["awsAccountId"]), "infrastructure")
    assert M.import_names({"Fn::ImportValue": {"Fn::Join": ["", [{"Ref": "Prefix"}, "VpcId"]]}}, {"Prefix": "Network"}, {}) == {"NetworkVpcId"}
    rejects(lambda: M.import_names({"Fn::ImportValue": {"Ref": "Resource"}}, {}, {}), "unsupported")
    # Standard CLI region/profile and full (automatic) pagination are retained.
    backend = M.AwsBackend(ROOT, "dev", "123456789012", TARGET, "test")
    with patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout='{"Exports":[]}', stderr="")) as run:
        backend.aws("list-exports")
        args = run.call_args.args[0]
        assert args[:5] == ["aws", "--region", "ap-northeast-1", "--profile", "test"]
        assert "--no-paginate" not in args
        configured = {**TARGET, "awsProfile": "configured"}
        for explicit in (None, "configured"):
            backend = M.AwsBackend(ROOT, "dev", "123456789012", configured, explicit)
            backend.aws("describe-stacks")
            assert run.call_args.args[0][:5] == ["aws", "--region", "ap-northeast-1", "--profile", "configured"]
        run.reset_mock()
        rejects(lambda: M.AwsBackend(ROOT, "dev", "123456789012", configured, "other"), "does not match target awsProfile")
        run.assert_not_called()
        M.AwsBackend(ROOT, "dev", "123456789012", TARGET).aws("list-exports")
        assert "--profile" not in run.call_args.args[0]


def check_session_cli():
    """Exercise entrypoint, preflight, persisted groups, approvals and immutable inputs."""
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "repo"
        (root / "framework/scripts").mkdir(parents=True)
        shutil.copy(ROOT / "framework/scripts/check-deploy-context.py", root / "framework/scripts/check-deploy-context.py")
        (root / "framework/rules").mkdir()
        (root / "framework/rules/aws-resource-naming.md").write_text(
            "| CloudFormation | Stack | `CloudFormation.Stack` | StackName | `.*` |\n")
        (root / "project.json").write_text(json.dumps({"targets": [{"environment": "dev", **TARGET, "awsProfile": "dev-profile"}]}))
        (root / "tasks").mkdir()
        contract = root / "tasks/active.md"
        contract.write_text("\n".join(["- Task type: `infrastructure`", "- Infrastructure phase: `deploy`",
                                     "- AWS API execution: `allowed`", "- Deploy/apply: `allowed`",
                                     "- Target environment: `dev`", "- Target AWS account: `123456789012`",
                                     "- Deployment scope: `A`, `B`", "- Authorized delete/replacement: `none`"]))
        values = {"desired.deployment.maxConcurrentStacks": "2"}
        for i, unit in enumerate(units(10, 20), 1):
            values.update({f"desired.stack.{i:03}.{key}": value for key, value in unit.items()})
            values[f"display.stack.{i:03}.comment"] = "アプリケーションを配置するstack"
        source = root / "model/dev/123456789012/cloudformation-stacks.properties"
        source.parent.mkdir(parents=True)
        source.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
        design = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        design.parent.mkdir(parents=True)
        design.write_text(markdown_for(design, values, root))
        template = root / "infra/cloudformation/templates/app.yaml"
        template.parent.mkdir(parents=True)
        template.write_text("Resources: {}\n")
        params = root / "infra/cloudformation/parameters/dev/123456789012"
        params.mkdir(parents=True)
        for name in ("a", "b"):
            (params / (name + ".json")).write_text("[]\n")
        state_file = base / "session.json"
        argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--stack", "A", "--stack", "B", "--state", str(state_file)]
        backends = []
        def backend_factory(root, environment, directory, target, profile, approvals):
            assert target["awsProfile"] == "dev-profile"
            backend = StubAws(destructive=True)
            backend.root, backend.approvals = root, set(approvals)
            backend.validate = lambda unit: backend.templates.update({unit["name"]: ({}, {})})
            backend.poll = lambda *args: "CREATE_COMPLETE"
            backends.append(backend)
            return backend
        def invoke(options=()):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    patch.object(M, "AwsBackend", side_effect=backend_factory), \
                    patch.object(shutil, "which", return_value="mock-command"), \
                    patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout='{"Account":"123456789012"}', stderr="")) as run:
                result = M.main(argv + list(options), root=root)
                if run.called:
                    assert run.call_args.args[0][:3] == ["mock-command", "--profile", "dev-profile"]
                return result
        assert invoke(["--profile", "other"]) == 2
        assert not backends and not state_file.exists()
        assert invoke() == 2
        session = json.loads(state_file.read_text())
        assert session["states"]["A"]["status"] == "BLOCKED"
        assert session["states"]["B"]["status"] == "NOT_STARTED"
        assert invoke(["--resume", "--approve-change-set", "cs-A"]) == 0
        session = json.loads(state_file.read_text())
        assert session["result"] == "GROUP_COMPLETE" and session["states"]["A"]["status"] == "SUCCESS"
        assert not any(op == "create-change-set" for op, _ in backends[-1].calls)
        assert invoke(["--resume"]) == 2
        session = json.loads(state_file.read_text())
        assert session["states"]["B"]["status"] == "BLOCKED"
        assert invoke(["--resume", "--approve-change-set", "cs-B"]) == 0
        assert invoke(["--resume"]) == 0
        assert not backends[-1].calls  # Completed run never redeploys successful stacks.
        assert invoke(["--resume", "--approve-change-set", "cs-A"]) == 2
        template.write_text("Resources: {Changed: {}}\n")
        assert invoke(["--resume"]) == 2
        template.write_text("Resources: {}\n")
        contract.write_text(contract.read_text().replace("`infrastructure`", "`governance`"))
        assert invoke(["--resume"]) == 2


check_scheduler()
check_aws_adapter()
check_template_validation()
check_inputs()
check_session_cli()
print("CloudFormation controller checks: PASS (8 required cases, blockers, rollback drain, exact change set approvals, scope and schema)")

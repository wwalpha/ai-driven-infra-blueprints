#!/usr/bin/env python3
"""Deterministic scheduler and AWS CLI adapter regression checks (no live AWS)."""
if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
import hashlib
import base64
import zipfile
import tempfile
import io
import shutil
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from model_design import markdown_for, stack_model, deployment_settings, deployment_bucket, properties
from design_layout import stack_delivery

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

    def template_arguments(self, unit, state):
        return ["--template-body", "file://" + str(self.paths(unit)[0])]

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
        if operation == "validate-template":
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
            assert not calls  # AWS validation happens at the unit's turn, after its bucket exists.
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
        path.write_text(path.read_text().replace("<!-- max-concurrent-stacks: 2 -->", "<!-- max-concurrent-stacks: 3 -->"))
        rejects(lambda: M.load_units(root, "dev", "123456789012", ["A"]), "mismatch")
        (root / "tasks").mkdir()
        contract = root / "tasks/active.md"
        contract.write_text("- Task type: `governance`\n")
        rejects(lambda: M.active_scope(root, ["A"], "dev", TARGET["awsAccountId"]), "infrastructure")
    assert M.import_names({"Fn::ImportValue": {"Fn::Join": ["", [{"Ref": "Prefix"}, "VpcId"]]}}, {"Prefix": "Network"}, {}) == {"NetworkVpcId"}
    rejects(lambda: M.import_names({"Fn::ImportValue": {"Ref": "Resource"}}, {}, {}), "unsupported")
    conditional = {"Conditions": {
        "Dev": {"Fn::Equals": [{"Ref": "Environment"}, "dev"]},
        "Stg": {"Fn::Not": [{"Condition": "Dev"}]},
        "Active": {"Fn::And": [{"Condition": "Dev"}, {"Fn::Or": [{"Condition": "Dev"}, {"Condition": "Stg"}]}]}},
        "Resources": {
            "Mwaa": {"Properties": {"Arn": {"Fn::If": ["Active", {"Fn::ImportValue": "DevBucketArn"},
                                                                     {"Fn::ImportValue": "StgBucketArn"}]}}},
            "StgOnly": {"Condition": "Stg", "Properties": {"Arn": {"Fn::ImportValue": "StgRoleArn"}}}},
        "Outputs": {"StgOnly": {"Condition": "Stg", "Value": {"Fn::ImportValue": "StgOutput"}}}}
    assert M.import_names(conditional, {"Environment": "dev"}, {}) == {"DevBucketArn"}
    assert M.import_names(conditional, {"Environment": "stg"}, {}) == {"StgBucketArn", "StgRoleArn", "StgOutput"}
    backend = StubAws(["DevBucketArn"])
    backend.templates["A"] = (conditional, {"Environment": "dev"})
    assert backend.prepare(units(1)[0], {"clientToken": "dev-only"}) == "READY"
    backend.templates["A"] = (conditional, {"Environment": "stg"})
    rejects(lambda: backend.check_imports(units(1)[0]), "missing export")
    conditional["Conditions"]["Dev"] = {"Condition": "Dev"}
    rejects(lambda: M.import_names(conditional, {"Environment": "dev"}, {}), "cyclic Condition")
    conditional["Conditions"]["Dev"] = {"Condition": "Missing"}
    rejects(lambda: M.import_names(conditional, {"Environment": "dev"}, {}), "unresolved")
    conditional["Conditions"]["Dev"] = "true"
    rejects(lambda: M.import_names(conditional, {"Environment": "dev"}, {}), "non-boolean")
    # Decoder scalars are subclasses; parameter values are plain strings.
    class MarkedString(str):
        pass
    conditional["Conditions"]["Dev"] = {"Fn::Equals": [{"Ref": "Environment"}, MarkedString("dev")]}
    assert M.import_names(conditional, {"Environment": "dev"}, {}) == {"DevBucketArn"}
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


class DeliveryAws(StubAws):
    template_arguments = M.AwsBackend.template_arguments

    def __init__(self, root, workdir, destructive=False):
        super().__init__(destructive=destructive)
        self.root, self.workdir = root, workdir
        self.objects, self.region, self.fail = {}, "ap-northeast-1", None
        self.export_values = {}

    def aws(self, operation, *arguments, service="cloudformation"):
        if service == "cloudformation":
            if operation == "list-exports" and self.export_values:
                self.calls.append((operation, arguments))
                return {"Exports": [{"Name": name, "Value": value} for name, value in self.export_values.items()]}
            return super().aws(operation, *arguments)
        self.calls.append((operation, arguments))
        if self.fail == operation:
            raise M.Blocked("simulated S3 permission/upload failure")
        assert arguments[arguments.index("--expected-bucket-owner") + 1] == TARGET["awsAccountId"]
        if operation == "get-bucket-location":
            return {"LocationConstraint": self.region}
        bucket, key = (arguments[arguments.index(flag) + 1] for flag in ("--bucket", "--key"))
        if operation == "put-object":
            assert arguments[arguments.index("--if-none-match") + 1] == "*"
            if (bucket, key) in self.objects:
                raise M.Blocked("(PreconditionFailed)")
            data = Path(arguments[arguments.index("--body") + 1]).read_bytes()
            checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
            assert checksum == arguments[arguments.index("--checksum-sha256") + 1]
            self.objects[bucket, key] = {"ChecksumSHA256": checksum, "ContentLength": len(data), "VersionId": "version+1", "data": data}
        if (bucket, key) not in self.objects:
            raise M.Blocked("(404)")
        return self.objects[bucket, key]


def check_delivery():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "repo"
        backend = DeliveryAws(root, base / "session.files")
        unit = units(10)[0]
        template, params = backend.paths(unit)
        template.parent.mkdir(parents=True)
        params.parent.mkdir(parents=True)
        params.write_text("[]", encoding="utf-8")
        backend.templates["A"] = ({"Resources": {}}, {})
        settings = {"templateBucket": "app-dev-assets", "templateKeyPrefix": "templates/"}
        # Measure UTF-8 bytes, with the exact 51,200 byte boundary and 1 MiB maximum.
        for size, mode in ((51200, "--template-body"), (51201, "--template-url"), (1024 * 1024, "--template-url")):
            template.write_bytes(("# あ\n".encode() * (size // 6)) + b" " * (size % 6))
            assert template.stat().st_size == size
            state = {"status": "NOT_STARTED"}
            assert backend.prepare(unit | settings, state) == "READY"
            validations = [args for op, args in backend.calls if op == "validate-template"]
            creates = [args for op, args in backend.calls if op == "create-change-set"]
            assert validations[-1][0] == mode
            assert validations[-1][1] == creates[-1][creates[-1].index(mode) + 1]
            if mode == "--template-url":
                assert validations[-1][1].endswith("?versionId=version%2B1")
            count = sum(op == "put-object" for op, _ in backend.calls)
            assert backend.prepare(unit | settings, state) == "READY"
            assert sum(op == "put-object" for op, _ in backend.calls) == count
        template.write_bytes(b" " * (1024 * 1024 + 1))
        rejects(lambda: backend.prepare(unit | settings, {}), "1 MiB")
        template.write_bytes(b" " * 51201)
        rejects(lambda: backend.prepare(unit, {}), "requires designed TemplateBucket")
        template.write_text("Resources: {}\n", encoding="utf-8")
        backend.calls.clear()
        assert backend.prepare(unit, {}) == "READY"
        assert not any(op in {"get-bucket-location", "head-object", "put-object"} for op, _ in backend.calls)

        source = root / "infra/cloudformation/artifacts/function-a.zip"
        source.parent.mkdir(parents=True)
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("index.py", "def handler(event, context): return event\n")
        def artifact(name, bucket="app-dev-assets", prop="Code", filename="function-a.zip"):
            return {"stack": "A", "resource": name, "property": prop,
                    "source": "infra/cloudformation/artifacts/" + filename, "bucket": bucket, "keyPrefix": "lambda/"}
        resources = {name: {"Type": "AWS::Lambda::Function", "Properties": {"Handler": "index.handler",
                     "Code": {"S3Bucket": bucket, "S3Key": "lambda/current.zip"}}}
                     for name, bucket in (("First", "app-dev-assets"), ("Second", "app-dev-assets"), ("Third", "app-dev-other"))}
        document = {"Resources": resources}
        template.write_text(json.dumps(document), encoding="utf-8")
        original = template.read_bytes()
        backend.templates["A"] = (document, {})
        prepared = unit | {"artifacts": [artifact("First"), artifact("Second"), artifact("Third", "app-dev-other")]}
        backend.calls.clear()
        state = {"status": "NOT_STARTED"}
        with patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            assert backend.prepare(prepared, state) == "READY"
        packaged = json.loads(Path(state["delivery"]["path"]).read_text())
        first, second, third = [packaged["Resources"][name]["Properties"]["Code"] for name in ("First", "Second", "Third")]
        assert first["S3Key"] == second["S3Key"] == third["S3Key"]
        assert first["S3Bucket"] != third["S3Bucket"] and first["S3ObjectVersion"] == "version+1"
        assert sum(op == "put-object" for op, _ in backend.calls) == 2  # Shared ZIP reused within a bucket.
        assert template.read_bytes() == original and document["Resources"]["First"]["Properties"]["Code"]["S3Key"] == "lambda/current.zip"
        assert packaged["Resources"]["First"]["Properties"]["Handler"] == "index.handler"
        assert max(i for i, (op, _) in enumerate(backend.calls) if op == "put-object") < next(i for i, (op, _) in enumerate(backend.calls) if op == "create-change-set")
        resumed = DeliveryAws(root, base / "session.files")
        resumed.objects, resumed.templates = backend.objects, backend.templates
        assert resumed.prepare(prepared, state) == "READY"
        assert not any(op in {"put-object", "create-change-set"} for op, _ in resumed.calls)
        obj = state["delivery"]["objects"][0]
        resumed.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"] = "changed"
        rejects(lambda: resumed.prepare(prepared, state), "checksum/size changed")
        resumed.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"] = obj["checksum"]
        old = source.read_bytes()
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("index.py", "changed code")
        rejects(lambda: resumed.prepare(prepared, state), "inputs changed")
        source.write_bytes(old)
        copy_path = Path(state["delivery"]["path"])
        old_copy = copy_path.read_bytes()
        copy_path.write_text("{}")
        rejects(lambda: resumed.prepare(prepared, state), "template changed")
        copy_path.write_bytes(old_copy)

        # All declared destinations are checked before uploading anything.
        for changed in ({"bucket": "wrong-bucket"}, {"keyPrefix": "wrong/"}):
            resumed.calls.clear()
            bad = unit | {"artifacts": [artifact("First") | changed]}
            rejects(lambda: resumed.prepare(bad, {}), "differs from the approved template")
            assert not any(op in {"put-object", "create-change-set"} for op, _ in resumed.calls)
        fresh = DeliveryAws(root, base / "fresh.files")
        fresh.templates = backend.templates
        fresh.region = "us-east-1"
        rejects(lambda: fresh.prepare(prepared, {}), "region does not match")
        fresh.region, fresh.fail = "ap-northeast-1", "put-object"
        rejects(lambda: fresh.prepare(prepared, {}), "upload failure")
        assert not any(op == "create-change-set" for op, _ in fresh.calls)
        fresh.fail = None
        source.unlink()
        rejects(lambda: fresh.prepare(prepared, {}), "source is missing")
        source.write_text("not a zip")
        rejects(lambda: fresh.prepare(prepared, {}), "prebuilt ZIP")
        # Inject link resolution without requiring Windows symlink privileges.
        resolve = Path.resolve
        with patch.object(Path, "resolve", lambda path, *args, **kwargs:
                          base / "outside.zip" if path == source else resolve(path, *args, **kwargs)):
            rejects(lambda: fresh.source_path(artifact("First")), "escapes")
        source.write_bytes(old)

        # Layer, Glue script and Step Functions definition use the same explicit mapping.
        script = source.with_name("job.py")
        script.write_text("print('job')")
        definition = source.with_name("state.json")
        definition.write_text('{"StartAt":"End","States":{"End":{"Type":"Succeed"}}}')
        other = {"Resources": {
            "Layer": {"Type": "AWS::Lambda::LayerVersion", "Properties": {"Content": {"S3Bucket": "app-dev-assets", "S3Key": "lambda/current.zip"}}},
            "Job": {"Type": "AWS::Glue::Job", "Properties": {"Command": {"Name": "glueetl", "ScriptLocation": "s3://app-dev-assets/lambda/job.py"}}},
            "State": {"Type": "AWS::StepFunctions::StateMachine", "Properties": {"DefinitionS3Location": {"Bucket": "app-dev-assets", "Key": "lambda/state.json"}}}}}
        template.write_text(json.dumps(other))
        fresh.templates["A"] = (other, {})
        mapped = unit | {"artifacts": [artifact("Layer", prop="Content"), artifact("Job", prop="Command.ScriptLocation", filename="job.py"),
                                       artifact("State", prop="DefinitionS3Location", filename="state.json")]}
        with patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            assert fresh.prepare(mapped, {}) == "READY"
        result = json.loads((fresh.workdir / "A.json").read_text())["Resources"]
        assert result["Job"]["Properties"]["Command"]["Name"] == "glueetl"
        assert result["State"]["Properties"]["DefinitionS3Location"]["Version"] == "version+1"

        # Model -> generated view -> projection retains settings and explicit file bindings.
        values = {f"desired.stack.001.{field}": value for field, value in unit.items()}
        values["display.stack.001.comment"] = "アプリケーションを配置するstack"
        reference = "[app-dev-assets](s3.md#s3-app-dev-assets)"
        values.update({"desired.deployment.templateBucket": reference, "desired.deployment.templateKeyPrefix": "templates/"})
        values.update({"desired.artifact.007." + field: value for field, value in artifact("First").items()})
        values["desired.artifact.007.bucket"] = reference
        (root / "framework/rules").mkdir(parents=True)
        (root / "framework/rules/aws-resource-naming.md").write_text("| CloudFormation | Stack | `CloudFormation.Stack` | StackName | `.*` |\n")
        design = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        design.parent.mkdir(parents=True)
        model = root / "model/dev/123456789012/s3.properties"
        model.parent.mkdir(parents=True)
        model.write_text("desired.resource.001.resourceType=S3.Bucket\ndesired.resource.001.logicalId=Assets\n"
                         "desired.resource.001.anchor=s3-app-dev-assets\ndesired.row.001-001.property=S3.Bucket.BucketName\n"
                         "desired.row.001-001.value=`app-dev-assets`\n")
        design.write_text(markdown_for(design, values, root))
        projected = stack_delivery(design) | {key: value for key, value in values.items() if key.startswith("desired.stack.")}
        settings, files = deployment_settings(projected)
        assert settings == deployment_settings(values)[0] and [a for _, a in files] == [a for _, a in deployment_settings(values)[1]]
        source_model = model.with_name("cloudformation-stacks.properties")
        source_model.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
        _, loaded = M.load_units(root, "dev", "123456789012", ["A"])
        assert loaded[0]["templateBucket"] == "app-dev-assets" and loaded[0]["artifacts"][0]["bucket"] == "app-dev-assets"
        rejects(lambda: deployment_bucket("[wrong](s3.md#s3-app-dev-assets)", design, root), "confirmed BucketName")
        rejects(lambda: deployment_settings(values | {"desired.deployment.templateBucket": "guessed-bucket"}), "reference s3.md")
        missing = dict(values)
        del missing["desired.deployment.templateKeyPrefix"]
        rejects(lambda: deployment_settings(missing), "specified together")
        for field, invalid in (("source", "../secret"), ("keyPrefix", "../"), ("stack", "unknown"), ("property", "Other")):
            rejects(lambda: deployment_settings(values | {"desired.artifact.007." + field: invalid}), "artifact" if field not in {"keyPrefix"} else "keyPrefix")
        duplicate = values | {key.replace(".007.", ".008."): value for key, value in values.items() if key.startswith("desired.artifact.")}
        rejects(lambda: deployment_settings(duplicate), "duplicate artifact destination")
        # Exercise the actual scoped staging/generation path, including a referenced S3 model.
        spec = importlib.util.spec_from_file_location("delivery_sync", ROOT / "framework/scripts/sync-model.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        shutil.copytree(ROOT / "framework", root / "framework", dirs_exist_ok=True)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}) + "\n")
        values["desired.stack.001.name"] = values["desired.artifact.007.stack"] = "cfn-stack-app-dev-job-01"
        source_model.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
        (design.parent / "s3.md").write_text('# S3 詳細設計\n<a id="s3-app-dev-assets"></a>\n')
        saved_model = model.read_bytes()
        with redirect_stdout(io.StringIO()):
            assert sync.sync(root, True, "dev", "123456789012", services=["cloudformation-stacks"]) == 0
            assert sync.sync(root, False, "dev", "123456789012", services=["cloudformation-stacks"]) == 0
        assert model.read_bytes() == saved_model
        assert deployment_settings(properties(sync.model_for(design, root)))[0] == deployment_settings(values)[0]
        only_artifacts = {key: value for key, value in values.items() if not key.startswith("desired.deployment.template")}
        design.write_text(markdown_for(design, only_artifacts, root))
        assert "| Property | Value |" not in design.read_text()
        assert deployment_settings(stack_delivery(design) | {"desired.stack.001.name": values["desired.stack.001.name"]})[1]

        # A producer Export changing after packaging cannot redirect the preserved bucket expression.
        template.write_text(json.dumps(document))
        document["Resources"]["First"]["Properties"]["Code"]["S3Bucket"] = {"Fn::ImportValue": "AssetsBucket"}
        backend.templates["A"] = (document, {})
        backend.export_values = {"AssetsBucket": "app-dev-assets"}
        one = unit | {"artifacts": [artifact("First")]}
        blocked = {"status": "NOT_STARTED"}
        with patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            assert backend.prepare(one, blocked) == "READY"
        backend.export_values["AssetsBucket"] = "other-bucket"
        rejects(lambda: backend.execute(one, blocked), "differs from the approved template")
        assert not any(op == "execute-change-set" for op, _ in backend.calls)

        # A small bootstrap stack can run before a later large template needs its bucket.
        bootstrap = DeliveryAws(root, base / "bootstrap.files")
        scoped = units(10, 20)
        scoped[0]["template"], scoped[1]["template"] = "bucket.yaml", "large.yaml"
        scoped[1].update(settings)
        for entry, size in zip(scoped, (20, 51201)):
            file, inputs = bootstrap.paths(entry)
            file.write_bytes(b" " * size)
            inputs.write_text("[]")
        with patch.dict(sys.modules, {"cfnlint.decode": SimpleNamespace(decode=lambda _: ({"Resources": {}}, []))}), \
                patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            for entry in scoped:
                bootstrap.validate(entry)
        assert not bootstrap.calls
        original_aws, bucket_created = bootstrap.aws, [False]
        def ordered_aws(operation, *args, **kwargs):
            if kwargs.get("service") == "s3api":
                assert bucket_created[0], "bucket used before producer completed"
            return original_aws(operation, *args, **kwargs)
        bootstrap.aws = ordered_aws
        def complete(entry, state):
            if entry["name"] == "A":
                bucket_created[0] = True
            return "CREATE_COMPLETE"
        bootstrap.poll = complete
        session = states(scoped)
        assert M.run_group(scoped, 1, session, bootstrap, sleep=lambda _: None) == "GROUP_COMPLETE"
        assert session["B"]["status"] == "NOT_STARTED" and not any(op == "put-object" for op, _ in bootstrap.calls)
        assert finish(scoped, 1, session, bootstrap) == "COMPLETE"
        assert any(op == "put-object" for op, _ in bootstrap.calls)


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
check_delivery()
check_session_cli()
print("CloudFormation controller checks: PASS (scheduler, exact approvals, S3 mappings/uploads, byte limits, checksum/source drift and scoped generation)")

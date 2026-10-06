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
import time
from threading import Barrier, get_ident
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
    assert [s["status"] for s in state.values()] == ["READY", "BLOCKED", "NOT_STARTED", "NOT_STARTED"]
    assert starts(fake) == [] and not fake.running
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
    assert starts(fake) == ["A", "B"] and state["A"]["status"] == "SUCCESS"


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
    with patch.object(M, "mappings", return_value=({}, {"A": {"App": ("model", "001")}})) as mapping_check:
        backend.execute(unit, state)
    assert mapping_check.call_count == 1
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
            assert run.call_args.args[0] == ["cfn-lint", "--regions", "ap-northeast-1", "--template", str(template), "--format", "json"]
            assert not calls  # AWS validation happens at the unit's turn, after its bucket exists.
            old = template.read_bytes()
            template.write_text("Resources: {Changed: {}}\n")
            rejects(lambda: backend.template_arguments(unit, {}), "changed after validation")
            template.write_bytes(old)
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
    # Native CFN pseudo parameters describe the stack account, independent of explicit resource IDs.
    execution = "999999999999"
    backend = StubAws([execution + "VpcId"])
    backend.target = {**TARGET, "awsExecutionAccountId": execution}
    backend.templates["A"] = ({"Fn::ImportValue": {"Fn::Sub": "${AWS::AccountId}VpcId"}}, {})
    backend.check_imports(units(1)[0])
    backend.exports = []
    artifact = {"resource": "Function", "property": "Code", "bucket": "bucket", "keyPrefix": execution + "/"}
    document = {"Resources": {"Function": {"Type": "AWS::Lambda::Function", "Properties": {
        "Code": {"S3Bucket": "bucket", "S3Key": {"Fn::Sub": "${AWS::AccountId}/code.zip"}}}}}}
    assert backend.artifact_bindings({"name": "A", "artifacts": [artifact]}, document, {})[0][0] == artifact
    assert backend.target["awsAccountId"] == TARGET["awsAccountId"]
    backend = M.AwsBackend(ROOT, "dev", "123456789012", {**TARGET, "awsExecutionAccountId": execution})
    with patch.object(backend, "aws", return_value={"ChecksumSHA256": "checksum", "ContentLength": 1}) as aws:
        backend.verify_object({"bucket": "bucket", "key": "key", "checksum": "checksum", "size": 1})
        arguments = aws.call_args.args
        assert arguments[arguments.index("--expected-bucket-owner") + 1] == execution


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
        assert sum(op == "get-bucket-location" for op, _ in backend.calls) == 1  # Existing bucket metadata reused.
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
        view = design.read_text()
        assert "| Property | Value |" not in view and "| TemplateBucket |" not in view and "| TemplateKeyPrefix |" not in view
        assert "### 配置ファイル" in view and f"<!-- templateBucket: {reference} -->" in view
        projected = stack_delivery(design) | {key: value for key, value in values.items() if key.startswith("desired.stack.")}
        settings, files = deployment_settings(projected)
        assert settings == deployment_settings(values)[0] and [a for _, a in files] == [a for _, a in deployment_settings(values)[1]]
        design.write_text(view + f"<!-- templateBucket: {reference} -->\n")
        rejects(lambda: stack_delivery(design), "duplicate S3 delivery setting")
        design.write_text(view.replace("<!-- templateKeyPrefix: templates/ -->", "<!-- templateKeyPrefix: -->"))
        rejects(lambda: stack_delivery(design), "invalid S3 delivery setting comment")
        legacy = view.replace(f"<!-- templateBucket: {reference} -->\n", "").replace("<!-- templateKeyPrefix: templates/ -->\n", "")
        legacy = legacy.replace("## S3配置\n", f"## S3配置\n\n| Property | Value |\n| --- | --- |\n| TemplateBucket | {reference} |\n| TemplateKeyPrefix | templates/ |\n")
        design.write_text(legacy)
        assert stack_delivery(design) == {key: value for key, value in projected.items() if not key.startswith("desired.stack.")}
        design.write_text(view)
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
        only_templates = {key: value for key, value in values.items() if not key.startswith("desired.artifact.")}
        template_view = markdown_for(design, only_templates, root)
        assert "## S3配置" not in template_view and "| Property | Value |" not in template_view
        design.write_text(template_view)
        assert deployment_settings(properties(sync.model_for(design, root)))[0] == deployment_settings(values)[0]
        design.write_text(template_view.replace("<!-- templateKeyPrefix: templates/ -->", "<!-- templateKeyPrefix: changed/ -->"))
        rejects(lambda: sync.validate_views(root, root, [design], {design: only_templates}), "model/display projection mismatch")
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
                                     "- Deployment scope: `A`, `B`", "- Authorized delete/replacement: `none`", "## Validation scope", "- `all`"]))
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
        argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--stack", "A", "--stack", "B", "--state", str(state_file), "--timing-log", str(base / "timing.jsonl")]
        backends, validation_calls = [], []
        destructive = [True]
        def backend_factory(root, environment, directory, target, profile, approvals):
            assert target["awsProfile"] == "dev-profile"
            backend = StubAws(destructive=destructive[0])
            if destructive[0]:
                # This scheduler/session fixture has no model; approval uses replacement.
                backend.change["Changes"][0]["ResourceChange"].update(Action="Modify", Replacement="True")
            backend.root, backend.approvals = root, set(approvals)
            def validate(unit):
                validation_calls.append(unit["name"])
                backend.templates.update({unit["name"]: ({}, {})})
            backend.validate = validate
            backend.load_inputs = lambda unit: backend.templates.update({unit["name"]: ({}, {})})
            backend.poll = lambda *args: "CREATE_COMPLETE"
            backends.append(backend)
            return backend
        session_runner = M.run_session
        execution_limits = []
        def run_session(*args):
            execution_limits.append(args[1])
            return session_runner(*args, sleep=lambda _: None)
        def invoke(options=()):
            def subprocess_result(command, **kwargs):
                return SimpleNamespace(returncode=0, stdout='{"Account":"123456789012"}' if "get-caller-identity" in command else "", stderr="")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                    patch.object(M, "AwsBackend", side_effect=backend_factory), \
                    patch.object(shutil, "which", return_value="mock-command"), \
                    patch.object(M.subprocess, "run", side_effect=subprocess_result) as run, \
                    patch.object(M, "run_session", side_effect=run_session):
                result = M.main(argv + list(options), root=root)
                if run.called:
                    context_calls = [c for c in run.call_args_list if "get-caller-identity" in c.args[0]]
                    assert len(context_calls) == 1
                    assert context_calls[0].args[0][:3] == ["mock-command", "--profile", "dev-profile"]
                return result
        assert invoke(["--profile", "other"]) == 2
        assert not backends and not state_file.exists()
        timing = [json.loads(line) for line in (base / "timing.jsonl").read_text().splitlines()]
        assert any(event["phase"] == "authenticationContext" and event["result"] == "FAIL" for event in timing)
        assert timing[-1]["phase"] == "controller" and timing[-1]["result"] == "FAIL"
        # Diagnose every mapping error before lint or AWS preparation, not 25 deployments.
        errors = {"A": ["A/MissingVpc: model resource matches=0", "A/MissingRole: model resource matches=0"],
                  "B": ["B/Repository: identifier row missing/ambiguous: RepositoryId"]}
        with patch.object(M, "mappings", side_effect=M.MappingError(errors)):
            assert invoke() == 2
        stopped = json.loads(state_file.read_text())
        assert stopped["result"] == "STOPPED" and stopped["validationErrors"] == errors
        assert all(s["status"] == "NOT_STARTED" for s in stopped["states"].values())
        assert all(stopped["states"][name]["preflightErrors"] == details for name, details in errors.items())
        assert stopped["metrics"]["validationCount"] == stopped["metrics"]["lintSeconds"] == 0
        assert stopped["metrics"]["inputLoadSeconds"] >= 0 and stopped["metrics"]["mappingCheckSeconds"] >= 0
        assert stopped["metrics"]["contextCheckSeconds"] >= 0
        assert not validation_calls and not backends[-1].calls and not execution_limits
        assert invoke(["--resume"]) == 2
        session = json.loads(state_file.read_text())
        assert "validationErrors" not in session and "validationError" not in session
        assert not any("preflightErrors" in state for state in session["states"].values())
        assert session["states"]["A"]["status"] == "BLOCKED", session
        assert session["states"]["B"]["status"] == "NOT_STARTED"
        assert invoke(["--resume", "--approve-change-set", "cs-A"]) == 2
        session = json.loads(state_file.read_text())
        assert session["result"] == "STOPPED" and session["states"]["A"]["status"] == "SUCCESS"
        assert [args[1] for op, args in backends[-1].calls if op == "create-change-set"] == ["B"]
        assert invoke(["--resume"]) == 2
        session = json.loads(state_file.read_text())
        assert session["states"]["B"]["status"] == "BLOCKED"
        assert invoke(["--resume", "--approve-change-set", "cs-B"]) == 0
        assert invoke(["--resume"]) == 0
        assert session["metrics"]["validationCount"] == 1
        assert validation_calls == ["A", "B"]
        assert not backends[-1].calls  # Completed run never redeploys successful stacks.
        assert invoke(["--resume", "--approve-change-set", "cs-A"]) == 2
        template.write_text("Resources: {Changed: {}}\n")
        assert invoke(["--resume"]) == 2
        template.write_text("Resources: {}\n")
        contract.write_text(contract.read_text().replace("`infrastructure`", "`governance`"))
        assert invoke(["--resume"]) == 2

        # Cases 1/2/3: one invocation, one whole-scope validation, all barriers inside it.
        contract.write_text(contract.read_text().replace("`governance`", "`infrastructure`"))
        destructive[0] = False
        for orders, limit in (((10,), 1), ((10,) * 4, 4), ((10,) * 4 + (20,) * 4, 4)):
            selected = units(*orders)
            values = {"desired.deployment.maxConcurrentStacks": str(limit)}
            for number, unit in enumerate(selected, 1):
                values.update({f"desired.stack.{number:03}.{key}": value for key, value in unit.items()})
                values[f"display.stack.{number:03}.comment"] = "実行するstack"
                (params / unit["parameters"]).write_text("[]\n")
            source.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
            design.write_text(markdown_for(design, values, root))
            contract.write_text(contract.read_text().replace(next(l for l in contract.read_text().splitlines() if l.startswith("- Deployment scope:")),
                                                           "- Deployment scope: " + ", ".join("`" + u["name"] + "`" for u in selected)))
            state_file = base / f"success-{len(orders)}.json"
            argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--state", str(state_file)]
            for unit in selected:
                argv += ["--stack", unit["name"]]
            assert invoke() == 0
            session = json.loads(state_file.read_text())
            assert session["result"] == "COMPLETE", session
            assert session["metrics"]["controllerInvocationCount"] == session["metrics"]["validationCount"] == 1
            assert session["metrics"]["deployOrderCount"] == len(set(orders))
            assert all(s["status"] == "SUCCESS" and s["observedSynced"] for s in session["states"].values())
            assert not any(op == "list-stacks" for op, _ in backends[-1].calls)
            assert invoke(["--resume"]) == 0 and not backends[-1].calls
            assert json.loads(state_file.read_text())["metrics"]["validationCount"] == 1
            # Legacy session gets one fresh validation; successful stacks are not reexecuted.
            session = json.loads(state_file.read_text())
            for key in ("version", "validationStatus", "validationDigest", "validationTemplates", "validationTemplatesDigest"):
                session.pop(key, None)
            state_file.write_text(json.dumps(session))
            assert invoke(["--resume"]) == 0 and not backends[-1].calls
            assert json.loads(state_file.read_text())["version"] == 2

            # Framework or validation dependency changes invalidate a prior PASS.
            policy = root / "framework/rules/validation-input.md"
            policy.write_text("validation input " + str(len(orders)))
            prior = json.loads(state_file.read_text())["metrics"]["validationCount"]
            assert invoke(["--resume"]) == 0 and not backends[-1].calls
            assert json.loads(state_file.read_text())["metrics"]["validationCount"] == prior + 1
            if limit == 4:
                # Sequential is a session cap, not a design edit or per-stack invocation.
                state_file = base / f"sequential-{len(orders)}.json"
                argv[argv.index("--state") + 1] = str(state_file)
                before = source.read_bytes()
                assert invoke(["--sequential"]) == 0 and execution_limits[-1] == 1
                assert source.read_bytes() == before
                assert json.loads(state_file.read_text())["result"] == "COMPLETE"
                assert invoke(["--resume", "--sequential"]) == 0 and not backends[-1].calls
                assert invoke(["--resume"]) == 2  # Resume cannot expand the saved cap.
        # Explicit update handoff retains the older producer/consumer editing contract.
        contract.write_text(contract.read_text().replace("Infrastructure phase: `deploy`", "Infrastructure phase: `update`"))
        state_file = base / "update-handoff.json"
        argv[argv.index("--state") + 1] = str(state_file)
        assert invoke(["--pause-after-group"]) == 0
        session = json.loads(state_file.read_text())
        assert session["result"] == "GROUP_COMPLETE"
        assert all(session["states"][u["name"]]["observedSynced"] for u in selected[:4])
        pending = params / selected[4]["parameters"]
        pending.write_text('[{"ParameterKey":"Environment","ParameterValue":"dev"}]')
        assert invoke(["--resume", "--pause-after-group"]) == 0
        session = json.loads(state_file.read_text())
        assert session["result"] == "COMPLETE" and session["metrics"]["validationCount"] == 2
        prepared = params / selected[0]["parameters"]
        prepared.write_text('[{"ParameterKey":"Changed","ParameterValue":"value"}]')
        assert invoke(["--resume"]) == 2


def check_parallel_and_restart():
    scoped = units(10, 10, 10, 10, 20, 20, 20, 20)
    sequential = Fake({"B": ["CREATE_FAILED"]})
    saved = {"states": states(scoped), "metrics": {"observedSyncSeconds": 0}}
    with patch.object(M, "sync_successful"):
        assert M.run_session(scoped, 1, saved, sequential, lambda: None, sleep=lambda _: None) == "STOPPED"
    assert sequential.peak == 1 and starts(sequential) == ["A", "B"]
    assert all(saved["states"][u["name"]]["status"] == "NOT_STARTED" for u in scoped[2:])
    state = states(scoped)
    backend = Fake()
    # Polls actually overlap. A barrier fails deterministically if they become serial.
    barrier = Barrier(4, timeout=3)
    poll = backend.poll
    def parallel_poll(unit, snapshot):
        barrier.wait()
        return poll(unit, snapshot)
    backend.poll = parallel_poll
    synced = []
    def sync(backend, selected, saved):
        synced.append([u["name"] for u in selected])
        for unit in selected:
            saved[unit["name"]]["observedSynced"] = True
    session = {"states": state, "metrics": {"observedSyncSeconds": 0}}
    with patch.object(M, "sync_successful", side_effect=sync):
        assert M.run_session(scoped, 4, session, backend, lambda: None, sleep=lambda _: None) == "COMPLETE"
    assert backend.peak == 4 and synced == [["A", "B", "C", "D"], ["E", "F", "G", "H"]]
    assert session["metrics"]["deployOrderCount"] == 2
    assert starts(backend) == [u["name"] for u in scoped]
    first_poll = next(i for i, e in enumerate(backend.events) if e[0] == "poll")
    assert sum(e[0] == "start" for e in backend.events[:first_poll]) == 4

    # Nonblocking production preparation creates all change sets before the first wait.
    backend = StubAws()
    selected = scoped[:4]
    backend.templates = {u["name"]: ({}, {}) for u in selected}
    state = states(selected)
    poll_barrier, review_barrier = Barrier(4, timeout=3), Barrier(4, timeout=3)
    review = backend.describe_change_set
    def parallel_review(unit, snapshot):
        assert sum(op == "create-change-set" for op, _ in backend.calls) == 4
        if snapshot["status"] == "CHANGESET_CREATING":
            review_barrier.wait()
        return review(unit, snapshot)
    backend.describe_change_set = parallel_review
    controller_thread, classify = get_ident(), backend.review_prepared
    def controller_review(unit, snapshot, change_set=None):
        assert get_ident() == controller_thread, "approval decision escaped controller thread"
        return classify(unit, snapshot, change_set)
    backend.review_prepared = controller_review
    def stack_poll(unit, snapshot):
        poll_barrier.wait()
        return "CREATE_COMPLETE"
    backend.poll = stack_poll
    assert M.run_group(selected, 4, state, backend, sleep=lambda _: None) == "GROUP_COMPLETE"
    assert sum(op == "execute-change-set" for op, _ in backend.calls) == 4

    # Interruption after submitting one stack, while its peer is prepared but unexecuted.
    selected = units(10, 10)
    state, backend = states(selected), Fake()
    execute = backend.execute
    def interrupted(unit, snapshot):
        execute(unit, snapshot)
        raise KeyboardInterrupt()
    backend.execute = interrupted
    try:
        M.run_group(selected, 2, state, backend, sleep=lambda _: None)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("interruption was hidden")
    assert state["A"]["status"] == "RUNNING" and state["B"]["status"] == "READY"
    backend.execute = execute
    assert finish(selected, 2, state, backend) == "COMPLETE"
    assert starts(backend) == ["A", "B"]  # A was polled, never redeployed.

    # Observed failure during restart also drains peers; it never leaves a RUNNING stack unobserved.
    state = {"A": {"status": "SUCCESS"}, "B": {"status": "RUNNING"}}
    backend = Fake({"B": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    backend.running = {"B"}
    session = {"states": state, "metrics": {"observedSyncSeconds": 0}}
    with patch.object(M, "sync_successful", side_effect=ValueError("AMBIGUOUS_OBSERVED_MAPPING")):
        assert M.run_session(selected, 2, session, backend, lambda: None, sleep=lambda _: None) == "STOPPED"
    assert state["B"]["status"] == "SUCCESS" and not backend.running and not starts(backend)
    assert session["observedError"] == "AMBIGUOUS_OBSERVED_MAPPING"


def check_observed_collector():
    from cloudformation_observed import sync_successful, mappings
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET, "awsExecutionAccountId": "999999999999"}]}) + "\n")
        source = root / "model/dev/123456789012/ec2.properties"
        source.parent.mkdir(parents=True)
        design = root / "docs/designs/dev/123456789012/ec2.md"
        design.parent.mkdir(parents=True)
        values = {"desired.service.ec2.serviceId": "ec2", "desired.service.ec2.ownedCatalogResourceTypes": "EC2.VPC,EC2.Subnet",
                  "display.service.title": "# EC2 詳細設計"}
        def resource(identity, kind, logical, anchor, rows):
            values.update({f"desired.resource.{identity}.resourceType": kind, f"desired.resource.{identity}.logicalId": logical,
                           f"desired.resource.{identity}.anchor": anchor, f"display.resource.{identity}.comment": "業務用ネットワークを構成するresource"})
            for index, (prop, value) in enumerate(rows, 1):
                key = f"desired.row.{identity}-{index:03d}"
                values.update({key + ".property": kind + "." + prop, key + ".value": value, key + ".comment": "設定値を指定する属性"})
        resource("001", "EC2.VPC", "vpc-test-dev", "ec2-vpc-test-dev", [
            ("Name", "`vpc-test-dev`"), ("VpcId", "[vpc-test-dev](#ec2-vpc-test-dev)"), ("CidrBlock", "`10.1.0.0/16`")])
        resource("002", "EC2.Subnet", "sbnt-test-dev-private-app-a-01", "ec2-sbnt-test-dev-private-app-a-01", [
            ("Name", "`sbnt-test-dev-private-app-a-01`"), ("VpcId", "[vpc-test-dev](#ec2-vpc-test-dev)"),
            ("SubnetId", "[sbnt-test-dev-private-app-a-01](#ec2-sbnt-test-dev-private-app-a-01)"), ("CidrBlock", "`10.1.1.0/24`")])
        # Initialize the existing standard observed row format, including comments.
        for rid in ("001-002", "002-003", "002-002"):
            for field in ("property", "comment"):
                values[f"observed.row.{rid}.{field}"] = values[f"desired.row.{rid}.{field}"]
            values[f"observed.row.{rid}.value"] = "PENDING_DEPLOY" if rid == "002-002" else "`PENDING_DEPLOY`"
        def save_model():
            source.write_text("\n".join(k + "=" + v for k, v in values.items()) + "\n")
            design.write_text(markdown_for(design, values, root))
        save_model()
        task = root / "tasks/active.md"
        task.parent.mkdir()
        task.write_text("- Task type: `infrastructure`\n## Validation scope\n- `dev/123456789012/ec2`\n## Allowed paths\n- `model/dev/123456789012/**`\n- `docs/designs/dev/123456789012/**`\n")
        backend = M.AwsBackend(root, "dev", "123456789012", TARGET)
        unit = units(10)[0]
        document = {"Resources": {"VpcTestDev": {"Type": "AWS::EC2::VPC"}},
                    "Outputs": {"VpcIdentity": {"Value": {"Ref": "VpcTestDev"}}}}
        backend.templates = {"A": (document, {})}
        backend.target = {**TARGET, "awsExecutionAccountId": "999999999999"}
        document["Conditions"] = {"ThisStack": {"Fn::And": [
            {"Fn::Equals": [{"Ref": "AWS::StackName"}, "A"]},
            {"Fn::Equals": [{"Ref": "AWS::AccountId"}, "999999999999"]}]}}
        document["Resources"]["VpcTestDev"]["Condition"] = "ThisStack"
        document["Outputs"]["VpcIdentity"]["Condition"] = "ThisStack"
        physical, output, removed = ["vpc-0123456789abcdef0"], ["vpc-0123456789abcdef0"], [False]
        def aws(operation, *args):
            if operation == "describe-stacks":
                return {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": [{"OutputKey": "VpcIdentity", "OutputValue": output[0]}]}]}
            assert operation == "list-stack-resources"
            return {"StackResourceSummaries": [] if removed[0] else [{"LogicalResourceId": "VpcTestDev", "ResourceType": "AWS::EC2::VPC", "PhysicalResourceId": physical[0]}]}
        backend.aws = aws
        before = source.read_bytes()
        # One model scan collects missing identities and identifier rows across stacks.
        import cloudformation_observed as observed
        subnet_identifier = values["desired.row.002-003.value"]
        values["desired.row.002-003.value"] = "`PENDING_DEPLOY`"
        source.write_text("\n".join(k + "=" + v for k, v in values.items()) + "\n")
        broken_templates = {
            "A": ({"Resources": {"MissingVpc": {"Type": "AWS::EC2::VPC"},
                                 "SbntTestDevPrivateAppA01": {"Type": "AWS::EC2::Subnet"}}}, {}),
            "B": ({"Resources": {"MissingRole": {"Type": "AWS::IAM::Role"}}}, {})}
        with patch.object(observed, "models", wraps=observed.models) as scan:
            try:
                mappings(root, "dev", "123456789012", broken_templates, units(10, 20))
            except observed.MappingError as error:
                assert set(error.errors) == {"A", "B"} and len(error.errors["A"]) == 2
                assert "MissingVpc" in str(error) and "MissingRole" in str(error) and "EC2.Subnet.SubnetId" in str(error)
            else:
                raise AssertionError("mapping diagnostics did not stop the full scope")
            assert scan.call_count == 1
        source.write_bytes(before)
        values["desired.row.002-003.value"] = subnet_identifier
        output[0] = "vpc-different"
        rejects(lambda: sync_successful(backend, [unit], states([unit])), "disagree")
        assert source.read_bytes() == before
        output[0] = physical[0]
        # Shared template identities cannot be assigned to one model row by guessing.
        duplicate = M.copy.deepcopy(document)
        duplicate["Resources"]["VpcTestDev"].pop("Condition")
        backend.templates["B"] = (duplicate, {})
        rejects(lambda: mappings(root, "dev", "123456789012", backend.templates, units(10, 10)), "also owned")
        assert source.read_bytes() == before
        # Out-of-scope incoming references block before writes, even with broad Allowed paths.
        consumer = source.with_name("consumer.properties")
        consumer.write_text("desired.row.001-001.property=EC2.Subnet.VpcId\ndesired.row.001-001.value=[vpc-test-dev](ec2.md#ec2-vpc-test-dev)\ndesired.row.001-001.comment=接続先\n")
        rejects(lambda: sync_successful(backend, [unit], states([unit])), "task scope violation")
        assert source.read_bytes() == before
        consumer.unlink()
        unrelated = root / "model/prod/999999999999/broken.properties"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("invalid=one\ninvalid=two\n")
        saved = states([unit])
        with redirect_stdout(io.StringIO()):
            sync_successful(backend, [unit], saved)
        observed = properties(source.read_text())
        assert observed["observed.row.001-002.value"] == "`" + physical[0] + "`"
        assert observed["observed.row.002-002.value"] == physical[0]
        assert observed["observed.row.002-003.value"] == "`PENDING_DEPLOY`"
        assert {k: v for k, v in observed.items() if not k.startswith("observed.")} == {k: v for k, v in values.items() if not k.startswith("observed.")}
        assert saved["A"]["observedSynced"] and physical[0] in design.read_text()
        # Replacement/current ID and output-absent PhysicalResourceId fallback.
        document["Outputs"] = {}
        physical[0] = "vpc-1234567890abcdef0"
        with redirect_stdout(io.StringIO()):
            sync_successful(backend, [unit], saved)
        assert properties(source.read_text())["observed.row.002-002.value"] == physical[0]
        assert "arn:aws" not in source.read_text()
        physical[0] = "arn:aws:ec2:ap-northeast-1:123456789012:vpc/secret"
        before = source.read_bytes()
        rejects(lambda: sync_successful(backend, [unit], saved), "non-ARN identifier unavailable")
        assert source.read_bytes() == before
        # Existing indexed services retain their index/part layout during observed updates.
        from model_files import model_file_contents, model_parts, read_model
        physical[0] = "vpc-abcdef01234567890"
        split = model_file_contents(source, source.read_text() + "# retained comment\n" * 620)
        for file, content in split.items():
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        parts = model_parts(source)
        assert len(parts) > 1
        index = source.read_bytes()
        with redirect_stdout(io.StringIO()):
            sync_successful(backend, [unit], saved)
        assert source.read_bytes() == index and model_parts(source) == parts
        assert properties(read_model(source))["observed.row.002-002.value"] == physical[0]

        # Approved physical deletion resets the formal row and every reference; retention blocks.
        document["Resources"] = {}
        saved["A"]["changes"] = [{"Action": "Remove", "LogicalResourceId": "VpcTestDev", "ResourceType": "AWS::EC2::VPC", "PolicyAction": "Retain"}]
        removed[0] = True
        before = read_model(source)
        rejects(lambda: sync_successful(backend, [unit], saved), "does not prove physical destruction")
        assert read_model(source) == before
        saved["A"]["changes"][0]["PolicyAction"] = "Delete"
        with redirect_stdout(io.StringIO()):
            sync_successful(backend, [unit], saved)
        assert properties(read_model(source))["observed.row.001-002.value"] == "`PENDING_DEPLOY`"
        assert properties(read_model(source))["observed.row.002-002.value"] == "PENDING_DEPLOY"


def check_shared_stack_mapping():
    from cloudformation_observed import mappings, sync_successful, preflight, validate_mapping_targets, removed_resources
    from model_files import read_model
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}) + "\n")
        source = root / "model/dev/123456789012/ec2.properties"
        source.parent.mkdir(parents=True)
        view = root / "docs/designs/dev/123456789012/ec2.md"
        view.parent.mkdir(parents=True)
        values, stack_values = {"desired.service.ec2.serviceId": "ec2", "desired.service.ec2.ownedCatalogResourceTypes": "EC2.VPC",
                                "display.service.title": "# EC2 詳細設計"}, {}
        scoped = []
        expected = {}
        for index, department in enumerate(("ism", "ced", "sd"), 1):
            identity = f"{index:03d}"
            logical = identity
            name = "vpc-app-dev-" + department
            anchor = "ec2-" + name
            unit = {"name": "cfn-stack-app-dev-" + department, "template": "department.yaml", "parameters": department + ".json", "deployOrder": "10"}
            scoped.append(unit)
            stack_values.update({f"desired.stack.{identity}.{key}": value for key, value in unit.items()})
            stack_values[f"display.stack.{identity}.comment"] = department + "部署のネットワークを配置するstack"
            values.update({f"desired.resource.{identity}.resourceType": "EC2.VPC", f"desired.resource.{identity}.cfn-logicalId": unit["name"] + "-DepartmentVpc",
                           f"desired.resource.{identity}.anchor": anchor, f"display.resource.{identity}.comment": department + "部署のネットワーク"})
            for number, (prop, value) in enumerate((("Name", "`" + name + "`"), ("VpcId", f"[{logical}](#{anchor})"),
                                                    ("CidrBlock", f"`10.{index}.0.0/16`")), 1):
                key = f"desired.row.{identity}-{number:03d}"
                values.update({key + ".property": "EC2.VPC." + prop, key + ".value": value, key + ".comment": "ネットワークの設定値"})
            expected[unit["name"]] = "vpc-" + str(index) * 17
        def save(path, data):
            path.write_text("\n".join(k + "=" + v for k, v in data.items()) + "\n", encoding="utf-8")
        save(source, values)
        stack_source = source.with_name("cloudformation-stacks.properties")
        save(stack_source, stack_values)
        view.write_text(markdown_for(view, values, root), encoding="utf-8")
        assert "cfn-logical-id:" not in view.read_text(encoding="utf-8")
        stack_view = view.with_name("cloudformation-stacks.md")
        stack_view.write_text(markdown_for(stack_view, stack_values, root), encoding="utf-8")
        task = root / "tasks/active.md"
        task.parent.mkdir()
        task.write_text("- Task type: `infrastructure`\n## Validation scope\n- `dev/123456789012/ec2`\n## Allowed paths\n- `model/dev/123456789012/**`\n- `docs/designs/dev/123456789012/**`\n")
        document = {"Parameters": {"Enabled": {"Type": "String", "Default": "yes"}},
                    "Conditions": {"Active": {"Fn::Equals": [{"Ref": "Enabled"}, "yes"]}, "Disabled": False},
                    "Resources": {"DepartmentVpc": {"Type": "AWS::EC2::VPC", "Condition": "Active"},
                                  "OptionalRepository": {"Type": "AWS::CodeCommit::Repository", "Condition": "Disabled"}},
                    "Outputs": {"VpcId": {"Condition": "Active", "Value": {"Fn::If": ["Active", {"Ref": "DepartmentVpc"}, {"Ref": "AWS::NoValue"}]}}}}
        backend = M.AwsBackend(root, "dev", "123456789012", TARGET)
        backend.templates = {unit["name"]: (document, {"Enabled": "yes"}) for unit in scoped}
        backend.mapping_plan = mappings(root, "dev", "123456789012", backend.templates, scoped)
        assert len(backend.mapping_plan[1]) == 3
        for index, unit in enumerate(scoped, 1):
            assert backend.mapping_plan[1][unit["name"]]["DepartmentVpc"][1] == f"{index:03d}"
        # Same parser and validator from the implementation CLI; defaults and stack inputs are local only.
        template = root / "infra/cloudformation/templates/department.yaml"
        template.parent.mkdir(parents=True)
        template.write_text(json.dumps(document))
        params = root / "infra/cloudformation/parameters/dev/123456789012"
        params.mkdir(parents=True)
        for unit in scoped:
            (params / unit["parameters"]).write_text("[]")
        with patch.dict(sys.modules, {"cfnlint.decode": SimpleNamespace(decode=lambda path: (json.loads(Path(path).read_text()), []))}), \
                patch.object(M, "subprocess") as no_aws:
            assert preflight(root, "dev", "123456789012", [u["name"] for u in scoped])[1] == backend.mapping_plan[1]
            no_aws.run.assert_not_called()
        def aws(operation, *args):
            name = args[args.index("--stack-name") + 1]
            if operation == "describe-stacks":
                return {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": [{"OutputKey": "VpcId", "OutputValue": expected[name]}]}]}
            assert operation == "list-stack-resources"
            return {"StackResourceSummaries": [{"LogicalResourceId": "DepartmentVpc", "ResourceType": "AWS::EC2::VPC", "PhysicalResourceId": expected[name]}]}
        backend.aws = aws
        with patch("cloudformation_observed.mappings", side_effect=AssertionError("must reuse validated mapping")), redirect_stdout(io.StringIO()):
            sync_successful(backend, scoped, states(scoped))
        actual = properties(read_model(source))
        for index, unit in enumerate(scoped, 1):
            assert actual[f"observed.row.{index:03d}-002.value"] == "`" + expected[unit["name"]] + "`"
        assert {k: v for k, v in actual.items() if not k.startswith("observed.")} == values
        before = source.read_bytes()
        def check(data=None, templates=None, message=""):
            save(source, data if data is not None else actual)
            rejects(lambda: mappings(root, "dev", "123456789012", templates or backend.templates, scoped), message)
        check(actual | {"desired.resource.001.cfn-logicalId": "invalid"}, message="invalid cfn-logicalId")
        check(actual | {"desired.resource.001.cfn-logicalId": scoped[0]["name"] + "-Missing"}, message="legacy fallback forbidden")
        check(actual | {"desired.resource.002.cfn-logicalId": scoped[0]["name"] + "-DepartmentVpc"}, message="matches=2")
        # A same-name legacy resource cannot repair an explicitly wrong direct identity.
        check(actual | {"desired.resource.001.logicalId": "DepartmentVpc", "desired.resource.001.cfn-logicalId": scoped[0]["name"] + "-Missing"}, message="legacy fallback forbidden")
        check(actual | {"desired.resource.001.cfn-logicalId": "absent-DepartmentVpc"}, message="undeclared stack")
        save(source, actual)
        wrong_type = M.copy.deepcopy(document)
        wrong_type["Resources"]["DepartmentVpc"]["Type"] = "AWS::S3::Bucket"
        check(templates={u["name"]: (wrong_type, {"Enabled": "yes"}) for u in scoped}, message="formal CFn type mismatch")
        # False resources do not require model endpoints or identifier rows.
        save(source, actual)
        inactive = dict(backend.templates)
        inactive[scoped[1]["name"]] = (document, {"Enabled": "no"})
        assert not mappings(root, "dev", "123456789012", inactive, scoped)[1][scoped[1]["name"]]
        save(stack_source, stack_values)
        values["desired.resource.001.resourceMode"] = "IMPORT"
        save(source, values)
        rejects(lambda: validate_mapping_targets(root, "dev", "123456789012", stack_values), "CREATE")
        del values["desired.resource.001.resourceMode"]
        save(source, values)
        for condition in ({"Ref": "Unknown"}, {"Condition": "Active"}, "yes"):
            invalid = M.copy.deepcopy(document)
            invalid["Conditions"]["Active"] = condition
            rejects(lambda: mappings(root, "dev", "123456789012", {u["name"]: (invalid, {}) for u in scoped}, scoped), "Condition" if condition == "yes" or "Condition" in condition else "unsupported")
        # CodeCommit identifier rows and non-primary EIP Outputs are diagnosed together.
        repo = source.with_name("codecommit.properties")
        repo_values = {"desired.resource.001.resourceType": "CodeCommit.Repository", "desired.resource.001.cfn-logicalId": scoped[0]["name"] + "-Repository",
                       "desired.resource.001.anchor": "codecommit-department-repo"}
        save(repo, repo_values)
        eip = {"desired.resource.004.resourceType": "EC2.EIP", "desired.resource.004.cfn-logicalId": scoped[0]["name"] + "-Eip",
               "desired.resource.004.anchor": "ec2-department-eip"}
        for number, prop in enumerate(("AllocationId", "PublicIp"), 1):
            eip.update({f"desired.row.004-{number:03d}.property": "EC2.EIP." + prop,
                        f"desired.row.004-{number:03d}.value": "[department-eip](#ec2-department-eip)",
                        f"desired.row.004-{number:03d}.comment": "固定アドレスの識別子"})
        save(source, values | eip)
        save(stack_source, stack_values)
        repo_doc = M.copy.deepcopy(document)
        repo_doc["Resources"]["Repository"] = {"Type": "AWS::CodeCommit::Repository"}
        repo_doc["Resources"]["Eip"] = {"Type": "AWS::EC2::EIP"}
        repo_templates = dict(backend.templates)
        repo_templates[scoped[0]["name"]] = (repo_doc, {"Enabled": "yes"})
        # Extend fixture scope solely for this explicitly mapped resource.
        task.write_text(task.read_text().replace("## Allowed paths", "- `dev/123456789012/codecommit`\n## Allowed paths"))
        try:
            mappings(root, "dev", "123456789012", repo_templates, scoped)
        except ValueError as error:
            assert "required GetAtt Output missing" in str(error)
            assert "CodeCommit.Repository.RepositoryId" not in str(error)
        repo_doc["Outputs"]["AllocationId"] = {"Value": {"Fn::GetAtt": "Eip.AllocationId"}, "Condition": "Disabled"}
        repo_doc["Outputs"]["PublicIp"] = {"Value": {"Fn::GetAtt": ["Eip", "PublicIp"]}}
        rejects(lambda: mappings(root, "dev", "123456789012", repo_templates, scoped), "required GetAtt Output missing")
        repo_doc["Outputs"]["AllocationId"].pop("Condition")
        repo_mapping = mappings(root, "dev", "123456789012", repo_templates, scoped)[1][scoped[0]["name"]]["Repository"]
        assert repo_mapping[0] == repo and not repo_mapping[4]
        # A removal is checked before execution even though the new Condition is false.
        save(stack_source, stack_values)
        save(source, actual)
        repo.unlink()
        backend.templates = inactive
        removing = {scoped[1]["name"]: {"DepartmentVpc": {"Type": "AWS::EC2::VPC", "PolicyAction": "Delete"}}}
        backend.mapping_plan = mappings(root, "dev", "123456789012", backend.templates, scoped, removing)
        def deletion_aws(operation, *args):
            if operation == "describe-stacks":
                return {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]}
            return {"StackResourceSummaries": []}
        backend.aws = deletion_aws
        deleted = states(scoped)
        deleted[scoped[1]["name"]]["changes"] = [{"Action": "Remove", "LogicalResourceId": "DepartmentVpc", "ResourceType": "AWS::EC2::VPC", "PolicyAction": "Delete"}]
        with redirect_stdout(io.StringIO()):
            sync_successful(backend, [scoped[1]], deleted)
        assert properties(read_model(source))["observed.row.002-002.value"] == "`PENDING_DEPLOY`"
        # Resume restores removal ownership from the immutable recorded change set, without re-execution.
        backend.mapping_plan = mappings(root, "dev", "123456789012", backend.templates, scoped,
                                        removed_resources(scoped, deleted), target=TARGET)
        with patch("cloudformation_observed.mappings", side_effect=AssertionError("resume must reuse validated plan")), redirect_stdout(io.StringIO()):
            sync_successful(backend, [scoped[1]], deleted)
        assert deleted[scoped[1]["name"]]["observedSynced"]
    print("Shared stack mapping checks: PASS (ism/ced/sd identifiers, Conditions, explicit failures, CodeCommit Outputs, validated-plan reuse, deletion)")


def check_integrated_child_mapping():
    from cloudformation_observed import mappings, sync_successful
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        model = root / "model/dev/123456789012"
        model.mkdir(parents=True)
        task = root / "tasks/active.md"
        task.parent.mkdir()
        task_text = "## Validation scope\n- `dev/123456789012/s3`\n- `dev/123456789012/ec2`\n- `dev/123456789012/codecommit`\n## Allowed paths\n- `model/dev/123456789012/**`\n- `docs/designs/dev/123456789012/**`\n"
        task.write_text(task_text)
        resources, documents = {}, {}
        unit = {"name": "cfn-stack-app-dev-integrated"}
        child_ids = []
        # Reproduce all 17 reported failures with identity-free child rows and no RepositoryId.
        for kind, parent_kind, parent_property, setting, count in (
            ("S3.BucketPolicy", "S3.Bucket", "Bucket", "PolicyDocument", 11),
            ("EC2.SubnetRouteTableAssociation", "EC2.Subnet", "SubnetId", "RouteTableId", 5),
        ):
            values = {}
            for number in range(1, count + 1):
                identity = f"{number:03d}"
                logical = parent_kind.split(".")[1] + str(number)
                child = "Child" + logical
                anchor = "resource-" + logical.lower()
                values.update({f"desired.resource.{identity}.resourceType": parent_kind,
                               f"desired.resource.{identity}.cfn-logicalId": unit["name"] + "-" + logical,
                               f"desired.resource.{identity}.anchor": anchor,
                               f"desired.row.{identity}-001.property": parent_kind + (".BucketName" if parent_kind == "S3.Bucket" else ".SubnetId"),
                               f"desired.row.{identity}-001.value": f"[{logical}](#{anchor})",
                               f"desired.row.{identity}-001.comment": "親識別子",
                               f"desired.row.{identity}-002.property": kind + "." + setting,
                               f"desired.row.{identity}-002.value": "`設定値`",
                               f"desired.row.{identity}-002.comment": "統合した子設定"})
                # Child precedes parent; ownership must not depend on template order.
                resources[child] = {"Type": "AWS::" + kind.replace(".", "::"),
                                    "Properties": {parent_property: {"Ref": logical}}}
                resources[logical] = {"Type": "AWS::" + parent_kind.replace(".", "::")}
                child_ids.append(child)
            path = model / ("s3.properties" if parent_kind == "S3.Bucket" else "ec2.properties")
            path.write_text("\n".join(k + "=" + v for k, v in values.items()) + "\n")
            documents[path] = values
        repo = model / "codecommit.properties"
        repo.write_text(f"desired.resource.001.resourceType=CodeCommit.Repository\ndesired.resource.001.cfn-logicalId={unit['name']}-Repository\ndesired.resource.001.anchor=codecommit-repository\n")
        resources["Repository"] = {"Type": "AWS::CodeCommit::Repository"}
        document = {"Conditions": {"Enabled": True, "Disabled": False}, "Resources": resources}
        def mapping(doc=document):
            return mappings(root, "dev", "123456789012", {unit["name"]: (doc, {})}, [unit], target=TARGET)
        plan = mapping()
        mapped = plan[1][unit["name"]]
        assert len(mapped) == 33  # 16 parents plus the 17 originally failing resources.
        for child in child_ids:
            assert not mapped[child][4] and len(mapped[child][3]) == 1
            parent = resources[child]["Properties"]
            assert mapped[child][:2] == mapped[next(iter(parent.values()))["Ref"]][:2]
        assert not mapped["Repository"][4]
        def reject_change(logical, definition, message):
            doc = M.copy.deepcopy(document)
            doc["Resources"][logical] = definition
            rejects(lambda: mapping(doc), message)
        child = resources["ChildBucket1"]
        reject_change("ChildBucket1", {**child, "Properties": {}}, "unambiguous local parent Ref")
        reject_change("ChildBucket1", {**child, "Properties": {"Bucket": "unknown"}}, "unambiguous local parent Ref")
        reject_change("ChildBucket1", {**child, "Properties": {"Bucket": {"Ref": "Subnet1"}}}, "formal CFn type mismatch")
        reject_change("Bucket1", {**resources["Bucket1"], "Condition": "Disabled"}, "parent missing, inactive")
        reject_change("DuplicateChild", child, "model resource also owned")
        reject_change("ChildBucket1", {**child, "Condition": "Unknown"}, "unresolved or cyclic Condition")
        conditional = {**child, "Properties": {"Bucket": {"Fn::If": ["Enabled", {"Ref": "Bucket1"}, "unknown"]}}}
        assert mapping({**document, "Resources": resources | {"ChildBucket1": conditional}})[1][unit["name"]]["ChildBucket1"] == mapped["ChildBucket1"]
        assert "ChildBucket1" not in mapping({**document, "Resources": resources | {"ChildBucket1": {**child, "Condition": "Disabled"}}})[1][unit["name"]]
        source = model / "s3.properties"
        original = source.read_text()
        source.write_text(original + "desired.resource.001.resourceMode=IMPORT\n")
        rejects(mapping, "requires CREATE")
        source.write_text(original.replace("S3.BucketPolicy.PolicyDocument", "S3.Bucket.VersioningConfiguration.Status", 1))
        rejects(mapping, "integrated child settings missing")
        source.write_text(original.replace(unit["name"] + "-Bucket1\n", unit["name"] + "-Wrong\n", 1))
        rejects(mapping, "legacy fallback forbidden")
        source.write_text(original)
        task.write_text("## Validation scope\n- `dev/123456789012/codecommit`\n")
        rejects(mapping, "task scope violation")
        task.write_text(task_text)
        before = {path: path.read_bytes() for path in model.glob("*.properties")}
        # Empty identifier sets must not collect child physical IDs or reset the parent's ID.
        children = {key: mapped[key] for key in [*child_ids, "Repository"]}
        backend = SimpleNamespace(root=root, environment="dev", directory="123456789012", target=TARGET,
                                  templates={unit["name"]: (document, {})}, mapping_plan=(plan[0], {unit["name"]: children}))
        backend.aws = lambda operation, *args: ({"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]} if operation == "describe-stacks" else
            {"StackResourceSummaries": [{"LogicalResourceId": key, "ResourceType": resources[key]["Type"], "PhysicalResourceId": "arn:aws:ignored"} for key in children]})
        state = states([unit])
        sync_successful(backend, [unit], state)
        assert state[unit["name"]]["observedSynced"]
        state[unit["name"]]["changes"] = [{"Action": "Remove", "LogicalResourceId": "ChildBucket1", "ResourceType": child["Type"], "PolicyAction": "Delete"}]
        backend.aws = lambda operation, *args: {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]} if operation == "describe-stacks" else {"StackResourceSummaries": [{"LogicalResourceId": key, "ResourceType": resources[key]["Type"]} for key in children if key != "ChildBucket1"]}
        sync_successful(backend, [unit], state)
        assert before == {path: path.read_bytes() for path in before}
    print("Integrated child mapping: PASS (11 BucketPolicies, 5 associations, hidden RepositoryId, strict ownership/scope/Conditions, identifier-free sync/deletion)")



def check_secretsmanager_arn_identifiers():
    from cloudformation_observed import mappings, sync_successful
    from model_design import catalog_outputs
    spec = importlib.util.spec_from_file_location("rotation_fixture", Path(__file__).with_name("rotation_schedule.checks.py"))
    rotation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rotation)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}) + "\n")
        model = root / "model/dev/123456789012"
        model.mkdir(parents=True)
        task = root / "tasks/active.md"
        task.parent.mkdir()
        task_text = "## Validation scope\n- `dev/123456789012/secretsmanager`\n- `dev/123456789012/kms`\n## Allowed paths\n- `model/dev/123456789012/**`\n- `docs/designs/dev/123456789012/**`\n"
        task.write_text(task_text)
        selected = units(1, 2)
        secrets = rotation.fixture()
        for identity, logical in (("001", "Secret1"), ("002", "Secret1Rotation")):
            secrets[f"desired.resource.{identity}.cfn-logicalId"] = "A-" + logical
        for field, value in {"property": "SecretsManager.Secret.KmsKeyId", "value": "[Key](kms.md#kms-app-dev-key)", "comment": "secretの暗号化鍵"}.items():
            secrets[f"desired.row.001-002.{field}"] = value
        key = rotation.HELPERS.model("kms", "KMS.Key", "app-dev-key", [
            ("KeyId", "[Key](#kms-app-dev-key)", "暗号化鍵のID"),
            ("KeyPolicy", "[KeyPolicy](kms/key-policy.json)", "鍵の権限")], "Key", "app-dev-key")
        key["desired.resource.001.cfn-logicalId"] = "A-Key"
        key["desired.row.001-002.document"] = json.dumps({"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": "secretsmanager.amazonaws.com"}, "Action": "kms:Decrypt", "Resource": "*"}]})
        stacks = {f"desired.stack.{i:03d}.{field}": value for i, unit in enumerate(selected, 1)
                  for field, value in unit.items()}
        for path, values in ((model / "secretsmanager.properties", secrets), (model / "kms.properties", key),
                             (model / "cloudformation-stacks.properties", stacks)):
            path.write_text(rotation.HELPERS.text(values))
        secret_ref = {"Ref": "Secret1"}
        document = {"Conditions": {"Enabled": True, "Disabled": False}, "Resources": {
            "Secret1": {"Type": "AWS::SecretsManager::Secret"},
            "Secret1Rotation": {"Type": "AWS::SecretsManager::RotationSchedule", "Properties": {"SecretId": secret_ref}},
            "Key": {"Type": "AWS::KMS::Key"}}, "Outputs": {"KeyId": {"Value": {"Ref": "Key"}}}}
        backend = Fake()
        backend.root, backend.environment, backend.directory, backend.target = root, "dev", "123456789012", TARGET
        backend.templates = {"A": (document, {}), "B": ({}, {})}
        def mapping():
            return mappings(root, "dev", "123456789012", backend.templates, selected, target=TARGET)
        backend.mapping_plan = mapping()
        assert not catalog_outputs(root, rotation.SECRET) and not catalog_outputs(root, rotation.ROTATION)
        assert catalog_outputs(root, "KMS.Key") == {"KMS.Key.KeyId"}
        arn = "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app-dev-secret-1-abcdef"
        actual = [{"LogicalResourceId": logical, "ResourceType": resource["Type"],
                   "PhysicalResourceId": "key-current" if logical == "Key" else arn}
                  for logical, resource in document["Resources"].items()]
        outputs = [{"OutputKey": "KeyId", "OutputValue": "key-current"}]
        def aws(operation, *args):
            return ({"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": outputs}]} if operation == "describe-stacks" else
                    {"StackResourceSummaries": actual})
        backend.aws = aws
        for arn_outputs in (False, True):
            if arn_outputs:
                document["Outputs"]["SecretArn"] = {"Value": secret_ref}
                document["Outputs"]["RotationArn"] = {"Value": {"Fn::GetAtt": ["Secret1Rotation", "Id"]}}
                outputs.extend({"OutputKey": name, "OutputValue": arn} for name in ("SecretArn", "RotationArn"))
            backend.mapping_plan = mapping()
            saved = states(selected)
            sync_successful(backend, selected, saved)
            assert all(state["observedSynced"] for state in saved.values())
        current = properties((model / "secretsmanager.properties").read_text())
        assert current["observed.row.001-002.value"] == "key-current"
        assert current["desired.row.002-003.value"] == secrets["desired.resource.002.parentReference"]
        assert not any(value in {rotation.SECRET + ".Id", rotation.ROTATION + ".Id"} for value in current.values())
        artifacts = list((root / "docs/designs").rglob("*.json"))
        assert artifacts and json.loads(artifacts[0].read_text()) == json.loads(key["desired.row.001-002.document"])
        assert all(arn not in path.read_text() for parent in (model, root / "docs/designs") for path in parent.rglob("*") if path.is_file())
        # Actual type, required normal Outputs and physical IDs stay strict, before writes.
        before = {path: path.read_bytes() for path in model.glob("*.properties")}
        actual[1]["ResourceType"] = "AWS::SecretsManager::Secret"
        rejects(lambda: sync_successful(backend, selected, states(selected)), "actual resource missing/type mismatch")
        actual[1]["ResourceType"] = document["Resources"]["Secret1Rotation"]["Type"]
        missing = outputs.pop(0)
        rejects(lambda: sync_successful(backend, selected, states(selected)), "required Output absent")
        outputs.insert(0, {**missing, "OutputValue": "wrong-key"})
        rejects(lambda: sync_successful(backend, selected, states(selected)), "disagree")
        outputs[0]["OutputValue"] = actual[2]["PhysicalResourceId"] = arn
        rejects(lambda: sync_successful(backend, selected, states(selected)), "non-ARN identifier unavailable")
        outputs[0]["OutputValue"] = actual[2]["PhysicalResourceId"] = "key-current"
        assert before == {path: path.read_bytes() for path in before}
        # The real collector completes the barrier before the next DeployOrder starts.
        session = {"states": states(selected), "metrics": {"observedSyncSeconds": 0}}
        assert M.run_session(selected, 1, session, backend, lambda: None, sleep=lambda _: None) == "COMPLETE"
        assert session["metrics"]["deployOrderCount"] == 2 and starts(backend) == ["A", "B"]
        failed = Fake()
        for field in ("root", "environment", "directory", "target", "templates", "mapping_plan", "aws"):
            setattr(failed, field, getattr(backend, field))
        outputs[0]["OutputValue"] = "wrong-key"
        session = {"states": states(selected), "metrics": {"observedSyncSeconds": 0}}
        assert M.run_session(selected, 1, session, failed, lambda: None, sleep=lambda _: None) == "STOPPED"
        assert starts(failed) == ["A"] and session["states"]["B"]["status"] == "NOT_STARTED"
        assert "disagree" in session["observedError"]
    print("Secrets Manager ARN identifiers: PASS (no required ARN Outputs/storage/propagation, logical parent, JSON, KMS guards, DeployOrder barrier)")

def check_api_timing():
    from deploy_preparation import Timing
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "timing.jsonl"
        backend = M.AwsBackend(ROOT, "dev", "123456789012", TARGET)
        backend.timing = Timing(ROOT, path)
        with patch.object(M.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout='{"Stacks":[]}', stderr="")):
            assert backend.aws("describe-stacks", "--stack-name", "private-stack") == {"Stacks": []}
        with patch.object(M.subprocess, "run", side_effect=M.subprocess.TimeoutExpired("aws", 60)):
            try:
                backend.aws("describe-stacks", "--stack-name", "private-stack")
            except M.subprocess.TimeoutExpired:
                pass
            else:
                raise AssertionError("API timeout accepted")
        events = [json.loads(line) for line in path.read_text().splitlines()]
        assert [event["result"] for event in events] == ["PASS", "FAIL"]
        assert all(event["phase"] == "awsApi" and event["seconds"] >= 0 for event in events)
        assert "private-stack" not in path.read_text() and "Stacks" not in path.read_text()


def check_controlled_repair():
    """Ten requested failure cases use real projection/edit/repair/scheduler/approval code."""
    from deploy_preparation import repair_changes, task_digest
    from cloudformation_inputs import load_template_inputs
    spec = importlib.util.spec_from_file_location('repair_models', Path(__file__).with_name('model_design.checks.py'))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = (base / 'repo').resolve()
        shutil.copytree(ROOT / 'framework', root / 'framework')
        (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', **TARGET}]}))
        modeldir = root / 'model/dev/123456789012'
        modeldir.mkdir(parents=True)
        unit = {'name': 'A', 'template': 'a.yaml', 'parameters': 'a.json', 'deployOrder': '1'}
        following = dict(unit, name='B', template='b.yaml', parameters='b.json', deployOrder='2')
        scoped = [unit, following]
        values = {f'desired.stack.{i:03d}.{key}': value for i, u in enumerate(scoped, 1) for key, value in u.items()}
        for i in (1, 2):
            values[f'display.stack.{i:03d}.comment'] = '対象stack'
        (modeldir / 'cloudformation-stacks.properties').write_text(helpers.text(values))
        template = root / 'infra/cloudformation/templates/a.yaml'
        template.parent.mkdir(parents=True)
        template.with_name('b.yaml').write_text('Resources: {}\n')
        parameters = root / 'infra/cloudformation/parameters/dev/123456789012'
        parameters.mkdir(parents=True)
        for key in ('a', 'b'):
            (parameters / (key + '.json')).write_text('[]\n')
        task = root / 'tasks/active.md'
        task.parent.mkdir()
        state_path = base / 'session.json'
        source_path = modeldir / 'ec2.properties'
        def configure(service, kind, rows, text, reason, *, create=False, repeated=False, destructive=False):
            for key in ('a', 'b'):
                (parameters / (key + '.json')).write_text('[]\n')
            template.with_name('b.yaml').write_text('Resources: {}\n')
            for i, u in enumerate(scoped, 1):
                values[f'desired.stack.{i:03d}.deployOrder'] = u['deployOrder']
            (modeldir / 'cloudformation-stacks.properties').write_text(helpers.text(values))
            for path in modeldir.glob('*.properties'):
                if path.name != 'cloudformation-stacks.properties':
                    path.unlink()
            resource = helpers.model(service, kind, 'app-dev-item', rows, 'Item')
            resource['desired.resource.001.cfn-logicalId'] = 'A-Item'
            modelpath = modeldir / (service + '.properties')
            modelpath.write_text(helpers.text(resource))
            template.write_text(text)
            relative = template.relative_to(root).as_posix()
            contract = '\n'.join(['## Task contract', '- Task type: `infrastructure`', '- Task status: `running`',
                '- Infrastructure phase: `deploy`', '- Controlled repair: `allowed`',
                f'- Deploy repair session: `{state_path}`', '## Validation scope', f'- `dev/123456789012/{service}`',
                '## Modified files', '- `tasks/active.md`', f'- `{relative}`',
                '## Allowed paths', '- `tasks/active.md`', f'- `{relative}`'])
            task.write_text(contract)
            backend = M.AwsBackend(root, 'dev', '123456789012', TARGET)
            session = {'states': states(scoped), 'metrics': {'observedSyncSeconds': 0},
                       'repository': str(root), 'taskFile': 'tasks/active.md', 'taskDigest': task_digest(contract),
                       'infraManifest': {p.relative_to(root).as_posix(): backend.file_digest(p) for p in (root / 'infra').rglob('*') if p.is_file()},
                       'unitDigests': {u['name']: backend.input_digest(u) for u in scoped}}
            backend.session, backend.states = session, session['states']
            backend.expected_digests = session['unitDigests']
            backend.workdir = base / 'files'
            calls, executions, validations = [], [], []
            current = {'A': None if create else 'UPDATE_COMPLETE', 'B': None}
            stackid = {name: f'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/{name}/session-unique' for name in ('A', 'B')}
            changes, tokens = {}, {}
            def aws(operation, *args, **kwargs):
                calls.append((operation, args))
                if operation in {'delete-stack', 'execute-change-set', 'create-change-set'}:
                    backend.guard()
                if '--stack-name' in args:
                    name = args[args.index('--stack-name')+1]
                    name = name.split(':stack/')[-1].split('/')[0]
                else:
                    name = 'A'
                if operation == 'describe-stacks':
                    if current[name] is None:
                        raise M.Blocked('stack does not exist')
                    return {'Stacks': [{'StackStatus': current[name], 'StackId': stackid[name]}]}
                if operation == 'list-stack-resources':
                    return {'StackResourceSummaries': []}
                if operation == 'create-change-set':
                    key = args[args.index('--change-set-name')+1]
                    changes[name] = key
                    return {'Id': key, 'StackId': stackid[name]}
                if operation == 'describe-change-set':
                    replacement = destructive and executions.count('A') >= 1 and name == 'A'
                    return {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE', 'Changes': [{'ResourceChange': {
                        'LogicalResourceId': 'Item', 'ResourceType': 'AWS::' + kind.replace('.', '::'),
                        'Action': 'Modify' if replacement else 'Add', 'Replacement': 'True' if replacement else 'False'}}]}
                if operation == 'execute-change-set':
                    executions.append(name)
                    tokens[name] = args[args.index('--client-request-token')+1]
                    failed = name == 'A' and (executions.count('A') == 1 or repeated)
                    current[name] = ('ROLLBACK_COMPLETE' if create else 'UPDATE_ROLLBACK_COMPLETE') if failed else 'CREATE_COMPLETE'
                    return {}
                if operation == 'describe-stack-events':
                    events = [{'ResourceType': 'AWS::CloudFormation::Stack', 'ClientRequestToken': tokens[name],
                               'ResourceStatus': current[name], 'StackId': stackid[name]}]
                    if 'ROLLBACK' in current[name]:
                        events.append({'ResourceType': 'AWS::' + kind.replace('.', '::'), 'LogicalResourceId': 'Item',
                                       'ResourceStatus': 'CREATE_FAILED', 'ResourceStatusReason': reason,
                                       'ClientRequestToken': tokens[name]})
                    return {'StackEvents': events}
                if operation == 'delete-stack':
                    assert args[args.index('--stack-name')+1] == stackid['A']
                    current['A'] = None
                return {}
            backend.aws = aws
            def guard():
                manifest = {p.relative_to(root).as_posix(): backend.file_digest(p) for p in (root / 'infra').rglob('*') if p.is_file()}
                if manifest != session['infraManifest']:
                    raise M.Blocked('unauthorized IaC change outside controlled repair')
                if any(backend.input_digest(u) != session['unitDigests'][u['name']] for u in scoped):
                    raise M.Blocked('unit digest changed')
            backend.guard = guard
            def save():
                state_path.write_text(json.dumps(session))
            def validate(u):
                validations.append(u['name'])
                repair_changes(root, task.read_text(), {session['states'][u['name']]['repairs'][-1]['path']})
                backend.validate(u)  # Real cfn-lint and template decoder, no AWS.
                assert backend.input_digest(u) == session['unitDigests'][u['name']]
            backend.refresh_validation, backend.save = validate, save
            backend.load_inputs(unit)
            backend.load_inputs(following)
            backend.validated_digests = dict(session['unitDigests'])
            save()
            def run():
                def synced(_backend, items, saved):
                    for item in items:
                        saved[item['name']]['observedSynced'] = True
                with patch.object(M, 'sync_successful', side_effect=synced):
                    return M.run_session(scoped, 2, session, backend, save, sleep=lambda _: None)
            return backend, session, calls, executions, validations, run
        vpc = 'Resources:\n  Item:\n    Type: AWS::EC2::VPC\n    Properties:\n      EnableDnsSupport: true\n'
        # Case 1: an omitted typed model property is inserted, validated and retried.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        before = template.read_text()
        assert run() == 'COMPLETE', session
        assert executed == ['A', 'A', 'B'] and validated == ['A']
        assert 'EnableDnsSupport: true' in template.read_text() and 'CidrBlock: 10.0.0.0/16' in template.read_text()
        history = session['states']['A']['repairs']
        assert history[0]['classification'] == 'AUTO_REPAIRABLE' and history[0]['oldDigest'] != history[0]['newDigest']
        assert len({args[args.index('--change-set-name')+1] for op, args in calls if op == 'create-change-set' and args[1] == 'A'}) == 2
        # Real task validator consumes session evidence, rejects arbitrary extra changes.
        spec = importlib.util.spec_from_file_location('repair_task_validator', Path(__file__).with_name('validate-blueprint.py'))
        vm = importlib.util.module_from_spec(spec); spec.loader.exec_module(vm)
        validator = vm.Validator(root); validator.task_type = 'infrastructure'; validator.infrastructure_phase = 'deploy'
        validator.changed_paths = {'infra/cloudformation/templates/a.yaml', 'tasks/active.md'}
        validator.check_task_type_requirements(); assert not validator.errors, validator.errors
        template.write_text(template.read_text() + '# unauthorized\n')
        validator.check_task_type_requirements(); assert validator.errors
        # Case 2: stale Subnet resolves from explicit CREATE identity, failed shell cleanup by StackId.
        lambda_text = '''Resources:
  Subnet:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: vpc-12345678
      CidrBlock: 10.0.0.0/24

  Item:
    Type: AWS::Lambda::Function
    Properties:
      Code:
        ZipFile: 'def handler(event, context): return 1'
      Runtime: python3.12
      Handler: index.handler
      Role: arn:aws:iam::123456789012:role/app-dev-role
      VpcConfig:
        SubnetIds: [subnet-0521f67350b825ab6]
        SecurityGroupIds: [sg-12345678]
'''
        backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
            [('VpcConfig.SubnetIds', '[subnet](ec2.md#ec2-app-dev-subnet)', 'subnet')], lambda_text, 'SubnetNotFound subnet-0521f67350b825ab6', create=True)
        subnet = helpers.model('ec2', 'EC2.Subnet', 'app-dev-subnet', [('SubnetId', '[subnet](#ec2-app-dev-subnet)', 'ID')], 'Subnet')
        subnet['desired.resource.001.cfn-logicalId'] = 'A-Subnet'
        source_path.write_text(helpers.text(subnet))
        task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/ec2`\n## Modified files'))
        session['taskDigest'] = task_digest(task.read_text()); backend.save()
        assert run() == 'COMPLETE', session
        assert executed == ['A', 'A', 'B'] and any(op == 'delete-stack' for op, _ in calls)
        assert '!Ref' in template.read_text() and 'Subnet' in template.read_text()
        assert session['states']['A']['cleanupStatus'] == 'DELETE_COMPLETE'
        # A nonfailing external Role expression does not force consultation for a known Subnet repair.
        lambda_with_import = lambda_text.replace('Role: arn:aws:iam::123456789012:role/app-dev-role', 'Role: !ImportValue RoleArn')
        backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
            [('VpcConfig.SubnetIds', '[subnet](ec2.md#ec2-app-dev-subnet)', 'subnet'),
             ('Role', '[role](iam.md#iam-app-dev-role)', 'role')], lambda_with_import, 'SubnetNotFound old subnet')
        source_path.write_text(helpers.text(subnet))
        role = helpers.model('iam', 'IAM.Role', 'app-dev-role', [('RoleName', '`app-dev-role`', '名前')], 'Role')
        role['desired.resource.001.cfn-logicalId'] = 'B-Role'
        (modeldir / 'iam.properties').write_text(helpers.text(role))
        task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/ec2`\n- `dev/123456789012/iam`\n## Modified files'))
        session['taskDigest'] = task_digest(task.read_text()); backend.save()
        event_subnet = {'LogicalResourceId': 'Item', 'ResourceType': 'AWS::Lambda::Function',
                        'ResourceStatus': 'STATIC_VALIDATION_FAILED', 'ResourceStatusReason': 'SubnetNotFound old subnet'}
        state = session['states']['A']; state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=[event_subnet])
        assert backend.repair(unit, state), state
        assert 'Role: !ImportValue RoleArn' in template.read_text()
        # Cross-stack Subnet correction confirms the existing actual Export expression and owner.
        external_lambda = 'Resources:\n  Item:' + lambda_text.split('\n  Item:', 1)[1]
        backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
            [('VpcConfig.SubnetIds', '[subnet](ec2.md#ec2-app-dev-subnet)', 'subnet')], external_lambda, 'SubnetNotFound old subnet')
        subnet['desired.resource.001.cfn-logicalId'] = 'B-Subnet'
        source_path.write_text(helpers.text(subnet))
        producer = {'Resources': {'Subnet': {'Type': 'AWS::EC2::Subnet', 'Properties': {'VpcId': 'vpc-12345678', 'CidrBlock': '10.0.0.0/24'}}},
                    'Outputs': {'SubnetId': {'Value': {'Ref': 'Subnet'}, 'Export': {'Name': 'SubnetExport'}}}}
        template.with_name('b.yaml').write_text(json.dumps(producer))
        task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/ec2`\n## Modified files'))
        session['taskDigest'] = task_digest(task.read_text())
        session['infraManifest']['infra/cloudformation/templates/b.yaml'] = backend.file_digest(template.with_name('b.yaml'), fresh=True)
        session['unitDigests']['B'] = backend.input_digest(following, fresh=True)
        original_aws = backend.aws
        def reference_aws(operation, *args, **kwargs):
            if operation == 'list-exports':
                calls.append((operation, args))
                return {'Exports': [{'Name': 'SubnetExport', 'Value': 'subnet-current',
                                     'ExportingStackId': 'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/B/id'}]}
            if operation == 'get-template':
                calls.append((operation, args)); return {'TemplateBody': producer}
            if operation == 'describe-stacks' and args == ('--stack-name', 'B'):
                calls.append((operation, args)); return {'Stacks': [{'StackStatus': 'CREATE_COMPLETE', 'Parameters': []}]}
            return original_aws(operation, *args, **kwargs)
        backend.aws = reference_aws
        state = session['states']['A']; state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=[event_subnet])
        backend.save()
        assert backend.repair(unit, state), state
        assert '!ImportValue' in template.read_text() and 'SubnetExport' in template.read_text()
        assert sum(op == 'get-template' for op, _ in calls) == 1
        subnet['desired.resource.001.cfn-logicalId'] = 'A-Subnet'
        # Case 3: explicit approved account projection, not an inference from AccessDenied.
        glue_text = 'Resources:\n  Item:\n    Type: AWS::Glue::Database\n    Properties:\n      CatalogId: "111111111111"\n      DatabaseInput:\n        Name: app_dev_database\n'
        backend, session, calls, executed, validated, run = configure('glue', 'Glue.Database',
            [('CatalogId', '`123456789012`', 'approved own account')], glue_text, 'Catalog AccessDenied')
        assert run() == 'COMPLETE', session
        assert '!Ref' in template.read_text() and 'AWS::AccountId' in template.read_text() and executed == ['A', 'A', 'B']
        # Case 4: external key absent, authoritative handoff unresolved: no edits.
        backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
            [('KmsKeyArn', '`UNSET`', 'external key unknown')], lambda_text, 'KMS key does not exist')
        before = template.read_bytes(); assert run() == 'STOPPED'
        assert template.read_bytes() == before and session['states']['A']['failureClassification'] == 'HUMAN_REQUIRED'
        assert not validated and not any(op == 'delete-stack' for op, _ in calls)
        # An IMPORT Key reference without an approved handoff is also never guessed.
        backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
            [('KmsKeyArn', '[key](kms.md#kms-app-dev-key)', 'external key')], lambda_text, 'KMS key does not exist')
        imported = helpers.model('kms', 'KMS.Key', 'app-dev-key', [('KeyId', '[key](#kms-app-dev-key)', '外部鍵')], 'Key')
        imported['desired.resource.001.resourceMode'] = 'IMPORT'
        (modeldir / 'kms.properties').write_text(helpers.text(imported))
        task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/kms`\n## Modified files'))
        session['taskDigest'] = task_digest(task.read_text()); backend.save()
        before = template.read_bytes(); assert run() == 'STOPPED' and template.read_bytes() == before
        assert session['states']['A']['failureClassification'] == 'HUMAN_REQUIRED' and not validated
        # Case 5: approved cross-account CatalogId already matches, never rewrite to execution account.
        backend, session, calls, executed, validated, run = configure('glue', 'Glue.Database',
            [('CatalogId', '`111111111111`', 'cross-account')], glue_text, 'Catalog AccessDenied')
        before = template.read_bytes(); assert run() == 'STOPPED' and template.read_bytes() == before
        assert session['states']['A']['failureClassification'] == 'HUMAN_REQUIRED'
        # Case 6: new replacement change set reaches the existing exact-ID Human approval gate.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing', destructive=True)
        assert run() == 'STOPPED' and executed == ['A']
        assert session['states']['A']['status'] == 'BLOCKED' and 'human confirmation' in session['states']['A']['reason']
        # Case 7: repeated logical error after deterministic repair has no new material correction.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock request-id changed', repeated=True)
        assert run() == 'STOPPED' and executed == ['A', 'A'] and len(session['states']['A']['repairs']) == 1
        # Case 8: out-of-scope bytes cannot be absorbed into a repair transaction.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        template.with_name('b.yaml').write_text('Resources: {}\n# unauthorized\n')
        before = template.read_bytes(); assert run() == 'STOPPED' and template.read_bytes() == before
        assert 'unauthorized IaC' in session['states']['A']['reason']
        # Case 9: successful peer is drained/synced once, never restarted during repair.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        following['deployOrder'] = '1'
        assert run() == 'COMPLETE' and executed.count('B') == 1 and executed.count('A') == 2
        following['deployOrder'] = '2'
        # Case 10: UPDATE_ROLLBACK_FAILED/ResourcesToSkip never causes skip or deletion.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_FAILED', reason='ResourcesToSkip required')
        before = template.read_bytes(); assert not backend.repair(unit, state)
        assert template.read_bytes() == before and state['failureClassification'] == 'HUMAN_REQUIRED'
        assert not any(op in {'delete-stack', 'continue-update-rollback'} for op, _ in calls)
        # The three-iteration cap is enforced independently of changing request/error strings.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        state = session['states']['A']
        event = {'LogicalResourceId': 'Item', 'ResourceType': 'AWS::EC2::VPC',
                 'ResourceStatus': 'STATIC_VALIDATION_FAILED', 'ResourceStatusReason': 'CidrBlock missing'}
        state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=[event],
                     repairs=[{'failureClass': 'Item:CidrBlock|Peer' + str(i) + ':Property', 'newFileDigest': str(i), 'stage': 'RETRY_READY'} for i in range(3)])
        assert not backend.repair(unit, state) and 'iteration limit' in state['reason'] and not validated
        # Structured lint failure is repaired before the first AWS change set.
        invalid = vpc.replace('true', 'invalid_boolean') + '      CidrBlock: 10.0.0.0/16\n'
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('EnableDnsSupport', '`true`', 'DNS')], invalid, 'EnableDnsSupport invalid')
        rejects(lambda: backend.validate(unit), 'cfn-lint failed')
        assert backend.validation_failures['A']
        state = session['states']['A']
        state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=backend.validation_failures['A'])
        assert backend.repair(unit, state) and validated == ['A'] and not calls, state
        # Both interruption boundaries recover only persisted exact candidate bytes, then revalidate.
        for boundary in ('REPAIR_INTENT', 'VALIDATING'):
            backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
                [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
            state = session['states']['A']; state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=[event])
            original_save = backend.save
            def interrupted():
                original_save()
                if state.get('repairs') and state['repairs'][-1]['stage'] == boundary:
                    raise KeyboardInterrupt()
            backend.save = interrupted
            try:
                backend.repair(unit, state)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError('repair interruption not exercised')
            assert not validated
            backend.save = original_save
            assert backend.repair(unit, state) and validated == ['A'] and state['status'] == 'NOT_STARTED'
            assert len(state['repairs']) == 1
        # Concurrent scope/parameter edits during diagnostics or intent persistence cannot be admitted.
        for boundary in ('diagnostics', 'intent'):
            backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
                [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
            state = session['states']['A']; state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=[event])
            untouched = template.read_bytes()
            if boundary == 'diagnostics':
                plan = backend.repair_plan
                def concurrent_plan(*args):
                    result = plan(*args)
                    (parameters / 'b.json').write_text('[]\n# scope change')
                    return result
                backend.repair_plan = concurrent_plan
            else:
                original_save = backend.save
                def concurrent_intent():
                    original_save()
                    if state.get('repairs') and state['repairs'][-1]['stage'] == 'REPAIR_INTENT':
                        (parameters / 'a.json').write_text('[]\n# unauthorized parameter change')
                backend.save = concurrent_intent
            assert not backend.repair(unit, state) and not validated and not executed
            if boundary == 'diagnostics':
                assert template.read_bytes() == untouched
            else:
                assert 'outside the exact authorized candidate' in state['reason']
        # Isolated stale parameter keeps its template Ref and changes only the reserved parameter file.
        parameter_template = 'Parameters:\n  Cidr:\n    Type: String\nResources:\n  Item:\n    Type: AWS::EC2::VPC\n    Properties:\n      CidrBlock: !Ref Cidr\n'
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], parameter_template, 'CidrBlock invalid')
        parameter = parameters / 'a.json'
        parameter.write_text('[{"ParameterKey":"Cidr","ParameterValue":"10.1.0.0/16"}]')
        relative = parameter.relative_to(root).as_posix()
        task.write_text(task.read_text().replace('## Modified files', '## Modified files\n- `' + relative + '`').replace('## Allowed paths', '## Allowed paths\n- `' + relative + '`'))
        session['taskDigest'] = task_digest(task.read_text())
        session['infraManifest'][relative] = backend.file_digest(parameter, fresh=True)
        session['unitDigests']['A'] = backend.input_digest(unit, fresh=True)
        state = session['states']['A']; state.update(status='FAILED', stackStatus='PRE_EXECUTION', failureEvents=[event])
        backend.save()
        before = template.read_bytes()
        assert backend.repair(unit, state) and template.read_bytes() == before
        assert json.loads(parameter.read_text())[0]['ParameterValue'] == '10.0.0.0/16'
        # Reset to a template case for the rollback safety checks below.
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        state = session['states']['A']
        # Unknown provenance and retained resource conditions are checked before delete.
        state.update(stackStatus='ROLLBACK_COMPLETE', operationType='CREATE', absentBeforeCreate=True, stackId='id', operationStackId='other')
        rejects(lambda: backend.cleanup_failed_create(unit, state), 'provenance')
        state['operationStackId'] = 'id'
        backend.templates['A'][0]['Resources']['Item']['DeletionPolicy'] = 'Retain'
        rejects(lambda: backend.cleanup_failed_create(unit, state), 'retained')
        backend.templates['A'][0]['Resources']['Item'].pop('DeletionPolicy')
        def protected(operation, *args):
            return {'Stacks': [{'StackId': 'id', 'StackStatus': 'ROLLBACK_COMPLETE', 'EnableTerminationProtection': True}]}
        backend.aws = protected
        rejects(lambda: backend.cleanup_failed_create(unit, state), 'protected')
        def partial_asset(operation, *args):
            if operation == 'describe-stacks':
                return {'Stacks': [{'StackId': 'id', 'StackStatus': 'ROLLBACK_COMPLETE'}]}
            return {'StackResourceSummaries': [{'LogicalResourceId': 'Item', 'ResourceType': 'AWS::EC2::VPC',
                                                'ResourceStatus': 'CREATE_FAILED', 'PhysicalResourceId': 'vpc-existing'}]}
        backend.aws = partial_asset
        rejects(lambda: backend.cleanup_failed_create(unit, state), 'still owns resources')
        assert M.merge_selected([{'Key': 'Name', 'Value': 'old'}, {'Key': 'Owner', 'Value': 'keep'}],
                                [{'Key': 'Name', 'Value': 'new'}], 'Tags') == [{'Key': 'Name', 'Value': 'new'}, {'Key': 'Owner', 'Value': 'keep'}]
        empty = 'Resources:\n  Item:\n    Type: AWS::EC2::VPC\n'
        assert 'Properties:' in M.repair_template(empty, 'Item', 'CidrBlock', '10.0.0.0/16')
        flow = 'Resources: {Item: {Type: AWS::EC2::VPC, Properties: {CidrBlock: old, EnableDnsSupport: true}}}\n'
        assert 'EnableDnsSupport: true' in M.repair_template(flow, 'Item', 'CidrBlock', '10.0.0.0/16')
        # Source-span edits preserve sibling keys and comments across scalar/list/map values.
        sample = 'Resources:\n  Item:\n    Type: AWS::Glue::Database\n    Properties:\n      CatalogId: "old" # comment\n      DatabaseInput:\n        Name: db\n        Description: old\n      Tags: [one]\n'
        updated = M.repair_template(sample, 'Item', 'DatabaseInput', {'Name': 'db', 'Description': 'new'})
        assert 'Tags: [one]' in updated and 'CatalogId: "old" # comment' in updated
    print('Controlled deploy repair: PASS (Cases 1-10, typed projection, static lint, session evidence, no guessed values, provenance/retention gates)')


check_controlled_repair()

check_api_timing()

check_scheduler()
check_aws_adapter()
check_template_validation()
check_inputs()
check_delivery()
check_session_cli()
check_parallel_and_restart()
check_observed_collector()
check_shared_stack_mapping()
check_integrated_child_mapping()
check_secretsmanager_arn_identifiers()
print("CloudFormation controller checks: PASS (scheduler, exact approvals, S3 mappings/uploads, byte limits, checksum/source drift and scoped generation)")

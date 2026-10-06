#!/usr/bin/env python3
"""Fake-only destroy acceptance: no network, credentials or live AWS mutations."""
from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cloudformation_observed as observed
from model_design import properties, markdown_for

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("destroy", Path(__file__).with_name("cloudformation-destroy.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TARGET = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}


def rejects(action, fragment):
    try:
        action()
    except (ValueError, M.Blocked) as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError("expected blocker: " + fragment)


def stack_id(name):
    return f"arn:aws:cloudformation:ap-northeast-1:123456789012:stack/{name}/uuid-{name}"


class Fake(M.AwsBackend):
    def __init__(self, names, outcomes=None, absent=(), exports=None):
        self.target = dict(TARGET)
        self.names = names
        self.calls = []
        self.deleted = []
        self.running = set()
        self.maximum = 0
        self.outcomes = outcomes or {}
        self.absent = set(absent)
        self.export_imports = exports or {}
        self.overrides = {}
        self.completed = set()
        self.lock = threading.Lock()
        self.profile = None
        self.polls = Counter()
        self.retained = set()
        self.hook = None

    def aws(self, operation, *arguments):
        with self.lock:
            self.calls.append((operation, arguments))
            assert operation in M.AwsBackend.READS | {"delete-stack", "get-caller-identity"}, operation
            if operation == "get-caller-identity":
                return {"Account": self.target.get("awsExecutionAccountId", self.target["awsAccountId"])}
            if operation == "list-exports":
                return {"Exports": [{"Name": export, "ExportingStackId": stack_id(producer)}
                                    for export, (producer, _) in self.export_imports.items()]}
            if operation == "list-imports":
                return {"Imports": self.export_imports[arguments[1]][1]}
            identity = arguments[1]
            name = identity.split("/")[1] if identity.startswith("arn:") else identity
            if operation == "describe-stacks":
                if name in self.absent or name in self.completed:
                    return None
                actual = "CREATE_COMPLETE"
                if name in self.running:
                    self.polls[name] += 1
                    sequence = self.outcomes.get(name, ["DELETE_IN_PROGRESS", "DELETE_COMPLETE"])
                    actual = sequence[min(self.polls[name] - 1, len(sequence) - 1)]
                    if actual == "DELETE_COMPLETE":
                        self.running.remove(name)
                        self.completed.add(name)
                    elif actual == "DELETE_FAILED":
                        self.running.remove(name)
                stack = {"StackName": name, "StackId": stack_id(name), "StackStatus": actual,
                         "EnableTerminationProtection": False, "ParentId": None, "RootId": None,
                         "Outputs": [{"ExportName": export} for export, (producer, _) in self.export_imports.items() if producer == name]}
                return {"Stacks": [stack | self.overrides.get(name, {})]}
            if operation == "delete-stack":
                assert identity == stack_id(name), "delete must use pinned StackId"
                assert "--deletion-mode" not in arguments
                assert name not in self.running
                self.running.add(name)
                self.deleted.append(name)
                self.maximum = max(self.maximum, len(self.running))
                if self.hook:
                    self.hook(name)
                return {}
            if operation == "describe-stack-events":
                return {"StackEvents": [{"ResourceStatus": "DELETE_SKIPPED", "LogicalResourceId": "Retained"}] if name in self.retained else []}
            raise AssertionError(operation)


def session(orders):
    return {"states": {name: {"StackName": name, "DeployOrder": order, "status": "NOT_STARTED",
                               "observedSynced": False} for name, order in orders.items()}}


def execute(orders, limit=1, fake=None):
    fake = fake or Fake(list(orders))
    state = session(orders)
    try:
        M.preflight(state, fake, limit, lambda: None)
        M.dependencies(state, fake, lambda: None)
    except M.Blocked as error:
        state.update(status="BLOCKED", reason=str(error))
        return state, fake
    state["status"] = M.run_session(state, fake, limit, lambda: None, lambda *_: None, sleep=lambda _: None)
    return state, fake


def check_order_and_safety():
    state, fake = execute({"A": 10, "B": 20, "C": 30})
    assert fake.deleted == ["C", "B", "A"] and state["status"] == "COMPLETE"
    print("D02: PASS reverse DeployOrder")
    state, fake = execute({"A": 30, "B": 30, "C": 30, "D": 20}, limit=2)
    assert fake.maximum == 2 and fake.deleted == ["A", "B", "C", "D"]
    # The fake keeps unfinished stacks in running; lower groups must start with no upper peers.
    fake = Fake(["A", "B", "C", "D"])
    def barrier(name):
        if name == "D":
            assert {"A", "B", "C"} <= fake.completed
    fake.hook = barrier
    execute({"A": 30, "B": 30, "C": 30, "D": 20}, 2, fake)
    print("D03: PASS bounded parallelism and group barrier")
    _, fake = execute({"A": 30, "B": 30, "C": 30}, limit=1)
    assert fake.maximum == 1
    print("D04: PASS sequential")
    state, fake = execute({"A": 10}, fake=Fake(["A"], exports={"Vpc": ("A", ["B"])}))
    assert state["status"] == "BLOCKED" and not fake.deleted and "outside" in state["reason"]
    print("D05: PASS outside importer stops every delete")
    state, fake = execute({"A": 10, "B": 20}, fake=Fake(["A", "B"], exports={"Vpc": ("A", ["B"])}))
    assert state["status"] == "COMPLETE" and fake.deleted == ["B", "A"]
    for orders in ({"A": 20, "B": 10}, {"A": 20, "B": 20}):
        state, fake = execute(orders, fake=Fake(["A", "B"], exports={"Vpc": ("A", ["B"])}))
        assert not fake.deleted and "actual import dependency conflicts with designed DeployOrder" in state["reason"]
    print("D06: PASS consumer first; conflicting/equal designed orders block")
    fake = Fake(["A"]); fake.overrides["A"] = {"EnableTerminationProtection": True}
    state, fake = execute({"A": 10}, fake=fake)
    assert state["status"] == "BLOCKED" and not fake.deleted
    print("D07: PASS termination protection")
    fake = Fake(["A"]); fake.overrides["A"] = {"ParentId": stack_id("Parent"), "RootId": stack_id("Parent")}
    state, fake = execute({"A": 10}, fake=fake)
    assert state["status"] == "BLOCKED" and not fake.deleted
    print("D08: PASS nested direct target")
    fake = Fake(["A", "B", "C", "D"], {"A": ["DELETE_FAILED"], "B": ["DELETE_IN_PROGRESS"] * 3 + ["DELETE_COMPLETE"]})
    state, fake = execute({"A": 30, "B": 30, "C": 30, "D": 20}, 2, fake)
    assert fake.deleted == ["A", "B"] and not fake.running and state["status"] == "BLOCKED"
    assert state["states"]["A"]["status"] == "DELETE_FAILED" and state["states"]["B"]["status"] == "DELETE_COMPLETE"
    assert all(state["states"][name]["status"] == "NOT_STARTED" for name in ("C", "D"))
    assert not any("FORCE_DELETE_STACK" in args for _, args in fake.calls)
    print("D09: PASS failure stops starts, drains peers, leaves lower order")
    for override in ({"StackId": stack_id("Other")}, {"StackName": "Other"},
                     {"StackId": stack_id("A").replace("123456789012", "999999999999")},
                     {"StackId": stack_id("A").replace("ap-northeast-1", "us-east-1")}):
        fake = Fake(["A"]); fake.overrides["A"] = override
        state, fake = execute({"A": 10}, fake=fake)
        assert not fake.deleted and state["status"] == "BLOCKED"


def check_absence():
    fake = Fake(["A"], absent=["A"])
    state = session({"A": 10})
    state["states"]["A"].update(StackId=stack_id("A"), status="DELETE_IN_PROGRESS", deleteObserved=True)
    M.preflight(state, fake, 1, lambda: None)
    assert state["states"]["A"]["status"] == "DELETE_COMPLETE"
    assert not fake.deleted
    print("D10: PASS saved deletion evidence + pinned absence")
    for evidence in ({}, {"StackId": stack_id("A"), "status": "DELETE_INTENT"}):
        state = session({"A": 10}); state["states"]["A"].update(evidence)
        M.preflight(state, fake, 1, lambda: None)
        assert state["states"]["A"]["status"] == "ALREADY_ABSENT"
    print("D11: PASS fresh absence / intent alone do not prove deletion")
    # Resume never switches to a replacement stack with the same name.
    fake = Fake(["A"]); fake.overrides["A"] = {"StackId": stack_id("A") + "-replacement"}
    state = session({"A": 10}); state["states"]["A"]["StackId"] = stack_id("A")
    rejects(lambda: M.preflight(state, fake, 1, lambda: None), "mismatch")


def fixture(root, names, models=False):
    (root / "model/dev/123456789012").mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}))
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for number, (name, order) in enumerate(names.items(), 1):
        values.update({f"desired.stack.{number:03d}.{key}": str(value) for key, value in
                       {"name": name, "deployOrder": order, "template": name + ".yaml", "parameters": name + ".json"}.items()})
    (root / "model/dev/123456789012/cloudformation-stacks.properties").write_text("\n".join(key + "=" + value for key, value in values.items()) + "\n")
    if models:
        shutil.copytree(ROOT / "framework", root / "framework")
        values = {"desired.service.ec2.serviceId": "ec2", "desired.service.ec2.ownedCatalogResourceTypes": "EC2.VPC,EC2.Subnet",
                  "display.service.title": "# EC2 詳細設計"}
        for number, name in enumerate(names, 1):
            identity = f"{number:03d}"
            values.update({f"desired.resource.{identity}.resourceType": "EC2.VPC",
                           f"desired.resource.{identity}.cfn-logicalId": name + "-Vpc",
                           f"desired.resource.{identity}.anchor": "ec2-vpc-test-dev-" + name.lower(),
                           f"display.resource.{identity}.comment": "ネットワークを構成するresource"})
            rows = [("Name", f"`vpc-test-dev-{name.lower()}`"),
                    ("VpcId", f"[{identity}](#ec2-vpc-test-dev-{name.lower()})"),
                    ("CidrBlock", f"`10.{number}.0.0/16`")]
            for index, (prop, value) in enumerate(rows, 1):
                prefix = f"desired.row.{identity}-{index:03d}"
                values.update({prefix + ".property": "EC2.VPC." + prop, prefix + ".value": value, prefix + ".comment": "設定値"})
            for field in ("property", "comment"):
                values[f"observed.row.{identity}-002.{field}"] = values[f"desired.row.{identity}-002.{field}"]
            values[f"observed.row.{identity}-002.value"] = f"`vpc-old-{name}`"
        # An IMPORT consumer reference participates without stack-owned destruction.
        values.update({"desired.resource.099.resourceType": "EC2.Subnet", "desired.resource.099.resourceMode": "IMPORT",
                       "desired.resource.099.anchor": "ec2-sbnt-test-dev-private-app-a-01",
                       "display.resource.099.comment": "接続先subnet"})
        for index, (prop, value) in enumerate([
            ("Name", "`sbnt-test-dev-private-app-a-01`"), ("VpcId", "[001](#ec2-vpc-test-dev-a)"),
            ("SubnetId", "[099](#ec2-sbnt-test-dev-private-app-a-01)"), ("CidrBlock", "`10.1.1.0/24`")], 1):
            prefix = f"desired.row.099-{index:03d}"
            values.update({prefix + ".property": "EC2.Subnet." + prop, prefix + ".value": value, prefix + ".comment": "設定値"})
        values["observed.row.099-002.value"] = "`vpc-old-A`"
        values["observed.row.099-003.value"] = "`subnet-existing`"
        for rid in ("099-002", "099-003"):
            for field in ("property", "comment"):
                values[f"observed.row.{rid}.{field}"] = values[f"desired.row.{rid}.{field}"]
        source = root / "model/dev/123456789012/ec2.properties"
        source.write_text("\n".join(key + "=" + value for key, value in values.items()) + "\n")
        design = root / "docs/designs/dev/123456789012/ec2.md"
        design.parent.mkdir(parents=True)
        design.write_text(markdown_for(design, values, root))
    # Start with a broad same-target contract to derive exact output reservations mechanically.
    contract = root / "tasks/destroy.md"
    contract.parent.mkdir()
    paths = ["tasks/destroy.md"]
    paths += [path.relative_to(root).as_posix() for path in (root / "model").rglob("*.properties")]
    paths += [path.relative_to(root).as_posix() for path in (root / "docs/designs").rglob("*.md")]
    contract.write_text("# Destroy\n\n## Task contract\n\n- Task type: `infrastructure`\n- Task status: `running`\n"
                        "- Infrastructure phase: `destroy`\n- AWS API execution: `allowed`\n- Destroy: `allowed`\n"
                        "- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Destroy scope: " + " ".join("`" + name + "`" for name in names) +
                        "\n\n## Validation scope\n\n- `dev/123456789012/" + ("ec2" if models else "cloudformation-stacks") + "`\n"
                        "\n## Required changes\n\n- [R1] 明示scopeをdestroyする。\n\n## Acceptance checks\n\n- [R1] `exists:project.json`\n"
                        "\n## Modified files\n\n" + "\n".join("- `" + path + "`" for path in paths) +
                        "\n\n## Allowed paths\n\n" + "\n".join("- `" + path + "`" for path in paths) + "\n")
    return contract


def check_controller():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"BLUEPRINT_TASK_FILE": "tasks/destroy.md"}):
        base = Path(directory); root = base / "repo"; root.mkdir()
        fixture(root, {"A": 10})
        fake = Fake(["A"])
        # Use the real AWS backend/real context; subprocess is the sole fake boundary.
        def aws_run(command, **kwargs):
            assert command[0] == "aws", command
            service_index = command.index("sts") if "sts" in command else command.index("cloudformation")
            response = fake.aws(command[service_index + 1], *command[service_index + 2:-3])
            if response is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id A does not exist")
            return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")
        read_text, rglob = Path.read_text, Path.rglob
        def checked_read(path, *args, **kwargs):
            assert path.suffix not in {".yaml", ".yml"} and "parameters" not in path.parts, path
            return read_text(path, *args, **kwargs)
        def checked_glob(path, *args, **kwargs):
            assert path not in {root / "infra", root / "framework"}, "full tree guard forbidden"
            return rglob(path, *args, **kwargs)
        argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--stack", "A", "--state", str(base / "session.json")]
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", side_effect=lambda command: "aws" if command == "aws" else None), \
                patch.object(M.time, "sleep", lambda _: None), patch.object(Path, "read_text", checked_read), patch.object(Path, "rglob", checked_glob), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            code = M.controller_main(argv, root)
            assert code == 0, (output.getvalue(), errors.getvalue())
            state = json.loads((base / "session.json").read_text())
            assert state["states"]["A"]["observedSynced"]
            counts = Counter(op for op, _ in fake.calls)
            assert counts["get-caller-identity"] == counts["delete-stack"] == counts["list-exports"] == 1
            assert not any(counts[op] for op in ("validate-template", "create-change-set", "execute-change-set", "get-template"))
            # Resume same immutable session: one additional authentication, no redelete or relist exports.
            assert M.controller_main(argv + ["--resume"], root) == 0
            assert sum(op == "list-exports" for op, _ in fake.calls) == 1
            assert fake.deleted == ["A"]
        print("D01: PASS real controller fake subprocess: STS=1, delete=1 by StackId, heavy AWS APIs=0")
        print("D14: PASS no template/parameter reads, infra/framework full guard scans or IaC tools")
        # --local-plan is genuinely offline, even before task creation.
        with patch.object(M.subprocess, "run", side_effect=AssertionError("local-plan used AWS")), redirect_stdout(io.StringIO()):
            assert M.controller_main(argv + ["--local-plan"], root) == 0
        # CLI sequential selects concurrency=1 without changing model limit.
        (base / "session.json").unlink()
        fake.absent.clear(); fake.completed.clear(); fake.deleted.clear()
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", return_value="aws"), \
                patch.object(M.time, "sleep", lambda _: None), redirect_stdout(io.StringIO()):
            assert M.controller_main(argv + ["--sequential"], root) == 0
        assert json.loads((base / "session.json").read_text())["identity"]["limit"] == 1
        # Profile mismatch blocks before any delete or STS.
        (base / "session.json").unlink()
        project = json.loads((root / "project.json").read_text()); project["targets"][0]["awsProfile"] = "configured"
        (root / "project.json").write_text(json.dumps(project)); fake.calls.clear()
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", return_value="aws"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert M.controller_main(argv + ["--profile", "other"], root) == 1
        assert not fake.calls


def check_observed():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"BLUEPRINT_TASK_FILE": "tasks/destroy.md"}):
        root = Path(directory); fixture(root, {"A": 30, "B": 20, "C": 10}, models=True)
        source = root / "model/dev/123456789012/ec2.properties"
        design = root / "docs/designs/dev/123456789012/ec2.md"
        before = properties(source.read_text())
        plan = M.local_plan(root, "dev", "123456789012", ["A", "B", "C"])
        assert set(plan["observed"]["paths"]) == {source.relative_to(root).as_posix(), design.relative_to(root).as_posix()}
        backend = Fake(["A", "B", "C"])
        backend.root, backend.environment, backend.directory = root, "dev", "123456789012"
        states = session({"A": 30, "B": 20, "C": 10})["states"]
        states["A"].update(status="DELETE_COMPLETE", StackId=stack_id("A"), deleteObserved=True)
        states["B"]["status"] = "DELETE_FAILED"
        calls = []
        destinations = observed.observed_destinations
        def counted_destinations(*args, **kwargs):
            output, views, sync = destinations(*args, **kwargs)
            real_sync = sync.sync
            def batch(*args, **kwargs):
                calls.append(kwargs.get("services"))
                return real_sync(*args, **kwargs)
            sync.sync = batch
            return output, views, sync
        with patch.object(observed, "observed_destinations", side_effect=counted_destinations), redirect_stdout(io.StringIO()):
            observed.sync_destroyed(backend, states, plan["observed"])
        after = properties(source.read_text())
        assert after["observed.row.001-002.value"] == "`PENDING_DEPLOY`"
        assert after["observed.row.099-002.value"] == "PENDING_DEPLOY"
        assert after["observed.row.002-002.value"] == before["observed.row.002-002.value"]
        assert after["observed.row.003-002.value"] == before["observed.row.003-002.value"]
        assert {key: value for key, value in before.items() if key.startswith("desired.")} == {key: value for key, value in after.items() if key.startswith("desired.")}
        assert states["A"]["observedSynced"] and not states["B"]["observedSynced"]
        assert "PENDING_DEPLOY" in design.read_text() and "vpc-old-A" not in design.read_text()
        assert calls == [["ec2"]]
        assert M.local_plan(root, "dev", "123456789012", ["A", "B", "C"]) == plan
        # Fresh absence must not synchronize even with a valid planned owner.
        absent = session({"A": 30})["states"]; absent["A"]["status"] = "ALREADY_ABSENT"
        snapshot = source.read_bytes(); observed.sync_destroyed(backend, absent, plan["observed"])
        assert source.read_bytes() == snapshot
        print("D12: PASS identifiers/incoming refs pending, desired unchanged, actual generation once")
        print("D13: PASS only proven A changed; failed B/unexecuted C unchanged")
        # Detect incoming links beyond target before mutation, not during successful-deletion sync.
        outside = root / "model/prod/999999999999/ec2.properties"; outside.parent.mkdir(parents=True)
        outside.write_text("desired.row.001-001.property=EC2.Subnet.VpcId\ndesired.row.001-001.value=[vpc](../../dev/123456789012/ec2.md#ec2-vpc-test-dev-a)\ndesired.row.001-001.comment=参照\n")
        rejects(lambda: M.local_plan(root, "dev", "123456789012", ["A"]), "task scope violation")
        outside.unlink()
        # Missing reservation blocks locally, before controller authentication.
        task = root / "tasks/destroy.md"; text = task.read_text(); task.write_text(text.replace("- `docs/designs/dev/123456789012/ec2.md`\n", ""))
        rejects(lambda: M.local_plan(root, "dev", "123456789012", ["A"]), "reservation")
        task.write_text(text)
        original = source.read_text(); source.write_text(original.replace("desired.resource.001.cfn-logicalId=A-Vpc\n", ""))
        rejects(lambda: M.local_plan(root, "dev", "123456789012", ["A"]), "explicit cfn-logicalId")


def main():
    check_order_and_safety()
    check_absence()
    check_controller()
    check_observed()
    print("cloudformation-destroy: PASS (D01-D14; fake AWS only)")


if __name__ == "__main__":
    main()

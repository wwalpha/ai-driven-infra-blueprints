#!/usr/bin/env python3
"""Fake-only destroy acceptance: no network, credentials or live AWS mutations."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
import json
import os
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import model.sources as _imports_model_sources
import pytest
import sync_runtime
from model.adapters import observed
from model.core import properties
from model.files import read_model
from model.render import markdown_for
from support.cloudformation_destroy_fixtures import (
    TARGET,
    Fake,
    M,
    rejects,
    session,
    stack_id,
)
from support.model_sources import allocate_fixture as allocate
from support.model_sources import snapshot_model, write_model
from support.pytest_cli import run
from support.repository_fixtures import fixture as repository
from support.repository_fixtures import git, start
from task_contract_core import selected_task
from utils.function_wrapper import BoundCallback as _bind_framework_callback

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")























def fixture(root, names, models=False):
    (root / "model/dev/123456789012").mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}) + "\n")
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for number, (name, order) in enumerate(names.items(), 1):
        values.update({f"desired.stack.{number:03d}.{key}": str(value) for key, value in
                       {"name": name, "deployOrder": order, "template": name + ".yaml", "parameters": name + ".json"}.items()})
    write_model(root / "model/dev/123456789012/cloudformation-stacks.properties", "\n".join(key + "=" + value for key, value in values.items()) + "\n")
    if models:
        values = {"desired.service.ec2.serviceId": "ec2", "desired.service.ec2.ownedCatalogResourceTypes": "EC2.VPC,EC2.Subnet",
                  "display.service.title": "# EC2 詳細設計"}
        for number, name in enumerate(names, 1):
            identity = f"{number:03d}"
            values.update({f"desired.resource.{identity}.resourceType": "EC2.VPC",
                f"desired.resource.{identity}.cfn-logicalId": name + "-Vpc",
                f"display.resource.{identity}.comment": "ネットワークを構成するresource"})
            values.update(allocate(values, [identity]))
            rows = [("Name", f"`vpc-test-dev-{name.lower()}`"),
                    ("VpcId", f"[{identity}](#resource-EC2_VPC_{identity})"),
                    ("CidrBlock", f"`10.{number}.0.0/16`")]
            for index, (prop, value) in enumerate(rows, 1):
                prefix = f"desired.row.{identity}-{index:03d}"
                values.update({prefix + ".property": "EC2.VPC." + prop, prefix + ".value": value, prefix + ".comment": "設定値"})
            for field in ("property", "comment"):
                values[f"observed.row.{identity}-002.{field}"] = values[f"desired.row.{identity}-002.{field}"]
            values[f"observed.row.{identity}-002.value"] = f"`vpc-old-{name}`"
        # An IMPORT consumer reference participates without stack-owned destruction.
        values.update({"desired.resource.099.resourceType": "EC2.Subnet",
            "desired.resource.099.resourceMode": "IMPORT",
            "display.resource.099.comment": "接続先subnet"})
        values.update(allocate(values, ['099']))
        for index, (prop, value) in enumerate([
            ("Name", "`sbnt-test-dev-private-app-a-01`"), ("VpcId", "[EC2_VPC_001](ec2.md#resource-EC2_VPC_001)"),
            ("SubnetId", "[EC2_Subnet_001](ec2.md#resource-EC2_Subnet_001)"), ("CidrBlock", "`10.1.1.0/24`")], 1):
            prefix = f"desired.row.099-{index:03d}"
            values.update({prefix + ".property": "EC2.Subnet." + prop, prefix + ".value": value, prefix + ".comment": "設定値"})
        values["observed.row.099-002.value"] = "`vpc-old-A`"
        values["observed.row.099-003.value"] = "`subnet-existing`"
        for rid in ("099-002", "099-003"):
            for field in ("property", "comment"):
                values[f"observed.row.{rid}.{field}"] = values[f"desired.row.{rid}.{field}"]
        source = root / "model/dev/123456789012/ec2.properties"
        write_model(source, "\n".join(key + "=" + value for key, value in values.items()) + "\n")
        design = root / "docs/designs/dev/123456789012/ec2.md"
        design.parent.mkdir(parents=True, exist_ok=True)
        design.write_text(markdown_for(design, values, root))
    # Start with a broad same-target contract to derive exact output paths mechanically.
    contract = root / "tasks/destroy.md"
    contract.parent.mkdir(exist_ok=True)
    paths = ["tasks/destroy.md"]
    paths += [path.relative_to(root).as_posix() for path in (root / "docs/designs").rglob("*.md")]
    paths += [path.relative_to(root).as_posix() for path in (root / "model").rglob("*.properties")]
    contract.write_text("# Destroy\n\n## Task contract\n\n- Task type: `infrastructure`\n- Task status: `running`\n"
                        "- Infrastructure phase: `destroy`\n- AWS API execution: `allowed`\n- Destroy: `allowed`\n"
                        "- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Destroy scope: " + " ".join("`" + name + "`" for name in names) +
                        "\n\n## Validation scope\n\n- `dev/123456789012/" + ("ec2" if models else "cloudformation-stacks") + "`\n"
                        "\n## Required changes\n\n- [R1] 明示scopeをdestroyする。\n\n## Acceptance checks\n\n- [R1] `exists:project.json`\n"
                        "\n## Modified files\n\n" + "\n".join("- `" + path + "`" for path in paths) +
                        "\n\n## Allowed paths\n\n" + "\n".join("- `" + path + "`" for path in paths) + "\n")
    return contract


def _callback_check_controller_checked_read(read_text, /, path, *args, **kwargs):
    assert path.suffix not in {".yaml", ".yml"} and "parameters" not in path.parts, path
    return read_text(path, *args, **kwargs)


def _callback_check_controller_aws_run(_state_check_controller_338, /, command, **kwargs):
    assert command[0] == "aws", command
    service_index = command.index("sts") if "sts" in command else command.index("cloudformation")
    response = _state_check_controller_338.fake.aws(command[service_index + 1], *command[service_index + 2:-3])
    if response is None:
        return SimpleNamespace(returncode=1, stdout="", stderr="An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id A does not exist")
    return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")


def _callback_check_controller_checked_glob(_state_check_controller_338, rglob, /, path, *args, **kwargs):
    assert path not in {_state_check_controller_338.root / "infra", _state_check_controller_338.root / "framework"}, "full tree guard forbidden"
    return rglob(path, *args, **kwargs)


def _callback_check_controller_mutate(_state_check_controller_338, original, task, /, name):
    if name == "A":
        if _state_check_controller_338.drift == "task":
            task.write_text(original + "\n")
        else:
            path = _state_check_controller_338.root / "issues/dev/123456789012/issues.md"
            path.parent.mkdir(parents=True)
            path.write_text("### cloudformation-stacks\n1. 未解決問題\n")


def check_controller(tmp_path):
    _state_check_controller_338 = _CallbackState()
    runner = M.run_session
    with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/destroy.md'}), patch.object(M, 'run_session', side_effect=lambda *args, **kwargs: runner(*args, **kwargs, sleep=lambda _: None)):
        base = tmp_path
        _state_check_controller_338.root = base / "repo"
        _state_check_controller_338.root.mkdir()
        fixture(_state_check_controller_338.root, {"A": 10})
        _state_check_controller_338.fake = Fake(["A"])
        # Use the real AWS backend/real context; subprocess is the sole fake boundary.
        aws_run = _bind_framework_callback(_callback_check_controller_aws_run, _state_check_controller_338)
        read_text, rglob = Path.read_text, Path.rglob
        checked_read = _bind_framework_callback(_callback_check_controller_checked_read, read_text)
        checked_glob = _bind_framework_callback(_callback_check_controller_checked_glob, _state_check_controller_338, rglob)
        argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--stack", "A", "--state", str(base / "session.json")]
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", side_effect=lambda command: "aws" if command == "aws" else None), \
                patch.object(M.tempfile, "gettempdir", return_value=str(base)), \
                patch.object(M.time, "sleep", lambda _: None), patch.object(Path, "read_text", checked_read), patch.object(Path, "rglob", checked_glob), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            code = M.controller_main(argv, _state_check_controller_338.root)
            assert code == 0, (output.getvalue(), errors.getvalue())
            state = json.loads((base / "session.json").read_text())
            assert state["states"]["A"]["observedSynced"]
            counts = Counter(op for op, _ in _state_check_controller_338.fake.calls)
            assert counts["get-caller-identity"] == counts["delete-stack"] == counts["list-exports"] == 1
            assert not any(counts[op] for op in ("validate-template", "create-change-set", "execute-change-set", "get-template"))
            # Resume same immutable session: one additional authentication, no redelete or relist exports.
            assert M.controller_main(argv + ["--resume"], _state_check_controller_338.root) == 0
            assert sum(op == "list-exports" for op, _ in _state_check_controller_338.fake.calls) == 1
            assert _state_check_controller_338.fake.deleted == ["A"]
            previous_calls = len(_state_check_controller_338.fake.calls)
            with patch.dict(os.environ, {"AWS_PROFILE": "different-resume-profile"}):
                assert M.controller_main(argv + ["--resume"], _state_check_controller_338.root) == 1
            assert len(_state_check_controller_338.fake.calls) == previous_calls
            state_path = base / "session.json"
            pristine = state_path.read_text()
            state = json.loads(pristine)
            state["states"]["A"]["DeployOrder"] = 99
            state_path.write_text(json.dumps(state))
            assert M.controller_main(argv + ["--resume"], _state_check_controller_338.root) == 1
            assert len(_state_check_controller_338.fake.calls) == previous_calls
            state_path.write_text(pristine)
        print("D01: PASS real controller fake subprocess: STS=1, delete=1 by StackId, heavy AWS APIs=0")
        # --local-plan is genuinely offline, even before task creation.
        with patch.object(M.subprocess, "run", side_effect=AssertionError("local-plan used AWS")), redirect_stdout(io.StringIO()):
            assert M.controller_main(argv + ["--local-plan"], _state_check_controller_338.root) == 0
        # CLI sequential selects concurrency=1 without changing model limit.
        (base / "session.json").unlink()
        _state_check_controller_338.fake.absent.clear()
        _state_check_controller_338.fake.completed.clear()
        _state_check_controller_338.fake.deleted.clear()
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", return_value="aws"), \
                patch.object(M.tempfile, "gettempdir", return_value=str(base)), \
                patch.object(M.time, "sleep", lambda _: None), redirect_stdout(io.StringIO()):
            assert M.controller_main(argv + ["--sequential"], _state_check_controller_338.root) == 0
        assert json.loads((base / "session.json").read_text())["identity"]["limit"] == 1
        # Profile mismatch blocks before any delete or STS.
        (base / "session.json").unlink()
        project = json.loads((_state_check_controller_338.root / "project.json").read_text())
        project["targets"][0]["awsProfile"] = "configured"
        (_state_check_controller_338.root / "project.json").write_text(json.dumps(project))
        _state_check_controller_338.fake.calls.clear()
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", return_value="aws"), \
                patch.object(M.tempfile, "gettempdir", return_value=str(base)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert M.controller_main(argv + ["--profile", "other"], _state_check_controller_338.root) == 1
        assert not _state_check_controller_338.fake.calls
        # Multiple deletes run the real lightweight guard; tree/body access remains trapped.
        _state_check_controller_338.root = base / "multi"
        _state_check_controller_338.root.mkdir()
        fixture(_state_check_controller_338.root, {"A": 30, "B": 20, "C": 10})
        _state_check_controller_338.fake = Fake(["A", "B", "C"])
        argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--stack", "A", "--stack", "B", "--stack", "C", "--state", str(base / "multi.json")]
        with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", side_effect=lambda command: "aws" if command == "aws" else None), \
                patch.object(M.tempfile, "gettempdir", return_value=str(base)), patch.object(M.time, "sleep", lambda _: None), \
                patch.object(Path, "read_text", checked_read), patch.object(Path, "rglob", checked_glob), \
                patch.object(M, "require_target_no_issues", wraps=M.require_target_no_issues) as issue_check, redirect_stdout(io.StringIO()):
            assert M.controller_main(argv, _state_check_controller_338.root) == 0
            assert issue_check.call_count == 1
        counts = Counter(op for op, _ in _state_check_controller_338.fake.calls)
        assert _state_check_controller_338.fake.deleted == ["A", "B", "C"]
        assert counts["get-caller-identity"] == counts["list-exports"] == 1 and counts["delete-stack"] == 3
        print("D14: PASS 3 real-guard deletes: STS=1, exports=1, issue check=1, full tree/body scans=0")
        # A relevant issue/task change after the first delete blocks subsequent starts.
        task = _state_check_controller_338.root / "tasks/destroy.md"
        original = task.read_text()
        for _state_check_controller_338.drift in ("task", "issue"):
            state_path = base / "multi.json"
            state_path.unlink()
            _state_check_controller_338.fake = Fake(["A", "B", "C"])
            mutate = _bind_framework_callback(_callback_check_controller_mutate, _state_check_controller_338, original, task)
            _state_check_controller_338.fake.hook = mutate
            with patch.object(M.subprocess, "run", side_effect=aws_run), patch("shutil.which", return_value="aws"), \
                    patch.object(M.tempfile, "gettempdir", return_value=str(base)), patch.object(M.time, "sleep", lambda _: None), redirect_stdout(io.StringIO()):
                assert M.controller_main(argv, _state_check_controller_338.root) == 1
            assert _state_check_controller_338.fake.deleted == ["A"] and not _state_check_controller_338.fake.running
            task.write_text(original)
            (_state_check_controller_338.root / "issues/dev/123456789012/issues.md").unlink(missing_ok=True)


@pytest.fixture
def managed_destroy_root():
    with repository() as primary:
        fixture(primary, {"A": 30, "B": 20, "C": 10}, models=True)
        git(primary, 'add', 'project.json', 'model', 'docs')
        git(primary, 'commit', '-qm', 'synthetic IMPORT baseline')
        root, state = start(primary, task_id='destroy', files=('file.txt',))
        with selected_task(root, state['task_file']):
            yield root


def _callback_check_observed_batch(calls, real_sync, /, *args, **kwargs):
    calls.append(kwargs.get("services"))
    return real_sync(*args, **kwargs)


def check_observed(managed_destroy_root):
    with patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': 'tasks/destroy.md'}):
        root = managed_destroy_root
        fixture(root, {"A": 30, "B": 20, "C": 10}, models=True)
        source = root / "model/dev/123456789012/ec2.properties"
        design = root / "docs/designs/dev/123456789012/ec2.md"
        # A planned resource's legacy ID is not a stack mapping (SnowCatConn case).
        baseline_values = properties(read_model(source))
        values = dict(baseline_values)
        for key, value in list(values.items()):
            if key.startswith(("desired.resource.003.", "display.resource.003.", "desired.row.003-", "observed.row.003-")):
                values[key.replace(".003", ".004", 1)] = value.replace("test-dev-c", "test-dev-unimplemented").replace("vpc-old-C", "PENDING_DEPLOY").replace("[003]", "[SnowCatConn]")
        del values["desired.resource.004.cfn-logicalId"]
        values["desired.resource.004.logicalId"] = "EC2_VPC_004"
        values["desired.resource.004.anchor"] = "resource-EC2_VPC_004"
        values["desired.service.identity.lastAllocated"] = '{"EC2.VPC":4,"EC2.Subnet":1}'
        values["desired.row.004-002.value"] = "[EC2_VPC_004](ec2.md#resource-EC2_VPC_004)"
        write_model(source, "\n".join(key + "=" + value for key, value in values.items()) + "\n")
        rejects(lambda: markdown_for(design, values, root), "cfn-logicalId")
        before = properties(read_model(source))
        plan = M.local_plan(root, "dev", "123456789012", ["A", "B", "C"])
        assert plan["observed"]["unmappedResources"] == [{
            "model": source.relative_to(root).as_posix(), "resource": "004", "logicalId": "EC2_VPC_004",
            "reason": "no cfn-logicalId; no observed identifier"}]
        assert all(owner["resource"] != "004" for owners in plan["observed"]["owners"].values() for owner in owners)
        assert all(not key.startswith("observed.row.004-")
                   for changes in plan["observed"]["updates"].values() for updates in changes.values() for key in updates)
        assert set(plan["observed"]["paths"]) == {design.relative_to(root).as_posix(), source.relative_to(root).as_posix()}
        write_model(source, baseline_values)
        before = properties(read_model(source))
        plan = M.local_plan(root, "dev", "123456789012", ["A", "B", "C"])
        assert not plan["observed"]["unmappedResources"]
        backend = Fake(["A", "B", "C"])
        backend.root, backend.environment, backend.directory = root, "dev", "123456789012"
        states = session({"A": 30, "B": 20, "C": 10})["states"]
        states["A"].update(status="DELETE_COMPLETE", StackId=stack_id("A"), deleteObserved=True)
        states["B"]["status"] = "DELETE_FAILED"
        calls = []
        real_sync = sync_runtime.sync
        batch = _bind_framework_callback(_callback_check_observed_batch, calls, real_sync)
        with patch.object(sync_runtime, "sync", side_effect=batch), redirect_stdout(io.StringIO()):
            observed.sync_destroyed(backend, states, plan["observed"])
        after = properties(read_model(source))
        assert after["observed.row.001-002.value"] == "`PENDING_DEPLOY`"
        assert after["observed.row.099-002.value"] == "PENDING_DEPLOY"
        assert after["observed.row.002-002.value"] == before["observed.row.002-002.value"]
        assert after["observed.row.003-002.value"] == before["observed.row.003-002.value"]
        assert "observed.row.004-002.value" not in after
        assert {key: value for key, value in before.items() if key.startswith("desired.")} == {key: value for key, value in after.items() if key.startswith("desired.")}
        assert states["A"]["observedSynced"] and not states["B"]["observedSynced"]
        assert "PENDING_DEPLOY" in design.read_text() and "vpc-old-A" not in design.read_text()
        assert calls == [["ec2"]]
        assert M.local_plan(root, "dev", "123456789012", ["A", "B", "C"]) == plan
        batched = session({"A": 30, "B": 20, "C": 10})["states"]
        for name in ("A", "B"):
            batched[name].update(status="DELETE_COMPLETE", StackId=stack_id(name), deleteObserved=True)
        calls.clear()
        with patch.object(sync_runtime, "sync", side_effect=batch), redirect_stdout(io.StringIO()):
            observed.sync_destroyed(backend, batched, plan["observed"])
        assert calls == [["ec2"]] and all(batched[name]["observedSynced"] for name in ("A", "B"))
        assert properties(read_model(source))["observed.row.002-002.value"] == "`PENDING_DEPLOY`"
        # Fresh absence must not synchronize even with a valid planned owner.
        absent = session({"A": 30})["states"]
        absent["A"]["status"] = "ALREADY_ABSENT"
        snapshot = snapshot_model(source)
        observed.sync_destroyed(backend, absent, plan["observed"])
        assert snapshot_model(source) == snapshot
        print("D12: PASS identifiers/incoming refs pending, desired unchanged, actual generation once")
        print("D13: PASS only proven A changed; failed B/unexecuted C unchanged")
        # Detect incoming links beyond target before mutation, not during successful-deletion sync.
        project = json.loads((root / "project.json").read_text())
        project["targets"].append({"environment": "prod", **TARGET, "awsAccountId": "999999999999"})
        (root / "project.json").write_text(json.dumps(project) + "\n")
        outside = root / "model/prod/999999999999/ec2.properties"
        outside.parent.mkdir(parents=True)
        write_model(outside, 'desired.resource.001.resourceType=EC2.Subnet\ndesired.resource.001.logicalId=EC2_Subnet_001\ndesired.resource.001.anchor=resource-EC2_Subnet_001\ndesired.service.identity.lastAllocated={"EC2.Subnet":1}\ndesired.row.001-001.property=EC2.Subnet.VpcId\ndesired.row.001-001.value=[EC2_VPC_001](../../dev/123456789012/ec2.md#resource-EC2_VPC_001)\ndesired.row.001-001.comment=参照\n')
        rejects(lambda: M.local_plan(root, "dev", "123456789012", ["A"]), "task scope violation")
        model_parts = _imports_model_sources.model_parts
        for file in model_parts(outside):
            file.unlink()
        outside.unlink(missing_ok=True)
        original = read_model(source)
        write_model(source, original.replace("desired.resource.001.cfn-logicalId=A-Vpc\n", ""))
        # Pending/absent identifiers can stay unmapped, even with a legacy ID.
        pending = M.local_plan(root, "dev", "123456789012", ["A"])
        assert pending["observed"]["owners"]["A"] == []
        assert {entry["resource"] for entry in pending["observed"]["unmappedResources"]} == {"001"}
        write_model(source, read_model(source).replace("observed.row.001-002.value=`PENDING_DEPLOY`", "observed.row.001-002.value=`vpc-existing`"))
        rejects(lambda: M.local_plan(root, "dev", "123456789012", ["A"]), "explicit cfn-logicalId")
        write_model(source, original.replace("desired.resource.002.cfn-logicalId=B-Vpc", "desired.resource.002.cfn-logicalId=A-Vpc"))
        rejects(lambda: M.local_plan(root, "dev", "123456789012", ["A"]), "duplicate ownership")
        print("D15: PASS unmapped pending design reported/unchanged; observed and duplicate ownership still block")






def main():
    return run(__file__, message='cloudformation-destroy: PASS (D01-D16; fake AWS only)')


if __name__ == "__main__":
    raise SystemExit(main())

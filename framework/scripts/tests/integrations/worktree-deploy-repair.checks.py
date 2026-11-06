#!/usr/bin/env python3
"""Production controller -> one-shot Implement -> independent Deploy and publication."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import subprocess
import tempfile
from types import SimpleNamespace

import pytest
import worktree_task as wt
from deploy import handoff
from deploy.contracts import accepted_changes, sha
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    clients,
    drive,
    git,
)
from support.worktree_deploy_fixtures import seed
from task_contract_core import read_task_snapshot, selected_task, start, suspend
from task_contract_runtime import complete, resume
from utils.local_evidence import evidence_store, write_sealed

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture(autouse=True)
def private_temporary_directory(tmp_path, monkeypatch):
    # Real target locks and evidence files remain active, in this fixture's OS temp area.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(tmp_path))


def _callback_external_round_trip_lifecycle(command, target, identity, *options):
    env = child_environment() | {"BLUEPRINT_TASK_FILE": "tasks/" + identity + ".md"}
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(wt.__file__)),
            command,
            "--repository-root",
            str(target),
            "--task-name" if command == "create" else "--task-id",
            identity,
            *map(str, options),
        ],
        cwd=target,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _callback_external_round_trip_record_validation(
    diagnostics, real_run, /, command, *args, **kwargs
):
    result = real_run(command, *args, **kwargs)
    if "--fresh" in command:
        diagnostics.append(result.stdout + result.stderr)
    return result


def _dependency_read(fake, operation, **kwargs):
    return getattr(fake, operation)(**kwargs)


def validate_parent(parent):
    interpreter, environment = wt.python_env.runtime(parent)
    command = [
        str(interpreter),
        "-B",
        str(Path(wt.__file__).with_name("blueprint-loop.py")),
        "--mode",
        "task",
        "--task-file",
        f"tasks/{parent.name}.md",
        "--fresh",
    ]
    checked = subprocess.run(
        command, cwd=parent, env=environment, capture_output=True, text=True, timeout=90
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def prepared_request(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, dict, str]:
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    parent = seed(tmp_path / "project", report, "repair")
    monkeypatch.chdir(parent)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{parent.name}.md")
    aws_state(aws)
    provider = json.loads(aws.read_text())
    name = "cfn-stack-app-dev-second"
    provider["stacks"][name] = {
        "status": "UPDATE_COMPLETE",
        "id": f"arn:aws:cloudformation:ap-northeast-1:{ACCOUNT}:stack/{name}/fixture",
    }
    aws.write_text(json.dumps(provider))
    relative = "infra/cloudformation/templates/second.yaml"
    model = f"model/dev/{ACCOUNT}/ec2.properties"
    task = read_task_snapshot(parent, f"tasks/{parent.name}.md", live=True)
    target = json.loads((parent / "project.json").read_text())["targets"][0]
    # The normal Implement entrance consumes an already diagnosed failure proof.
    # Controller failure injection and classification belong to UT.
    failure = handoff.record_failure(
        SimpleNamespace(
            root=parent,
            states={
                "cfn-stack-app-dev-second": {
                    "status": "FAILED",
                    "failure": {
                        "classification": "IAC_CANDIDATE",
                        "executionState": "NOT_EXECUTED",
                    },
                }
            },
            run_context={
                "taskFile": task.name,
                "taskDigest": task.task_digest,
                "consumedInputs": {relative: sha(parent / relative)},
                "modelInputs": {model: sha(parent / model)},
            },
            target=target,
            environment="dev",
            directory=ACCOUNT,
        )
    )
    diagnosis = {
        "cfn-stack-app-dev-second": {
            "reason": "The current failed VPC CidrBlock differs from its explicitly approved Model value.",
            "inputRefs": [{"path": relative, "sha256": sha(parent / relative)}],
            "modelRefs": [
                {
                    "path": model,
                    "sha256": sha(parent / model),
                    "key": "desired.row.001-002.value",
                }
            ],
        }
    }
    fake = clients(parent, report, aws)(None, "cloudformation")

    reader = _bind_framework_callback(_dependency_read, fake)
    journal = report.with_suffix(".operations.json")
    with (
        patch.object(handoff, "dependency_reader", return_value=reader),
        patch.object(handoff.operation_journal, "location", return_value=journal),
    ):
        request = handoff.issue_request(parent, Path(failure), diagnosis, [relative])
    request_path = (
        evidence_store(parent)
        / ("deploy-repair-" + request["requestId"])
        / "request.json"
    )
    request_path.parent.mkdir()
    write_sealed(parent, request_path, request)
    with (
        patch.object(handoff, "dependency_reader", return_value=reader),
        patch.object(handoff.operation_journal, "location", return_value=journal),
    ):
        request = wt.deploy_checkpoint(parent, parent.name, request_path)
    return parent, report, aws, request, relative


def check_external_implement_round_trip(tmp_path, monkeypatch):
    parent, report, aws, request, relative = prepared_request(tmp_path, monkeypatch)
    request_path = Path(request["requestPath"])
    request, result_path = managed_delivery(parent, request, relative)
    assert git(parent, "rev-parse", "HEAD").strip() == request["commit"]
    assert not result_path.exists() and not request_path.parent.exists()
    with selected_task(parent, f"tasks/{parent.name}.md"):
        assert accepted_changes(
            parent, (parent / f"tasks/{parent.name}.md").read_text(), {relative}
        ) == {relative}
    # Independent current-input Deploy is a separate invocation, with no result/session entrance.
    assert drive(parent, report, aws) == 0
    assert git(parent, "rev-parse", "HEAD").strip() == request["commit"]
    assert not report.with_suffix(".operations.json").exists()
    validate_parent(parent)


def managed_delivery(
    parent: Path,
    request: dict,
    relative: str,
) -> tuple[dict, Path]:
    assert request["parentTip"] == git(parent, "rev-parse", "HEAD").strip()
    suspend(
        parent,
        f"tasks/{parent.name}.md",
        "authorized external implement repair " + request["requestId"],
    )
    child_state = _callback_external_round_trip_lifecycle(
        "create", parent, "repair-one", "--repair-request", request["requestPath"]
    )
    child = Path(child_state["worktree"])
    assert git(child, "rev-parse", "HEAD").strip() == request["parentTip"]
    child_task = child_state["task_file"]
    child_id = child_state["task_id"]
    assert child_state["task_name"] == "repair-one"
    assert child_task == f"tasks/{child_id}.md"
    assert wt.load(parent, parent.name)[3]["iacRepair"]["childTask"] == child_id
    paths = "\n".join("- `" + p + "`" for p in [child_task, relative])
    contract = (
        "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n"
        "- Infrastructure phase: `implement`\n- AWS API execution: `forbidden`\n- AWS mutation: `forbidden`\n- Deploy/apply: `forbidden`\n"
        f"- Target environment: `dev`\n- Target AWS account: `{ACCOUNT}`\n- Deploy repair request: `{request['requestPath']}`\n"
        "## Required changes\n- [R1] Correct approved Vpc CidrBlock\n## Acceptance checks\n- [R1] `changed:"
        + relative
        + "`\n"
        "## Validation scope\n"
        + "".join("- `" + scope + "`\n" for scope in request["validationScope"])
        + "## Modified files\n"
        + paths
        + "\n## Allowed paths\n"
        + paths
        + "\n"
    )
    start(child, child_task, contract)
    (child / relative).write_text(
        (child / relative).read_text().replace("10.2.0.0/16", "10.0.0.0/16")
    )
    real_run, diagnostics = subprocess.run, []
    record_validation = _bind_framework_callback(
        _callback_external_round_trip_record_validation, diagnostics, real_run
    )
    with (
        selected_task(child, child_task),
        patch.object(subprocess, "run", side_effect=record_validation),
    ):
        _callback_external_round_trip_lifecycle(
            "repair-validate",
            child,
            child_id,
            "--repair-request",
            request["requestPath"],
        )
        complete(child, child_task)
    result = _callback_external_round_trip_lifecycle("finalize", child, child_id)
    result_path = Path(result["repair_result"])
    assert (
        result_path.is_file()
        and git(parent, "rev-parse", "HEAD").strip() == result["tip"]
    )
    wt.automatic_cleanup(parent, child_id)
    assert not child.exists()
    resume(parent, f"tasks/{parent.name}.md")
    return {**request, "commit": result["commit"]}, result_path


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

#!/usr/bin/env python3
"""Presentation contracts: no AWS calls, mutation, inferred approval or normal retries."""

import json
import shlex
import sys
from argparse import Namespace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import deploy_handoff
import pytest
from deploy import cli_guidance as G
from deploy import controller, failures, preparation
from model.core import ReferenceResolutionError
from support.fixture_cases import load_case
from support.regression_cases import case_ids
from utils.aws.identity import IdentityError
from utils.cloudformation.environment import EnvironmentValuePending

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]
ARGS = Namespace(
    environment="dev",
    alias="app",
    aws_account_id=None,
    stack=["app-network", "app-worker"],
    profile="app dev",
    sequential=True,
)


def exception_route_case(case):
    data = case["data"]
    constructors = {
        "ValueError": ValueError,
        "InputChanged": G.InputChanged,
        "OSError": OSError,
        "IdentityError": IdentityError,
        "RuntimeError": RuntimeError,
    }
    error = constructors[data["errorType"]](data["message"])
    report = G.stopped(data["stage"], error)
    if data["message"] in json.dumps(report):
        pytest.fail("guidance exposed a synthetic protected value", pytrace=False)
    TestCase().assertEqual(report["nextAction"]["type"], data["nextAction"])
    TestCase().assertIsNone(report["nextAction"]["command"])
    TestCase().assertTrue(report["cause"]["detailDigest"])
    return report


@pytest.mark.parametrize("case_id", case_ids("deploy_cli_guidance"))
def check_exception_routes_do_not_echo_secrets(case_runner, case_id):
    case_runner.run("deploy_cli_guidance", case_id, exception_route_case)


def error_with_synthetic_leak(describe, error):
    return {**describe(error), "detail": "private-secret"}


def check_error_secret_guard_precedes_snapshot(monkeypatch):
    monkeypatch.setattr(
        G, "safe_error", partial(error_with_synthetic_leak, G.safe_error)
    )
    with pytest.raises(pytest.fail.Exception, match="protected value"):
        exception_route_case(load_case("deploy_cli_guidance", "error-01"))



def check_local_completion_guidance():
    assert "Git integration is separate" in G.CONTROLLER_HELP
    assert "not a Git checkpoint" in G.CONTROLLER_HELP



def check_missing_template_safe_diagnostic():
    path = "/private/task/inputs-123/App.json"
    error = FileNotFoundError(2, "secret", path)
    report = G.stopped("STEP", error, template_paths={path})["cause"]
    assert report["code"] == "FILE_NOT_FOUND"
    assert report["path"] == path and report["errno"] == 2
    assert report["operation"] == "access"
    hidden = G.stopped("STEP", error)["cause"]
    assert path not in json.dumps(hidden) and "secret" not in json.dumps(hidden)


def check_missing_template_operation_and_errno(tmp_path):
    path = tmp_path / "inputs-missing" / "App.json"
    try:
        path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        result = G.stopped("STEP", error, template_paths={str(path)})["cause"]
        assert result["path"] == str(path)
        assert result["errno"] == 2 and result["operation"] in {"open", "read"}
        assert str(path) not in json.dumps(G.stopped("STEP", error))
    else:
        pytest.fail("missing template unexpectedly existed")


def check_pending_failure_uses_type_not_prose():
    state = {"status": "BLOCKED"}
    failures.exception(state, EnvironmentValuePending("secret"), "PREPARATION")
    assert state["failure"]["classification"] == "NEEDS_HUMAN"
    assert state["failure"]["dependencyWait"] is True
    failures.exception(state, ValueError("PENDING_DEPLOY"), "PREPARATION")
    assert state["failure"]["classification"] == "NEEDS_HUMAN"


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize(
    "filename", ["preparation.json", "approved plan's $(ignored).json"]
)
def check_preparation_success_output(tmp_path, capsys, registered, filename):
    root, logs = tmp_path / "repo", tmp_path / "logs"
    root.mkdir()
    logs.mkdir()
    plan = logs / filename
    with (
        patch.object(G, "command_environment", return_value=["env"]),
        patch.object(
            preparation,
            "register" if registered else "prepare",
            return_value={
                "preparationSeconds": 0,
                "within60Seconds": True,
                "contract": "contract.md",
                "targetSummary": "target-summary.json",
            },
        ),
    ):
        args = ["--repository-root", str(root)]
        args += (
            ["--register", str(plan)]
            if registered
            else [
                "--environment",
                "dev",
                "--alias",
                "app",
                "--stack",
                "App",
                "--service",
                "ec2",
                "--task-file",
                "tasks/deploy-app.md",
                "--log-dir",
                str(logs),
            ]
        )
        assert preparation.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["result"] == ("REGISTERED" if registered else "PREPARED_OFFLINE")
    TestCase().assertEqual(report["executionMethod"], "sdk")
    assert {
        "plan",
        "contract",
        "targetSummary",
        "timing",
        "preparationSeconds",
        "within60Seconds",
    } <= report.keys()
    if registered:
        argv = shlex.split(report["nextAction"]["command"].split(" && ", 1)[1])
        assert argv[-2:] == ["--run-controller", str(plan)]
        assert report["plan"] == str(plan)
        assert sys.executable in argv
    else:
        assert report["nextAction"]["command"] is None
        assert Path(report["plan"]).is_file()
        assert Path(report["plan"]).name == "preparation.json"


def check_preparation_and_handoff_keep_failure_exit_codes(tmp_path, capsys):
    with patch.object(preparation, "register", side_effect=G.InputChanged("secret")):
        assert (
            preparation.main(
                [
                    "--repository-root",
                    str(tmp_path / "repo"),
                    "--register",
                    str(tmp_path / "plan.json"),
                ]
            )
            == 1
        )
    report = json.loads(capsys.readouterr().out)
    TestCase().assertEqual(report["executionMethod"], "sdk")
    assert report["nextAction"]["type"] == "PREPARE_AGAIN"
    with patch.object(
        deploy_handoff.handoff, "discard_failure", side_effect=ValueError("secret")
    ):
        assert (
            deploy_handoff.main(
                [
                    "--repository-root",
                    str(tmp_path / "repo"),
                    "--failure",
                    str(tmp_path / "failure.json"),
                    "--discard-failure",
                ]
            )
            == 2
        )
    assert json.loads(capsys.readouterr().out)["nextAction"]["command"] is None


def check_action_is_required(tmp_path):
    with pytest.raises(SystemExit) as error:
        controller.controller_main(
            ["--environment", "dev", "--alias", "app", "--stack", "app"], tmp_path
        )
    assert error.value.code == 2


def check_handled_controller_stop_prints_one_json(tmp_path, capsys):
    with patch.object(
        controller.steps.context,
        "load_target",
        side_effect=ValueError("private-secret"),
    ):
        assert (
            controller.main(
                [
                    "--environment",
                    "dev",
                    "--alias",
                    "app",
                    "--stack",
                    "app",
                    "--action",
                    "advance",
                ],
                root=tmp_path,
            )
            == 2
        )
    report = json.loads(capsys.readouterr().out)
    assert report["result"] == "STOPPED" and report["stage"] == "STEP"


def check_structured_reference_cause_and_handoff_command(tmp_path):
    error = ReferenceResolutionError(
        "private-secret", category="REFERENCE_PENDING_DEPLOY"
    )
    report = G.stopped("GENERATION", error)
    assert report["nextAction"]["type"] == "DEPENDENCY_WAIT"
    assert report["cause"]["diagnosticCategories"] == ["REFERENCE_PENDING_DEPLOY"]
    state = {"status": "BLOCKED"}
    failures.exception(state, error, "PREPARATION")
    assert state["failure"]["classification"] == "NEEDS_HUMAN"
    assert state["failure"]["dependencyWait"] is True
    with patch.object(G, "command_environment", return_value=["env"]):
        report = G.handoff_result(
            {
                "requestId": "current-id",
                "taskFile": "tasks/parent.md",
                "repository": str(tmp_path),
            }
        )
    argv = shlex.split(report["nextAction"]["command"].split(" && ", 1)[1])
    assert sys.executable in argv
    assert "BLUEPRINT_TASK_FILE=tasks/parent.md" in argv
    assert argv[-4:] == [
        "--task-file",
        "tasks/parent.md",
        "--suspend-reason",
        "one-shot implement repair current-id",
    ]
    assert "--resume" not in argv and "--repair-request" not in argv


@pytest.mark.parametrize(
    ("error", "code", "details"),
    [
        (
            FileNotFoundError(
                2, "private-secret", "/tmp/repo/model/dev/app/kms.properties"
            ),
            "FILE_NOT_FOUND",
            {"target": "model/dev/app/kms.properties"},
        ),
        (
            json.JSONDecodeError("private-secret", "private-secret", 1),
            "InputDecodeError",
            {"line": 1, "column": 2},
        ),
        (
            G.PreparationError(
                "private-secret",
                code="PREPARATION_ENVIRONMENT_INCOMPLETE",
                missing=["boto3", "git", "pip-check", "private-secret"],
            ),
            "PREPARATION_ENVIRONMENT_INCOMPLETE",
            {"missingConditions": ["boto3", "git", "pip-check"]},
        ),
        (
            G.InputChanged(
                "private-secret",
                target="model/dev/app/iam/part-001.properties",
                condition="input-file",
            ),
            "PREPARATION_INPUT_CHANGED",
            {
                "target": "model/dev/app/iam/part-001.properties",
                "condition": "input-file",
            },
        ),
        (IdentityError("private-secret", "AccountMismatch"), "AccountMismatch", {}),
    ],
)
def check_known_error_details(error, code, details):
    report = G.stopped("PREPARATION", error)
    assert report["cause"]["code"] == code
    assert details.items() <= report["cause"].items()
    assert report["cause"]["detailDigest"]
    assert "private-secret" not in json.dumps(report)
    assert report["nextAction"]["command"] is None


def check_reference_diagnostics_filter_values():
    error = ReferenceResolutionError(
        "private-secret",
        category="REFERENCE_PENDING_DEPLOY",
        code="REFERENCE_PENDING_DEPLOY",
        model="/tmp/repo/model/dev/app/codebuild.properties",
        modelKey="desired.row.001-002.value",
        producerModel="/tmp/repo/model/dev/app/kms.properties",
        targetLogicalId="KMS_Key_001",
        attribute="KeyId",
        pointer="/Environment/Secret/private-secret",
        value="private-secret",
        action="private-secret",
        credential="private-secret",
    )
    report = G.stopped("GENERATION", error)
    diagnostic = report["cause"]["diagnostics"][0]
    assert diagnostic == {
        "category": "REFERENCE_PENDING_DEPLOY",
        "code": "REFERENCE_PENDING_DEPLOY",
        "status": "WARNING",
        "model": "model/dev/app/codebuild.properties",
        "modelKey": "desired.row.001-002.value",
        "producerModel": "model/dev/app/kms.properties",
        "targetLogicalId": "KMS_Key_001",
        "attribute": "KeyId",
    }
    assert "private-secret" not in json.dumps(report)
    error.diagnostics = [
        {
            "code": "Token=private-secret",
            "category": "private-secret",
            "status": "private-secret",
            "model": "/tmp/private-secret",
            "producerModel": "model/dev/app/../private-secret.properties",
            "modelKey": "desired.row.001.value=private-secret",
            "attribute": "private-secret",
            "targetLogicalId": "Credential=private-secret",
            "message": "private-secret",
        }
    ]
    assert G.safe_error(error)["diagnostics"] == [{}]


def check_preparation_dependency_json(tmp_path, capsys):
    with (
        patch.object(
            preparation.importlib,
            "import_module",
            side_effect=ImportError("private-secret"),
        ),
        patch.object(
            preparation.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=1, stdout="private-secret", stderr=""
            ),
        ),
        patch.object(preparation.shutil, "which", return_value=None),
    ):
        assert (
            preparation.main(
                [
                    "--repository-root",
                    str(tmp_path / "repo"),
                    "--environment",
                    "dev",
                    "--alias",
                    "app",
                    "--stack",
                    "App",
                    "--service",
                    "ec2",
                    "--task-file",
                    "tasks/deploy-app.md",
                    "--log-dir",
                    str(tmp_path / "logs"),
                ]
            )
            == 1
        )
    report = json.loads(capsys.readouterr().out)
    TestCase().assertEqual(report["executionMethod"], "sdk")
    assert report["cause"]["missingConditions"] == [
        "boto3",
        "botocore",
        "PyYAML",
        "pip-check",
        "git",
    ]
    assert "private-secret" not in json.dumps(report)


def check_unknown_error_fields_and_environment_fail_closed(tmp_path):
    error = ValueError("private-secret PENDING_DEPLOY missing token credential")
    error.code = ["private-secret"]
    report = G.stopped("PREPARATION", error)
    assert report["nextAction"]["type"] == "HUMAN_REVIEW"
    assert report["nextAction"]["command"] is None and report["cause"]["code"] is None
    assert "private-secret" not in json.dumps(report)
    with patch.object(G, "command_environment", return_value=None):
        assert (
            G.preparation_result(tmp_path, tmp_path / "plan.json", True)["nextAction"][
                "command"
            ]
            is None
        )
        assert (
            G.handoff_result(
                {
                    "repository": str(tmp_path),
                    "taskFile": "tasks/parent.md",
                    "requestId": "current-id",
                }
            )["nextAction"]["command"]
            is None
        )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

#!/usr/bin/env python3
"""Presentation contracts: no AWS calls, mutation, inferred approval or normal retries."""

import ast
import copy
import json
import re
import shlex
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import deploy_handoff
import pytest
from deploy import cli_guidance as G
from deploy import controller, failures, preparation
from model.core import ReferenceResolutionError
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


@pytest.mark.parametrize(
    ("result", "context", "kind", "stage"),
    [
        ("COMPLETE", {}, "VERIFY_TASK", "COMPLETE"),
        (
            "STOPPED",
            {
                "states": {
                    "a": {
                        "status": "BLOCKED",
                        "failure": {"classification": "APPROVAL"},
                    }
                }
            },
            "HUMAN_APPROVAL",
            "CHANGESET_REVIEW",
        ),
        (
            "STOPPED",
            {
                "states": {
                    "a": {
                        "status": "BLOCKED",
                        "failure": {"classification": "AUTHORIZATION"},
                    }
                }
            },
            "CONTEXT_REVIEW",
            "AWS_AUTHORIZATION",
        ),
        (
            "STOPPED",
            {
                "states": {
                    "a": {
                        "status": "BLOCKED",
                        "failure": {
                            "classification": "NEEDS_HUMAN",
                            "dependencyWait": True,
                        },
                    }
                }
            },
            "DEPENDENCY_WAIT",
            "PREPARATION",
        ),
        (
            "STOPPED",
            {
                "states": {
                    "a": {
                        "status": "BLOCKED",
                        "failure": {
                            "stage": "CHANGESET_REVIEW",
                            "classification": "NEEDS_HUMAN",
                        },
                    }
                }
            },
            "HUMAN_REVIEW",
            "CHANGESET_REVIEW",
        ),
        (
            "STOPPED",
            {
                "states": {
                    "a": {
                        "status": "FAILED",
                        "failure": {
                            "stage": "EXECUTE",
                            "classification": "NEEDS_HUMAN",
                        },
                    }
                }
            },
            "HUMAN_REVIEW",
            "EXECUTE",
        ),
        (
            "STOPPED",
            {"observedError": "secret=never-return"},
            "HUMAN_REVIEW",
            "OBSERVED",
        ),
        (
            "STOPPED",
            {"generationError": "secret=never-return"},
            "HUMAN_REVIEW",
            "GENERATION",
        ),
        (
            "STOPPED",
            {"pendingGeneration": {"ec2.md": {"reason": "REFERENCE_PENDING_DEPLOY"}}},
            "DEPENDENCY_WAIT",
            "GENERATION",
        ),
        (
            "STOPPED",
            {
                "states": {
                    "a": {
                        "status": "BLOCKED",
                        "reason": "PENDING_DEPLOY approval recover execute repair",
                    }
                }
            },
            "HUMAN_REVIEW",
            "CONTROLLER",
        ),
    ],
)
def check_controller_routes(result, context, kind, stage):
    original = copy.deepcopy(context)
    report = G.controller_result(
        result, context, ARGS, ROOT, repair_failure="/tmp/failure.json"
    )
    assert report["nextAction"]["type"] == kind and report["stage"] == stage
    assert report["nextAction"]["command"] is None
    assert "never-return" not in json.dumps(report)
    assert context == original


@pytest.mark.parametrize("authority", [False, True])
@pytest.mark.parametrize(
    "classification",
    ["IAC_CANDIDATE", "NEEDS_HUMAN", "APPROVAL", "AUTHORIZATION", "DEPENDENCY_WAIT"],
)
def check_repair_candidate_requires_structured_cause_and_authority(
    authority, classification
):
    context = {
        "states": {
            "a": {"status": "BLOCKED", "failure": {"classification": classification}}
        }
    }
    report = G.controller_result(
        "STOPPED",
        context,
        ARGS,
        ROOT,
        repair_failure="/tmp/failure.json",
        task_text="- External IaC repair: `allowed`" if authority else "",
    )
    assert (report["nextAction"]["type"] == "INVESTIGATE_IAC") == (
        authority and classification == "IAC_CANDIDATE"
    )
    assert report["nextAction"]["command"] is None


@pytest.mark.parametrize(
    "state",
    [
        {"status": "RUNNING"},
        {"status": "BLOCKED", "failure": {"executionState": "UNKNOWN"}},
    ],
)
def check_unknown_execution_only_proposes_original_recovery(tmp_path, state):
    root = tmp_path / "repo with spaces"
    context = {"taskFile": "tasks/current-task.md", "states": {"a": state}}
    with patch.object(G, "command_environment", return_value=["env"]):
        report = G.controller_result("STOPPED", context, ARGS, root)
    command = report["nextAction"]["command"]
    argv = shlex.split(command.split(" && ", 1)[1])
    assert "BLUEPRINT_TASK_FILE=tasks/current-task.md" in argv
    assert str(ROOT / "framework/scripts/run-python.py") in argv
    assert shlex.split(command.split(" && ", 1)[0]) == ["cd", str(root)]
    assert argv[argv.index("--profile") + 1] == "app dev"
    assert argv.count("--stack") == 2 and argv[-2:] == ["--action", "status"]
    assert "--approve-change-set" not in argv and "--resume" not in argv
    with patch.object(controller.steps, "run", return_value=0) as run:
        assert (
            controller.controller_main(argv[argv.index("--environment") :], root) == 0
        )
    assert run.call_args.args[0].action == "status"
    context.pop("taskFile")
    assert (
        G.controller_result("STOPPED", context, ARGS, root)["nextAction"]["command"]
        is None
    )


@pytest.mark.parametrize(
    ("stage", "error", "kind"),
    [
        ("PREPARATION", ValueError("private-secret"), "HUMAN_REVIEW"),
        ("REGISTRATION", G.InputChanged("private-secret"), "PREPARE_AGAIN"),
        ("REGISTRATION", OSError("private-secret"), "HUMAN_REVIEW"),
        ("TASK_AUTHORITY", ValueError("private-secret"), "CONTEXT_REVIEW"),
        ("AUTHENTICATION", IdentityError("private-secret"), "CONTEXT_REVIEW"),
        ("TARGET_SELECTION", RuntimeError("private-secret"), "CONTEXT_REVIEW"),
        ("HANDOFF", ValueError("private-secret"), "HUMAN_REVIEW"),
    ],
)
def check_exception_routes_do_not_echo_secrets(stage, error, kind):
    report = G.stopped(stage, error)
    assert (
        report["nextAction"]["type"] == kind and report["nextAction"]["command"] is None
    )
    assert "private-secret" not in json.dumps(report)
    assert report["cause"]["detailDigest"]


def check_pending_failure_uses_type_not_prose():
    state = {"status": "BLOCKED"}
    failures.exception(state, EnvironmentValuePending("secret"), "PREPARATION")
    assert state["failure"]["classification"] == "NEEDS_HUMAN"
    assert state["failure"]["dependencyWait"] is True
    failures.exception(state, ValueError("PENDING_DEPLOY"), "PREPARATION")
    assert state["failure"]["classification"] == "NEEDS_HUMAN"


@pytest.mark.parametrize(
    ("script", "module", "tokens"),
    [
        (
            "deploy_preparation.py",
            "deploy/preparation.py",
            ["Offline Preparation", "--register", "--run-controller", "--service"],
        ),
        (
            "cloudformation-deploy.py",
            "deploy/controller.py",
            [
                "--action",
                "--approve-change-set",
                "MaxConcurrentStacks",
                "Snapshot",
            ],
        ),
        (
            "deploy_handoff.py",
            "deploy_handoff.py",
            ["inputRefs", "modelRefs", "--discard-failure", "repair-validate"],
        ),
        (
            "check-deploy-context.py",
            "aws_context.py",
            [
                "terraform init",
                "terraform plan -out=",
                "terraform apply",
                "partial",
                "AWS_PROFILE",
            ],
        ),
    ],
)
def check_cli_help_and_example_options(script, module, tokens):
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "framework/scripts" / script), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert all(token in result.stdout for token in tokens)
    tree = ast.parse((ROOT / "framework/scripts" / module).read_text())
    options = {"--help"} | {
        a.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add_argument"
        for a in n.args
        if isinstance(a, ast.Constant)
        and isinstance(a.value, str)
        and a.value.startswith("--")
    }
    for line in result.stdout.splitlines():
        if script in line and line.strip().startswith(("python3 ", "env ")):
            for option in re.findall(r"--[a-z][a-z-]+", line):
                assert option in options, (script, option)
    if script == "cloudformation-deploy.py":
        assert all(
            old not in result.stdout
            for old in ["--state", "--resume", "--repair-result", "--observe-only"]
        )


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
        assert str(ROOT / "framework/scripts/run-python.py") in argv
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
    assert json.loads(capsys.readouterr().out)["nextAction"]["type"] == "PREPARE_AGAIN"
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
    assert str(ROOT / "framework/scripts/run-python.py") in argv
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
        assert G.recovery_command(ARGS, tmp_path, "tasks/parent.md") is None
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

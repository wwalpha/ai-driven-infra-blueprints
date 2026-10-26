#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from types import SimpleNamespace

import pytest
from support.deploy_preparation_fixtures import (
    ROOT,
    M,
    Path,
    json,
    patch,
    subprocess,
    sys,
    tempfile,
)
from utils.aws.identity import IdentityError

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_dependencies_and_timing():
    with (
        patch.object(M.importlib, "import_module", side_effect=ImportError),
        patch.object(M.shutil, "which", return_value=None),
    ):
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert all(
                name in str(error) for name in ("boto3", "botocore", "PyYAML", "git")
            )
        else:
            raise AssertionError("missing dependencies accepted")
    with (
        patch.object(M.importlib, "import_module"),
        patch.object(M.importlib.metadata, "version", return_value="different.patch"),
        patch.object(M.shutil, "which", return_value="tool"),
        patch.object(subprocess, "run") as run,
    ):
        run.return_value.returncode = 0
        assert M.environment(ROOT)["versions"]["boto3"] == "different.patch"
        assert run.call_args.args[0] == [sys.executable, "-m", "pip", "check"]
        run.return_value.returncode = 1
        run.return_value.stdout, run.return_value.stderr = "conflicting dependency", ""
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert "conflicting dependency" in str(error)
        else:
            raise AssertionError("pip check failure accepted")
    with tempfile.TemporaryDirectory() as directory:
        try:
            M.Timing(Path(directory), Path(directory) / "timing.jsonl")
        except ValueError:
            pass
        else:
            raise AssertionError("repository-local timing accepted")
        path = Path(directory) / "external.jsonl"
        timing = M.Timing(ROOT, path)
        try:
            with timing.phase("authenticationContext"):
                raise RuntimeError("credential failure")
        except RuntimeError:
            pass
        event = json.loads(path.read_text())
        assert event["result"] == "FAIL" and event["phase"] == "authenticationContext"


def check_identity_failure_precedes_preparation(tmp_path):
    args = SimpleNamespace(
        task_file="tasks/test.md",
        service=["vpc"],
        environment="dev",
        aws_account_id="123456789012",
        alias=None,
        profile="explicit",
    )
    target = {
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation",
    }
    timing = M.Timing(tmp_path / "repository", tmp_path / "timing.jsonl")
    with (
        patch.object(M, "environment", return_value={}),
        patch.object(M, "load_target", return_value=target),
        patch.object(
            M, "select_profile", side_effect=IdentityError("identity rejected")
        ) as select,
        patch.object(M, "candidate") as candidate,
        patch.object(M.subprocess, "run") as aws,
    ):
        with pytest.raises(IdentityError, match="identity rejected"):
            M.prepare(tmp_path / "repository", args, tmp_path / "run", timing)
        select.assert_called_once_with(target, "explicit")
        candidate.assert_not_called()
        aws.assert_not_called()


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

#!/usr/bin/env python3
"""Small self-check for check-deploy-context.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))



import io
import json
import os
import subprocess
import tempfile
from unittest import mock

import aws_context as MODULE

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "project.json").write_text(
            json.dumps(
                {
                    "projectName": "test",
                    "targets": [
                        {
                            "environment": "production",
                            "awsAccountId": "210987654321",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        },
                        {
                            "alias": "cde",
                            "environment": "stg",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "terraform",
                        },
                        {
                            "alias": "non-cde",
                            "environment": "stg",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "terraform",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.object(
            MODULE.shutil, "which", side_effect=lambda command: f"/mock/{command}"
        ), mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"123456789012"}', ""),
        ) as run:
            target = MODULE.check_deploy_context(
                root, "stg", alias="cde", profile="deploy"
            )
            assert target == {
                "alias": "cde",
                "awsAccountId": "123456789012",
                "awsRegion": "ap-northeast-1",
                "iacEngine": "terraform",
            }
            assert run.call_args.args[0][:3] == ["/mock/aws", "--profile", "deploy"]
            assert run.call_args.args[0][3:5] == ["--region", "ap-northeast-1"]

        commands: list[str] = []
        with mock.patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda command: commands.append(command) or f"/mock/{command}",
        ), mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"210987654321"}', ""),
        ) as run:
            MODULE.check_deploy_context(root, "production", account_id="210987654321")
            assert commands == ["aws"]
            assert "--profile" not in run.call_args.args[0]

        commands = []
        with mock.patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda command: commands.append(command) or f"/mock/{command}",
        ), mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"210987654321"}', ""),
        ):
            MODULE.check_deploy_context(
                root, "production", account_id="210987654321", read_only=True
            )
            assert commands == ["aws"]

        try:
            MODULE.load_target(root, "stg", account_id="123456789012")
        except MODULE.DeployContextError as error:
            assert "topology target must exist exactly once" in str(error)
        else:
            raise AssertionError("aliased target was selected without its alias")

        topology = json.loads((root / "project.json").read_text(encoding="utf-8"))
        topology["targets"][1]["awsProfile"] = "stg-cde"
        topology["targets"][2]["awsProfile"] = "stg-non-cde"
        (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
        with mock.patch.dict(os.environ, {"AWS_PROFILE": "ambient"}), mock.patch.object(
            MODULE.shutil, "which", return_value="/mock/aws"
        ), mock.patch.object(
            MODULE.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"123456789012"}', ""),
        ) as run:
            target = MODULE.check_deploy_context(root, "stg", alias="cde", read_only=True)
            assert target["awsProfile"] == "stg-cde"
            assert run.call_args.args[0][:3] == ["/mock/aws", "--profile", "stg-cde"]
            run.reset_mock()
            failure = MODULE.IdentityError("identity rejected")
            with mock.patch.object(MODULE, "select_profile", side_effect=failure) as select:
                try:
                    MODULE.check_deploy_context(root, "stg", alias="cde", profile="explicit")
                except MODULE.IdentityError as error:
                    assert error is failure
                else:
                    raise AssertionError("identity rejection ignored")
                select.assert_called_once_with(target, "explicit")
            run.assert_not_called()
            run.return_value = subprocess.CompletedProcess([], 1, "", "profile not found")
            try:
                MODULE.check_deploy_context(root, "stg", alias="cde")
            except MODULE.DeployContextError as error:
                assert "profile not found" in str(error)
            else:
                raise AssertionError("failed configured profile was accepted")
            assert run.call_count == 1
            assert run.call_args.args[0][2] == "stg-cde"

        topology["targets"][1]["awsExecutionAccountId"] = "999999999999"
        (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
        with mock.patch.object(MODULE.shutil, "which", return_value="/mock/aws"), mock.patch.object(
            MODULE.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"999999999999"}', ""),
        ) as run:
            with mock.patch.object(MODULE, "verify_account", return_value="999999999999") as verify:
                target = MODULE.check_deploy_context(root, "stg", alias="cde", read_only=True)
                verify.assert_called_once_with(target, "999999999999")
                assert target["awsAccountId"] == "123456789012"
                assert target["awsExecutionAccountId"] == "999999999999"
            with mock.patch.object(MODULE, "verify_account", side_effect=failure):
                try:
                    MODULE.check_deploy_context(root, "stg", alias="cde", read_only=True)
                except MODULE.IdentityError as error:
                    assert error is failure
                else:
                    raise AssertionError("STS identity rejection ignored")
        topology["targets"][0]["awsExecutionAccountId"] = "999999999999"
        (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
        assert MODULE.load_target(root, "production", account_id="210987654321")["awsAccountId"] == "210987654321"
        topology["targets"][0]["awsRegion"] = "Tokyo"
        (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
        try:
            MODULE.load_target(root, "production", account_id="210987654321")
        except MODULE.DeployContextError as error:
            assert "AWS region ID is invalid" in str(error)
        else:
            raise AssertionError("invalid AWS region ID was accepted")
        with mock.patch.object(MODULE, "check_deploy_context", side_effect=failure), \
                mock.patch.object(MODULE.Path, "cwd", return_value=root), \
                mock.patch.object(sys, "argv", ["check-deploy-context", "--environment", "stg", "--alias", "cde"]), \
                mock.patch.object(sys, "stderr", new_callable=io.StringIO) as errors:
            assert MODULE.main() == 1
            assert "Deploy context: FAIL: identity rejected" in errors.getvalue()
    print("check-deploy-context: PASS")


if __name__ == "__main__":
    main()

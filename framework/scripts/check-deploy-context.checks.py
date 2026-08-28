#!/usr/bin/env python3
"""Small self-check for check-deploy-context.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("check-deploy-context.py")
SPEC = importlib.util.spec_from_file_location("check_deploy_context", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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
                            "environment": "staging",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "terraform",
                        },
                        {
                            "alias": "non-cde",
                            "environment": "staging",
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
                root, "staging", alias="cde", profile="deploy"
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
        ):
            MODULE.check_deploy_context(root, "production", account_id="210987654321")
            assert commands == ["aws", "cfn-lint"]

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

        with mock.patch.object(MODULE.shutil, "which", return_value="/mock/aws"), mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"999999999999"}', ""),
        ):
            try:
                MODULE.check_deploy_context(root, "staging", alias="non-cde")
            except MODULE.DeployContextError as error:
                assert "AWS account mismatch" in str(error)
            else:
                raise AssertionError("account mismatch was accepted")

        try:
            MODULE.load_target(root, "staging", account_id="123456789012")
        except MODULE.DeployContextError as error:
            assert "topology target must exist exactly once" in str(error)
        else:
            raise AssertionError("aliased target was selected without its alias")
    print("check-deploy-context: PASS")


if __name__ == "__main__":
    main()

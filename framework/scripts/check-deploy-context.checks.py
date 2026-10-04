#!/usr/bin/env python3
"""Small self-check for check-deploy-context.py."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
import os
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
            assert commands == ["aws", "cfn-lint"]
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

        with mock.patch.object(MODULE.shutil, "which", return_value="/mock/aws"), mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, '{"Account":"999999999999"}', ""),
        ):
            try:
                MODULE.check_deploy_context(root, "stg", alias="non-cde")
            except MODULE.DeployContextError as error:
                assert "AWS account mismatch" in str(error)
            else:
                raise AssertionError("account mismatch was accepted")

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
            for alias in ("cde", "non-cde"):
                for read_only in (False, True):
                    target = MODULE.check_deploy_context(root, "stg", alias=alias, read_only=read_only)
                    assert target["awsProfile"] == f"stg-{alias}"
                    assert run.call_args.args[0][:3] == ["/mock/aws", "--profile", f"stg-{alias}"]
            MODULE.check_deploy_context(root, "stg", alias="cde", profile="stg-cde")
            run.reset_mock()
            try:
                MODULE.check_deploy_context(root, "stg", alias="cde", profile="other")
            except MODULE.DeployContextError as error:
                assert "does not match target awsProfile" in str(error)
            else:
                raise AssertionError("conflicting AWS profile was accepted")
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
            for read_only in (False, True):
                target = MODULE.check_deploy_context(root, "stg", alias="cde", read_only=read_only)
                assert target["awsAccountId"] == "123456789012"
                assert target["awsExecutionAccountId"] == "999999999999"
                assert run.call_args.args[0][2] == "stg-cde"
            run.return_value = subprocess.CompletedProcess([], 0, '{"Account":"123456789012"}', "")
            try:
                MODULE.check_deploy_context(root, "stg", alias="cde", read_only=True)
            except MODULE.DeployContextError as error:
                assert "expected 999999999999, actual 123456789012" in str(error)
            else:
                raise AssertionError("resource account was accepted as execution account")
        topology["targets"][0]["awsExecutionAccountId"] = "999999999999"
        (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
        assert MODULE.load_target(root, "production", account_id="210987654321")["awsAccountId"] == "210987654321"
        for invalid in (None, 123456789012, "", "UNSET", "123", "1234567890123", " 123456789012", "123456789012\n", "１２３４５６７８９０１２"):
            topology["targets"][1]["awsExecutionAccountId"] = invalid
            (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
            with mock.patch.object(MODULE.subprocess, "run") as run:
                try:
                    MODULE.check_deploy_context(root, "stg", alias="cde", read_only=True)
                except MODULE.DeployContextError as error:
                    assert "AWS execution account ID is invalid" in str(error)
                else:
                    raise AssertionError(f"invalid execution account was accepted: {invalid!r}")
                run.assert_not_called()
        del topology["targets"][1]["awsExecutionAccountId"]
        for invalid in (None, 123, "", " ", " padded ", "UNSET", "bad\nprofile", "bad\0profile"):
            topology["targets"][1]["awsProfile"] = invalid
            (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
            try:
                MODULE.load_target(root, "stg", alias="cde")
            except MODULE.DeployContextError as error:
                assert "AWS profile is invalid" in str(error)
            else:
                raise AssertionError(f"invalid AWS profile was accepted: {invalid!r}")
        topology["targets"][0]["awsRegion"] = "Tokyo"
        (root / "project.json").write_text(json.dumps(topology), encoding="utf-8")
        try:
            MODULE.load_target(root, "production", account_id="210987654321")
        except MODULE.DeployContextError as error:
            assert "AWS region ID is invalid" in str(error)
        else:
            raise AssertionError("invalid AWS region ID was accepted")
    print("check-deploy-context: PASS")


if __name__ == "__main__":
    main()

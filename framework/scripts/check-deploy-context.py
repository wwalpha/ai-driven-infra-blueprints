#!/usr/bin/env python3
"""Deterministically verify the AWS context for one topology target."""

from __future__ import annotations

from validation_cache import input_text

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from issue_gate import require_target_no_issues


from project_targets import DeployContextError, select_target


def load_target(
    root: Path,
    environment: str,
    account_id: str | None = None,
    alias: str | None = None,
) -> dict[str, str]:
    path = root / "project.json"
    try:
        topology = json.loads(input_text(path, encoding="utf-8"))
    except FileNotFoundError as error:
        raise DeployContextError("project.json is missing") from error
    except json.JSONDecodeError as error:
        raise DeployContextError(f"project.json is invalid: {error}") from error

    return select_target(topology, environment, account_id, alias)


def check_deploy_context(
    root: Path,
    environment: str,
    account_id: str | None = None,
    alias: str | None = None,
    profile: str | None = None,
    read_only: bool = False,
) -> dict[str, str]:
    target = load_target(root, environment, account_id, alias)
    if not read_only:
        try:
            require_target_no_issues(root, (environment, alias or target["awsAccountId"]))
        except (OSError, ValueError) as error:
            raise DeployContextError(str(error)) from error
    configured_profile = target.get("awsProfile")
    if configured_profile and profile is not None and profile != configured_profile:
        raise DeployContextError("explicit AWS profile does not match target awsProfile")
    profile = configured_profile or profile
    required_commands = ["aws"]
    if not read_only:
        required_commands.append(
            "cfn-lint" if target["iacEngine"] == "cloudformation" else "terraform"
        )
    command_paths = {command: shutil.which(command) for command in required_commands}
    missing = [command for command, path in command_paths.items() if path is None]
    if missing:
        raise DeployContextError(f"required command not found: {', '.join(missing)}")

    command = [command_paths["aws"]]
    if profile:
        command += ["--profile", profile]
    command += [
        "--region",
        target["awsRegion"],
        "sts",
        "get-caller-identity",
        "--output",
        "json",
        "--no-cli-pager",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        raise DeployContextError("AWS credential check timed out") from error
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f"exit {result.returncode}"
        raise DeployContextError(f"AWS credential check failed: {detail}")

    try:
        caller_account = json.loads(result.stdout).get("Account")
    except (json.JSONDecodeError, AttributeError) as error:
        raise DeployContextError("AWS caller identity response is invalid") from error
    execution_account = target.get("awsExecutionAccountId", target["awsAccountId"])
    if caller_account != execution_account:
        raise DeployContextError(
            f"AWS account mismatch: expected {execution_account}, actual {caller_account or 'unknown'}"
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--aws-account-id")
    selector.add_argument("--alias")
    parser.add_argument("--profile")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="verify AWS credentials and target without requiring an IaC command",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    try:
        target = check_deploy_context(
            root,
            args.environment,
            args.aws_account_id,
            args.alias,
            args.profile,
            read_only=args.read_only,
        )
    except DeployContextError as error:
        print(f"Deploy context: FAIL: {error}", file=sys.stderr)
        return 1

    print("Read-only AWS context: PASS" if args.read_only else "Deploy context: PASS")
    print(f"- environment: {args.environment}")
    if args.alias:
        print(f"- alias: {args.alias}")
    print(f"- AWS resource account: {target['awsAccountId']}")
    print(f"- AWS execution account: {target.get('awsExecutionAccountId', target['awsAccountId'])}")
    print(f"- AWS region: {target['awsRegion']}")
    if target.get("awsProfile") or args.profile:
        print(f"- AWS profile: {target.get('awsProfile') or args.profile}")
    print(f"- IaC engine: {target['iacEngine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

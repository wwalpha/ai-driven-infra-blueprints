#!/usr/bin/env python3
"""Deterministically verify the AWS context for one topology target."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


class DeployContextError(RuntimeError):
    pass


def load_target(
    root: Path,
    environment: str,
    account_id: str | None = None,
    alias: str | None = None,
) -> dict[str, str]:
    if bool(account_id) == bool(alias):
        raise DeployContextError("exactly one of AWS account ID or alias is required")
    if account_id and not re.fullmatch(r"\d{12}", account_id):
        raise DeployContextError("AWS account ID must be 12 digits")
    if alias and (
        not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias)
        or re.fullmatch(r"\d{12}", alias)
    ):
        raise DeployContextError("alias must be lower-kebab-case and not a 12-digit number")

    path = root / "project.json"
    try:
        topology = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DeployContextError("project.json is missing") from error
    except json.JSONDecodeError as error:
        raise DeployContextError(f"project.json is invalid: {error}") from error

    targets = topology.get("targets") if isinstance(topology, dict) else None
    if not isinstance(targets, list):
        raise DeployContextError("project.json targets must be an array")

    matches = [
        target
        for target in targets
        if isinstance(target, dict)
        and target.get("environment") == environment
        and (
            target.get("alias") == alias
            if alias
            else "alias" not in target and target.get("awsAccountId") == account_id
        )
    ]
    if len(matches) != 1:
        selector = alias or account_id
        raise DeployContextError(f"topology target must exist exactly once: {environment}/{selector}")

    target = matches[0]
    resolved_account_id = target.get("awsAccountId")
    region = target.get("awsRegion")
    engine = target.get("iacEngine")
    if not isinstance(resolved_account_id, str) or not re.fullmatch(r"\d{12}", resolved_account_id):
        raise DeployContextError("target AWS account ID is invalid")
    if not isinstance(region, str) or not region:
        raise DeployContextError("target AWS region is missing")
    if engine not in {"cloudformation", "terraform"}:
        raise DeployContextError(f"invalid target IaC engine: {engine}")
    resolved = {
        "awsAccountId": resolved_account_id,
        "awsRegion": region,
        "iacEngine": engine,
    }
    if alias:
        resolved["alias"] = alias
    return resolved


def check_deploy_context(
    root: Path,
    environment: str,
    account_id: str | None = None,
    alias: str | None = None,
    profile: str | None = None,
    read_only: bool = False,
) -> dict[str, str]:
    target = load_target(root, environment, account_id, alias)
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
    if caller_account != target["awsAccountId"]:
        raise DeployContextError(
            f"AWS account mismatch: expected {target['awsAccountId']}, actual {caller_account or 'unknown'}"
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
    print(f"- AWS account: {target['awsAccountId']}")
    print(f"- AWS region: {target['awsRegion']}")
    print(f"- IaC engine: {target['iacEngine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

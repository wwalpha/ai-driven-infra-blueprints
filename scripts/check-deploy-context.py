#!/usr/bin/env python3
"""Deterministically verify the AWS deployment context for one topology target."""

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


def load_target(root: Path, environment: str, account_id: str) -> dict[str, str]:
    if not re.fullmatch(r"\d{12}", account_id):
        raise DeployContextError("AWS account ID must be 12 digits")

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
        and target.get("awsAccountId") == account_id
    ]
    if len(matches) != 1:
        raise DeployContextError(f"topology target must exist exactly once: {environment}/{account_id}")

    target = matches[0]
    region = target.get("awsRegion")
    engine = target.get("iacEngine")
    if not isinstance(region, str) or not region:
        raise DeployContextError("target AWS region is missing")
    if engine not in {"cloudformation", "terraform"}:
        raise DeployContextError(f"invalid target IaC engine: {engine}")
    return {"awsRegion": region, "iacEngine": engine}


def check_deploy_context(
    root: Path, environment: str, account_id: str, profile: str | None = None
) -> dict[str, str]:
    target = load_target(root, environment, account_id)
    required_commands = ["aws", "cfn-lint"] if target["iacEngine"] == "cloudformation" else ["aws", "terraform"]
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
    if caller_account != account_id:
        raise DeployContextError(
            f"AWS account mismatch: expected {account_id}, actual {caller_account or 'unknown'}"
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    parser.add_argument("--aws-account-id", required=True)
    parser.add_argument("--profile")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    try:
        target = check_deploy_context(root, args.environment, args.aws_account_id, args.profile)
    except DeployContextError as error:
        print(f"Deploy context: FAIL: {error}", file=sys.stderr)
        return 1

    print("Deploy context: PASS")
    print(f"- environment: {args.environment}")
    print(f"- AWS account: {args.aws_account_id}")
    print(f"- AWS region: {target['awsRegion']}")
    print(f"- IaC engine: {target['iacEngine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

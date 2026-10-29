"""Pure topology target selection shared by Model reads and AWS context checks."""

import json
import re

import utils.input_cache as _imports_validation_cache
from utils.aws.identity import execution_account, select_profile, validate_account_id


class DeployContextError(RuntimeError):
    pass


def select_target(topology, environment, account_id=None, alias=None):
    if bool(account_id) == bool(alias):
        raise DeployContextError("exactly one of AWS account ID or alias is required")
    if account_id:
        validate_account_id(account_id)
    if alias and (
        not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias)
        or re.fullmatch(r"\d{12}", alias)
    ):
        raise DeployContextError(
            "alias must be lower-kebab-case and not a 12-digit number"
        )

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
        raise DeployContextError(
            f"topology target must exist exactly once: {environment}/{selector}"
        )

    target = matches[0]
    resolved_account_id = target.get("awsAccountId")
    region = target.get("awsRegion")
    engine = target.get("iacEngine")
    validate_account_id(resolved_account_id, "target AWS account ID")
    execution_account(target)
    select_profile(target)
    if not isinstance(region, str) or not region:
        raise DeployContextError("target AWS region is missing")
    if not re.fullmatch(r"[a-z]{2,}(?:-[a-z0-9]+)+-[1-9][0-9]*", region):
        raise DeployContextError("target AWS region ID is invalid")
    if engine not in {"cloudformation", "terraform"}:
        raise DeployContextError(f"invalid target IaC engine: {engine}")
    resolved = {
        "environment": environment,
        "suffix": target.get("suffix"),
        "awsAccountId": resolved_account_id,
        "awsRegion": region,
        "iacEngine": engine,
    }
    if alias:
        resolved["alias"] = alias
    for field in ("awsExecutionAccountId", "awsProfile"):
        if field in target:
            resolved[field] = target[field]
    return resolved


def load_target(
    root,
    environment: str,
    account_id: str | None = None,
    alias: str | None = None,
    *,
    include_naming: bool = False,
) -> dict[str, str | None]:
    input_text = _imports_validation_cache.input_text
    path = root / "project.json"
    try:
        topology = json.loads(input_text(path, encoding="utf-8"))
    except FileNotFoundError as error:
        raise DeployContextError("project.json is missing") from error
    except json.JSONDecodeError as error:
        raise DeployContextError(f"project.json is invalid: {error}") from error

    target = select_target(topology, environment, account_id, alias)
    if not include_naming:
        target.pop("environment")
        target.pop("suffix")
    return target


LOWER_KEBAB_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def load_target_directory(root, environment, directory, *, include_naming=False):
    """Reuse topology validation without invoking credential checks or any AWS operation."""
    try:
        return load_target(
            root,
            environment,
            directory if directory.isdigit() else None,
            None if directory.isdigit() else directory,
            include_naming=include_naming,
        )
    except DeployContextError as error:
        raise ValueError(str(error)) from error

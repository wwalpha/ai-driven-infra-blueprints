"""Pure topology target selection shared by Model reads and AWS context checks."""

import json
import re

import utils.input_cache as _imports_validation_cache


class DeployContextError(RuntimeError):
    pass


def select_target(topology, environment, account_id=None, alias=None):
    if bool(account_id) == bool(alias):
        raise DeployContextError("exactly one of AWS account ID or alias is required")
    if account_id and not re.fullmatch(r"\d{12}", account_id):
        raise DeployContextError("AWS account ID must be 12 digits")
    if alias and (
        not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias)
        or re.fullmatch(r"\d{12}", alias)
    ):
        raise DeployContextError("alias must be lower-kebab-case and not a 12-digit number")

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
    if not re.fullmatch(r"[a-z]{2,}(?:-[a-z0-9]+)+-[1-9][0-9]*", region):
        raise DeployContextError("target AWS region ID is invalid")
    if engine not in {"cloudformation", "terraform"}:
        raise DeployContextError(f"invalid target IaC engine: {engine}")
    resolved = {
        "awsAccountId": resolved_account_id,
        "awsRegion": region,
        "iacEngine": engine,
    }
    if alias:
        resolved["alias"] = alias
    if "awsExecutionAccountId" in target:
        execution_account = target["awsExecutionAccountId"]
        if not isinstance(execution_account, str) or not re.fullmatch(r"[0-9]{12}", execution_account):
            raise DeployContextError("target AWS execution account ID is invalid")
        resolved["awsExecutionAccountId"] = execution_account
    if "awsProfile" in target:
        profile = target["awsProfile"]
        if (not isinstance(profile, str) or not profile or profile != profile.strip()
                or profile == "UNSET" or any(char in profile for char in "\r\n\0")):
            raise DeployContextError("target AWS profile is invalid")
        resolved["awsProfile"] = profile
    return resolved


def load_target(
    root,
    environment: str,
    account_id: str | None = None,
    alias: str | None = None,
) -> dict[str, str]:

    input_text = _imports_validation_cache.input_text
    path = root / "project.json"
    try:
        topology = json.loads(input_text(path, encoding="utf-8"))
    except FileNotFoundError as error:
        raise DeployContextError("project.json is missing") from error
    except json.JSONDecodeError as error:
        raise DeployContextError(f"project.json is invalid: {error}") from error

    return select_target(topology, environment, account_id, alias)


LOWER_KEBAB_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

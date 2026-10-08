"""Project target placement validation."""


from __future__ import annotations
from pathlib import Path
import json
import re
LOWER_KEBAB_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

def check_target_file(path: Path, base: Path, *, accounts, findings) -> tuple[str, str] | None:
    parts = path.relative_to(base).parts
    findings.check(len(parts) == 3, f"target file must be <environment>/<target-directory>/<file>: {findings.relative(path)}")
    if len(parts) != 3:
        return None
    target = (parts[0], parts[1])
    findings.check(target in accounts, f"target is not defined in project.json: {findings.relative(path)}")
    return target


def check_validation_scope(accounts, changed_paths, contract_scope, findings, root, scope, task_iac_paths):
    if task_iac_paths is not None:
        for changed in sorted(changed_paths):
            if changed.startswith("infra/"):
                findings.check(root / changed in task_iac_paths,
                           f"changed IaC path is outside Deployment scope: {changed}")
    scope = contract_scope if contract_scope is not None else scope
    if scope is None:
        return
    for environment, target, service in sorted(scope):
        findings.check((environment, target) in accounts, f"validation target is not defined in project.json: {environment}/{target}")
        for base, suffix in (("model", ".properties"), ("docs/designs", ".md")):
            relative = f"{base}/{environment}/{target}/{service}{suffix}"
            findings.check((root / relative).is_file(), f"validation input missing: {relative}")
    for changed in sorted(changed_paths):
        for base in ("model/", "docs/designs/"):
            if changed.startswith(base):
                parts = Path(changed.removeprefix(base)).parts
                identity = (parts[0], parts[1], Path(parts[2]).stem) if len(parts) >= 3 else None
                findings.check(identity in scope, f"changed design path is outside validation scope: {changed}")


def check_project_topology(accounts, findings, root, template_mode):
    path = root / "project.json"
    if template_mode:
        return
    text = path.read_text(encoding="utf-8")
    findings.check(text.endswith("\n"), "project.json must end with a newline")
    try:
        topology = json.loads(text)
    except json.JSONDecodeError as error:
        findings.errors.append(f"invalid project.json: {error}")
        return
    findings.check(isinstance(topology, dict), "project.json root must be an object")
    if not isinstance(topology, dict):
        return
    findings.check(set(topology) == {"projectName", "targets"}, "project.json must contain only projectName and targets")

    project_name = topology.get("projectName")
    findings.check(isinstance(project_name, str) and project_name not in {"", "UNSET"}, "projectName is required")

    targets = topology.get("targets")
    findings.check(isinstance(targets, list) and bool(targets), "targets must be a non-empty array")
    if not isinstance(targets, list):
        return
    order: list[tuple[str, str]] = []
    environment_targets: dict[str, list[dict[str, str]]] = {}
    account_engines: dict[tuple[str, str], str] = {}
    execution_account_engines: dict[tuple[str, str], str] = {}
    required = {"environment", "awsAccountId", "awsRegion", "iacEngine"}
    allowed = required | {"alias", "awsProfile", "awsExecutionAccountId", "suffix"}
    for index, target_values in enumerate(targets, 1):
        findings.check(isinstance(target_values, dict), f"target {index} must be an object")
        if not isinstance(target_values, dict):
            continue
        findings.check(
            required <= set(target_values) <= allowed,
            f"target {index} must contain {sorted(required)} and optional alias/awsProfile/awsExecutionAccountId/suffix only",
        )
        if not required <= set(target_values):
            continue
        values = list(target_values.values())
        findings.check(all(isinstance(value, str) for value in values), f"target {index} values must be strings")
        if not all(isinstance(value, str) for value in values):
            continue
        environment = target_values["environment"]
        account = target_values["awsAccountId"]
        region = target_values["awsRegion"]
        engine = target_values["iacEngine"]
        alias = target_values.get("alias", "")
        target_directory = alias or account
        target = f"{environment}/{target_directory}"
        execution_account = target_values.get("awsExecutionAccountId", account)
        findings.check(
            re.fullmatch(r"[0-9]{12}", execution_account) is not None,
            f"invalid AWS execution account: {target}",
        )
        if "awsProfile" in target_values:
            profile = target_values["awsProfile"]
            findings.check(
                bool(profile) and profile == profile.strip() and profile != "UNSET"
                and not any(char in profile for char in "\r\n\0"),
                f"invalid AWS profile: {target}",
            )
        if "suffix" in target_values:
            findings.check(
                LOWER_KEBAB_PATTERN.fullmatch(target_values["suffix"]) is not None,
                f"invalid naming suffix: {target}: expected a non-empty lower-kebab-case string",
            )
        findings.check("UNSET" not in values and all(values), f"target contains unset value: {target}")
        findings.check(LOWER_KEBAB_PATTERN.fullmatch(environment) is not None, f"invalid Environment ID: {environment}")
        findings.check(re.fullmatch(r"\d{12}", account) is not None, f"invalid AWS account: {target}")
        if alias:
            findings.check(
                LOWER_KEBAB_PATTERN.fullmatch(alias) is not None
                and re.fullmatch(r"\d{12}", alias) is None,
                f"invalid target alias: {target}",
            )
        if region in {"", "UNSET"}:
            findings.check(False, f"AWS region is required: {target}")
        else:
            findings.check(
                re.fullmatch(r"[a-z]{2,}(?:-[a-z0-9]+)+-[1-9][0-9]*", region) is not None,
                f"invalid AWS region ID: {target}: {region}",
            )
        findings.check(engine in {"cloudformation", "terraform"}, f"invalid IaC engine: {target}")
        key = (environment, target_directory)
        order.append(key)
        findings.check(key not in accounts, f"duplicate target directory in environment: {target}")
        if key not in accounts:
            accounts[key] = {
                "account": account,
                "alias": alias,
                "region": region,
                "engine": engine,
            }
        environment_targets.setdefault(environment, []).append(target_values)
        account_key = (environment, account)
        previous_engine = account_engines.get(account_key)
        findings.check(
            previous_engine in {None, engine},
            f"aliases for the same environment/AWS account must use one IaC engine: {environment}/{account}",
        )
        account_engines.setdefault(account_key, engine)
        execution_key = (environment, execution_account)
        findings.check(
            execution_account_engines.get(execution_key) in {None, engine},
            f"targets for the same environment/AWS execution account must use one IaC engine: {environment}/{execution_account}",
        )
        execution_account_engines.setdefault(execution_key, engine)

    for environment, environment_values in environment_targets.items():
        aliases = [value.get("alias", "") for value in environment_values]
        if len(environment_values) == 1:
            findings.check(not aliases[0], f"single-target environment must omit alias: {environment}")
        else:
            findings.check(
                all(aliases),
                f"multi-target environment requires alias on every target: {environment}",
            )
            findings.check(
                len(aliases) == len(set(aliases)),
                f"target aliases must be unique within environment: {environment}",
            )
    findings.check(order == sorted(order), "targets must be sorted by environment and target directory")
    return


def check_initialized_paths(accounts, findings, root, scope, template_mode):
    if template_mode:
        return
    for (environment, target_directory), values in accounts.items():
        if scope is not None and not any(item[:2] == (environment, target_directory) for item in scope):
            continue
        paths = [
            root / "docs" / "designs" / environment / target_directory,
            root / "model" / environment / target_directory,
        ]
        if values["engine"] == "cloudformation":
            paths.append(root / "infra" / "cloudformation" / "parameters" / environment / target_directory)
        else:
            paths.append(root / "infra" / "terraform" / "environments" / environment / target_directory)
        for path in paths:
            findings.check(path.is_dir(), f"initialized target path missing: {findings.relative(path)}")


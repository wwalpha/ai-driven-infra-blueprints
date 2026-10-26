"""Project target placement validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import model.core as _imports_model_core
import model.importing.scope as _imports_model_importing_scope
import model.sources as _imports_model_sources
import sync_progress as _imports_sync_progress
from model.change_plan import assemble, task_plan
from model.impact import scope_diagnostic
from utils.aws.identity import IdentityError, select_profile, validate_account_id
from utils.input_cache import input_is_dir, input_is_file, input_text
from utils.project_targets import LOWER_KEBAB_PATTERN as LOWER_KEBAB_PATTERN

from .terraform import root_directory


def check_target_file(
    path: Path, base: Path, *, accounts, findings
) -> tuple[str, str] | None:
    parts = path.relative_to(base).parts
    findings.check(
        len(parts) == 3,
        f"target file must be <environment>/<target-directory>/<file>: {findings.relative(path)}",
    )
    if len(parts) != 3:
        return None
    target = (parts[0], parts[1])
    findings.check(
        target in accounts,
        f"target is not defined in project.json: {findings.relative(path)}",
    )
    return target


def check_validation_scope(
    accounts,
    changed_paths,
    contract_scope,
    findings,
    root,
    scope,
    task_iac_paths,
    *,
    candidates=False,
    before=None,
    base=None,
):
    if task_iac_paths is not None:
        for changed in sorted(changed_paths):
            if changed.startswith("infra/"):
                findings.check(
                    root / changed in task_iac_paths,
                    f"changed IaC path is outside Deployment scope: {changed}",
                )
    scope = contract_scope if contract_scope is not None else scope
    impact = set()
    if scope or candidates:
        try:
            if before is not None:
                source_scope = _imports_model_sources.source_scope
                changed = {
                    source_scope(root, root / path)
                    for path in changed_paths
                    if path.startswith("model/")
                }
                impact = set(
                    assemble(
                        root,
                        {
                            (item.environment, item.target, item.service)
                            for item in changed
                        },
                        before,
                        _imports_model_sources.FileReads(),
                    ).services
                )
            else:
                impact = set(task_plan(root, changed_paths, base=base).services)
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid Model source scope: {error}")
    if scope is None:
        return impact if candidates else None
    if not scope:
        findings.check(
            not any(path.startswith("model/") for path in changed_paths),
            "Model source changes require service Validation scope",
        )
    for environment, target, service in sorted(scope):
        findings.check(
            (environment, target) in accounts,
            f"validation target is not defined in project.json: {environment}/{target}",
        )
        model_exists = _imports_model_sources.model_exists
        try:
            findings.check(
                model_exists(
                    root / "model" / environment / target / (service + ".properties")
                ),
                f"validation properties input missing: {environment}/{target}/{service}",
            )
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid validation properties input: {error}")
        for design_base, suffix in () if candidates else (("docs/designs", ".md"),):
            relative = f"{design_base}/{environment}/{target}/{service}{suffix}"
            if not input_is_file(root / relative):
                ReferenceResolutionError = _imports_model_core.ReferenceResolutionError
                load_model = _imports_model_sources.load_model
                try:
                    load_model(
                        root
                        / "model"
                        / environment
                        / target
                        / (service + ".properties")
                    )
                except ReferenceResolutionError as error:
                    findings.warn(error, source=relative, retainedView=None)
                    continue
                except (OSError, ValueError) as error:
                    findings.check(
                        False,
                        f"invalid validation properties input: {relative}: {error}",
                    )
                    continue
            findings.check(
                input_is_file(root / relative), f"validation input missing: {relative}"
            )
    if impact != scope:
        output_file = _imports_sync_progress.output_file
        print("Model impact: " + scope_diagnostic(impact, scope), file=output_file())
    for entry in impact:
        findings.check(
            entry in scope,
            f"Model source change requires affected validation scope: {'/'.join(entry)}",
        )
    for changed in sorted(changed_paths):
        for base in ("model/", "docs/designs/"):
            if changed.startswith(base):
                parts = Path(changed.removeprefix(base)).parts
                if base == "model/":
                    source_scope = _imports_model_sources.source_scope
                    try:
                        selected = source_scope(root, root / changed)
                        identity = (
                            selected.environment,
                            selected.target,
                            selected.service,
                        )
                    except ValueError as error:
                        findings.check(False, f"invalid Model source scope: {error}")
                        continue
                else:
                    identity = (
                        (
                            parts[0],
                            parts[1],
                            Path(parts[2]).stem if len(parts) == 3 else parts[2],
                        )
                        if len(parts) >= 3
                        else None
                    )
                findings.check(
                    identity in scope,
                    f"changed design path is outside validation scope: {changed}",
                )

    return impact


def check_project_topology(
    accounts, findings, root, template_mode, *, scope_import=True
):
    selected = _imports_model_importing_scope.selected
    path = root / "project.json"
    if template_mode:
        return
    text = input_text(path, encoding="utf-8")
    findings.check(text.endswith("\n"), "project.json must end with a newline")
    try:
        topology = json.loads(text)
    except json.JSONDecodeError as error:
        findings.errors.append(f"invalid project.json: {error}")
        return
    findings.check(isinstance(topology, dict), "project.json root must be an object")
    if not isinstance(topology, dict):
        return
    findings.check(
        set(topology) == {"projectName", "targets"},
        "project.json must contain only projectName and targets",
    )

    project_name = topology.get("projectName")
    findings.check(
        isinstance(project_name, str) and project_name not in {"", "UNSET"},
        "projectName is required",
    )

    targets = topology.get("targets")
    findings.check(
        isinstance(targets, list) and bool(targets), "targets must be a non-empty array"
    )
    if not isinstance(targets, list):
        return
    identity = selected(root) if scope_import else None
    if identity is not None:
        view_targets = _imports_model_importing_scope.view_targets
        target_scope = {item[:2] for item in view_targets(root)}
        targets = [
            target
            for target in targets
            if isinstance(target, dict)
            and (
                target.get("environment"),
                target.get("alias", target.get("awsAccountId")),
            )
            in target_scope
        ]
        findings.check(
            len(targets) == len(target_scope),
            "IMPORT validation targets must exist exactly once in project.json",
        )
    order: list[tuple[str, str]] = []
    environment_targets: dict[str, list[dict[str, str]]] = {}
    account_engines: dict[tuple[str, str], str] = {}
    execution_account_engines: dict[tuple[str, str], str] = {}
    required = {"environment", "awsAccountId", "awsRegion", "iacEngine"}
    allowed = required | {"alias", "awsProfile", "awsExecutionAccountId", "suffix"}
    for index, target_values in enumerate(targets, 1):
        findings.check(
            isinstance(target_values, dict), f"target {index} must be an object"
        )
        if not isinstance(target_values, dict):
            continue
        findings.check(
            required <= set(target_values) <= allowed,
            f"target {index} must contain {sorted(required)} and optional alias/awsProfile/awsExecutionAccountId/suffix only",
        )
        if not required <= set(target_values):
            continue
        values = list(target_values.values())
        findings.check(
            all(isinstance(value, str) for value in values),
            f"target {index} values must be strings",
        )
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
        for field, label in (
            ("awsAccountId", "account"),
            ("awsExecutionAccountId", "execution account"),
            ("awsProfile", "profile"),
        ):
            if field not in target_values:
                continue
            try:
                if field == "awsProfile":
                    select_profile(target_values)
                else:
                    validate_account_id(target_values[field])
            except IdentityError:
                findings.check(False, f"invalid AWS {label}: {target}")
            else:
                findings.check(True, f"invalid AWS {label}: {target}")
        if "suffix" in target_values:
            findings.check(
                LOWER_KEBAB_PATTERN.fullmatch(target_values["suffix"]) is not None,
                f"invalid naming suffix: {target}: expected a non-empty lower-kebab-case string",
            )
        findings.check(
            "UNSET" not in values and all(values),
            f"target contains unset value: {target}",
        )
        findings.check(
            LOWER_KEBAB_PATTERN.fullmatch(environment) is not None,
            f"invalid Environment ID: {environment}",
        )
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
                re.fullmatch(r"[a-z]{2,}(?:-[a-z0-9]+)+-[1-9][0-9]*", region)
                is not None,
                f"invalid AWS region ID: {target}: {region}",
            )
        findings.check(
            engine in {"cloudformation", "terraform"}, f"invalid IaC engine: {target}"
        )
        findings.check(
            engine != "terraform" or environment != "modules",
            f"Terraform environment conflicts with shared modules directory: {target}",
        )
        key = (environment, target_directory)
        order.append(key)
        findings.check(
            key not in accounts, f"duplicate target directory in environment: {target}"
        )
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
        if identity is not None:
            continue
        aliases = [value.get("alias", "") for value in environment_values]
        if len(environment_values) == 1:
            findings.check(
                not aliases[0],
                f"single-target environment must omit alias: {environment}",
            )
        else:
            findings.check(
                all(aliases),
                f"multi-target environment requires alias on every target: {environment}",
            )
    findings.check(
        order == sorted(order),
        "targets must be sorted by environment and target directory",
    )
    return


def check_initialized_paths(
    accounts, findings, root, scope, template_mode, *, candidates=False
):
    if template_mode:
        return
    for (environment, target_directory), values in accounts.items():
        if scope is not None and not any(
            item[:2] == (environment, target_directory) for item in scope
        ):
            continue
        paths = (
            []
            if candidates
            else [root / "docs" / "designs" / environment / target_directory]
        )
        if values["engine"] == "cloudformation":
            paths.append(
                root
                / "infra"
                / "cloudformation"
                / "parameters"
                / environment
                / target_directory
            )
        elif values["engine"] == "terraform":
            paths.append(root_directory(root, (environment, target_directory)))
        for path in paths:
            findings.check(
                input_is_dir(path),
                f"initialized target path missing: {findings.relative(path)}",
            )

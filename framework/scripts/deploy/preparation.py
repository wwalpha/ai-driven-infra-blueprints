#!/usr/bin/env python3
"""Prepare CloudFormation offline, register its contract, or explicitly launch one controller."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import task_contract_core as _imports_task_contract
import worktree_python
import worktree_state
from model.dependency_index import revision as file_revision
from model.sources import stack_snapshot
from utils.aws.identity import execution_account, select_profile
from utils.aws_mappings import definition_root
from utils.file_operations import sha
from utils.project_targets import load_target

from deploy import cli_guidance
from deploy.inputs import deployment_input_paths, load_units, paths
from deploy.required_readings import required_readings
from deploy.timing import Timing


def environment(root):
    """Report all missing dependencies together, without probing another interpreter."""
    versions, errors, missing = {}, [], []
    for name, distribution in (
        ("boto3", "boto3"),
        ("botocore", "botocore"),
        ("yaml", "PyYAML"),
    ):
        try:
            importlib.import_module(name)
            versions[distribution] = importlib.metadata.version(distribution)
        except (ImportError, importlib.metadata.PackageNotFoundError):
            errors.append(f"missing Python dependency: {distribution}")
            missing.append(distribution)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"], capture_output=True, encoding="utf-8"
    )
    if result.returncode:
        missing.append("pip-check")
        errors.append(
            "Python dependency consistency failed: "
            + (result.stdout + result.stderr).strip()
        )
    tools = {name: shutil.which(name) for name in ("git",)}
    errors.extend(
        f"missing command: {name}" for name, path in tools.items() if path is None
    )
    missing.extend(name for name, path in tools.items() if path is None)
    if errors:
        raise cli_guidance.PreparationError(
            "\n".join(errors),
            code="PREPARATION_ENVIRONMENT_INCOMPLETE",
            missing=missing,
        )
    return {"python": sys.executable, "versions": versions, "tools": tools}


def candidate(root, task, env, directory, target, stacks, services):
    safe_path = _imports_task_contract.safe_path
    files, sources, generated_views = {task}, set(), set()
    for service in services:
        source = root / "model" / env / directory / (service + ".properties")
        design = root / "docs/designs" / env / directory / (service + ".md")
        files.update(model_input_paths(root, [f"{env}/{directory}/{service}"]))
        views = {design, *design.with_suffix("").rglob("*.json")}
        generated_views.update(views)
        files.update(path.relative_to(root).as_posix() for path in views)
        if service == "cloudformation-stacks":
            sources.update(stack_snapshot(source).dependencies)
    for path in files:
        safe_path(root, path)
    scope = [f"{env}/{directory}/{service}" for service in services]
    units = ", ".join(f"`{name}`" for name in stacks)
    lines = [
        "# Prepared deployment",
        "",
        "## Task contract",
        "",
        "- Task type: `infrastructure`",
        "- Task status: `running`",
        "- Infrastructure phase: `deploy`",
        f"- Target environment: `{env}`",
        f"- Target AWS account: `{target['awsAccountId']}`",
    ]
    if "alias" in target:
        lines.append(f"- Target alias: `{target['alias']}`")
    lines += [
        f"- Goal: {env}/{directory}の承認済みCloudFormation {units}を元Taskの許可範囲でdeployし、必要なobservedを同期する。",
        f"- Deployment scope: {units}",
        "- AWS API execution: `allowed`",
        "- Deploy/apply: `allowed`",
        "- Authorized delete/replacement: `none`",
        "",
        "## Validation scope",
        "",
    ]
    lines += [f"- `{value}`" for value in scope]
    lines += [
        "",
        "## Required changes",
        "",
        "- [R1] 指定stackのdeploy完了と成功後のobserved同期を確認する。",
        "",
        "## Acceptance checks",
        "",
    ]
    lines += [
        "## Modified files",
        "",
        *[f"- `{path}`" for path in sorted(files)],
        "",
        "## Allowed paths",
        "",
        *[f"- `{path}`" for path in sorted(files)],
        "",
    ]
    return "\n".join(lines), sources, scope, generated_views


@_imports_task_contract.task_read_scope
def prepare(root, args, run, timing):
    TASK_NAME = _imports_task_contract.TASK_NAME
    contracts = _imports_task_contract.contracts
    safe_path = _imports_task_contract.safe_path
    if not TASK_NAME.fullmatch(args.task_file):
        raise ValueError("use a new tasks/<task-name>.md")
    if (
        not args.service
        or len(set(args.service)) != len(args.service)
        or any(
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", service)
            for service in args.service
        )
    ):
        raise ValueError("explicit, unique service IDs are required")
    with timing.phase("environment"):
        runtime = environment(root)
    with timing.phase("contractPreparation"):
        target = load_target(root, args.environment, args.aws_account_id, args.alias)
        if target["iacEngine"] != "cloudformation":
            raise ValueError(
                "offline preparation currently supports CloudFormation only"
            )
        profile = select_profile(target, args.profile)
        directory = args.alias or target["awsAccountId"]
        limit, units = load_units(root, args.environment, directory, args.stack)
        services = sorted(set(args.service) | {"cloudformation-stacks"})
        text, sources, scope, generated_views = candidate(
            root,
            args.task_file,
            args.environment,
            directory,
            target,
            args.stack,
            services,
        )
        execution_inputs = set(
            deployment_input_paths(root, args.environment, directory, target, units)
        )
        if generated_views & execution_inputs:
            raise ValueError("generated view conflicts with execution/required input")
        text = text.replace(
            "- Authorized delete/replacement: `none`",
            "- Authorized delete/replacement: `none`\n- Runtime recovery: `allowed`\n"
            + (
                "- External IaC repair: `allowed`"
                if getattr(args, "allow_external_repair", False)
                else "- External IaC repair: `forbidden`"
            ),
        )
        checks = [
            f"- [R1] `exists:{path.relative_to(root).as_posix()}`"
            for unit in units
            for path in paths(root, args.environment, directory, target, unit)
        ]
        text = text.replace(
            "## Acceptance checks\n",
            "## Acceptance checks\n" + "\n".join(sorted(set(checks))) + "\n",
        )
        records = contracts(root)
        if args.task_file in records:
            raise ValueError(
                "task already exists; select its current contract for an independent controller run"
            )
        contract = run / "contract.md"
        contract.write_text(text, encoding="utf-8")
    with timing.phase("documentRead"):
        rules = required_readings(root)
        required = [
            "AGENTS.md",
            "project.json",
            ".agents/skills/deploy/SKILL.md",
        ]
        sources.update(rules)
        required_inputs = {
            *(
                (
                    definition_root(root)
                    if path.startswith(("framework/", ".agents/"))
                    else root
                )
                / path
                for path in required
            ),
            *rules,
        }
        conflicts = generated_views & (execution_inputs | required_inputs)
        if conflicts:
            raise ValueError(
                "generated view conflicts with execution/required input: "
                + ", ".join(
                    path.relative_to(root).as_posix() for path in sorted(conflicts)
                )
            )
        sources.update(required_inputs)
        deferred = (
            execution_inputs
            | generated_views
            | {root / p for p in model_input_paths(root, scope)}
        )
        deferred -= sources
        identities = {}
        for path in deferred:
            safe_path(root, path.relative_to(root).as_posix())
            identities[path.relative_to(root).as_posix()] = file_revision(path)
        documents, hashes = [], {}
        docs = run / "documents"
        docs.mkdir()
        for index, path in enumerate(sorted(sources), 1):
            base = root if path.is_relative_to(root) else definition_root(root)
            relative = path.relative_to(base).as_posix()
            safe_path(base, relative)
            data = path.read_bytes()
            hashes[relative] = hashlib.sha256(data).hexdigest()
            if path in rules and data.decode("utf-8") != rules[path]["sourceText"]:
                raise ValueError(f"rule changed during preparation: {relative}")
            # Generated views and binary build artifacts remain fingerprinted, without body chunks.
            if path in generated_views or path.suffix == ".zip":
                continue
            content = rules[path]["text"] if path in rules else data.decode("utf-8")
            chunks = []
            for offset in range(0, len(content), 6000):
                output = docs / f"{index:03d}-{len(chunks) + 1:03d}.txt"
                output.write_text(content[offset : offset + 6000], encoding="utf-8")
                chunks.append(str(output))
            documents.append(
                {
                    "source": relative,
                    "sha256": hashes[relative],
                    "chunks": chunks,
                    "sections": rules[path]["sections"] if path in rules else [""],
                }
            )
        summary = {
            "environment": args.environment,
            "alias": target.get("alias"),
            "resourceAccount": target["awsAccountId"],
            "executionAccount": execution_account(target),
            "region": target["awsRegion"],
            "profile": profile,
            "maxConcurrentStacks": 1 if args.sequential else limit,
            "stacks": units,
            "serviceIds": services,
            "inputPaths": sorted(
                path.relative_to(root).as_posix()
                for path in sources
                if path.is_relative_to(root)
            ),
            "deliveryRequired": any(
                unit.get("artifacts")
                or paths(root, args.environment, directory, target, unit)[0]
                .stat()
                .st_size
                > 51200
                for unit in units
            ),
            "problems": [],
        }
        summary_text = json.dumps(summary, ensure_ascii=False, indent=2)
        summary_file = run / "target-summary.json"
        summary_file.write_text(summary_text, encoding="utf-8")
        documents.append(
            {
                "source": "target-summary",
                "chunks": [str(summary_file)],
                "kind": "variable",
            }
        )
        chunks = []
        content = contract.read_text(encoding="utf-8")
        for offset in range(0, len(content), 6000):
            output = docs / f"contract-{len(chunks) + 1:03d}.txt"
            output.write_text(content[offset : offset + 6000], encoding="utf-8")
            chunks.append(str(output))
        documents.append(
            {
                "source": args.task_file,
                "sha256": sha(contract),
                "chunks": chunks,
                "kind": "variable",
            }
        )
    selector = (
        ["--alias", args.alias]
        if args.alias
        else ["--aws-account-id", args.aws_account_id]
    )
    command = [
        sys.executable,
        str(definition_root(root) / "framework/scripts/cloudformation-deploy.py"),
        "--environment",
        args.environment,
        *selector,
    ]
    if (root / ".git").exists() and worktree_python.runtime(root) is not None:
        worktree_state.managed_task_state(root, args.task_file)
        command += ["--action", "advance"]
    for unit in units:
        command += ["--stack", unit["name"]]
    command += ["--timing-log", str(timing.path)]
    if args.profile:
        command += ["--profile", args.profile]
    if args.sequential:
        command.append("--sequential")
    return {
        "repository": str(root),
        "taskFile": args.task_file,
        "contract": str(contract),
        "contractDigest": sha(contract),
        "runtime": runtime,
        "inputs": hashes,
        "inputIdentities": identities,
        "documents": documents,
        "generatedViews": sorted(
            path.relative_to(root).as_posix() for path in generated_views
        ),
        "scope": scope,
        "controllerArgv": command,
        "modelInputPaths": model_input_paths(root, scope),
        "environment": {
            key: os.environ[key] for key in ("PATH", "PYTHONPATH") if key in os.environ
        }
        | {"BLUEPRINT_TASK_FILE": args.task_file, "PYTHONDONTWRITEBYTECODE": "1"},
        "reviewStarted": time.perf_counter(),
    }


def model_input_paths(root, scope):
    """Declared entrances and part file identities only; no authority expansion."""
    return sorted(
        {
            path.relative_to(root).as_posix()
            for entry in scope
            for source in [root / "model" / (entry + ".properties")]
            for path in [source, *source.with_suffix("").rglob("*.properties")]
        }
    )


def register(root, path, timing):
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["repository"] != str(root) or plan["runtime"]["python"] != sys.executable:
        raise cli_guidance.InputChanged(
            "use the same repository and Python interpreter as preparation",
            condition="repository-or-python",
        )
    if any(
        os.environ.get(key) != value
        for key, value in plan["environment"].items()
        if key in {"PATH", "PYTHONPATH"}
    ):
        raise cli_guidance.InputChanged(
            "prepared runtime environment changed", condition="runtime-environment"
        )
    if time.perf_counter() < plan["reviewStarted"]:
        raise cli_guidance.InputChanged(
            "preparation clock reset; prepare again", condition="preparation-clock"
        )
    if {name: shutil.which(name) for name in plan["runtime"]["tools"]} != plan[
        "runtime"
    ]["tools"]:
        raise cli_guidance.InputChanged(
            "prepared command paths changed", condition="command-paths"
        )
    with timing.phase("documentReview", started=plan["reviewStarted"]):
        safe_path = _imports_task_contract.safe_path
        for relative, digest in plan["inputs"].items():
            base = (
                definition_root(root)
                if relative.startswith(("framework/", ".agents/"))
                else root
            )
            safe_path(base, relative)
            if not (base / relative).is_file() or sha(base / relative) != digest:
                raise cli_guidance.InputChanged(
                    f"preparation input changed or deleted; review the change and necessary inputs, then prepare again: {relative}",
                    target=relative,
                    condition="input-file",
                )
        if any(
            file_revision(root / p) != identity
            for p, identity in plan["inputIdentities"].items()
        ):
            raise cli_guidance.InputChanged(
                "deferred deployment input changed; prepare again",
                condition="deferred-inputs",
            )
        if model_input_paths(root, plan["scope"]) != plan["modelInputPaths"]:
            raise cli_guidance.InputChanged(
                "preparation Model dependency file set changed; prepare again",
                condition="model-file-set",
            )
        contract = Path(plan["contract"]).resolve()
        if contract.is_relative_to(root) or sha(contract) != plan["contractDigest"]:
            raise cli_guidance.InputChanged(
                "contract candidate changed; prepare again",
                condition="contract-candidate",
            )
    with timing.phase("contractRegistration"):
        result = subprocess.run(
            [
                sys.executable,
                str(definition_root(root) / "framework/scripts/task_contract.py"),
                "--repository-root",
                str(root),
                "--task-file",
                plan["taskFile"],
                "--source",
                str(contract),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode:
            raise ValueError(
                result.stdout.strip()
                or result.stderr.strip()
                or "contract registration failed"
            )
    plan["registeredContractDigest"] = sha(root / plan["taskFile"])
    plan["preparationSeconds"] += time.perf_counter() - plan["reviewStarted"]
    plan["within60Seconds"] = plan["preparationSeconds"] <= 60
    path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return plan


def run_controller(root, path):
    """One subprocess/run for the entire prepared scope; safety stays in the controller."""
    task_snapshot = _imports_task_contract.task_snapshot
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["repository"] != str(root) or plan["controllerArgv"][:2] != [
        sys.executable,
        str(definition_root(root) / "framework/scripts/cloudformation-deploy.py"),
    ]:
        raise ValueError("use the prepared repository and Python interpreter")
    if any(
        argument.split("=", 1)[0] == "--repository-root"
        for argument in plan["controllerArgv"][2:]
    ):
        raise ValueError(
            "controller repository must come from the prepared working directory"
        )
    snapshot = task_snapshot(root, plan["taskFile"])
    if snapshot.raw_digest != plan["registeredContractDigest"]:
        raise ValueError(
            "registered contract changed; review the current Task before a new run"
        )
    if any(
        os.environ.get(key) != value
        for key, value in plan["environment"].items()
        if key in {"PATH", "PYTHONPATH"}
    ):
        raise ValueError("prepared runtime environment changed")
    return subprocess.run(
        plan["controllerArgv"], cwd=root, env=os.environ | plan["environment"]
    ).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=cli_guidance.PREPARATION_HELP,
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().resolve())
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--register",
        type=Path,
        help="register a reviewed external preparation.json; never deploy",
    )
    mode.add_argument(
        "--run-controller",
        type=Path,
        help="execute an explicitly authorized registered plan, one controller only",
    )
    parser.add_argument("--environment")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--alias")
    selector.add_argument("--aws-account-id")
    parser.add_argument("--stack", action="append")
    parser.add_argument(
        "--service",
        action="append",
        help="all owning/referencing service IDs, explicitly reviewed",
    )
    parser.add_argument("--task-file")
    parser.add_argument("--profile")
    parser.add_argument(
        "--allow-external-repair",
        action="store_true",
        help="explicitly authorize the separate implement repair loop",
    )
    parser.add_argument("--sequential", action="store_true")
    parser.add_argument(
        "--log-dir", type=Path, help="external parent for a fresh preparation directory"
    )
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    selected_plan = args.register or args.run_controller
    plan_path = selected_plan.resolve() if selected_plan else None
    parent = (
        selected_plan.resolve().parent
        if selected_plan
        else (args.log_dir or Path(tempfile.gettempdir())).resolve()
    )
    if parent.is_relative_to(root):
        parser.error("preparation outputs must be outside repository")
    if not selected_plan and not all(
        (
            args.environment,
            args.alias or args.aws_account_id,
            args.stack,
            args.task_file,
        )
    ):
        parser.error("environment, target, stack and new task-file are required")
    parent.mkdir(parents=True, exist_ok=True)
    run = (
        parent
        if selected_plan
        else Path(tempfile.mkdtemp(prefix="blueprint-deploy-prepare-", dir=parent))
    )
    timing = Timing(root, run / "timing.jsonl")
    started = time.perf_counter()
    try:
        if args.run_controller:
            return run_controller(root, args.run_controller.resolve())
        with timing.phase("registration" if args.register else "preparation"):
            if args.register:
                plan = register(root, plan_path, timing)
            else:
                plan = prepare(root, args, run, timing)
                plan["preparationSeconds"] = time.perf_counter() - started
                plan["within60Seconds"] = plan["preparationSeconds"] <= 60
                plan_path = run / "preparation.json"
                plan_path.write_text(
                    json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        print(
            json.dumps(
                {
                    "result": "REGISTERED" if args.register else "PREPARED_OFFLINE",
                    **cli_guidance.preparation_result(
                        root, plan_path, bool(args.register)
                    ),
                    "plan": str(plan_path),
                    "timing": str(timing.path),
                    "preparationSeconds": plan["preparationSeconds"],
                    "within60Seconds": plan["within60Seconds"],
                },
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, KeyError) as error:
        print(
            json.dumps(
                {
                    "result": "STOPPED",
                    **cli_guidance.stopped(
                        "CONTROLLER_LAUNCH"
                        if args.run_controller
                        else "REGISTRATION"
                        if args.register
                        else "PREPARATION",
                        error,
                    ),
                },
                indent=2,
            )
        )
        print(
            f"Deployment preparation: BLOCKED ({error}); timing: {timing.path}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

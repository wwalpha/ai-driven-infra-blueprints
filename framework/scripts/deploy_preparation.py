#!/usr/bin/env python3
"""Prepare CloudFormation offline, register its contract, or explicitly launch one controller."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Lock
import time


class Timing:
    """Invocation-owned, thread-safe diagnostics outside the repository."""
    def __init__(self, root, path=None):
        self.path = Path(path).resolve() if path else None
        self.lock = Lock()
        if self.path:
            if self.path.is_relative_to(root.resolve()):
                raise ValueError("deployment timing must be outside repository")
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def phase(self, name, started=None, **fields):
        started, result = time.perf_counter() if started is None else started, "PASS"
        try:
            yield
        except BaseException:
            result = "FAIL"
            raise
        finally:
            if self.path:
                event = {"phase": name, "seconds": time.perf_counter() - started,
                         "result": result, "utc": datetime.now(timezone.utc).isoformat(),
                         "pid": os.getpid(), "python": sys.executable, **fields}
                with self.lock, self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def environment(root):
    """Report all missing dependencies together, without probing another interpreter."""
    versions, errors = {}, []
    for name, distribution in (("boto3", "boto3"), ("botocore", "botocore"),
                               ("yaml", "PyYAML"), ("cfnlint", "cfn-lint")):
        try:
            importlib.import_module(name)
            versions[distribution] = importlib.metadata.version(distribution)
        except (ImportError, importlib.metadata.PackageNotFoundError):
            errors.append(f"missing Python dependency: {distribution}")
    requirement = (root / "framework/scripts/requirements-aws-compare.txt").read_text(encoding="utf-8")
    for line in requirement.splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.split("==")
            if name in versions and versions[name] != version:
                errors.append(f"{name} requires {version}; found {versions[name]}")
    tools = {name: shutil.which(name) for name in ("aws", "cfn-lint", "git")}
    errors.extend(f"missing command: {name}" for name, path in tools.items() if path is None)
    if errors:
        raise ValueError("\n".join(errors))
    return {"python": sys.executable, "versions": versions, "tools": tools}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate(root, task, env, directory, target, stacks, services):
    from model_files import model_parts, read_model, model_file_contents
    from model_design import properties, entries
    from task_contract import safe_path
    sync = module("preparation_sync", root / "framework/scripts/sync-model.py")
    files, sources = {task}, set()
    for service in services:
        source = root / "model" / env / directory / (service + ".properties")
        design = root / "docs/designs" / env / directory / (service + ".md")
        text = read_model(source)
        values = properties(text)
        parts = model_parts(source)
        sources.update([source, *parts, design])
        files.update(path.relative_to(root).as_posix() for path in [source, *parts, design])
        # Reserve possible part growth before observed sync; no model values are written.
        additions = []
        for rid, row in entries(values, "desired.row."):
            for field in ("property", "value", "comment"):
                key = f"observed.row.{rid}.{field}"
                if key not in values:
                    additions.append(key + "=" + row[field])
            if match := sync.JSON_LINK.fullmatch(row["value"]):
                artifact = (design.parent / match.group(1)).resolve()
                if not artifact.is_relative_to(design.parent / service):
                    raise ValueError(f"generated JSON must belong to selected service: {artifact}")
                files.add(artifact.relative_to(root).as_posix())
                sources.add(artifact)
        projected = text if not additions else text.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
        files.update(path.relative_to(root).as_posix() for path in model_file_contents(source, projected))
    for path in files:
        safe_path(root, path)
    scope = [f"{env}/{directory}/{service}" for service in services]
    units = ", ".join(f"`{name}`" for name in stacks)
    lines = ["# Prepared deployment", "", "## Task contract", "",
             "- Task type: `infrastructure`", "- Task status: `running`", "- Infrastructure phase: `deploy`",
             f"- Target environment: `{env}`", f"- Target AWS account: `{target['awsAccountId']}`"]
    if "alias" in target:
        lines.append(f"- Target alias: `{target['alias']}`")
    lines += [f"- Goal: {env}/{directory}の承認済みCloudFormation {units}を変更せずdeployし、必要なobservedを同期する。",
              f"- Deployment scope: {units}", "- AWS API execution: `allowed`", "- Deploy/apply: `allowed`",
              "- Authorized delete/replacement: `none`", "", "## Validation scope", ""]
    lines += [f"- `{value}`" for value in scope]
    lines += ["", "## Required changes", "", "- [R1] 指定stackのdeploy完了と成功後のobserved同期を確認する。",
              "", "## Acceptance checks", ""]
    lines += ["## Modified files", "", *[f"- `{path}`" for path in sorted(files)],
              "", "## Allowed paths", "", *[f"- `{path}`" for path in sorted(files)], ""]
    return "\n".join(lines), sources, scope


def prepare(root, args, run, timing):
    from task_contract import TASK_NAME, contracts, reservations, safe_path
    from issue_gate import issue_errors
    if not TASK_NAME.fullmatch(args.task_file) or args.task_file == "tasks/active.md":
        raise ValueError("use a new tasks/<task-name>.md")
    if not args.service or len(set(args.service)) != len(args.service) or any(
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", service) for service in args.service):
        raise ValueError("explicit, unique service IDs are required")
    with timing.phase("environment"):
        runtime = environment(root)
    with timing.phase("contractPreparation"):
        controller = module("preparation_controller", root / "framework/scripts/cloudformation-deploy.py")
        context = module("preparation_context", root / "framework/scripts/check-deploy-context.py")
        target = context.load_target(root, args.environment, args.aws_account_id, args.alias)
        if target["iacEngine"] != "cloudformation":
            raise ValueError("offline preparation currently supports CloudFormation only")
        if target.get("awsProfile") and args.profile is not None and args.profile != target["awsProfile"]:
            raise ValueError("explicit AWS profile does not match target awsProfile")
        directory = args.alias or target["awsAccountId"]
        _, units = controller.load_units(root, args.environment, directory, args.stack)
        services = sorted(set(args.service) | {"cloudformation-stacks"})
        text, sources, scope = candidate(root, args.task_file, args.environment, directory, target, args.stack, services)
        errors = issue_errors(root, {tuple(value.split("/")) for value in scope})
        if errors:
            raise ValueError("\n".join(errors))
        backend = controller.AwsBackend(root, args.environment, directory, target, args.profile)
        for unit in units:
            sources.update(backend.paths(unit))
            sources.update(backend.source_path(artifact) for artifact in unit.get("artifacts", []))
        checks = [f"- [R1] `exists:{path.relative_to(root).as_posix()}`" for unit in units for path in backend.paths(unit)]
        text = text.replace("## Acceptance checks\n", "## Acceptance checks\n" + "\n".join(sorted(set(checks))) + "\n")
        records = contracts(root)
        if args.task_file in records:
            raise ValueError("task already exists; resume the existing task/session")
        reservations(root, {**records, args.task_file: text})
        contract = run / "contract.md"
        contract.write_text(text, encoding="utf-8")
    with timing.phase("documentRead"):
        required = ["AGENTS.md", "README.md", "project.json", "framework/prompts/codex/04_deploy.md",
                    "framework/rules/detailed-design.md", "framework/rules/model-information.md",
                    "framework/rules/cloudformation.md", "framework/rules/observed-values.md",
                    "framework/rules/loop-engineering.md"]
        sources.update(root / path for path in required)
        documents, hashes = [], {}
        docs = run / "documents"
        docs.mkdir()
        for index, path in enumerate(sorted(sources), 1):
            relative = path.relative_to(root).as_posix()
            safe_path(root, relative)
            data = path.read_bytes()
            hashes[relative] = hashlib.sha256(data).hexdigest()
            # Binary build artifacts are fingerprinted, never rendered as documents.
            if path.suffix == ".zip":
                continue
            content = data.decode("utf-8")
            chunks = []
            for offset in range(0, len(content), 6000):
                output = docs / f"{index:03d}-{len(chunks) + 1:03d}.txt"
                output.write_text(content[offset:offset + 6000], encoding="utf-8")
                chunks.append(str(output))
            documents.append({"source": relative, "sha256": hashes[relative], "chunks": chunks})
        chunks = []
        content = contract.read_text(encoding="utf-8")
        for offset in range(0, len(content), 6000):
            output = docs / f"contract-{len(chunks) + 1:03d}.txt"
            output.write_text(content[offset:offset + 6000], encoding="utf-8")
            chunks.append(str(output))
        documents.append({"source": args.task_file, "sha256": sha(contract), "chunks": chunks})
    selector = ["--alias", args.alias] if args.alias else ["--aws-account-id", args.aws_account_id]
    command = [sys.executable, str(root / "framework/scripts/cloudformation-deploy.py"),
               "--environment", args.environment, *selector]
    for unit in units:
        command += ["--stack", unit["name"]]
    command += ["--state", str(run / "session.json"), "--timing-log", str(timing.path)]
    if args.profile:
        command += ["--profile", args.profile]
    if args.sequential:
        command.append("--sequential")
    return {"repository": str(root), "taskFile": args.task_file, "contract": str(contract),
            "contractDigest": sha(contract), "runtime": runtime, "inputs": hashes, "documents": documents,
            "scope": scope, "controllerArgv": command,
            "environment": {key: os.environ[key] for key in ("PATH", "PYTHONPATH") if key in os.environ}
                           | {"BLUEPRINT_TASK_FILE": args.task_file, "PYTHONDONTWRITEBYTECODE": "1"},
            "reviewStarted": time.perf_counter()}


def register(root, path, timing):
    from issue_gate import issue_errors
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["repository"] != str(root) or plan["runtime"]["python"] != sys.executable:
        raise ValueError("use the same repository and Python interpreter as preparation")
    if any(os.environ.get(key) != value for key, value in plan["environment"].items() if key in {"PATH", "PYTHONPATH"}):
        raise ValueError("prepared runtime environment changed")
    if time.perf_counter() < plan["reviewStarted"]:
        raise ValueError("preparation clock reset; prepare again")
    if {name: shutil.which(name) for name in plan["runtime"]["tools"]} != plan["runtime"]["tools"]:
        raise ValueError("prepared command paths changed")
    with timing.phase("documentReview", started=plan["reviewStarted"]):
        from task_contract import safe_path
        for relative, digest in plan["inputs"].items():
            safe_path(root, relative)
            if sha(root / relative) != digest:
                raise ValueError(f"preparation input changed; reread and prepare again: {relative}")
        contract = Path(plan["contract"]).resolve()
        if contract.is_relative_to(root) or sha(contract) != plan["contractDigest"]:
            raise ValueError("contract candidate changed; prepare again")
    with timing.phase("contractRegistration"):
        errors = issue_errors(root, {tuple(value.split("/")) for value in plan["scope"]})
        if errors:
            raise ValueError("\n".join(errors))
        result = subprocess.run([sys.executable, str(root / "framework/scripts/task_contract.py"),
                                 "--repository-root", str(root), "--task-file", plan["taskFile"],
                                 "--source", str(contract)], capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise ValueError(result.stdout.strip() or result.stderr.strip() or "contract registration failed")
    plan["preparationSeconds"] += time.perf_counter() - plan["reviewStarted"]
    plan["within60Seconds"] = plan["preparationSeconds"] <= 60
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def run_controller(root, path):
    """One subprocess/session for the entire prepared scope; safety stays in the controller."""
    from task_contract import task_path
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["repository"] != str(root) or plan["controllerArgv"][:2] != [sys.executable, str(root / "framework/scripts/cloudformation-deploy.py")]:
        raise ValueError("use the prepared repository and Python interpreter")
    selected = task_path(root, plan["taskFile"])
    if sha(selected) != plan["contractDigest"]:
        raise ValueError("registered contract changed; use existing controller resume procedure")
    if any(os.environ.get(key) != value for key, value in plan["environment"].items() if key in {"PATH", "PYTHONPATH"}):
        raise ValueError("prepared runtime environment changed")
    state = Path(plan["controllerArgv"][plan["controllerArgv"].index("--state") + 1])
    if state.exists():
        raise ValueError("controller session already exists; resume that same session")
    return subprocess.run(plan["controllerArgv"], cwd=root, env=os.environ | plan["environment"]).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--register", type=Path, help="register a reviewed external preparation.json; never deploy")
    mode.add_argument("--run-controller", type=Path, help="execute an explicitly authorized registered plan, one controller only")
    parser.add_argument("--environment")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--alias")
    selector.add_argument("--aws-account-id")
    parser.add_argument("--stack", action="append")
    parser.add_argument("--service", action="append", help="all owning/referencing service IDs, explicitly reviewed")
    parser.add_argument("--task-file")
    parser.add_argument("--profile")
    parser.add_argument("--sequential", action="store_true")
    parser.add_argument("--log-dir", type=Path, help="external parent for a fresh preparation directory")
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    selected_plan = args.register or args.run_controller
    parent = (selected_plan.resolve().parent if selected_plan else (args.log_dir or Path(tempfile.gettempdir())).resolve())
    if parent.is_relative_to(root):
        parser.error("preparation outputs must be outside repository")
    if not selected_plan and not all((args.environment, args.alias or args.aws_account_id, args.stack, args.task_file)):
        parser.error("environment, target, stack and new task-file are required")
    parent.mkdir(parents=True, exist_ok=True)
    run = parent if selected_plan else Path(tempfile.mkdtemp(prefix="blueprint-deploy-prepare-", dir=parent))
    timing = Timing(root, run / "timing.jsonl")
    started = time.perf_counter()
    try:
        if args.run_controller:
            return run_controller(root, args.run_controller.resolve())
        with timing.phase("registration" if args.register else "preparation"):
            if args.register:
                plan = register(root, args.register.resolve(), timing)
            else:
                plan = prepare(root, args, run, timing)
                plan["preparationSeconds"] = time.perf_counter() - started
                plan["within60Seconds"] = plan["preparationSeconds"] <= 60
                (run / "preparation.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"result": "REGISTERED" if args.register else "PREPARED_OFFLINE",
                          "plan": str(run / "preparation.json"), "timing": str(timing.path),
                          "preparationSeconds": plan["preparationSeconds"], "within60Seconds": plan["within60Seconds"]}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, KeyError) as error:
        print(f"Deployment preparation: BLOCKED ({error}); timing: {timing.path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

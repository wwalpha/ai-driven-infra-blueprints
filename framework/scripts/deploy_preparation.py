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


def markdown_prose(text):
    """Yield original offsets and lines outside fenced examples."""
    offset, fence = 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            yield offset, line
        offset += len(line)


def markdown_sections(text):
    """Index real headings and their explicit anchors, ignoring fenced examples."""
    headings, aliases = [], []
    for offset, line in markdown_prose(text):
        if match := re.fullmatch(r'<a id="([^"<>]+)"></a>\s*', line):
            aliases.append(match[1])
        elif match := re.match(r"^(#{1,6}) (.+?)\s*#*\s*$", line):
            anchor = re.sub(r"[^\w -]", "", match[2].lower()).replace(" ", "-")
            headings.append((offset, len(match[1]), [anchor, *aliases]))
            aliases = []
    result = {}
    for index, (start, level, anchors) in enumerate(headings):
        end = next((pos for pos, depth, _ in headings[index + 1:] if depth <= level), len(text))
        for anchor in anchors:
            if anchor in result and result[anchor] != text[start:end]:
                raise ValueError(f"ambiguous rule section: {anchor}")
            result[anchor] = text[start:end]
    return result


def rule_readings(root, source, text, engine=None):
    """Use the document's rule links as the single source of reading scope."""
    from task_contract import safe_path
    root, source = root.resolve(), source.resolve()
    readings, contents = {}, {}
    prose = "".join(re.sub(r"(`+).*?\1", "", line) for _, line in markdown_prose(text))
    for raw in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", prose):
        if ":" in raw or raw.startswith("#"):
            continue
        target, _, anchor = raw.partition("#")
        if Path(target).suffix != ".md":
            continue
        path = (source.parent / target).resolve()
        if not any(path.is_relative_to(root / directory) for directory in ("framework/rules", ".agents/skills")):
            continue
        relative = path.relative_to(root).as_posix()
        safe_path(root, relative)
        if path not in contents:
            contents[path] = path.read_bytes().decode("utf-8")
        content = contents[path]
        sections = markdown_sections(content)
        if anchor and anchor not in sections:
            raise ValueError(f"missing rule section: {source.relative_to(root)} -> {relative}#{anchor}")
        if engine and path.name in {"cloudformation.md", "terraform.md"} and path.stem != engine:
            continue
        readings.setdefault(path, set()).add(anchor)
    return {path: {"sections": sorted(anchors), "sourceText": contents[path],
                   "text": contents[path] if "" in anchors
                   else "\n".join(markdown_sections(contents[path])[anchor] for anchor in sorted(anchors))}
            for path, anchors in readings.items()}


def candidate(root, task, env, directory, target, stacks, services):
    from model_files import model_parts, read_model, model_file_contents
    from model_design import properties, entries
    from task_contract import safe_path
    sync = module("preparation_sync", root / "framework/scripts/sync-model.py")
    files, sources, generated_views = {task}, set(), set()
    for service in services:
        source = root / "model" / env / directory / (service + ".properties")
        design = root / "docs/designs" / env / directory / (service + ".md")
        text = read_model(source)
        values = properties(text)
        parts = model_parts(source)
        sources.update([source, *parts, design])
        generated_views.add(design)
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
                if "document" not in row:
                    raise ValueError(f"authoritative JSON document missing: resource {rid.rpartition('-')[0]}, row {rid}, path {artifact.relative_to(root)}")
                files.add(artifact.relative_to(root).as_posix())
                sources.add(artifact)
                generated_views.add(artifact)
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
    return "\n".join(lines), sources, scope, generated_views


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
        text, sources, scope, generated_views = candidate(root, args.task_file, args.environment, directory, target, args.stack, services)
        errors = issue_errors(root, {tuple(value.split("/")) for value in scope})
        if errors:
            raise ValueError("\n".join(errors))
        backend = controller.AwsBackend(root, args.environment, directory, target, args.profile)
        execution_inputs = {path for unit in units for path in backend.paths(unit)}
        execution_inputs.update(backend.source_path(artifact) for unit in units for artifact in unit.get("artifacts", []))
        sources.update(execution_inputs)
        checks = [f"- [R1] `exists:{path.relative_to(root).as_posix()}`" for unit in units for path in backend.paths(unit)]
        text = text.replace("## Acceptance checks\n", "## Acceptance checks\n" + "\n".join(sorted(set(checks))) + "\n")
        records = contracts(root)
        if args.task_file in records:
            raise ValueError("task already exists; resume the existing task/session")
        reservations(root, {**records, args.task_file: text})
        contract = run / "contract.md"
        contract.write_text(text, encoding="utf-8")
    with timing.phase("documentRead"):
        prompt = root / "framework/prompts/codex/04_deploy.md"
        reading = markdown_sections(prompt.read_text(encoding="utf-8"))["read-before-changing-files"]
        reading = reading.split("\n### Conditional rule readings", 1)[0]
        rules = rule_readings(root, prompt, reading, engine="cloudformation")
        if not rules:
            raise ValueError("deployment prompt has no required rule readings")
        required = ["AGENTS.md", "project.json", "framework/prompts/codex/04_deploy.md"]
        sources.update(rules)
        required_inputs = {*(root / path for path in required), *rules}
        conflicts = generated_views & (execution_inputs | required_inputs)
        if conflicts:
            raise ValueError("generated view conflicts with execution/required input: " +
                             ", ".join(path.relative_to(root).as_posix() for path in sorted(conflicts)))
        sources.update(required_inputs)
        documents, hashes = [], {}
        docs = run / "documents"
        docs.mkdir()
        for index, path in enumerate(sorted(sources), 1):
            relative = path.relative_to(root).as_posix()
            safe_path(root, relative)
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
                output.write_text(content[offset:offset + 6000], encoding="utf-8")
                chunks.append(str(output))
            documents.append({"source": relative, "sha256": hashes[relative], "chunks": chunks,
                              "sections": rules[path]["sections"] if path in rules else [""],
                              "sourceCharacters": len(data.decode("utf-8")), "readCharacters": len(content)})
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
            "generatedViews": sorted(path.relative_to(root).as_posix() for path in generated_views),
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
            if not (root / relative).is_file() or sha(root / relative) != digest:
                raise ValueError(f"preparation input changed or deleted; review the change and necessary inputs, then prepare again: {relative}")
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

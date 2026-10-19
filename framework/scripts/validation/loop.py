#!/usr/bin/env python3
"""Run the deterministic local blueprint validation on any supported OS."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from validation_scope import active_scope
from regression_guard import authorize_full_regression
from task_contract import SELECTOR, task_path, suspend, contracts


class StartupDiagnostics:
    """Persist startup progress without depending on the console or timing log."""

    def __init__(self, root, directory):
        self.root = root
        self.directory = directory
        self.current = {"step": "diagnostics.start", "api": "pathlib.Path.open", "cwd": str(root)}

    def record(self, event, **fields):
        with (self.directory / "startup.jsonl").open("a", encoding="utf-8", errors="backslashreplace") as stream:
            stream.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                                     "event": event, **self.current, **fields}, ensure_ascii=True) + "\n")
            stream.flush()

    @contextmanager
    def step(self, name, api, **fields):
        previous = self.current
        self.current = {"step": name, "api": api, "cwd": str(self.root), **fields}
        self.record("start")
        yield
        self.record("end")
        self.current = previous

    def print(self, message):
        with self.step("stdout.print", "builtins.print"):
            print(message)
        with self.step("stdout.flush", "sys.stdout.flush"):
            sys.stdout.flush()

    def failure(self, error):
        frames = traceback.extract_tb(error.__traceback__)
        last = frames[-1] if frames else None
        details = {**self.current, "exception_type": type(error).__name__, "message": str(error),
                   "errno": getattr(error, "errno", None), "winerror": getattr(error, "winerror", None),
                   "filename": getattr(error, "filename", None), "filename2": getattr(error, "filename2", None),
                   "command": getattr(error, "cmd", None) or self.current.get("command"),
                   "returncode": getattr(error, "returncode", None),
                   "location": {"filename": last.filename, "line": last.lineno, "function": last.name,
                                "source": last.line} if last else None,
                   "traceback": "".join(traceback.format_exception(error))}
        # A separate file still works when opening/writing startup.jsonl itself failed.
        for save in (lambda: (self.directory / "startup-error.json").write_text(
                json.dumps(details, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"),
                     lambda: self.record("error", **details)):
            try:
                save()
            except OSError:
                pass
        return details


def changed_paths(root: Path) -> set[str]:
    changed = set()
    for arguments in (["diff", "--no-renames", "--name-only", "-z"],
                      ["diff", "--cached", "--no-renames", "--name-only", "-z"],
                      ["ls-files", "--others", "--exclude-standard", "-z"]):
        result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError("cannot determine changed paths for framework regression")
        changed.update(path for path in result.stdout.split("\0") if path)
    return changed


def framework_changed(paths: set[str]) -> bool:
    # Shared distribution inputs; cover all framework dependencies without a resolver.
    return any(path.startswith(("framework/", ".agents/")) or path in {"AGENTS.md", "README.md"}
               for path in paths)


def run_commands(root: Path, commands: list[list[str]], environment: dict[str, str],
                 directory: Path, heartbeat_seconds: float = 30, jobs: int = 1,
                 diagnostics=None, stop_after_validator_failure=False, validation_call=None) -> int:
    """Only adjacent regression scripts overlap; diagnostics retain command order."""
    started = time.perf_counter()
    failed = []
    status = "error"
    running = {}
    completed = {}
    next_index = 0
    displayed = 0
    diagnostics = diagnostics or StartupDiagnostics(root, directory)
    diagnostics.print(f"Local loop logs: {directory}")
    with diagnostics.step("timing.open", "pathlib.Path.open", target_path=str(directory / "timing.jsonl")):
        timing = (directory / "timing.jsonl").open("w", encoding="utf-8", buffering=1)
    with timing:
        def record(event, **fields):
            timing.write(json.dumps({"event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.perf_counter() - started, 6), **fields},
                ensure_ascii=False) + "\n")

        def regression(command):
            return command[0] != "git" and (command[1].endswith(".checks.py") or
                                           Path(command[1]).name.startswith("test_"))

        def finish(index, item, returncode, error="", interrupted=False):
            process, stream, step, output, began, _ = item
            stream.close()
            duration = time.perf_counter() - began
            result = "interrupted" if interrupted else "error" if error else "pass" if returncode == 0 else "fail"
            record("step_end", step=step, status=result, returncode=returncode,
                   duration_seconds=round(duration, 6), error=error, output=str(output))
            completed[index] = (step, output, duration, result, error)

        record("loop_start", repository=str(root), pid=os.getpid(), python=sys.executable,
               step_count=len(commands), jobs=jobs, python_version=sys.version,
               hash_seed=environment.get("PYTHONHASHSEED"))
        try:
            while next_index < len(commands) or running:
                while next_index < len(commands) and len(running) < jobs:
                    command = commands[next_index]
                    if running and (not regression(command) or
                                    any(not regression(commands[i]) for i in running)):
                        break
                    index = next_index
                    step = "git-diff-check" if command[0] == "git" else Path(command[1]).name
                    output = directory / f"{index + 1:02d}-{step}.log"
                    began = time.perf_counter()
                    record("step_start", step=step, output=str(output), command=command)
                    print(f"[{index + 1}/{len(commands)}] START {step}", flush=True)
                    stream = output.open("w", encoding="utf-8")
                    item = [None, stream, step, output, began, began]
                    # Register before launching so interruption always closes the log.
                    running[index] = item
                    next_index += 1
                    if index == 0 and validation_call is not None:
                        from contextlib import redirect_stdout, redirect_stderr
                        try:
                            record('step_running', step=step, pid=os.getpid())
                            with redirect_stdout(stream), redirect_stderr(stream):
                                returncode = validation_call()
                            finish(index, running.pop(index), returncode)
                        except (OSError, ValueError, KeyError, TypeError) as error:
                            finish(index, running.pop(index), 1, str(error))
                        break
                    try:
                        child_environment = {key: value for key, value in environment.items()
                                             if not regression(command) or key != SELECTOR}
                        item[0] = subprocess.Popen(command, cwd=root, env=child_environment,
                                                   stdout=stream, stderr=subprocess.STDOUT)
                        record("step_running", step=step, pid=item[0].pid)
                    except OSError as error:
                        finish(index, running.pop(index), None, str(error))
                    if not regression(command):
                        break
                for index, item in list(running.items()):
                    process, stream, step, output, began, last_heartbeat = item
                    try:
                        returncode = process.wait(timeout=min(0.05, heartbeat_seconds))
                    except subprocess.TimeoutExpired:
                        now = time.perf_counter()
                        if now - last_heartbeat >= heartbeat_seconds:
                            item[5] = now
                            record("heartbeat", step=step, pid=process.pid,
                                   duration_seconds=round(now - began, 6))
                            print(f"[{index + 1}/{len(commands)}] RUNNING {step} ({now - began:.1f}s, PID {process.pid})", flush=True)
                    else:
                        finish(index, running.pop(index), returncode)
                while displayed in completed:
                    step, output, duration, result, error = completed.pop(displayed)
                    with output.open(encoding="utf-8", errors="replace") as stream:
                        shutil.copyfileobj(stream, sys.stdout)
                    print(f"[{displayed + 1}/{len(commands)}] {result.upper()} {step} ({duration:.1f}s){': ' + error if error else ''}", flush=True)
                    if result != "pass":
                        failed.append(step)
                    displayed += 1
                    if stop_after_validator_failure and displayed == 1 and result != 'pass':
                        record('steps_skipped', reason='integrated validator failed', count=len(commands) - next_index)
                        next_index = len(commands)
            status = "fail" if failed else "pass"
            if failed:
                print(f"Blueprint local loop: FAIL ({', '.join(failed)})", flush=True)
                return 1
            count = sum(regression(command) for command in commands)
            print(f"Blueprint local loop: PASS ({count} framework regression scripts)", flush=True)
            return 0
        except KeyboardInterrupt:
            status = "interrupted"
            print("Blueprint local loop: INTERRUPTED (remaining checks not executed)", flush=True)
            return 130
        finally:
            # Signal every child before waiting for any of them.
            for item in running.values():
                if item[0] is not None:
                    item[0].terminate()
            for index, item in running.items():
                process = item[0]
                if process is not None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                finish(index, item, process.returncode if process is not None else None, interrupted=True)
            record("loop_end", status=status, failed_steps=failed,
                   duration_seconds=round(time.perf_counter() - started, 6))
            print(f"Local loop elapsed: {time.perf_counter() - started:.1f}s; timing: {directory / 'timing.jsonl'}", flush=True)


def utf8_environment():
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0",
            "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def utf8_preflight(directory, environment, diagnostics=None):
    diagnostics = diagnostics or StartupDiagnostics(Path.cwd(), directory)
    command = [sys.executable, "-X", "utf8", "-c",
               "from pathlib import Path; import sys; "
               "p=Path(sys.argv[1]); p.write_text('日本語', encoding='utf-8'); "
               "assert p.read_text(encoding='utf-8') == '日本語'; print('日本語')",
               str(directory / "utf8.txt")]
    with diagnostics.step("utf8.subprocess", "subprocess.run", command=command):
        result = subprocess.run(command, cwd=diagnostics.root, env=environment,
                                capture_output=True, encoding="utf-8", check=True)
    with diagnostics.step("utf8.output", "str.strip"):
        if result.stdout.strip() != "日本語":
            raise ValueError("UTF-8 preflight failed")
    with diagnostics.step("utf8.cleanup", "pathlib.Path.unlink", target_path=str(directory / "utf8.txt")):
        (directory / "utf8.txt").unlink()


def select_checks(root, paths, affected=False):
    unit_root = root / "framework/scripts/tests/units"
    checks = sorted({*(root / "framework/scripts/tests").rglob("*.checks.py"),
                     *unit_root.rglob("test_*.py")}, key=lambda path: path.name)
    units = [path for path in checks if path.is_relative_to(unit_root)]
    if not units:
        raise ValueError("no framework regression checks discovered")
    if not affected:
        return units, "all UT requested"
    # Exact paths only: unknown siblings and unresolved deletions stay full regression.
    mapping = {path.relative_to(root).as_posix(): {path.name} for path in checks}
    mapping["framework/scripts/tests/integrations/parameter_cases.py"] = {"service-parameter-inputs.checks.py"}
    mapping["framework/scripts/tests/integrations/service_contracts.py"] = {"model_parameter_inputs.checks.py"}
    mapping["framework/scripts/blueprint-loop.py"] = {"blueprint-loop.checks.py"}
    mapping.update({f"framework/scripts/tests/{category}/validation_checks/{name}.py":
                    {"validate-blueprint.checks.py", "validation-units.checks.py"}
                    for category in ("units", "integrations")
                    for name in ("task", "design", "references", "cloudformation", "scope", "contracts",
                                 "scenario", "runner", "terraform")})
    mapping["framework/scripts/tests/support/validator.py"] = {check.name for check in checks}
    mapping["framework/scripts/tests/integrations/model_design.checks.py"] = {check.name for check in checks}
    mapping["framework/scripts/tests/integrations/rotation_schedule.checks.py"] = {"rotation_schedule.checks.py", "cloudformation-deploy.checks.py"}
    # check_links/check_projection dynamically load the reference fixture and its layout inputs.
    mapping["framework/scripts/tests/integrations/design_document.checks.py"] = {
        "design_document.checks.py", "validate-blueprint.checks.py", "sync-model.checks.py"}
    mapping["framework/scripts/tests/integrations/design_layout.checks.py"] = {
        *mapping["framework/scripts/tests/integrations/design_document.checks.py"], "design_layout.checks.py", "policy_tables.checks.py"}
    # EC2 restoration is consumed through shared layout, projection and dynamic fixtures.
    mapping["framework/scripts/ec2_display.py"] = {check.name for check in checks}
    mapping["framework/scripts/model_core.py"] = {check.name for check in checks}
    for name in ("service_rows", "model_display"):
        mapping[f"framework/scripts/{name}.py"] = {check.name for check in checks}
    for name in ("model_projection", "model_references"):
        mapping[f"framework/scripts/{name}.py"] = {check.name for check in checks}
    for name in ("sync_runtime", "sync_views", "sync_files"):
        mapping[f"framework/scripts/{name}.py"] = {check.name for check in checks}
    comparison = {"comparison_core.checks.py", "issues_scan.checks.py", "check-model-aws.checks.py",
                  "cloudformation-deploy.checks.py", "deploy_preparation.checks.py", "model_files.checks.py"}
    mapping["framework/scripts/comparison_rows.py"] = comparison
    mapping["framework/scripts/check-model-aws.py"] = comparison
    mapping["framework/scripts/issues_iac.py"] = comparison - {"check-model-aws.checks.py"}
    mapping["framework/scripts/cloudformation-deploy.py"] = {"cloudformation-deploy.checks.py", "deploy_preparation.checks.py", "model_files.checks.py"}
    for name in ("__init__", "scheduler", "aws_adapter", "delivery", "change_sets", "repair", "secret_bootstrap", "session"):
        mapping[f"framework/scripts/deployment/{name}.py"] = mapping["framework/scripts/cloudformation-deploy.py"]
    # JSON/identity helpers are also used by shared design/catalog processing.
    mapping["framework/scripts/iac_values.py"] = {check.name for check in checks}
    mapping["framework/scripts/issues_reports.py"] = {"issues_scan.checks.py", "comparison_core.checks.py"}
    mapping["framework/scripts/issues_scan.py"] = {"issues_scan.checks.py"}
    mapping["framework/scripts/s3_delivery.py"] = {"cloudformation-deploy.checks.py", "deploy_preparation.checks.py", "model_files.checks.py"}
    mapping["framework/scripts/iac_evaluation.py"] = comparison - {"check-model-aws.checks.py"}
    mapping["framework/scripts/script_loader.py"] = comparison - {"check-model-aws.checks.py"}
    mapping.update({f"framework/scripts/validation/{name}.py": {check.name for check in checks}
                    for name in ("scenario", "cloudformation", "task", "framework_contracts", "project",
                                 "design", "design_tables", "design_links", "findings")})
    # A split suite keeps its unit cases in every existing dependency selection.
    names = {check.name for check in checks}
    for targets in mapping.values():
        targets.update(name.replace(".checks.py", "-unit.checks.py") for name in list(targets)
                       if name.replace(".checks.py", "-unit.checks.py") in names)
        if "validate-blueprint.checks.py" in targets and "validation-units.checks.py" in names:
            targets.add("validation-units.checks.py")
    mapping["framework/scripts/issues_iac.py"].update(
        path.name for path in units if path.name == "test_issues_iac.py")
    selected = set()
    for path in sorted(paths):
        if not framework_changed({path}):
            continue
        if path not in mapping or not (root / path).is_file() or not mapping[path] <= {check.name for check in checks}:
            return units, f"all UT: shared or unknown dependency: {path}"
        selected.update(mapping[path])
    return [path for path in units if path.name in selected], "affected: explicit leaf/runner mapping, UT only"


def git(root, *arguments, environment=None):
    return subprocess.run(["git", *arguments], cwd=root, env=environment,
                          capture_output=True, encoding="utf-8", check=True).stdout.strip()


def index_tree(root, directory):
    # Use a private index; write-tree must not lock or refresh the user's index.
    source = Path(git(root, "rev-parse", "--git-path", "index"))
    if not source.is_absolute():
        source = root / source
    private = directory / "index"
    shutil.copyfile(source, private)
    return git(root, "write-tree", environment={**os.environ, "GIT_INDEX_FILE": str(private)})


def staged_snapshot(root, args, directory, environment):
    base = git(root, "rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}")
    head = git(root, "rev-parse", "HEAD")
    tree = index_tree(root, directory)
    snapshot = directory / "repository"
    snapshot.mkdir()
    git(snapshot, "init", "--quiet")
    # Copy two trees and the comparison commit, without unrelated branch/history objects.
    objects = git(root, "rev-list", "--objects", "--no-object-names", f"{base}^{{tree}}", tree)
    with tempfile.TemporaryFile() as pack:
        subprocess.run(["git", "pack-objects", "--stdout"], cwd=root,
                       input=(base + "\n" + objects + "\n").encode(), stdout=pack,
                       stderr=subprocess.PIPE, check=True)
        pack.seek(0)
        subprocess.run(["git", "index-pack", "--stdin"], cwd=snapshot,
                       stdin=pack, capture_output=True, check=True)
    (snapshot / ".git/shallow").write_text(base + "\n", encoding="ascii")
    git(snapshot, "checkout", "--quiet", "--detach", base)
    git(snapshot, "read-tree", "--reset", "-u", tree)
    selected = task_path(snapshot).relative_to(snapshot).as_posix()
    import_task = '- Workflow: `import`' in contracts(snapshot).get(selected, '')
    try:
        if import_task:
            from import_guard import copy_import_proof
            copy_import_proof(root, snapshot)
        metadata = {"source": str(root), "base": base, "head": head, "tree": tree}
        (directory / "snapshot.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(f"Staged snapshot: {tree}; base: {base}; metadata: {directory / 'snapshot.json'}", flush=True)
        command = [sys.executable, "-X", "utf8", str(snapshot / "framework/scripts/blueprint-loop.py"),
                   "--mode", args.mode, "--jobs", str(args.jobs), "--log-dir", str(directory),
                   "--validation-jobs", str(args.validation_jobs), *(["--fresh"] if args.fresh else []),
                   *(["--all"] if args.all else []), *(["--affected"] if args.affected else []),
                   *(["--profile"] if args.profile else [])]
        if os.name == "nt":
            # Never dispatch an older staged entrypoint that predates the password gate.
            for name in ("blueprint-loop.py", "validation/loop.py", "regression_guard.py"):
                source = root / "framework/scripts" / name
                saved = snapshot / "framework/scripts" / name
                if not saved.is_file() or saved.read_bytes() != source.read_bytes():
                    raise ValueError("Windows staged validation requires the current runner and regression guard to be staged")
        # .lock is local configuration, outside the staged task tree.
        source_lock = root / ".lock"
        if source_lock.is_symlink():
            raise ValueError("repo .lock must be a regular file")
        saved_lock = source_lock.read_bytes() if source_lock.is_file() else None
        if saved_lock is not None:
            (snapshot / ".lock").write_bytes(saved_lock)
        process = subprocess.Popen(command, cwd=snapshot, env=environment,
                                   **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}))
        try:
            result = process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        current_tree = index_tree(root, directory)
        current_lock = source_lock.read_bytes() if source_lock.is_file() else None
        unchanged = current_tree == tree and git(root, "rev-parse", "HEAD") == head and current_lock == saved_lock
        metadata.update(returncode=result, source_unchanged=unchanged)
        (directory / "snapshot.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        if not unchanged:
            print("Staged snapshot is stale: source HEAD/index/.lock changed; result applies only to the saved tree.", flush=True)
            return 1
        return result
    finally:
        if import_task:
            from import_guard import discard_import_proof, evidence_store
            discard_import_proof(snapshot, selected)
            store = evidence_store(snapshot)
            # This freshly created snapshot owns its seal; source evidence is retained.
            (store / 'seal.key').unlink(missing_ok=True)
            store.rmdir()


def suspend_selected(root, selected, reason):
    if not selected:
        return  # Never guess which task to release when selection failed.
    try:
        if suspend(root, selected, reason):
            print(f"Task suspended: {selected}; reason recorded in the contract.", flush=True)
    except (OSError, ValueError) as error:
        try:
            print(f"Task suspension/notification failed: {selected}: {error}", file=sys.stderr, flush=True)
        except OSError:
            pass  # Suspension and the caller's failure exit must not depend on the console.


def failure_reason(directory, returncode):
    details = [f"Local loop failed (exit {returncode}); logs: {directory}"]
    timing = directory / "timing.jsonl"
    if timing.is_file():
        events = [json.loads(line) for line in timing.read_text(encoding="utf-8").splitlines()]
        for event in events:
            if event["event"] == "step_end" and event["status"] != "pass":
                details.append(f"{event['step']}: {event['status']}, exit {event['returncode']}; {event['error']}")
                output = Path(event["output"])
                details.append(f"Diagnostic log: {output}")
                if output.is_file():
                    details.extend(output.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
    return "\n".join(details)


def run_loop(root: Path, options, *, final_candidate=None) -> int:
    """Run the existing scheduler against explicit options and an optional final candidate.

    Returns the ordinary loop exit code, retaining logs/timing/stop rules. Final
    candidates use committed latest-base differences and read-only validation.
    """
    from task_contract import selected_task
    if final_candidate is not None and (root.resolve() != final_candidate.root or options.write or options.staged):
        raise ValueError('final loop requires the actual read-only candidate')
    with selected_task(root, final_candidate.task_file if final_candidate is not None else options.task_file):
        return _run_loop(root, options, final_candidate)


def _run_loop(root, args, final_candidate):
    def fail(message):
        raise ValueError(message)
    if args.staged and args.write or args.staged != bool(args.base):
        fail('invalid staged/write/base options')
    if args.affected and (args.mode == 'full' or args.all):
        fail('--affected cannot narrow full/--all validation')
    if cache_directory := os.environ.get("BLUEPRINT_VALIDATION_CACHE_DIR"):
        cache_path = Path(cache_directory).resolve()
        if cache_path == root or root in cache_path.parents:
            fail("validation cache must be outside the repository")
    selected_name = None if args.staged else args.task_file
    try:
        if not args.staged:
            selected = task_path(root)
            if selected.is_file():
                selected_name = selected.relative_to(root).as_posix()
        scope = active_scope(root, args.all) if not args.staged else set()
        if args.write and (scope == set() or args.all and active_scope(root) == set()):
            raise ValueError("--write requires service scope; framework scope cannot generate Models")
        repository_changed = set(final_candidate.changed_paths) if final_candidate is not None else changed_paths(root) if not args.staged else set()
        changed = repository_changed - {".lock"}
    except (OSError, ValueError) as error:
        suspend_selected(root, selected_name, f"Local loop preflight failed: {error}")
        fail(str(error))
    full_validation = scope is None
    regression = (args.mode == "full" or args.all or framework_changed(repository_changed)
                  or (args.mode == "local" and scope is None))
    try:
        checks, reason = select_checks(root, repository_changed, args.affected) if regression else ([], "shared framework unchanged")
    except ValueError as error:
        print(f"Blueprint local loop: ERROR ({error})", file=sys.stderr)
        suspend_selected(root, selected_name, f"Regression discovery failed: {error}")
        return 2
    if regression and not args.staged and (not args.affected or
            set(checks) == set(select_checks(root, set())[0])):
        try:
            authorize_full_regression(root)
        except KeyboardInterrupt:
            print("Full regression authorization cancelled; no checks started.", file=sys.stderr)
            suspend_selected(root, selected_name, "Full regression authorization cancelled; no checks started.")
            return 130
        except (OSError, ValueError) as error:
            print(f"Blueprint local loop: LOCKED ({error}); no checks started.", file=sys.stderr)
            suspend_selected(root, selected_name, f"Full regression authorization failed: {error}; no checks started.")
            return 2
    log_parent = (args.log_dir or Path(tempfile.gettempdir())).expanduser().resolve()
    if log_parent == root or root in log_parent.parents:
        fail("--log-dir must be outside the repository")
    log_parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="blueprint-loop-", dir=log_parent))
    diagnostics = StartupDiagnostics(root, directory)
    try:
        diagnostics.record("directory_created", directory=str(directory), pid=os.getpid(), python=sys.executable)
        diff_scope = []
        with diagnostics.step("task.contract.read", "pathlib.Path.read_text", task=selected_name):
            if not regression and not full_validation and selected_name:
                contract = (root / selected_name).read_text(encoding="utf-8").splitlines()
                if "- Task type: `infrastructure`" in contract and any(
                        f"- Infrastructure phase: `{phase}`" in contract for phase in ("deploy", "update")):
                    diff_scope = ["--", *[f":(top,literal){path}" for path in sorted(changed)]] if changed else ["--", ":(exclude)**"]
        command = ["git", "config", "--get", "core.whitespace"]
        with diagnostics.step("git.config", "subprocess.run", command=command):
            whitespace = subprocess.run(command, cwd=root, capture_output=True, encoding="utf-8")
            diagnostics.record("result", returncode=whitespace.returncode)
            if whitespace.returncode not in (0, 1):
                raise subprocess.CalledProcessError(whitespace.returncode, command,
                                                    whitespace.stdout, whitespace.stderr)
        with diagnostics.step("commands.prepare", "utf8_environment"):
            whitespace_rules = whitespace.stdout.strip() or "blank-at-eol,blank-at-eof,space-before-tab"
            diff_check = ["git", "-c", "core.whitespace=" + whitespace_rules + ",cr-at-eol", "diff"]
            commands = [
                [
                    sys.executable,
                    str(root / "framework" / "scripts" / "validate-blueprint.py"),
                    "--repository-root",
                    str(root),
                    "--jobs", str(args.validation_jobs),
                    *(["--write"] if args.write else []),
                    *(["--fresh"] if args.fresh or args.mode == "full" or args.all else []),
                    *(["--all"] if full_validation else []),
                    *(["--repository-wide-iac"] if regression else []),
                    *(["--contract-scope"] if args.mode in {"task", "full"} and scope is not None else []),
                ],
                *(
                    [sys.executable, str(path)]
                    for path in checks
                ),
                [*diff_check, "--check", *diff_scope],
                [*diff_check, "--cached", "--check", *diff_scope],
            ]
            environment = utf8_environment()
            if args.profile:
                environment["BLUEPRINT_PROFILE_DIR"] = str(directory)
        if not args.staged:
            diagnostics.print(f"Validation: {'all' if full_validation else 'active scope'}; "
                              f"framework regression: {('selected UT' if args.affected else 'all UT') if regression else 'skipped (shared framework unchanged)'}")
        if regression and not args.staged:
            diagnostics.print(f"Regression selection: {reason}; {len(checks)} UT suites selected: {', '.join(path.name for path in checks) or 'none'}")
            omitted = sorted(path.name for path in select_checks(root, set())[0] if path not in checks)
            diagnostics.print("IT execution: GitHub Actions only (0 local IT suites)")
            diagnostics.print(f"UT not executed: {', '.join(omitted) or 'none'}")
        utf8_preflight(directory, environment, diagnostics)
        if args.staged:
            return staged_snapshot(root, args, directory, environment)
        validation_call = None
        if not args.staged:
            from validation.runner import run_validation
            from types import SimpleNamespace
            def validation_call():
                validation_options = SimpleNamespace(task_file=selected_name, write=args.write,
                    all=full_validation, fresh=args.fresh or args.mode == 'full' or args.all,
                    jobs=args.validation_jobs, repository_wide_iac=regression,
                    contract_scope=args.mode in {'task', 'full'} and scope is not None)
                if args.profile:
                    import cProfile
                    import pstats
                    profile = cProfile.Profile()
                    try:
                        result = profile.runcall(run_validation, root, validation_options, final_candidate=final_candidate)
                    finally:
                        profile.dump_stats(str(directory / 'validate-blueprint.prof'))
                        pstats.Stats(profile).strip_dirs().sort_stats('cumulative').print_stats(25)
                else:
                    result = run_validation(root, validation_options, final_candidate=final_candidate)
                return result.display_report()
        if final_candidate is not None:
            commands[-2:] = [[*diff_check, '--check', final_candidate.base_commit, final_candidate.candidate_head, '--']]
        result = run_commands(root, commands, environment, directory, jobs=args.jobs, diagnostics=diagnostics, stop_after_validator_failure=args.write, validation_call=validation_call)
        if result:
            suspend_selected(root, selected_name, failure_reason(directory, result))
        return result
    except KeyboardInterrupt as error:
        diagnostics.failure(error)
        suspend_selected(root, selected_name, f"Local loop interrupted; checks incomplete; logs: {directory}")
        return 130
    except Exception as error:
        details = diagnostics.failure(error)
        suspend_selected(root, selected_name,
                         f"Local loop error at {details['step']} ({details['api']}): {error}; "
                         f"logs: {directory}; traceback: {directory / 'startup-error.json'}")
        try:
            print(f"Blueprint local loop: ERROR ({error}); logs: {directory}\n{details['traceback']}",
                  file=sys.stderr, flush=True)
        except OSError:
            pass  # The saved exception must survive a broken console.
        return 2


def interrupt(signum, frame):
    raise KeyboardInterrupt



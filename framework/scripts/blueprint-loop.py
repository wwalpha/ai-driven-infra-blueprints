#!/usr/bin/env python3
"""Run the deterministic local blueprint validation on any supported OS."""

from __future__ import annotations

import argparse
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

from validation_scope import active_scope
from regression_guard import authorize_full_regression
from task_contract import (SELECTOR, task_path, task_changes, suspend, contracts, reservations,
                           bind_worktree, worktree_owner, local_contract)


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
                 directory: Path, heartbeat_seconds: float = 30, jobs: int = 1) -> int:
    """Only adjacent regression scripts overlap; diagnostics retain command order."""
    started = time.perf_counter()
    failed = []
    status = "error"
    running = {}
    completed = {}
    next_index = 0
    displayed = 0
    print(f"Local loop logs: {directory}", flush=True)
    with (directory / "timing.jsonl").open("w", encoding="utf-8", buffering=1) as timing:
        def record(event, **fields):
            timing.write(json.dumps({"event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.perf_counter() - started, 6), **fields},
                ensure_ascii=False) + "\n")

        def regression(command):
            return command[0] != "git" and command[1].endswith(".checks.py")

        def finish(index, item, returncode, error="", interrupted=False):
            process, stream, step, output, began, _ = item
            stream.close()
            duration = time.perf_counter() - began
            result = "interrupted" if interrupted else "error" if error else "pass" if returncode == 0 else "fail"
            record("step_end", step=step, status=result, returncode=returncode,
                   duration_seconds=round(duration, 6), error=error, output=str(output))
            completed[index] = (step, output, duration, result, error)

        record("loop_start", repository=str(root), pid=os.getpid(), python=sys.executable,
               step_count=len(commands), jobs=jobs)
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
                    record("step_start", step=step, output=str(output))
                    print(f"[{index + 1}/{len(commands)}] START {step}", flush=True)
                    stream = output.open("w", encoding="utf-8")
                    item = [None, stream, step, output, began, began]
                    # Register before launching so interruption always closes the log.
                    running[index] = item
                    next_index += 1
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


def utf8_preflight(directory, environment):
    command = [sys.executable, "-X", "utf8", "-c",
               "from pathlib import Path; import sys; "
               "p=Path(sys.argv[1]); p.write_text('日本語', encoding='utf-8'); "
               "assert p.read_text(encoding='utf-8') == '日本語'; print('日本語')",
               str(directory / "utf8.txt")]
    result = subprocess.run(command, env=environment, capture_output=True, encoding="utf-8", check=True)
    if result.stdout.strip() != "日本語":
        raise ValueError("UTF-8 preflight failed")
    (directory / "utf8.txt").unlink()


def select_checks(root, paths, affected=False):
    checks = sorted((root / "framework/scripts").glob("*.checks.py"))
    if not affected:
        return checks, "all requested"
    # Only leaf test edits and the standalone runner have a proven narrow dependency set.
    mapping = {path.relative_to(root).as_posix(): {path.name} for path in checks}
    mapping["framework/scripts/blueprint-loop.py"] = {"blueprint-loop.checks.py"}
    selected = set()
    for path in sorted(paths):
        if not framework_changed({path}):
            continue
        if path not in mapping or not mapping[path] <= {check.name for check in checks}:
            return checks, f"all: shared or unknown dependency: {path}"
        selected.update(mapping[path])
    return [path for path in checks if path.name in selected], "affected: explicit leaf/runner mapping"


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
    # A validation snapshot executes source-local tasks in an independent Git directory.
    # Rebind only those contracts inside the disposable snapshot; foreign tasks stay foreign.
    for name, text in contracts(snapshot, include_foreign=True).items():
        if worktree_owner(text) is not None and local_contract(root, text):
            (snapshot / name).write_text(bind_worktree(snapshot, text), encoding="utf-8")
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
        for name in ("blueprint-loop.py", "regression_guard.py"):
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


def suspend_selected(root, selected, reason):
    if not selected:
        return  # Never guess which task to release when selection failed.
    try:
        if suspend(root, selected, reason):
            print(f"Task suspended: {selected}; reservations released; reason recorded in the contract.", flush=True)
    except (OSError, ValueError) as error:
        print(f"Task suspension failed: {selected}: {error}", file=sys.stderr)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("task", "full", "local"), required=True,
                        help="task/local: active-scope validation; full: also all regression tests")
    parser.add_argument("--all", action="store_true", help="Explicit whole-repository validation and all regression tests")
    parser.add_argument("--task-file", help="Selected tasks/<task-name>.md contract")
    parser.add_argument("--log-dir", type=Path, help="Parent directory for run logs (outside the repository; default: OS temporary directory)")
    parser.add_argument("--profile", action="store_true", help="Profile model_design/design_catalog checks into the run directory")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2, help="Independent regression workers (default: 2)")
    parser.add_argument("--validation-jobs", type=int, choices=(1, 2, 4), default=4,
                        help="Service validation workers (default: 4)")
    parser.add_argument("--fresh", action="store_true", help="Revalidate catalog/services without successful-result reuse")
    parser.add_argument("--staged", action="store_true", help="Validate a fixed staged tree in a private repository")
    parser.add_argument("--base", help="Explicit comparison commit for --staged (including incoming changes)")
    parser.add_argument("--affected", action="store_true", help="Select proven affected checks; unknown dependencies run all")
    args = parser.parse_args()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    if args.staged != bool(args.base):
        parser.error("--staged and --base must be specified together")
    if args.affected and (args.mode == "full" or args.all):
        parser.error("--affected cannot narrow full/--all validation")

    root = Path(__file__).resolve().parents[2]
    if cache_directory := os.environ.get("BLUEPRINT_VALIDATION_CACHE_DIR"):
        cache_path = Path(cache_directory).resolve()
        if cache_path == root or root in cache_path.parents:
            parser.error("validation cache must be outside the repository")
    selected_name = None if args.staged else os.environ.get(SELECTOR)
    try:
        if not args.staged:
            selected = task_path(root)
            if selected.is_file():
                selected_name = selected.relative_to(root).as_posix()
        scope = active_scope(root, args.all) if not args.staged else set()
        repository_changed = changed_paths(root) if not args.staged else set()
        changed = repository_changed
        if not args.staged:
            selected = task_path(root)
            if selected.is_file():
                changed = task_changes(root, changed - {".lock"}, selected.relative_to(root).as_posix())
    except (OSError, ValueError) as error:
        suspend_selected(root, selected_name, f"Local loop preflight failed: {error}")
        parser.error(str(error))
    full_validation = scope is None
    regression = (args.mode == "full" or args.all or framework_changed(repository_changed)
                  or (args.mode == "local" and scope is None))
    checks, reason = select_checks(root, repository_changed, args.affected) if regression else ([], "shared framework unchanged")
    if not args.staged:
        print(f"Validation: {'all' if full_validation else 'active scope'}; "
              f"framework regression: {('selected' if args.affected else 'all') if regression else 'skipped (shared framework unchanged)'}", flush=True)
    if regression and not args.staged:
        print(f"Regression selection: {reason}; selected: {', '.join(path.name for path in checks) or 'none'}", flush=True)
        omitted = sorted(path.name for path in (root / "framework/scripts").glob("*.checks.py") if path not in checks)
        print(f"Not executed: {', '.join(omitted) or 'none'}", flush=True)
    if regression and not args.staged and (not args.affected or
            set(checks) == set((root / "framework/scripts").glob("*.checks.py"))):
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
        parser.error("--log-dir must be outside the repository")
    log_parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="blueprint-loop-", dir=log_parent))
    diff_scope = []
    if not regression and not full_validation and selected_name:
        contract = (root / selected_name).read_text(encoding="utf-8").splitlines()
        if "- Task type: `infrastructure`" in contract and any(
                f"- Infrastructure phase: `{phase}`" in contract for phase in ("deploy", "update")):
            # Ownership was checked by task_changes above, including every unreserved change.
            diff_scope = ["--", *[f":(top,literal){path}" for path in sorted(changed)]] if changed else ["--", ":(exclude)**"]
    commands = [
        [
            sys.executable,
            str(root / "framework" / "scripts" / "validate-blueprint.py"),
            "--repository-root",
            str(root),
            "--jobs", str(args.validation_jobs),
            *(["--fresh"] if args.fresh or args.mode == "full" or args.all else []),
            *(["--all"] if full_validation else []),
            *(["--repository-wide-iac"] if regression else []),
            *(["--contract-scope"] if args.mode in {"task", "full"} and scope is not None else []),
        ],
        *(
            [sys.executable, str(path)]
            for path in checks
        ),
        ["git", "diff", "--check", *diff_scope],
        ["git", "diff", "--cached", "--check", *diff_scope],
    ]
    environment = utf8_environment()
    if args.profile:
        environment["BLUEPRINT_PROFILE_DIR"] = str(directory)
    try:
        utf8_preflight(directory, environment)
        if args.staged:
            return staged_snapshot(root, args, directory, environment)
        result = run_commands(root, commands, environment, directory, jobs=args.jobs)
        if result:
            suspend_selected(root, selected_name, failure_reason(directory, result))
        elif selected_name:
            pending = reservations(root, contracts(root))[selected_name].deferred
            if pending:
                print("Blueprint task: DEFERRED (Active checks passed; remains running): " + ", ".join(pending), flush=True)
        return result
    except KeyboardInterrupt:
        suspend_selected(root, selected_name, f"Local loop interrupted; checks incomplete; logs: {directory}")
        return 130
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Blueprint local loop: ERROR ({error}); logs: {directory}", file=sys.stderr)
        suspend_selected(root, selected_name, f"Local loop error: {error}; logs: {directory}")
        return 2


def interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupt)
    # UTF-8 mode must be set before Python initializes file/subprocess defaults.
    if not sys.flags.utf8_mode:
        os.execvpe(sys.executable, [sys.executable, "-X", "utf8", *sys.argv], utf8_environment())
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())

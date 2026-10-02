#!/usr/bin/env python3
"""Run the deterministic local blueprint validation on any supported OS."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from validation_scope import active_scope


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
                 directory: Path, heartbeat_seconds: float = 30) -> int:
    started = time.perf_counter()
    failed = []
    status = "error"
    print(f"Local loop logs: {directory}", flush=True)
    with (directory / "timing.jsonl").open("w", encoding="utf-8", buffering=1) as timing:
        def record(event, **fields):
            timing.write(json.dumps({
                "event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                **fields,
            }, ensure_ascii=False) + "\n")

        record("loop_start", repository=str(root), pid=os.getpid(),
               python=sys.executable, step_count=len(commands))
        try:
            for index, command in enumerate(commands, 1):
                step = "git-diff-check" if command[0] == "git" else Path(command[1]).name
                output = directory / f"{index:02d}-{step}.log"
                step_started = time.perf_counter()
                record("step_start", step=step, output=str(output))
                print(f"[{index}/{len(commands)}] START {step}", flush=True)
                returncode = None
                process = None
                interrupted = False
                error = ""
                with output.open("w", encoding="utf-8") as stream:
                    try:
                        process = subprocess.Popen(command, cwd=root, env=environment,
                                                   stdout=stream, stderr=subprocess.STDOUT)
                        try:
                            record("step_running", step=step, pid=process.pid)
                            while True:
                                try:
                                    returncode = process.wait(timeout=heartbeat_seconds)
                                    break
                                except subprocess.TimeoutExpired:
                                    elapsed = time.perf_counter() - step_started
                                    record("heartbeat", step=step, pid=process.pid,
                                           duration_seconds=round(elapsed, 6))
                                    print(f"[{index}/{len(commands)}] RUNNING {step} ({elapsed:.1f}s, PID {process.pid})", flush=True)
                        except BaseException:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                            raise
                    except KeyboardInterrupt:
                        interrupted = True
                        returncode = process.returncode if process is not None else None
                    except OSError as exception:
                        error = str(exception)
                duration = time.perf_counter() - step_started
                step_status = "pass" if returncode == 0 else "fail"
                if interrupted or error:
                    step_status = "interrupted" if interrupted else "error"
                record("step_end", step=step, status=step_status, returncode=returncode,
                       duration_seconds=round(duration, 6), error=error)
                with output.open(encoding="utf-8", errors="replace") as stream:
                    shutil.copyfileobj(stream, sys.stdout)
                print(f"[{index}/{len(commands)}] {step_status.upper()} {step} ({duration:.1f}s){': ' + error if error else ''}", flush=True)
                if interrupted:
                    status = "interrupted"
                    print("Blueprint local loop: INTERRUPTED (remaining checks not executed)", flush=True)
                    return 130
                if returncode != 0:
                    failed.append(step)
            status = "fail" if failed else "pass"
            if failed:
                print(f"Blueprint local loop: FAIL ({', '.join(failed)})", flush=True)
                return 1
            count = sum(command[1].endswith(".checks.py") for command in commands)
            print(f"Blueprint local loop: PASS ({count} framework regression scripts)", flush=True)
            return 0
        except KeyboardInterrupt:
            status = "interrupted"
            return 130
        finally:
            record("loop_end", status=status, failed_steps=failed,
                   duration_seconds=round(time.perf_counter() - started, 6))
            print(f"Local loop elapsed: {time.perf_counter() - started:.1f}s; timing: {directory / 'timing.jsonl'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("task", "full", "local"), required=True,
                        help="task/local: active-scope validation; full: also all regression tests")
    parser.add_argument("--all", action="store_true", help="Explicit whole-repository validation and all regression tests")
    parser.add_argument("--log-dir", type=Path, help="Parent directory for run logs (outside the repository; default: OS temporary directory)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    try:
        scope = active_scope(root, args.all)
        changed = changed_paths(root)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    full_validation = scope is None
    regression = (args.mode == "full" or args.all or framework_changed(changed)
                  or (args.mode == "local" and scope is None))
    checks = sorted((root / "framework" / "scripts").glob("*.checks.py")) if regression else []
    print(f"Validation: {'all' if full_validation else 'active scope'}; "
          f"framework regression: {'all' if regression else 'skipped (shared framework unchanged)'}", flush=True)
    log_parent = (args.log_dir or Path(tempfile.gettempdir())).expanduser().resolve()
    if log_parent == root or root in log_parent.parents:
        parser.error("--log-dir must be outside the repository")
    log_parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="blueprint-loop-", dir=log_parent))
    commands = [
        [
            sys.executable,
            str(root / "framework" / "scripts" / "validate-blueprint.py"),
            "--repository-root",
            str(root),
            *(["--all"] if full_validation else []),
            *(["--contract-scope"] if args.mode in {"task", "full"} and scope is not None else []),
        ],
        *(
            [sys.executable, str(path)]
            for path in checks
        ),
        ["git", "diff", "--check"],
        ["git", "diff", "--cached", "--check"],
    ]
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0",
                   "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        return run_commands(root, commands, environment, directory)
    except OSError as error:
        print(f"Blueprint local loop: ERROR ({error}); logs: {directory}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

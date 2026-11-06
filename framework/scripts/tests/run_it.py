#!/usr/bin/env python3
"""Official offline UT/IT entrypoint: isolated suites, one seed bundle, runtime receipts."""

import argparse
import ast
import json
import math
import os
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from contextlib import nullcontext, suppress
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest as _imports_pytest
import support.it_fixture_bundle as _imports_support_it_fixture_bundle
import validation.loop as _imports_validation_loop
from support.it_discovery import discover
from support.it_revision import compare_revisions
from support.pytest_cli import unit_commands
from support.worktree_test_policy import (
    POLICY_RECEIPT,
    POLICY_TOKEN,
    ordinary_suite,
    source_snapshot,
    violations,
)
from support.worktree_test_policy import audit as worktree_audit
from task_contract_core import SELECTOR

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TESTS = Path(__file__).resolve().parent
REPAIR_SUITE = "integrations/worktree-deploy-repair.checks.py"
REPAIR_CASES = (REPAIR_SUITE + "::check_external_implement_round_trip",)
CHECKPOINT_SUITE = "integrations/worktree-deploy-checkpoint.checks.py"
CHECKPOINT_CASES = tuple(
    CHECKPOINT_SUITE + "::" + name
    for name in (
        "check_parallel_checkpoint_and_restart",
        "check_combined_checkpoint_after_peer_completion",
    )
)
PARALLEL_CASES = {REPAIR_SUITE: REPAIR_CASES, CHECKPOINT_SUITE: CHECKPOINT_CASES}


def inventory(tests):
    discovery = discover(tests)
    return discovery, [*discovery.errors, *violations(tests)]


def path_setup(node):
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == "sys.path.insert"
        and len(node.value.args) == 2
        and not node.value.keywords
        and isinstance(node.value.args[0], ast.Constant)
        and node.value.args[0].value == 0
    )


def check_assertion_guards(tests):
    """Prove each entry rejects -O before definitions/calls, without launching every suite."""
    for path in sorted(tests.rglob("*.checks.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.If) and ast.unparse(node.test) == "not __debug__":
                expected = ast.parse(
                    "if not __debug__:\n raise SystemExit('Focused checks require assertions; run without -O')"
                ).body[0]
                if ast.dump(node) != ast.dump(expected):
                    raise ValueError(f"invalid assertion guard: {path}")
                code = compile(
                    ast.Module(body=[node], type_ignores=[]),
                    str(path),
                    "exec",
                    optimize=1,
                )
                try:
                    exec(code, {})
                except SystemExit as error:
                    if "Focused checks require assertions" not in str(error):
                        raise ValueError(
                            f"assertion guard did not reject optimization: {path}"
                        ) from error
                else:
                    raise ValueError(f"assertion guard did not exit: {path}")
                break
            allowed = (
                path_setup(node)
                or isinstance(node, (ast.Import, ast.ImportFrom))
                or isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                or isinstance(node, ast.Assign)
                and all(ast.unparse(t).startswith("sys.path[") for t in node.targets)
            )
            if not allowed:
                raise ValueError(f"code before assertion guard: {path}:{node.lineno}")
        else:
            raise ValueError(f"missing assertion guard: {path}")


class PytestReceipt:
    def __init__(self, tests, case_id=None):
        self.tests = tests
        self.case_id = case_id
        self.collected = []
        self.passed = []

    def pytest_configure(self, config):
        self.rootpath = config.rootpath

    def key(self, nodeid):
        path, name = nodeid.split("::", 1)
        return (
            (self.rootpath / path).resolve().relative_to(self.tests).as_posix()
            + "::"
            + name
        )

    def pytest_collection_modifyitems(self, session, config, items):
        if self.case_id is None:
            return
        found = [self.key(item.nodeid) for item in items]
        cases = PARALLEL_CASES.get(self.case_id.split("::", 1)[0], ())
        if self.case_id not in cases:
            raise ValueError(f"unknown repair case: {self.case_id}")
        if len(found) != len(cases) or set(found) != set(cases):
            raise ValueError(f"repair collection mismatch: {found}")
        selected = [item for item in items if self.key(item.nodeid) == self.case_id]
        deselected = [item for item in items if self.key(item.nodeid) != self.case_id]
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected

    def pytest_collection_finish(self, session):
        self.collected.extend(self.key(item.nodeid) for item in session.items)

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.passed.append(self.key(report.nodeid))


def _callback_run_child_audit(completed, metrics, tests, /, event, args):
    if event in ("shutil.copytree", "shutil.copyfile", "subprocess.Popen"):
        metrics[event] += 1
        if event == "subprocess.Popen" and Path(args[0]).stem == "git":
            metrics["subprocess.git"] += 1
    elif event == "blueprint.it_fixture.generated":
        metrics["generated:" + args[0]] += 1
    elif event == "blueprint.it_case.completed":
        source = Path(args[0]).resolve().relative_to(tests.resolve()).as_posix()
        completed[source + "::" + args[1]] += 1


def _callback_run_child_measured_pytest(
    plugin, pytest_main, /, args=None, plugins=None
):
    return pytest_main(args, plugins=[*(plugins or []), plugin])


def run_child(suite, tests, receipt, baseline=False, case_id=None):
    """Execute existing entrypoints, including pytest_cli.run and top-level scripts."""
    sys.path[:0] = [str(tests.parent), str(tests)]
    pytest = _imports_pytest
    plugin = PytestReceipt(tests, case_id)
    pytest_main = pytest.main
    measured_pytest = _bind_framework_callback(
        _callback_run_child_measured_pytest, plugin, pytest_main
    )
    pytest.main = measured_pytest
    completed, metrics = Counter(), Counter()
    suite_key = suite.resolve().relative_to(tests.resolve()).as_posix()
    audit = _bind_framework_callback(
        _callback_run_child_audit, completed, metrics, tests
    )
    sys.addaudithook(audit)
    sys.addaudithook(worktree_audit)
    sys.argv = [str(suite)]
    try:
        with nullcontext() if baseline else ordinary_suite(suite, tests):
            runpy.run_path(str(suite), run_name="__main__")
    finally:
        receipt.write_text(
            json.dumps(
                {
                    "version": 1,
                    "suite": suite_key,
                    "completed": completed,
                    "collected": plugin.collected,
                    "passed": plugin.passed,
                    "metrics": metrics,
                }
            ),
            encoding="utf-8",
        )


def receipt_errors(receipt, suite=None):
    if not isinstance(receipt, dict) or receipt.get("version") != 1:
        return ["missing/invalid runtime receipt schema"]
    owner = receipt.get("suite")
    if (
        not isinstance(owner, str)
        or not owner
        or (suite is not None and owner != suite)
    ):
        return ["invalid runtime receipt suite"]
    for field in ("completed", "metrics"):
        values = receipt.get(field)
        if not isinstance(values, dict) or any(
            not isinstance(k, str) or type(v) is not int or v < 1
            for k, v in values.items()
        ):
            return [f"invalid runtime receipt {field}"]
    for field in ("collected", "passed"):
        values = receipt.get(field)
        if not isinstance(values, list) or any(
            not isinstance(k, str) or not k.startswith(owner + "::") for k in values
        ):
            return [f"invalid runtime receipt {field}"]
        if len(set(values)) != len(values):
            return [f"duplicate runtime receipt {field}"]
    if any(
        not k.startswith("integrations/") or "::" not in k for k in receipt["completed"]
    ):
        return ["invalid runtime receipt completed owner"]
    if not set(receipt["passed"]) <= set(receipt["collected"]):
        return ["passed runtime case was not collected"]
    return []


def reachability(cases, receipts, registered=None, owners=None):
    registered = cases if registered is None else registered
    completed, collected, passed = Counter(), Counter(), Counter()
    errors = [] if cases else ["empty IT discovery"]
    suites = set()
    for receipt in receipts:
        invalid = receipt_errors(receipt)
        if invalid:
            errors += invalid
            continue
        owner = receipt["suite"]
        if owner in suites:
            errors.append(f"duplicate runtime receipt suite: {owner}")
        suites.add(owner)
        if owner not in {path for path, _ in cases if path.endswith(".checks.py")}:
            errors.append(f"unknown runtime receipt suite: {owner}")
        for key, count in receipt["completed"].items():
            identity = tuple(key.split("::", 1))
            if registered.get(identity) not in ("direct", "module"):
                errors.append(f"unknown completed IT case: {key}")
            elif owners is not None and owner not in owners.get(identity, set()):
                errors.append(f"incorrect completed IT owner: {owner}: {key}")
            completed[key] += count
        collected.update(receipt["collected"])
        passed.update(receipt["passed"])
        if set(receipt["collected"]) != set(receipt["passed"]):
            errors.append(f"{owner}: collected nodes did not all pass")
    for path in sorted(
        {path for path, _ in cases if path.endswith(".checks.py")} - suites
    ):
        errors.append(f"missing runtime receipt: {path}")
    for key in collected:
        if cases.get(tuple(key.split("[", 1)[0].split("::", 1))) != "pytest":
            errors.append(f"unknown collected IT case: {key}")
        if collected[key] != 1 or passed[key] != 1:
            errors.append(f"duplicate/incomplete pytest node: {key}")
    for (path, name), mode in cases.items():
        key = path + "::" + name
        if mode == "pytest":
            if not any(node.split("[", 1)[0] == key for node in collected):
                errors.append(f"{key}: expected pytest entry was not collected")
        elif mode not in ("direct", "module") or not completed[key]:
            errors.append(f"{key}: verification did not complete")
    return errors


def repair_receipt(receipts, suite=REPAIR_SUITE, cases=REPAIR_CASES):
    combined = {
        "version": 1,
        "suite": suite,
        "completed": {},
        "collected": [],
        "passed": [],
        "metrics": {},
    }
    if len(receipts) != len(cases):
        raise ValueError("missing repair case receipt")
    metrics = Counter()
    completed = Counter()
    for case, receipt in zip(cases, receipts, strict=True):
        invalid = receipt_errors(receipt, suite)
        if invalid:
            raise ValueError(f"{case}: {'; '.join(invalid)}")
        if receipt["collected"] != [case] or receipt["passed"] != [case]:
            raise ValueError(f"{case}: incorrect collected/passed cases")
        combined["collected"].extend(receipt["collected"])
        combined["passed"].extend(receipt["passed"])
        metrics.update(receipt["metrics"])
        completed.update(receipt["completed"])
    combined["metrics"] = dict(metrics)
    combined["completed"] = dict(completed)
    return combined


def run_parallel_repair(suite, tests, output):
    suite_key = suite.relative_to(tests).as_posix()
    cases = PARALLEL_CASES[suite_key]
    discovery, errors = inventory(tests)
    selected = {
        path + "::" + name
        for (path, name), mode in discovery.cases.items()
        if path == suite_key and mode == "pytest"
    }
    if errors or selected != set(cases):
        raise ValueError(f"parallel discovery mismatch: {selected}; {errors}")
    logs = Path(tempfile.mkdtemp(prefix="framework-repair-it-logs-"))
    children = []
    success = False
    try:
        deadline = time.monotonic() + (300 if suite_key == REPAIR_SUITE else 1800)
        for index, case in enumerate(cases):
            if index >= 2:
                previous_case, previous, _log, _receipt = children[index - 2]
                try:
                    code = previous.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(f"{previous_case}: process timed out") from error
                if code:
                    raise RuntimeError(f"{previous_case}: process exited {code}")
            receipt = output / f"repair-{index}.json"
            receipt.unlink(missing_ok=True)
            log = (logs / f"case-{index}.log").open("w", encoding="utf-8")
            environment = os.environ.copy()
            private = logs / f"case-{index}"
            private.mkdir()
            environment.update(
                {
                    "TMPDIR": str(private),
                    "TMP": str(private),
                    "TEMP": str(private),
                    "BLUEPRINT_VALIDATION_CACHE_DIR": str(private / "cache"),
                }
            )
            command = [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(Path(__file__).resolve()),
                "--suite",
                str(suite),
                "--tests",
                str(tests),
                "--receipt",
                str(receipt),
                "--case-id",
                case,
            ]
            try:
                process = subprocess.Popen(
                    command,
                    cwd=tests.parents[2],
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=(os.name != "nt"),
                )
            except BaseException:
                log.close()
                raise
            children.append((case, process, log, receipt))
        for case, process, _log, _receipt in children:
            try:
                code = process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f"{case}: process timed out") from error
            if code:
                raise RuntimeError(f"{case}: process exited {code}")
        if suite_key == REPAIR_SUITE and time.monotonic() > deadline:
            raise RuntimeError("repair suite: process timed out")
        receipts = []
        for case, _process, _log, receipt in children:
            try:
                receipts.append(json.loads(receipt.read_text(encoding="utf-8")))
            except (OSError, ValueError) as error:
                raise ValueError(f"{case}: missing/invalid receipt: {error}") from error
        result = repair_receipt(receipts, suite_key, cases)
        success = True
        return result
    finally:
        for _case, process, _log, _receipt in children:
            if process.poll() is None:
                if os.name != "nt":
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
        for _case, process, log, _receipt in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
            log.close()
        for index, (case, _process, _log, _receipt) in enumerate(children):
            print(f"--- {case} ---", flush=True)
            print(
                (logs / f"case-{index}.log").read_text(
                    encoding="utf-8", errors="replace"
                ),
                flush=True,
            )
        if success and suite_key != CHECKPOINT_SUITE:
            shutil.rmtree(logs)
        else:
            label = "Checkpoint" if suite_key == CHECKPOINT_SUITE else "Repair"
            print(f"{label} case logs retained: {logs}", file=sys.stderr, flush=True)


def execute_suites(tests, output, summary, baseline=False):
    suites = sorted((tests / "integrations").rglob("*.checks.py"))
    if not suites:
        raise ValueError("No integration suites discovered")
    rows, receipts = [], []
    summary.write("| IT suite | Result | Seconds |\n| --- | --- | ---: |\n")
    for suite in suites:
        print(f"::group::{suite.name}", flush=True)
        started = time.monotonic()
        receipt = output / (suite.name + ".json")
        if not baseline and suite.relative_to(tests).as_posix() in PARALLEL_CASES:
            receipt.unlink(missing_ok=True)
        try:
            if not baseline and suite.relative_to(tests).as_posix() in PARALLEL_CASES:
                data = run_parallel_repair(suite, tests, output)
                receipt.write_text(json.dumps(data), encoding="utf-8")
                code = 0
            else:
                code = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        "-X",
                        "utf8",
                        str(Path(__file__).resolve()),
                        *(["--baseline"] if baseline else []),
                        "--suite",
                        str(suite),
                        "--tests",
                        str(tests),
                        "--receipt",
                        str(receipt),
                    ],
                    cwd=tests.parents[2],
                ).returncode
        except (OSError, ValueError, RuntimeError) as error:
            print(error, file=sys.stderr, flush=True)
            code = 1
        elapsed = time.monotonic() - started
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
            invalid = receipt_errors(data, suite.relative_to(tests).as_posix())
            if invalid:
                raise ValueError("; ".join(invalid))
            receipts.append(data)
        except (OSError, ValueError) as error:
            print(
                f"missing/invalid runtime receipt: {suite.name}: {error}",
                file=sys.stderr,
            )
            code = 1
        status = "PASS" if code == 0 else "FAIL"
        rows.append(
            {
                "suite": suite.name,
                "code": code,
                "seconds": elapsed,
                "metrics": data.get("metrics", {}) if code == 0 else {},
            }
        )
        print(
            f"{status}: {suite.name} ({elapsed:.3f}s, exit={code})\n::endgroup::",
            flush=True,
        )
        summary.write(f"| {suite.name} | {status} | {elapsed:.3f} |\n")
        summary.flush()
    failed = sum(row["code"] != 0 for row in rows)
    summary.write(
        f"\nSuites: {len(rows)}; PASS: {len(rows) - failed}; FAIL: {failed}\n"
    )
    return rows, receipts


def _callback_run_all_audit(_state_run_all_284, metrics, /, event, args):
    if _state_run_all_284.measuring:
        if event in (
            "shutil.copytree",
            "shutil.copyfile",
            "subprocess.Popen",
            "blueprint.it_bundle.initialized",
        ):
            metrics[event] += 1
        elif event == "blueprint.it_fixture.generated":
            metrics["generated:" + args[0]] += 1


def run_all(tests, summary, baseline=False):
    policy_errors = [] if baseline else violations(tests)
    if policy_errors:
        raise ValueError("Worktree test policy: " + "; ".join(policy_errors))
    # Only the official runner owns the shared bundle's lifetime and cleanup.
    _state_run_all_284 = _CallbackState()
    if not baseline:
        ENV = _imports_support_it_fixture_bundle.ENV
        bundle = _imports_support_it_fixture_bundle.bundle
    else:
        ENV = "BLUEPRINT_IT_FIXTURES"
    discovery, errors = (None, []) if baseline else inventory(tests)
    cases = {} if discovery is None else discovery.cases
    if not baseline:
        check_assertion_guards(tests)
    started = time.monotonic()
    metrics = Counter()
    _state_run_all_284.measuring = True
    audit = _bind_framework_callback(
        _callback_run_all_audit, _state_run_all_284, metrics
    )
    sys.addaudithook(audit)
    previous = os.environ.pop(ENV, None)
    previous_cache = os.environ.get("BLUEPRINT_VALIDATION_CACHE_DIR")
    previous_task = os.environ.pop(SELECTOR, None)
    rows, receipts = [], []
    try:
        with tempfile.TemporaryDirectory(prefix="framework-it-receipts-") as directory:
            os.environ["BLUEPRINT_VALIDATION_CACHE_DIR"] = str(
                Path(directory) / "cache"
            )
            with nullcontext(None) if baseline else bundle() as fixture:
                if fixture is not None:
                    os.environ[ENV] = str(fixture)
                rows, receipts = execute_suites(
                    tests, Path(directory), summary, baseline
                )
                if not baseline and cases:
                    errors += reachability(cases, receipts, owners=discovery.owners)
    except RuntimeError as error:
        errors.append(str(error))
    finally:
        _state_run_all_284.measuring = False
        os.environ.pop(ENV, None)
        if previous is not None:
            os.environ[ENV] = previous
        if previous_cache is None:
            os.environ.pop("BLUEPRINT_VALIDATION_CACHE_DIR", None)
        else:
            os.environ["BLUEPRINT_VALIDATION_CACHE_DIR"] = previous_cache
        if previous_task is not None:
            os.environ[SELECTOR] = previous_task
    if not baseline:
        errors.extend(
            f"suite process failed: {row['suite']} (exit={row['code']})"
            for row in rows
            if row["code"]
        )
    for receipt in receipts:
        metrics.update(receipt.get("metrics", {}))
    result = {
        "seconds": time.monotonic() - started,
        "bundle_initializations": None
        if baseline
        else metrics["blueprint.it_bundle.initialized"],
        "seed_generations": None
        if baseline
        else {
            key.removeprefix("generated:"): count
            for key, count in metrics.items()
            if key.startswith("generated:")
        },
        "selection": "full",
        "selected_cases": len(cases),
        "collected_nodes": sum(len(receipt["collected"]) for receipt in receipts),
        "definition_comparison": "not verified; current sources cannot prove historical deletion",
        "reachability": "not verified (baseline)"
        if baseline
        else "verified"
        if not errors
        else "failed",
        "metrics": dict(metrics),
        "suites": rows,
        "reachability_errors": errors,
    }
    if not baseline:
        NAMES = _imports_support_it_fixture_bundle.NAMES
        if result["bundle_initializations"] != 1 or result[
            "seed_generations"
        ] != dict.fromkeys(NAMES, 1):
            errors.append("common fixtures must be initialized exactly once")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    for error in errors:
        print("FAIL reachability: " + error, file=sys.stderr)
    if baseline:
        summary.write(
            "\nBaseline reachability: not verified; fixture generation metrics: not comparable.\n"
        )
    summary.write(
        f"\nBundle initializations: {result['bundle_initializations']}; "
        f"reachability errors: {len(errors)}; total seconds: {result['seconds']:.3f}\n"
    )
    summary.write("\n```json\n" + json.dumps(result["metrics"], indent=2) + "\n```\n")
    if errors:
        summary.write("\n" + "\n".join("- " + error for error in errors) + "\n")
    return result


def unit_timing(directory, commands, wall):
    """Read completed child receipts before the temporary directory is removed."""
    errors, files, cases, groups = [], {}, [], []
    try:
        events = [
            json.loads(line)
            for line in (directory / "timing.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        starts = [event for event in events if event["event"] == "step_start"]
        running = [event for event in events if event["event"] == "step_running"]
        ends = {
            event["output"]: event for event in events if event["event"] == "step_end"
        }
        if (
            len(starts) != len(commands)
            or len(running) != len(starts)
            or len(ends) != len(starts)
            or sum(event["event"] == "step_end" for event in events) != len(ends)
        ):
            raise ValueError("incomplete process timing records")
        receipts = {}
        for receipt in directory.glob("pytest-*.json"):
            try:
                pid = int(receipt.name.split("-")[1])
                data = json.loads(receipt.read_text(encoding="utf-8"))
                if (
                    not isinstance(data, dict)
                    or not isinstance(data.get("cases"), list)
                    or not isinstance(data.get("collected"), list)
                ):
                    raise ValueError(f"invalid receipt: {receipt.name}")
                if any(not isinstance(node, str) for node in data["collected"]) or any(
                    not isinstance(case, dict) for case in data["cases"]
                ):
                    raise ValueError(f"invalid receipt: {receipt.name}")
                if len(set(data["collected"])) != len(data["collected"]) or set(
                    data["collected"]
                ) != {case.get("nodeid") for case in data["cases"]}:
                    errors.append(f"missing or unexpected pytest cases: {receipt.name}")
                receipts.setdefault(pid, []).extend(data["cases"])
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                errors.append(
                    f"missing/invalid UT timing data: {receipt.name}: {error}"
                )
        seen = set()
        for command, start, child in zip(commands, starts, running, strict=True):
            if start["command"] != command or start["output"] not in ends:
                raise ValueError("mismatched process timing records")
            end = ends[start["output"]]
            if (
                end["status"] not in ("pass", "fail", "error", "interrupted")
                or type(end["duration_seconds"]) not in (int, float)
                or not math.isfinite(end["duration_seconds"])
                or end["duration_seconds"] < 0
            ):
                raise ValueError("invalid process timing record")
            grouped = command[2:3] == ["--group"]
            paths = command[3:] if grouped else [command[1]]
            paths = [str(Path(path).resolve()) for path in paths]
            data = receipts.pop(child["pid"], [])
            if grouped:
                groups.append(
                    {
                        "paths": paths,
                        "status": end["status"],
                        "duration": end["duration_seconds"],
                    }
                )
            for path in paths:
                if path in files:
                    raise ValueError(f"duplicate file: {path}")
                files[path] = {
                    "path": path,
                    "cases": [],
                    "process": None if grouped else end["duration_seconds"],
                    "status": "PASS" if end["status"] == "pass" else "FAIL",
                }
            for case in data:
                if (
                    not isinstance(case, dict)
                    or case.get("path") not in files
                    or case["path"] not in paths
                ):
                    raise ValueError("invalid case owner")
                nodeid, phases, status = (
                    case.get("nodeid"),
                    case.get("phases"),
                    case.get("status"),
                )
                if (
                    not isinstance(nodeid, str)
                    or nodeid in seen
                    or not isinstance(phases, dict)
                    or not phases
                    or any(
                        key not in ("setup", "call", "teardown")
                        or type(value) not in (int, float)
                        or not math.isfinite(value)
                        or value < 0
                        for key, value in phases.items()
                    )
                    or status not in ("PASS", "FAIL", "SKIP", "INCOMPLETE")
                ):
                    raise ValueError(f"invalid or duplicate case: {nodeid}")
                seen.add(nodeid)
                if "teardown" not in phases or status == "INCOMPLETE":
                    errors.append(f"incomplete pytest timing: {nodeid}")
                case["total"] = sum(phases.values())
                cases.append(case)
                files[case["path"]]["cases"].append(case)
            if grouped:
                for path in paths:
                    statuses = {case["status"] for case in files[path]["cases"]}
                    if not statuses or "INCOMPLETE" in statuses:
                        files[path]["status"] = "INCOMPLETE"
                        errors.append(
                            f"missing/incomplete grouped pytest timing: {path}"
                        )
                    elif "FAIL" in statuses:
                        files[path]["status"] = "FAIL"
                    elif statuses == {"SKIP"}:
                        files[path]["status"] = "SKIP"
                    else:
                        files[path]["status"] = "PASS"
            if not grouped and not data:
                source = Path(paths[0]).read_text(encoding="utf-8")
                if (
                    "pytest.main(" in source
                    or "support.pytest_cli import run" in source
                ):
                    errors.append(f"missing pytest timing: {paths[0]}")
        # Receipts from subprocesses started by a test are not runner children.
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        errors.append(f"missing/invalid UT timing data: {error}")
    return {
        "wall": wall,
        "files": list(files.values()),
        "cases": cases,
        "errors": errors,
        "groups": groups,
    }


def display_unit_timing(result, summary):
    lines = [
        "### Framework UT Timing",
        "",
        f"UT total wall time: {result['wall']:.3f}s",
        f"UT timing: {'INCOMPLETE' if result['errors'] else 'COMPLETE'}",
    ]
    counts = Counter(case["status"] for case in result["cases"])
    lines.append(
        f"Cases: PASS {counts['PASS']}; FAIL {counts['FAIL']}; SKIP {counts['SKIP']}; INCOMPLETE {counts['INCOMPLETE']}"
    )
    lines.extend(
        [
            "",
            "| UT file | Case result / process-only result | Case sum (s) | Process (s) |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    ordered = sorted(
        result["files"],
        key=lambda row: sum(case["total"] for case in row["cases"])
        if row["cases"]
        else row["process"] or 0,
        reverse=True,
    )
    for row in ordered:
        duration = sum(case["total"] for case in row["cases"])
        case_time = f"{duration:.3f}" if row["cases"] else "—"
        process = f"{row['process']:.3f}" if row["process"] is not None else "—"
        status = row["status"] if row["cases"] else row["status"] + " (process only)"
        lines.append(
            f"| {Path(row['path']).name} | {status} | {case_time} | {process} |"
        )
    for group in result["groups"]:
        lines.append(
            f"Group process: {group['status'].upper()} ({group['duration']:.3f}s): "
            + ", ".join(Path(path).name for path in group["paths"])
        )
    cases = sorted(result["cases"], key=lambda case: case["total"], reverse=True)
    lines.extend(["", "Slowest UT Cases (top 20):"])
    lines.extend(
        f"- {case['status']} {case['nodeid']}: {case['total']:.3f}s (call: {format(case['phases']['call'], '.3f') + 's' if 'call' in case['phases'] else '—'})"
        for case in cases[:20]
    )
    lines.extend(f"UT timing ERROR: {error}" for error in result["errors"])
    compact_lines = lines.copy()
    lines.extend(
        [
            "",
            "<details><summary>All UT cases (setup / call / teardown / total seconds)</summary>",
            "",
            "| Case | Result | Setup | Call | Teardown | Total |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in cases:
        phases = [
            f"{case['phases'][key]:.3f}" if key in case["phases"] else "—"
            for key in ("setup", "call", "teardown")
        ]
        lines.append(
            f"| {case['nodeid']} | {case['status']} | {' | '.join(phases)} | {case['total']:.3f} |"
        )
    lines.extend(["", "</details>"])
    report = "\n".join(lines) + "\n"
    print(report, flush=True)
    if summary is not None:
        try:
            limit = 65536
            detail_header = lines[len(compact_lines) : len(compact_lines) + 5]
            detail_rows = lines[len(compact_lines) + 5 : -2]
            footer = "\n</details>\n"
            notice = "\nSummary size limit: {} case(s) omitted; full details are in the job log.\n"
            compact_notice = "\nSummary size limit: some summary lines omitted.\n"
            reserved = (
                len(
                    (
                        "\n".join(detail_header)
                        + footer
                        + notice.format(len(cases))
                        + compact_notice
                    ).encode("utf-8")
                )
                + 2
            )
            selected_indexes = set()
            used = reserved
            error_start = len(compact_lines) - len(result["errors"])
            priority = list(range(error_start, len(compact_lines))) + list(
                range(error_start)
            )
            for index in priority:
                size = len((compact_lines[index] + "\n").encode("utf-8"))
                if used + size <= limit:
                    selected_indexes.add(index)
                    used += size
            compact_omitted = len(selected_indexes) < len(compact_lines)
            selected = [
                line
                for index, line in enumerate(compact_lines)
                if index in selected_indexes
            ]
            selected.extend(detail_header)
            omitted = 0
            for row in detail_rows:
                size = len((row + "\n").encode("utf-8"))
                if used + size <= limit:
                    selected.append(row)
                    used += size
                else:
                    omitted += 1
            if omitted:
                selected.extend(["", notice.format(omitted).strip()])
            selected.extend(["", "</details>"])
            if compact_omitted:
                selected.append(compact_notice.strip())
            summary.write("\n".join(selected) + "\n")
        except OSError as error:
            print(f"UT timing summary write failed: {error}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", default="")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--it-only", action="store_true", help="Run IT without executing UT"
    )
    modes.add_argument(
        "--ut-only",
        action="store_true",
        help="Run all UTs without IT discovery, collection or execution",
    )
    parser.add_argument(
        "--compare-root",
        type=Path,
        help="Compare IT definitions with a trusted checkout; imports pytest suites in isolated collection children, no test bodies",
    )
    parser.add_argument("--baseline", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--suite", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--tests", type=Path, default=TESTS, help=argparse.SUPPRESS)
    parser.add_argument("--receipt", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--case-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.ut_only and (
        args.suite
        or args.compare_root
        or args.baseline_root
        or args.baseline
        or args.case_id
        or args.receipt
    ):
        parser.error("--ut-only cannot be combined with IT or comparison options")
    if args.suite:
        if args.case_id and (
            args.baseline
            or args.suite.resolve().relative_to(args.tests.resolve()).as_posix()
            not in PARALLEL_CASES
            or args.case_id
            not in PARALLEL_CASES.get(
                args.suite.resolve().relative_to(args.tests.resolve()).as_posix(), ()
            )
        ):
            raise ValueError(f"unknown repair case: {args.case_id}")
        run_child(args.suite, args.tests, args.receipt, args.baseline, args.case_id)
        return 0
    if args.compare_root:
        comparison = compare_revisions(
            args.compare_root.resolve() / "framework/scripts/tests", TESTS
        )
        report = (
            "IT definition comparison (reductions require PR review):\n"
            + json.dumps(comparison, ensure_ascii=False, indent=2)
        )
        print(report, flush=True)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(
                os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8"
            ) as summary:
                summary.write("\n```text\n" + report + "\n```\n")
        return 0
    sys.path[:0] = [str(TESTS.parent), str(TESTS)]
    unit_failed = False
    if not args.it_only:
        units, reason = _imports_validation_loop.select_checks(TESTS.parents[2])
        print(f"{reason}: {len(units)} UT suites", flush=True)
        with tempfile.TemporaryDirectory(prefix="framework-ut-") as directory:
            commands = unit_commands(units)
            environment = _imports_validation_loop.utf8_environment()
            environment["BLUEPRINT_UT_TIMING_DIR"] = directory
            started = time.monotonic()
            snapshot = source_snapshot(TESTS)
            errors = violations(TESTS)
            if errors:
                raise ValueError("Worktree test policy: " + "; ".join(errors))
            if source_snapshot(TESTS) != snapshot:
                raise ValueError(
                    "Worktree test policy: sources changed during inspection"
                )
            token = uuid.uuid4().hex
            receipt = Path(directory) / "worktree-policy.json"
            receipt.write_text(
                json.dumps(
                    {
                        "root": str(TESTS.resolve()),
                        "pid": os.getpid(),
                        "token": token,
                        "snapshot": snapshot,
                    }
                ),
                encoding="utf-8",
            )
            environment[POLICY_RECEIPT] = str(receipt)
            environment[POLICY_TOKEN] = token
            unit_status = _imports_validation_loop.run_commands(
                TESTS.parents[2], commands, environment, Path(directory), jobs=2
            )
            if source_snapshot(TESTS) != snapshot:
                raise ValueError("Worktree test policy: sources changed during UT")
            timing = unit_timing(Path(directory), commands, time.monotonic() - started)
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            try:
                with (
                    open(summary_path, "a", encoding="utf-8")
                    if summary_path
                    else nullcontext(None) as summary
                ):
                    display_unit_timing(timing, summary)
            except OSError as error:
                print(f"UT timing summary open failed: {error}", file=sys.stderr)
                display_unit_timing(timing, None)
        unit_failed = bool(unit_status or timing["errors"])
        if args.ut_only:
            return int(unit_failed)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    with (
        open(summary_path, "a", encoding="utf-8")
        if summary_path
        else nullcontext(sys.stdout)
    ) as summary:
        if args.baseline_root:
            baseline_tests = (
                Path(args.baseline_root).resolve() / "framework/scripts/tests"
            )
            if (baseline_tests.parent / "requirements.txt").read_bytes() != (
                TESTS.parent / "requirements.txt"
            ).read_bytes():
                raise ValueError(
                    "before/after measurement requires identical Python requirements"
                )
            summary.write("\n### Baseline\n\n")
            before = run_all(baseline_tests, summary, baseline=True)
        summary.write("\n### Current\n\n")
        after = run_all(TESTS, summary)
        if args.baseline_root:
            summary.write(
                f"\nObserved times: baseline {before['seconds']:.3f}s; current {after['seconds']:.3f}s.\n"
                "Validation content and suite equivalence are not established; these are not a same-condition speedup.\n"
                "Legacy profiler-derived fixture request/generation counts are not comparable.\n"
            )
    return int(
        unit_failed
        or any(
            result["reachability_errors"]
            or any(row["code"] for row in result["suites"])
            for result in ([before, after] if args.baseline_root else [after])
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

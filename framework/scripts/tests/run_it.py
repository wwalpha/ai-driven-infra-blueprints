#!/usr/bin/env python3
"""Official offline UT/IT entrypoint: isolated suites, one seed bundle, runtime receipts."""

import argparse
import ast
import json
import os
import re
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from contextlib import nullcontext, suppress
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest as _imports_pytest
import support.it_fixture_bundle as _imports_support_it_fixture_bundle
import validation.loop as _imports_validation_loop
from support.worktree_test_policy import audit as worktree_audit
from support.worktree_test_policy import ordinary_suite, violations
from task_contract_core import SELECTOR

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TESTS = Path(__file__).resolve().parent
REPAIR_SUITE = "integrations/worktree-deploy-repair.checks.py"
REPAIR_CASES = (
    REPAIR_SUITE + "::check_external_implement_round_trip[batch]",
    REPAIR_SUITE + "::check_external_implement_round_trip[steps]",
    REPAIR_SUITE + "::check_merge_recovery",
)
CHECKPOINT_SUITE = "integrations/worktree-deploy-checkpoint.checks.py"
CHECKPOINT_CASES = tuple(
    CHECKPOINT_SUITE + "::" + name
    for name in (
        "check_parallel_checkpoint_and_restart",
        "check_success_checkpoint_survives_peer_failure",
        "check_model_publication_interruption",
        "check_generation_wait_and_resume",
    )
)
PARALLEL_CASES = {REPAIR_SUITE: REPAIR_CASES, CHECKPOINT_SUITE: CHECKPOINT_CASES}


def registered_cases(tests):
    pattern = r"^\| `[^`]+` \| `([^`]+)` \| IT \| \[[^]]+\]\(([^)#]+)(?:#[^)]*)?\) \| (\w+) / (\d+)"
    rows = re.findall(pattern, (tests / "CASES.md").read_text(encoding="utf-8"), re.M)
    cases = {(path, name): (mode, int(count)) for name, path, mode, count in rows}
    if len(cases) != len(rows):
        raise ValueError("duplicate IT case ledger entries")
    return cases


def inventory(tests):
    """The existing ledger is the only case list; reject stale/unregistered entries."""
    cases = registered_cases(tests)
    errors = violations(tests)
    if not cases:
        errors.append("empty IT case ledger")
    suites = sorted((tests / "integrations").rglob("*.py"))
    for path in suites:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(tests).as_posix()
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        aliases = {
            n.targets[0].id
            for n in tree.body
            if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Name)
        }
        owned = {
            name: value for (file, name), value in cases.items() if file == relative
        }
        if path.name.endswith(".checks.py") and not owned:
            errors.append(f"unregistered IT suite: {relative}")
        for name in functions:
            if name.startswith("check_") and name not in owned:
                errors.append(f"unregistered IT case: {relative}::{name}")
        imports = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "support.it_case_receipt"
            for alias in node.names
            if alias.asname is None
        }
        for name, (mode, count) in owned.items():
            if mode not in ("pytest", "direct", "direct_group", "module") or count < 1:
                errors.append(f"invalid IT registration: {relative}::{name}")
            elif mode == "module":
                expected = ast.parse("module_complete(__file__)").body[0]
                if (
                    name != "__module__"
                    or count != 1
                    or "module_complete" not in imports
                    or ast.dump(tree.body[-1]) != ast.dump(expected)
                ):
                    errors.append(
                        f"missing terminal module completion: {relative}::{name}"
                    )
            elif name not in functions and not (mode == "pytest" and name in aliases):
                errors.append(f"missing IT case: {relative}::{name}")
            elif mode in ("direct", "direct_group"):
                decorators = functions[name].decorator_list
                if (
                    count != 1
                    or "it_case" not in imports
                    or not decorators
                    or ast.unparse(decorators[0]) != "it_case"
                ):
                    errors.append(
                        f"missing outer completion decorator: {relative}::{name}"
                    )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.endswith(".checks")
            ):
                errors.append(f"IT module dependency: {relative}: {node.value}")
    present = {p.relative_to(tests).as_posix() for p in suites}
    errors += [f"missing IT file: {file}" for file, _ in cases if file not in present]
    return cases, errors


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


def reachability(cases, receipts, registered=None):
    registered = cases if registered is None else registered
    completed, collected, passed = Counter(), Counter(), Counter()
    errors = [] if cases else ["empty IT case ledger"]
    owners = set()
    for receipt in receipts:
        invalid = receipt_errors(receipt)
        if invalid:
            errors += invalid
            continue
        owner = receipt["suite"]
        if owner in owners:
            errors.append(f"duplicate runtime receipt suite: {owner}")
        owners.add(owner)
        completed.update(receipt["completed"])
        for key in receipt["collected"]:
            collected[key.split("[", 1)[0]] += 1
        for key in receipt["passed"]:
            passed[key.split("[", 1)[0]] += 1
    for path in sorted(
        {path for path, _ in cases if path.endswith(".checks.py")} - owners
    ):
        errors.append(f"missing runtime receipt: {path}")
    for key in collected:
        if cases.get(tuple(key.split("::", 1)), (None,))[0] != "pytest":
            errors.append(f"unregistered collected IT case: {key}")
    for key in completed:
        if registered.get(tuple(key.split("::", 1)), (None,))[0] not in (
            "direct",
            "direct_group",
            "module",
        ):
            errors.append(f"unregistered completed IT case: {key}")
    for (path, name), (mode, count) in cases.items():
        key = path + "::" + name
        if mode == "pytest":
            if collected[key] != count or passed[key] != count:
                errors.append(
                    f"{key}: expected {count}, collected {collected[key]}, passed body {passed[key]}"
                )
        elif mode not in ("direct", "direct_group", "module") or not completed[key]:
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
    ledger = {
        name: value
        for (path, name), value in registered_cases(tests).items()
        if path == suite_key
    }
    expected = (
        {
            "check_external_implement_round_trip": ("pytest", 2),
            "check_merge_recovery": ("pytest", 1),
        }
        if suite_key == REPAIR_SUITE
        else {case.split("::", 1)[1]: ("pytest", 1) for case in cases}
    )
    if ledger != expected:
        raise ValueError(f"repair ledger mismatch: {ledger}")
    logs = Path(tempfile.mkdtemp(prefix="framework-repair-it-logs-"))
    children = []
    success = False
    try:
        deadline = time.monotonic() + 1800
        for index, case in enumerate(cases):
            if suite_key == CHECKPOINT_SUITE and index >= 2:
                previous_case, previous, _, _ = children[index - 2]
                try:
                    code = previous.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(f"{previous_case}: process timed out") from error
                if code:
                    raise RuntimeError(f"{previous_case}: process exited {code}")
            receipt = output / f"repair-{index}.json"
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
        if success:
            shutil.rmtree(logs)
        else:
            print(f"Repair case logs retained: {logs}", file=sys.stderr, flush=True)


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
    cases, errors = ({}, []) if baseline else inventory(tests)
    registered = cases
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
                    errors += reachability(cases, receipts, registered)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", default="")
    parser.add_argument("--baseline", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--suite", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--tests", type=Path, default=TESTS, help=argparse.SUPPRESS)
    parser.add_argument("--receipt", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--case-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
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
    sys.path[:0] = [str(TESTS.parent), str(TESTS)]
    _imports_validation_loop.authorize_full_regression(TESTS.parents[2])
    units, reason = _imports_validation_loop.select_checks(TESTS.parents[2])
    print(f"{reason}: {len(units)} UT suites", flush=True)
    with tempfile.TemporaryDirectory(prefix="framework-ut-") as directory:
        unit_status = _imports_validation_loop.run_commands(
            TESTS.parents[2],
            [[sys.executable, str(path)] for path in units],
            _imports_validation_loop.utf8_environment(),
            Path(directory),
            jobs=2,
        )
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
        bool(unit_status)
        or any(
            result["reachability_errors"]
            or any(row["code"] for row in result["suites"])
            for result in ([before, after] if args.baseline_root else [after])
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Official offline IT entrypoint: isolated suites, one seed bundle, runtime receipts."""
import argparse
import ast
from collections import Counter
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import time

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

TESTS = Path(__file__).resolve().parent


def registered_cases(tests):
    pattern = r'^\| `[^`]+` \| `([^`]+)` \| IT \| \[[^]]+\]\(([^)#]+)(?:#[^)]*)?\) \| (\w+) / (\d+)'
    rows = re.findall(pattern, (tests / 'CASES.md').read_text(encoding='utf-8'), re.M)
    cases = {(path, name): (mode, int(count)) for name, path, mode, count in rows}
    if len(cases) != len(rows):
        raise ValueError('duplicate IT case ledger entries')
    return cases


def inventory(tests):
    """The existing ledger is the only case list; reject stale/unregistered entries."""
    cases = registered_cases(tests)
    errors = []
    if not cases:
        errors.append('empty IT case ledger')
    for path in sorted((tests / 'integrations').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        relative = path.relative_to(tests).as_posix()
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        aliases = {n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)
                   and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Name)}
        for name in names:
            if name.startswith('check_') and (relative, name) not in cases:
                errors.append(f'unregistered IT case: {relative}::{name}')
        for file, name in cases:
            if file == relative and name not in names | aliases:
                errors.append(f'missing IT case: {relative}::{name}')
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.checks'):
                errors.append(f'IT module dependency: {relative}: {node.value}')
    present = {p.relative_to(tests).as_posix() for p in (tests / 'integrations').rglob('*.py')}
    errors += [f'missing IT file: {file}' for file, _ in cases if file not in present]
    return cases, errors


def check_assertion_guards(tests):
    """Prove each entry rejects -O before definitions/calls, without launching every suite."""
    for path in sorted(tests.rglob('*.checks.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.If) and ast.unparse(node.test) == 'not __debug__':
                expected = ast.parse("if not __debug__:\n raise SystemExit('Focused checks require assertions; run without -O')").body[0]
                if ast.dump(node) != ast.dump(expected):
                    raise ValueError(f'invalid assertion guard: {path}')
                code = compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec', optimize=1)
                try:
                    exec(code, {})
                except SystemExit as error:
                    if 'Focused checks require assertions' not in str(error):
                        raise ValueError(f'assertion guard did not reject optimization: {path}') from error
                else:
                    raise ValueError(f'assertion guard did not exit: {path}')
                break
            allowed = (isinstance(node, (ast.Import, ast.ImportFrom)) or
                       isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) or
                       isinstance(node, ast.Assign) and all(ast.unparse(t).startswith('sys.path[') for t in node.targets))
            if not allowed:
                raise ValueError(f'code before assertion guard: {path}:{node.lineno}')
        else:
            raise ValueError(f'missing assertion guard: {path}')


class PytestReceipt:
    def __init__(self, tests):
        self.tests = tests
        self.collected = []
        self.passed = []

    def pytest_configure(self, config):
        self.rootpath = config.rootpath

    def key(self, nodeid):
        path, name = nodeid.split('::', 1)
        return (self.rootpath / path).resolve().relative_to(self.tests).as_posix() + '::' + name

    def pytest_collection_finish(self, session):
        self.collected.extend(self.key(item.nodeid) for item in session.items)

    def pytest_runtest_logreport(self, report):
        if report.when == 'call' and report.passed:
            self.passed.append(self.key(report.nodeid))


def run_child(suite, tests, receipt, baseline=False):
    """Execute existing entrypoints, including pytest_cli.run and top-level scripts."""
    sys.path[:0] = [str(tests.parent), str(tests)]
    import pytest
    plugin = PytestReceipt(tests)
    pytest_main = pytest.main
    def measured_pytest(args=None, plugins=None):
        return pytest_main(args, plugins=[*(plugins or []), plugin])
    pytest.main = measured_pytest
    calls, metrics = Counter(), Counter()
    prefix = str(tests / 'integrations') + os.sep
    def profile(frame, event, arg):
        if event == 'call' and frame.f_code.co_filename.startswith(prefix):
            file = Path(frame.f_code.co_filename).relative_to(tests).as_posix()
            calls[file + '::' + frame.f_code.co_name] += 1
        if event == 'call' and frame.f_code.co_filename.startswith(str(tests / 'support')):
            if frame.f_code.co_name in ('input_templates', 'typed_services', 'generated_policy'):
                metrics['fixture_requests:' + frame.f_code.co_name] += 1
                if baseline:
                    metrics['generated:' + frame.f_code.co_name] += 1
    def audit(event, args):
        if event in ('shutil.copytree', 'shutil.copyfile', 'subprocess.Popen'):
            metrics[event] += 1
        elif event == 'blueprint.it_fixture.generated':
            metrics['generated:' + args[0]] += 1
    sys.addaudithook(audit)
    sys.setprofile(profile)
    sys.argv = [str(suite)]
    try:
        runpy.run_path(str(suite), run_name='__main__')
    finally:
        sys.setprofile(None)
        receipt.write_text(json.dumps({'calls': calls, 'collected': plugin.collected,
                                       'passed': plugin.passed, 'metrics': metrics}), encoding='utf-8')


def reachability(cases, receipts):
    calls, collected, passed = Counter(), Counter(), Counter()
    for receipt in receipts:
        calls.update(receipt.get('calls', {}))
        for key in receipt.get('collected', []):
            collected[key.split('[', 1)[0]] += 1
        for key in receipt.get('passed', []):
            passed[key.split('[', 1)[0]] += 1
    errors = []
    for key in collected:
        if tuple(key.split('::', 1)) not in cases:
            errors.append(f'unregistered collected IT case: {key}')
    for (path, name), (mode, count) in cases.items():
        key = path + '::' + name
        if mode == 'pytest':
            if collected[key] != count or passed[key] != count:
                errors.append(f'{key}: expected {count}, collected {collected[key]}, passed body {passed[key]}')
        elif not calls[key]:
            errors.append(f'{key}: verification body not reached')
    return errors


def execute_suites(tests, output, summary, baseline=False):
    suites = sorted((tests / 'integrations').rglob('*.checks.py'))
    if not suites:
        raise ValueError('No integration suites discovered')
    rows, receipts = [], []
    summary.write('| IT suite | Result | Seconds |\n| --- | --- | ---: |\n')
    for suite in suites:
        print(f'::group::{suite.name}', flush=True)
        started = time.monotonic()
        receipt = output / (suite.name + '.json')
        try:
            code = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()),
                                   *(['--baseline'] if baseline else []),
                                   '--suite', str(suite), '--tests', str(tests), '--receipt', str(receipt)],
                                  cwd=tests.parents[2]).returncode
        except OSError as error:
            print(error, file=sys.stderr, flush=True)
            code = 1
        elapsed = time.monotonic() - started
        try:
            receipts.append(json.loads(receipt.read_text(encoding='utf-8')))
        except (OSError, ValueError) as error:
            print(f'missing/invalid runtime receipt: {suite.name}: {error}', file=sys.stderr)
            code = 1
        status = 'PASS' if code == 0 else 'FAIL'
        rows.append({'suite': suite.name, 'code': code, 'seconds': elapsed})
        print(f'{status}: {suite.name} ({elapsed:.3f}s, exit={code})\n::endgroup::', flush=True)
        summary.write(f'| {suite.name} | {status} | {elapsed:.3f} |\n')
        summary.flush()
    failed = sum(row['code'] != 0 for row in rows)
    summary.write(f'\nSuites: {len(rows)}; PASS: {len(rows) - failed}; FAIL: {failed}\n')
    return rows, receipts


def run_all(tests, summary, baseline=False):
    # Only the official runner owns the shared bundle's lifetime and cleanup.
    if not baseline:
        from support.it_fixture_bundle import bundle, ENV
    else:
        ENV = 'BLUEPRINT_IT_FIXTURES'
    cases, errors = inventory(tests)
    if not baseline:
        check_assertion_guards(tests)
    started = time.monotonic()
    metrics = Counter()
    measuring = True
    def audit(event, args):
        if measuring:
            if event in ('shutil.copytree', 'shutil.copyfile', 'subprocess.Popen', 'blueprint.it_bundle.initialized'):
                metrics[event] += 1
            elif event == 'blueprint.it_fixture.generated':
                metrics['generated:' + args[0]] += 1
    sys.addaudithook(audit)
    previous = os.environ.pop(ENV, None)
    previous_cache = os.environ.get('BLUEPRINT_VALIDATION_CACHE_DIR')
    rows, receipts = [], []
    try:
        with tempfile.TemporaryDirectory(prefix='framework-it-receipts-') as directory:
            os.environ['BLUEPRINT_VALIDATION_CACHE_DIR'] = str(Path(directory) / 'cache')
            with (nullcontext(None) if baseline else bundle()) as fixture:
                if fixture is not None:
                    os.environ[ENV] = str(fixture)
                rows, receipts = execute_suites(tests, Path(directory), summary, baseline)
                errors += reachability(cases, receipts)
    except RuntimeError as error:
        errors.append(str(error))
    finally:
        measuring = False
        os.environ.pop(ENV, None)
        if previous is not None:
            os.environ[ENV] = previous
        if previous_cache is None:
            os.environ.pop('BLUEPRINT_VALIDATION_CACHE_DIR', None)
        else:
            os.environ['BLUEPRINT_VALIDATION_CACHE_DIR'] = previous_cache
    for receipt in receipts:
        metrics.update(receipt.get('metrics', {}))
    result = {'seconds': time.monotonic() - started, 'bundle_initializations': metrics['blueprint.it_bundle.initialized'],
              'seed_generations': {key.removeprefix('generated:'): count for key, count in metrics.items() if key.startswith('generated:')},
              'metrics': dict(metrics), 'suites': rows, 'reachability_errors': errors}
    if not baseline:
        from support.it_fixture_bundle import NAMES
        if result['bundle_initializations'] != 1 or result['seed_generations'] != dict.fromkeys(NAMES, 1):
            errors.append('common fixtures must be initialized exactly once')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    for error in errors:
        print('FAIL reachability: ' + error, file=sys.stderr)
    summary.write(f'\nBundle initializations: {result["bundle_initializations"]}; '
                  f'reachability errors: {len(errors)}; total seconds: {result["seconds"]:.3f}\n')
    summary.write('\n```json\n' + json.dumps(result['metrics'], indent=2) + '\n```\n')
    if errors:
        summary.write('\n' + '\n'.join('- ' + error for error in errors) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', default='')
    parser.add_argument('--baseline', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--suite', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--tests', type=Path, default=TESTS, help=argparse.SUPPRESS)
    parser.add_argument('--receipt', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.suite:
        run_child(args.suite, args.tests, args.receipt, args.baseline)
        return 0
    sys.path[:0] = [str(TESTS.parent), str(TESTS)]
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    with (open(summary_path, 'a', encoding='utf-8') if summary_path else nullcontext(sys.stdout)) as summary:
        if args.baseline_root:
            baseline_tests = Path(args.baseline_root).resolve() / 'framework/scripts/tests'
            if (baseline_tests.parent / 'requirements.txt').read_bytes() != (TESTS.parent / 'requirements.txt').read_bytes():
                raise ValueError('before/after measurement requires identical Python requirements')
            summary.write('\n### Baseline\n\n')
            before = run_all(baseline_tests, summary, baseline=True)
        summary.write('\n### Current\n\n')
        after = run_all(TESTS, summary)
        if args.baseline_root:
            summary.write(f'\nSame-run instrumented time: {before["seconds"]:.3f}s → {after["seconds"]:.3f}s\n')
    return int(bool(after['reachability_errors']) or any(row['code'] for row in after['suites']))


if __name__ == '__main__':
    raise SystemExit(main())

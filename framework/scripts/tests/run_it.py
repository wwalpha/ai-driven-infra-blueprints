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
    suites = sorted((tests / 'integrations').rglob('*.py'))
    for path in suites:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        relative = path.relative_to(tests).as_posix()
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        aliases = {n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)
                   and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Name)}
        owned = {name: value for (file, name), value in cases.items() if file == relative}
        if path.name.endswith('.checks.py') and not owned:
            errors.append(f'unregistered IT suite: {relative}')
        for name in functions:
            if name.startswith('check_') and name not in owned:
                errors.append(f'unregistered IT case: {relative}::{name}')
        imports = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                   and node.module == 'support.it_case_receipt'
                   for alias in node.names if alias.asname is None}
        for name, (mode, count) in owned.items():
            if mode not in ('pytest', 'direct', 'direct_group', 'module') or count < 1:
                errors.append(f'invalid IT registration: {relative}::{name}')
            elif mode == 'module':
                expected = ast.parse('module_complete(__file__)').body[0]
                if (name != '__module__' or count != 1 or 'module_complete' not in imports
                        or ast.dump(tree.body[-1]) != ast.dump(expected)):
                    errors.append(f'missing terminal module completion: {relative}::{name}')
            elif name not in functions and not (mode == 'pytest' and name in aliases):
                errors.append(f'missing IT case: {relative}::{name}')
            elif mode in ('direct', 'direct_group'):
                decorators = functions[name].decorator_list
                if (count != 1 or 'it_case' not in imports or not decorators
                        or ast.unparse(decorators[0]) != 'it_case'):
                    errors.append(f'missing outer completion decorator: {relative}::{name}')
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.checks'):
                errors.append(f'IT module dependency: {relative}: {node.value}')
    present = {p.relative_to(tests).as_posix() for p in suites}
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


def run_child(suite, tests, receipt, baseline=False, cases=()):
    """Execute existing entrypoints, including pytest_cli.run and top-level scripts."""
    sys.path[:0] = [str(tests.parent), str(tests)]
    import pytest
    plugin = PytestReceipt(tests)
    pytest_main = pytest.main
    def measured_pytest(args=None, plugins=None):
        return pytest_main(args, plugins=[*(plugins or []), plugin])
    pytest.main = measured_pytest
    completed, metrics = Counter(), Counter()
    suite_key = suite.resolve().relative_to(tests.resolve()).as_posix()
    def audit(event, args):
        if event in ('shutil.copytree', 'shutil.copyfile', 'subprocess.Popen'):
            metrics[event] += 1
            if event == 'subprocess.Popen' and Path(args[0]).stem == 'git':
                metrics['subprocess.git'] += 1
        elif event == 'blueprint.it_fixture.generated':
            metrics['generated:' + args[0]] += 1
        elif event == 'blueprint.it_case.completed':
            source = Path(args[0]).resolve().relative_to(tests.resolve()).as_posix()
            completed[source + '::' + args[1]] += 1
    sys.addaudithook(audit)
    sys.argv = [str(suite)]
    try:
        if cases:
            raise SystemExit(pytest.main([str(suite) + '::' + name for name in cases]))
        runpy.run_path(str(suite), run_name='__main__')
    finally:
        receipt.write_text(json.dumps({'version': 1, 'suite': suite_key, 'completed': completed, 'collected': plugin.collected,
                                       'passed': plugin.passed, 'metrics': metrics}), encoding='utf-8')


def receipt_errors(receipt, suite=None):
    if not isinstance(receipt, dict) or receipt.get('version') != 1:
        return ['missing/invalid runtime receipt schema']
    owner = receipt.get('suite')
    if not isinstance(owner, str) or not owner or (suite is not None and owner != suite):
        return ['invalid runtime receipt suite']
    for field in ('completed', 'metrics'):
        values = receipt.get(field)
        if not isinstance(values, dict) or any(not isinstance(k, str) or type(v) is not int or v < 1
                                               for k, v in values.items()):
            return [f'invalid runtime receipt {field}']
    for field in ('collected', 'passed'):
        values = receipt.get(field)
        if not isinstance(values, list) or any(not isinstance(k, str) or not k.startswith(owner + '::') for k in values):
            return [f'invalid runtime receipt {field}']
        if len(set(values)) != len(values):
            return [f'duplicate runtime receipt {field}']
    if any(not k.startswith('integrations/') or '::' not in k for k in receipt['completed']):
        return ['invalid runtime receipt completed owner']
    if not set(receipt['passed']) <= set(receipt['collected']):
        return ['passed runtime case was not collected']
    return []


def reachability(cases, receipts):
    completed, collected, passed = Counter(), Counter(), Counter()
    errors = [] if cases else ['empty IT case ledger']
    owners = set()
    for receipt in receipts:
        invalid = receipt_errors(receipt)
        if invalid:
            errors += invalid
            continue
        owner = receipt['suite']
        if owner in owners:
            errors.append(f'duplicate runtime receipt suite: {owner}')
        owners.add(owner)
        completed.update(receipt['completed'])
        for key in receipt['collected']:
            collected[key.split('[', 1)[0]] += 1
        for key in receipt['passed']:
            passed[key.split('[', 1)[0]] += 1
    for path in sorted({path for path, _ in cases if path.endswith('.checks.py')} - owners):
        errors.append(f'missing runtime receipt: {path}')
    for key in collected:
        if cases.get(tuple(key.split('::', 1)), (None,))[0] != 'pytest':
            errors.append(f'unregistered collected IT case: {key}')
    for key in completed:
        if cases.get(tuple(key.split('::', 1)), (None,))[0] not in ('direct', 'direct_group', 'module'):
            errors.append(f'unregistered completed IT case: {key}')
    for (path, name), (mode, count) in cases.items():
        key = path + '::' + name
        if mode == 'pytest':
            if collected[key] != count or passed[key] != count:
                errors.append(f'{key}: expected {count}, collected {collected[key]}, passed body {passed[key]}')
        elif mode not in ('direct', 'direct_group', 'module') or not completed[key]:
            errors.append(f'{key}: verification did not complete')
    return errors


def execute_suites(tests, output, summary, baseline=False, selected=None):
    suites = sorted((tests / 'integrations').rglob('*.checks.py'))
    if selected is not None:
        suites = [suite for suite in suites if any(path == suite.relative_to(tests).as_posix() for path, _ in selected)]
    if not suites and selected is None:
        raise ValueError('No integration suites discovered')
    rows, receipts = [], []
    summary.write('| IT suite | Result | Seconds |\n| --- | --- | ---: |\n')
    for suite in suites:
        print(f'::group::{suite.name}', flush=True)
        started = time.monotonic()
        receipt = output / (suite.name + '.json')
        owned = {name: mode for (path, name), (mode, _) in (selected or {}).items()
                 if path == suite.relative_to(tests).as_posix()}
        # Mixed/direct suites retain their authored entrypoint. Selected pytest
        # cases use the same pytest configuration and runtime receipt plugin.
        nodes = [argument for name in sorted(owned) for argument in ('--case', name)] if owned and all(mode == 'pytest' for mode in owned.values()) else []
        try:
            code = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()),
                                   *(['--baseline'] if baseline else []),
                                   *nodes, '--suite', str(suite), '--tests', str(tests), '--receipt', str(receipt)],
                                  cwd=tests.parents[2]).returncode
        except OSError as error:
            print(error, file=sys.stderr, flush=True)
            code = 1
        elapsed = time.monotonic() - started
        try:
            data = json.loads(receipt.read_text(encoding='utf-8'))
            invalid = receipt_errors(data, suite.relative_to(tests).as_posix())
            if invalid:
                raise ValueError('; '.join(invalid))
            receipts.append(data)
        except (OSError, ValueError) as error:
            print(f'missing/invalid runtime receipt: {suite.name}: {error}', file=sys.stderr)
            code = 1
        status = 'PASS' if code == 0 else 'FAIL'
        rows.append({'suite': suite.name, 'code': code, 'seconds': elapsed,
                     'metrics': data.get('metrics', {}) if code == 0 else {}})
        print(f'{status}: {suite.name} ({elapsed:.3f}s, exit={code})\n::endgroup::', flush=True)
        summary.write(f'| {suite.name} | {status} | {elapsed:.3f} |\n')
        summary.flush()
    failed = sum(row['code'] != 0 for row in rows)
    summary.write(f'\nSuites: {len(rows)}; PASS: {len(rows) - failed}; FAIL: {failed}\n')
    return rows, receipts


def run_all(tests, summary, baseline=False, selected=None):
    # Only the official runner owns the shared bundle's lifetime and cleanup.
    if not baseline:
        from support.it_fixture_bundle import bundle, ENV
    else:
        ENV = 'BLUEPRINT_IT_FIXTURES'
    cases, errors = ({}, []) if baseline else inventory(tests)
    if selected is not None:
        cases = selected
        summary.write(f'\nSelected IT cases: {len(cases)}; unselected cases were not run.\n')
        for path, name in cases:
            summary.write(f'- {path}::{name}\n')
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
            with (nullcontext(None) if baseline or selected is not None else bundle()) as fixture:
                if fixture is not None:
                    os.environ[ENV] = str(fixture)
                rows, receipts = execute_suites(tests, Path(directory), summary, baseline, selected)
                if not baseline and cases:
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
    result = {'seconds': time.monotonic() - started, 'bundle_initializations': None if baseline else metrics['blueprint.it_bundle.initialized'],
              'seed_generations': None if baseline else {key.removeprefix('generated:'): count for key, count in metrics.items() if key.startswith('generated:')},
              'selection': 'full' if selected is None else 'affected',
              'selected_cases': len(cases),
              'reachability': 'not verified (baseline)' if baseline else 'not required (no affected IT)' if selected == {} else 'verified' if not errors else 'failed',
              'metrics': dict(metrics), 'suites': rows, 'reachability_errors': errors}
    if not baseline and selected is None:
        from support.it_fixture_bundle import NAMES
        if result['bundle_initializations'] != 1 or result['seed_generations'] != dict.fromkeys(NAMES, 1):
            errors.append('common fixtures must be initialized exactly once')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    for error in errors:
        print('FAIL reachability: ' + error, file=sys.stderr)
    if baseline:
        summary.write('\nBaseline reachability: not verified; fixture generation metrics: not comparable.\n')
    summary.write(f'\nBundle initializations: {result["bundle_initializations"]}; '
                  f'reachability errors: {len(errors)}; total seconds: {result["seconds"]:.3f}\n')
    summary.write('\n```json\n' + json.dumps(result['metrics'], indent=2) + '\n```\n')
    if errors:
        summary.write('\n' + '\n'.join('- ' + error for error in errors) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', default='')
    parser.add_argument('--affected', metavar='BASE', help='Select dependencies of BASE..HEAD; default is explicit full IT')
    parser.add_argument('--baseline', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--suite', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--tests', type=Path, default=TESTS, help=argparse.SUPPRESS)
    parser.add_argument('--receipt', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--case', action='append', default=[], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.suite:
        run_child(args.suite, args.tests, args.receipt, args.baseline, args.case)
        return 0
    sys.path[:0] = [str(TESTS.parent), str(TESTS)]
    selected = None
    unit_status = 0
    if args.affected:
        if args.baseline_root:
            parser.error('--affected cannot narrow an explicit baseline/full measurement')
        from validation.loop import select_checks, run_commands, utf8_environment
        root = TESTS.parents[2]
        paths = subprocess.run(['git', 'diff', '--no-renames', '--name-only', '-z', args.affected, 'HEAD', '--'],
                               cwd=root, capture_output=True, text=True, check=True).stdout
        cases, errors = inventory(TESTS)
        if errors:
            raise ValueError('; '.join(errors))
        selected, reason = select_checks(root, set(paths.split('\0')) - {''}, True, integration_cases=cases)
        print(reason, flush=True)
        units, unit_reason = select_checks(root, set(paths.split('\0')) - {''}, True)
        print(f'{unit_reason}: {len(units)} UT suites', flush=True)
        if units:
            with tempfile.TemporaryDirectory(prefix='framework-affected-ut-') as directory:
                unit_status = run_commands(root, [[sys.executable, str(path)] for path in units],
                                           utf8_environment(), Path(directory), jobs=2)
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    with (open(summary_path, 'a', encoding='utf-8') if summary_path else nullcontext(sys.stdout)) as summary:
        if args.baseline_root:
            baseline_tests = Path(args.baseline_root).resolve() / 'framework/scripts/tests'
            if (baseline_tests.parent / 'requirements.txt').read_bytes() != (TESTS.parent / 'requirements.txt').read_bytes():
                raise ValueError('before/after measurement requires identical Python requirements')
            summary.write('\n### Baseline\n\n')
            before = run_all(baseline_tests, summary, baseline=True)
        summary.write('\n### Current\n\n')
        after = run_all(TESTS, summary, selected=selected)
        if args.baseline_root:
            summary.write(f'\nObserved times: baseline {before["seconds"]:.3f}s; current {after["seconds"]:.3f}s.\n'
                          'Validation content and suite equivalence are not established; these are not a same-condition speedup.\n'
                          'Legacy profiler-derived fixture request/generation counts are not comparable.\n')
    return int(bool(unit_status) or any(result['reachability_errors'] or any(row['code'] for row in result['suites'])
                   for result in ([before, after] if args.baseline_root else [after])))


if __name__ == '__main__':
    raise SystemExit(main())

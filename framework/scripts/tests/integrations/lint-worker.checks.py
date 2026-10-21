"""Real offline lint equivalence and backend input guards on synthetic files only."""
import json
from pathlib import Path
import subprocess
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest
from deployment import lint_worker
from script_loader import module

M = module('cloudformation-deploy.py', 'lint_worker_backend')


def arguments(template, *extra):
    return ['cfn-lint', '--regions', 'us-east-1', '--template', str(template), '--format', 'json', *extra]


def baseline(args):
    return subprocess.run(args, capture_output=True, text=True)


def same(worker, args):
    old, new = baseline(args), worker.run(args)
    assert (new.returncode, new.stdout, new.stderr) == (old.returncode, old.stdout, old.stderr), (args, vars(old), vars(new))
    return new


def check_configuration_isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('AWS_EC2_METADATA_DISABLED', 'true')
    template = tmp_path / 'app.json'
    good = {'Resources': {'Bucket': {'Type': 'AWS::S3::Bucket', 'Properties': {}}}}
    rule = tmp_path / 'custom.txt'
    rule.write_text('AWS::S3::Bucket BucketName EQUALS expected WARN "fixture name"\n', encoding='utf-8')
    registry = tmp_path / 'registry'
    registry.mkdir()
    schema = registry / 'schema.json'
    custom = {'typeName': 'AWS::S3::Bucket', 'description': 'fixture',
              'properties': {'Name': {'type': 'string'}}, 'required': ['Name'],
              'primaryIdentifier': ['/properties/Name'], 'additionalProperties': False}
    schema.write_text(json.dumps(custom), encoding='utf-8')
    worker = lint_worker.Worker()
    try:
        # Revisit default after both custom rules and schema overrides, including failures.
        for data, extra in (
                (good, []),
                ({'Resources': {'Bucket': {'Type': 'AWS::S3::Bucket', 'Properties': {'Unknown': True}}}}, []),
                (good, []),
                (good, ['--custom-rules', str(rule)]),
                ({'Resources': {'Item': {'Type': custom['typeName'], 'Properties': {'Name': 'first'}}}}, ['--registry-schemas', str(registry)]),
                ({'Resources': {'Item': {'Type': custom['typeName'], 'Properties': {}}}}, ['--registry-schemas', str(registry)]),
                ({'Resources': {'Item': {'Type': custom['typeName'], 'Properties': {'Name': 'first'}}}}, []),
                (good, [])):
            template.write_text(json.dumps(data), encoding='utf-8')
            same(worker, arguments(template, *extra))
        # Reload changed configuration content at the same path, not just a new filename.
        template.write_text(json.dumps({'Resources': {'Item': {'Type': custom['typeName'], 'Properties': {'Name': 'first'}}}}), encoding='utf-8')
        custom['properties']['Name']['enum'] = ['second']
        schema.write_text(json.dumps(custom), encoding='utf-8')
        assert same(worker, arguments(template, '--registry-schemas', str(registry))).returncode
    finally:
        worker.close()
    assert worker.process.returncode == 0


def check_custom_rule_state_and_child_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template = tmp_path / 'app.json'
    template.write_text('{"Resources":{"Bucket":{"Type":"AWS::S3::Bucket"}}}', encoding='utf-8')
    rules = tmp_path / 'rules'
    rules.mkdir()
    rule = rules / 'Stateful.py'
    rule.write_text("""from cfnlint.rules import CloudFormationLintRule, RuleMatch
calls = 0
class Stateful(CloudFormationLintRule):
    id = 'E9999'
    shortdesc = 'State isolation'
    description = 'Synthetic stateful rule'
    tags = ['fixture']
    def match(self, cfn):
        global calls
        calls += 1
        return [RuleMatch(['Resources'], 'invocation ' + str(calls))]
""", encoding='utf-8')
    config = tmp_path / '.cfnlintrc'
    worker = lint_worker.Worker()
    try:
        for enabled in (True, False, True):
            config.write_text(json.dumps({'append_rules': [str(rules)]} if enabled else {}), encoding='utf-8')
            result = same(worker, arguments(template))
            assert bool(result.returncode) == enabled
            if enabled:
                assert 'invocation 1' in result.stdout
    finally:
        worker.close()
    # A child that dies without sending a response must fail closed and leave no worker.
    rule.write_text('import os; os._exit(7)\n', encoding='utf-8')
    config.write_text(json.dumps({'append_rules': [str(rules)]}), encoding='utf-8')
    worker = lint_worker.Worker()
    try:
        with pytest.raises(ValueError, match='communication failed'):
            worker.run(arguments(template))
    finally:
        worker.close()
    assert worker.process.poll() is not None


def check_backend_guards_and_diagnostics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template = tmp_path / 'infra/cloudformation/templates/app.json'
    parameters = tmp_path / 'infra/cloudformation/parameters/dev/fixture/app.json'
    for path in (template, parameters):
        path.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps({'Resources': {'Bucket': {'Type': 'AWS::S3::Bucket', 'Properties': {}}}})
    template.write_text(good, encoding='utf-8')
    parameters.write_text('[]', encoding='utf-8')
    units = [dict(name=name, template='app.json', parameters='app.json') for name in ('first', 'second')]
    def operation(use_worker, mutate=None, mismatch=False):
        backend = M.AwsBackend(tmp_path, 'dev', 'fixture', {'awsRegion': 'us-east-1'})
        backend.aws = lambda *a, **kw: pytest.fail('AWS forbidden')
        if mismatch:
            backend.expected_digests = {'first': 'wrong'}
        failures = []
        with lint_worker.scope(backend, units if use_worker else []):
            real_lint = getattr(backend, 'lint', subprocess.run)
            def lint(*args, **kwargs):
                result = real_lint(*args, **kwargs)
                if mutate:
                    mutate.write_text(mutate.read_text(encoding='utf-8') + '\n', encoding='utf-8')
                return result
            backend.lint = lint
            for unit in units:
                try:
                    backend.validate(unit)
                except M.Blocked as error:
                    failures.append(str(error))
        return backend.validated_digests, backend.validation_failures, backend.templates, failures
    assert operation(False) == operation(True)
    assert operation(False, mismatch=True) == operation(True, mismatch=True)
    template.write_text(good.replace('"Properties": {}', '"Properties": {"Unknown": true}'), encoding='utf-8')
    assert operation(False) == operation(True)
    for changed in (template, parameters):
        results = []
        for enabled in (False, True):
            template.write_text(good, encoding='utf-8')
            parameters.write_text('[]', encoding='utf-8')
            results.append(operation(enabled, mutate=changed))
        assert results[0] == results[1]
        assert all('changed during validation' in error for error in results[0][-1])


def check_dead_worker_and_exception_cleanup(tmp_path):
    backend = type('Backend', (), {})()
    template = tmp_path / 'good.json'
    template.write_text('{"Resources":{"Bucket":{"Type":"AWS::S3::Bucket"}}}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='injected'), lint_worker.scope(backend, [1, 2]):
        worker = backend.lint.__self__
        assert worker.run(arguments(template)).returncode == 0
        process = worker.process
        raise RuntimeError('injected caller exception')
    assert process.poll() == 0 and not hasattr(backend, 'lint')
    worker = lint_worker.Worker()
    try:
        worker.run(arguments(template))
        worker.process.kill()
        worker.process.wait()
        with pytest.raises(ValueError, match='communication failed'):
            worker.run(arguments(template))
    finally:
        worker.close()
    assert worker.process.poll() is not None


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

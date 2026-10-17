"""Isolated local-issues regressions and optional A/B/C fixture benchmark."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.model_sources import snapshot_model

from support.model_sources import write_model

from model_files import read_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

from support.pytest_cli import run

import argparse

from collections import Counter

from contextlib import contextmanager

import hashlib

import json

import os

import re

from support.model_sources import write_fixture_files

import shutil

import statistics

import subprocess

import tempfile

import time

from unittest.mock import patch

from issues_iac import Comparison

from script_loader import module

from iac_values import same, selected_same, strict_json

from issues_scan import scan, mechanical, naming_materials, save_scan, summary, verify_inputs, review_payload, detail_payload

from issues_reports import save, blocks, numbered, identifier, iac_report, iac_dataset, iac_summary, value_differences

from model_design import markdown_for, naming_targets, naming_target_matches

from model_core import properties, entries

from design_layout import resource_name_fields

from model_files import load_model, read_model, model_file_contents, resource_row_index

from validation_cache import input_scope

from task_contract import SELECTOR

from issue_gate import issue_errors

ROOT = Path(__file__).resolve().parents[4]

from support.it_workspace import copy_framework

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_fixture_files({path: text})

def write_report(path, markdown):
    write(path, markdown)

def render_iac(root, path, environment, directory, services, records, display=None):
    entries, actions, fields = iac_dataset(records, environment, directory, services, display)
    return iac_report(environment, directory, services, records, display), {'entries': entries, 'actions': actions, 'value_differences': fields}

def fixture(root, stacks=1, services=('s3', 'cloudwatch-logs', 'sqs'), parts=False):
    # Only immutable framework inputs/runtime; never copy any consumer/task/report.
    for directory in ('materials', 'rules', 'scripts', 'mappings'):
        copy_framework(root / 'framework' / directory, relative=Path('') / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    target = {'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}
    write(root / 'project.json', json.dumps({'projectName': 'fixture', 'targets': [target]}) + '\n')
    specs = {'s3': ('S3.Bucket', 'Bucket', 'BucketName', 'bucket', [('VersioningConfiguration.Status', '`Enabled`')]),
             'cloudwatch-logs': ('Logs.LogGroup', 'Log', 'LogGroupName', 'cwlogs', [('RetentionInDays', '`7`')]),
             'sqs': ('SQS.Queue', 'Queue', 'QueueName', 'sqs', [('VisibilityTimeout', '`30`')])}
    values = {service: {f'desired.service.{service}.serviceId': service,
                       f'desired.service.{service}.ownedCatalogResourceTypes': specs[service][0],
                       'display.service.title': f'# {service} 詳細設計',
                       'desired.note.001.text': 'human確認: application=app; environment=dev; purpose=data。例外は対象resourceに明示する。'} for service in services}
    stackvalues = {'desired.deployment.maxConcurrentStacks': '1'}
    resources = {}
    for service in services:
        kind, logical, field, prefix, extra = specs[service]
        resources[logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {field: {'Fn::Sub': prefix + '-${Name}'}}}
        for prop, value in extra:
            parts_path = prop.split('.')
            node = resources[logical]['Properties']
            for piece in parts_path[:-1]:
                node = node.setdefault(piece, {})
            node[parts_path[-1]] = json.loads(value.strip('`')) if value.strip('`').isdigit() else value.strip('`')
        resources[logical]['Properties']['Tags'] = [{'Key': 'owner', 'Value': 'fixture'}]
    # An unrelated resource must not be treated as an excess selected-service issue.
    resources['OtherService'] = {'Type': 'AWS::EC2::VPC', 'Properties': {'CidrBlock': '10.0.0.0/16'}}
    template = {'AWSTemplateFormatVersion': '2010-09-09', 'Parameters': {'Name': {'Type': 'String'}, 'Enabled': {'Type': 'String', 'Default': 'yes'}},
                'Conditions': {'Active': {'Fn::Equals': [{'Ref': 'Enabled'}, 'yes']}}, 'Resources': resources}
    write(root / 'infra/cloudformation/templates/shared.yaml', json.dumps(template, indent=2) + '\n')
    for number in range(1, stacks + 1):
        stackname = f'cfn-stack-app-dev-data{number}'
        identity = f'{number:03d}'
        stackvalues.update({f'desired.stack.{identity}.name': stackname, f'desired.stack.{identity}.template': 'shared.yaml',
                            f'desired.stack.{identity}.parameters': f'stack-{number}.json', f'desired.stack.{identity}.deployOrder': '1',
                            f'display.stack.{identity}.comment': 'fixture用の独立stack'})
        write(root / f'infra/cloudformation/parameters/dev/123456789012/stack-{number}.json',
              json.dumps([{'ParameterKey': 'Name', 'ParameterValue': f'app-dev-data{number}'}]) + '\n')
        for service in services:
            kind, logical, field, prefix, extra = specs[service]
            name = f'{prefix}-app-dev-data{number}'
            values[service].update({f'desired.resource.{identity}.resourceType': kind,
                                   f'desired.resource.{identity}.logicalId': logical + str(number),
                                   f'desired.resource.{identity}.cfn-logicalId': stackname + '-' + logical,
                                   f'desired.resource.{identity}.anchor': service + '-' + name,
                                   f'display.resource.{identity}.comment': 'fixture用の設定'})
            rows = [(field, '`' + name + '`'), *([('Region', '`ap-northeast-1`')] if service == 's3' else []), *extra, ('Tags[].Key', '`owner`'), ('Tags[].Value', '`fixture`')]
            if service == 'sqs':
                rows.append(('QueueUrl', f'[Queue{number}](#{service}-{name})'))
            for rownumber, (prop, value) in enumerate(rows, 1):
                rid = f'{identity}-{rownumber:03d}'
                values[service].update({f'desired.row.{rid}.property': kind + '.' + prop,
                                       f'desired.row.{rid}.value': value, f'desired.row.{rid}.comment': 'fixtureの設定値'})
                if prop == 'QueueUrl':
                    values[service].update({f'observed.row.{rid}.property': kind + '.' + prop, f'observed.row.{rid}.value': '`PENDING_DEPLOY`', f'observed.row.{rid}.comment': 'fixtureの設定値'})
    write(root / 'model/dev/123456789012/cloudformation-stacks.properties', '\n'.join(f'{key}={value}' for key, value in stackvalues.items()) + '\n')
    for service, modelvalues in values.items():
        text = '\n'.join(f'{key}={value}' for key, value in modelvalues.items()) + '\n'
        if parts:
            text = '# fixture padding to exercise real part locations\n' * 560 + text
        path = root / f'model/dev/123456789012/{service}.properties'
        write_fixture_files(model_file_contents(path, text))
        write(root / f'docs/designs/dev/123456789012/{service}.md', markdown_for(root / f'docs/designs/dev/123456789012/{service}.md', modelvalues, root))
    write(root / 'docs/designs/dev/123456789012/cloudformation-stacks.md', markdown_for(root / 'docs/designs/dev/123456789012/cloudformation-stacks.md', stackvalues, root))
    return values, template

@contextmanager
def task(root, services, name='save', allowed=None):
    reports = ['issues/dev/123456789012/issues.md', 'issues/dev/123456789012/iac-issues.md']
    files = [f'tasks/{name}.md', *(allowed if allowed is not None else reports)]
    text = '# fixture task\n\n## Task contract\n\n- Task type: `migration`\n- Task status: `running`\n\n'
    text += '## Validation scope\n\n' + ''.join(f'- `dev/123456789012/{service}`\n' for service in services)
    for heading in ('Allowed paths', 'Modified files'):
        text += '\n## ' + heading + '\n\n' + ''.join(f'- `{file}`\n' for file in files)
    write(root / f'tasks/{name}.md', text)
    previous = os.environ.get(SELECTOR)
    os.environ[SELECTOR] = f'tasks/{name}.md'
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SELECTOR, None)
        else:
            os.environ[SELECTOR] = previous
        (root / f'tasks/{name}.md').unlink(missing_ok=True)

def compare(root, services):
    @input_scope
    def run():
        comparison = Comparison(root, 'dev', '123456789012', services)
        return comparison, comparison.run()
    return run()

def mutate_template(root, template):
    write(root / 'infra/cloudformation/templates/shared.yaml', json.dumps(template, indent=2) + '\n')

def expect_error(function, phrase=None):
    with pytest.raises((ValueError, OSError, RuntimeError)) as error:
        function()
    assert phrase is None or phrase in str(error.value), str(error.value)

def sequential_reports(root):
    # Successive report writes merge the latest contents.
    from task_contract import refresh, status
    commands = []
    contexts = []
    names = []
    for service in ('s3', 'sqs'):
        context = task(root, [service], name='parallel-' + service)
        context.__enter__()
        contexts.append(context)
        name = 'tasks/parallel-' + service + '.md'
        names.append(name)
        refresh(root, name)
        result = root.parent / ('results-' + service + '.json')
        write(result, json.dumps({'issues': [{'service': service, 'message': 'concurrent-' + service}]}))
        commands.append([sys.executable, '-B', str(ROOT / 'framework/scripts/issues_scan.py'), '--repository-root', str(root),
                         '--task-file', name, 'save-results', '--environment', 'dev',
                         '--target-directory', '123456789012', '--service', service, '--results', str(result)])
    try:
        report = 'issues/dev/123456789012/issues.md'
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
        assert status((root / names[1]).read_text()) == 'running'
        text = (root / report).read_text()
        assert 'concurrent-s3' in text and 'concurrent-sqs' in text
    finally:
        for context in reversed(contexts):
            context.__exit__(None, None, None)

def legacy_mechanical(root, services):
    # Benchmark-only 1005v1-equivalent service path: existing subprocess generator.
    import importlib.util
    spec = importlib.util.spec_from_file_location('benchmark_validator', root / 'framework/scripts/validate-blueprint.py')
    legacy_validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy_validator)
    validator = legacy_validator.Validator(root, {('dev', '123456789012', service) for service in services}, cache=True, fresh=True, workers=1)
    import io
    from contextlib import redirect_stdout
    with redirect_stdout(io.StringIO()):
        validator.check_project_topology()
        validator.check_validation_scope()
        validator.check_model_files()
        validator.check_scoped_designs()
        validator.check_iac_selection()
    return validator.errors

def required_context(root, services):
    from model_design import naming_rule_files
    files = set()
    for service in services:
        kind = {'s3': 'S3', 'sqs': 'SQS', 'cloudwatch-logs': 'Logs'}[service]
        files.update(naming_rule_files(root, kind))
    from issues_scan import rule_section
    shared = []
    for file, headings in [('model-information.md', ('## Model authority', '## Properties format')),
                           ('detailed-design.md', ('## Markdown structure', '## Links and anchors'))]:
        text = (root / 'framework/rules' / file).read_text()
        shared.extend(rule_section(text, heading) for heading in headings)
    return '\n'.join([*(path.read_text() for path in sorted(files)), *shared])

def baseline_input(root, services):
    # Old skill reads authoritative parts and generated Markdown and rewrites the inventory.
    texts = [required_context(root, services)]
    for service in services:
        path = root / f'model/dev/123456789012/{service}.properties'
        from model_files import model_parts
        texts.extend(file.read_text() for file in __import__('model_templates').source_inputs(path))
        texts.append((root / f'docs/designs/dev/123456789012/{service}.md').read_text())
    report = root / 'issues/dev/123456789012/issues.md'
    if report.exists():
        texts.append(report.read_text())
    return '\n'.join(texts)

def worker(root, variant, services):
    counts = Counter()
    timings = {}
    process_count = 1
    original_read, original_bytes = Path.read_text, Path.read_bytes
    import importlib.util
    original_properties, original_model_read = __import__('model_core').properties, __import__('model_files').read_model
    if variant in 'AB':
        modules = []
        for name in ('model_core', 'model_files'):
            spec = importlib.util.spec_from_file_location('baseline_' + name, root / 'framework/scripts' / (name + '.py'))
            loaded = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded)
            modules.append(loaded)
        original_parse = modules[0].properties
        __import__('model_files').read_model = modules[1].read_model
    else:
        original_parse = __import__('model_core')._parse_properties
    original_run = subprocess.run
    def read(path, *args, **kwargs):
        if path.suffix == '.properties' and 'model' in path.parts:
            counts['model_reads'] += 1
            counts['model_text_reads'] += 1
        return original_read(path, *args, **kwargs)
    def read_bytes(path):
        if path.suffix == '.properties' and 'model' in path.parts:
            counts['model_reads'] += 1
            counts['model_byte_reads'] += 1
        return original_bytes(path)
    def parse(text):
        counts['model_parses'] += 1
        return original_parse(text)
    def run(*args, **kwargs):
        nonlocal process_count
        process_count += 1
        command = args[0] if args else kwargs.get('args')
        if isinstance(command, list) and len(command) > 1 and command[1].endswith('/sync-model.py'):
            countfile = root.parent / ('child-counts-' + str(process_count) + '.json')
            code = """import sys,json,importlib.util
from pathlib import Path
from collections import Counter
sys.dont_write_bytecode=True
filename=sys.argv[1]; destination=Path(sys.argv[2]); sys.argv=[filename,*sys.argv[3:]]
sys.path.insert(0,str(Path(filename).parent))
import model_core
counts=Counter(); old_read=Path.read_text; old_bytes=Path.read_bytes; parse_name='_parse_properties' if hasattr(model_core,'_parse_properties') else 'properties'; old_parse=getattr(model_core,parse_name)
base=Path(sys.argv[sys.argv.index('--repository-root')+1])/'model'
def read(path,*args,**kwargs):
 if path.suffix=='.properties' and 'model' in path.parts: counts['model_reads']+=1; counts['model_text_reads']+=1
 return old_read(path,*args,**kwargs)
def read_bytes(path):
 if path.suffix=='.properties' and 'model' in path.parts: counts['model_reads']+=1; counts['model_byte_reads']+=1
 return old_bytes(path)
def parse(text):
 counts['model_parses']+=1
 return old_parse(text)
Path.read_text=read; Path.read_bytes=read_bytes; setattr(model_core,parse_name,parse)
spec=importlib.util.spec_from_file_location('bench_sync',filename); loaded=importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
try: status=loaded.main()
finally: destination.write_text(json.dumps(dict(counts)))
raise SystemExit(status)
"""
            command = [command[0], '-B', '-c', code, command[1], str(countfile), *command[2:]]
            result = original_run(command, *args[1:], **kwargs)
            if countfile.exists():
                counts.update(json.loads(countfile.read_text()))
                countfile.unlink()
            return result
        return original_run(*args, **kwargs)
    started = time.perf_counter()
    with patch.object(Path, 'read_text', read), patch.object(Path, 'read_bytes', read_bytes), patch('model_core.properties' if variant in 'AB' else 'model_core._parse_properties', parse), patch.object(subprocess, 'run', run):
        if variant == 'C':
            artifact = scan(root, 'dev', '123456789012', services, fresh=True, jobs=1)
            llm = required_context(root, services) + json.dumps(review_payload(artifact, '/tmp/fixture-scan.json'), ensure_ascii=False)
            llm_output = json.dumps({'reviewed_names': [item['id'] for item in artifact['naming']['names']],
                                     'reviewed_judgments': [item['id'] for item in artifact['judgments']]})
            errors = [item['message'] for item in artifact['ordinary']]
            records = artifact['iac']
            counts['template_decodes'] += artifact['metrics']['template_decodes']
            save_started = time.perf_counter()
            save_scan(root, artifact, {'reviewed_names': [item['id'] for item in artifact['naming']['names']], 'reviewed_judgments': [item['id'] for item in artifact['judgments']]})
            timings['save_seconds'] = time.perf_counter() - save_started
            timings.update({key: artifact['metrics'][key] for key in ('mechanical_seconds', 'iac_seconds')})
        else:
            start = time.perf_counter()
            errors = legacy_mechanical(root, services)
            timings['mechanical_seconds'] = time.perf_counter() - start
            llm = baseline_input(root, services)
            records = []
            start = time.perf_counter()
            if variant == 'B':
                for service in services:
                    completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--reference', '--fixture', str(root), '--services', service], capture_output=True, text=True, check=True)
                    result = json.loads(completed.stdout)
                    records.extend(result['records'])
                    counts.update(result['counts'])
                    llm += json.dumps(result['records'], ensure_ascii=False)
            timings['iac_seconds'] = time.perf_counter() - start
            llm_output = (root / 'issues/dev/123456789012/issues.md').read_text() + (json.dumps(records, ensure_ascii=False) if records else '')
            save_started = time.perf_counter()
            if variant == 'B':
                save(root, 'dev', '123456789012', services, iac=records)
            else:
                # Old skill's already-authored report write; LLM time is unmeasured.
                write(root / 'issues/dev/123456789012/issues.md', llm_output)
            timings['save_seconds'] = time.perf_counter() - save_started
    __import__('model_files').read_model = original_model_read
    return {'wall_seconds': time.perf_counter() - started, **timings, 'processes': process_count, 'counts_all_processes': dict(counts),
            'llm_input_bytes': len(llm.encode('utf-8')), 'llm_input_chars': len(llm), 'llm_output_bytes': len(llm_output.encode('utf-8')),
            'ordinary': sorted(errors), 'coverage': sorted((item['category'], item['service'], item['resource'], item['property'], item.get('stack')) for item in records),
            'iac_counts': dict(Counter(item['category'] for item in records))}

def benchmark(logdir, repeats=5):
    logdir.mkdir(parents=True, exist_ok=True)
    if logdir.resolve().is_relative_to(ROOT):
        raise ValueError('benchmark logs must be outside repository')
    baseline = logdir / 'baseline'
    baseline.mkdir(exist_ok=True)
    for filename in ('model_files.py', 'model_design.py', 'validate-blueprint.py'):
        result = subprocess.run(['git', 'show', 'HEAD:framework/scripts/' + filename], cwd=ROOT, capture_output=True, text=True, check=True)
        write(baseline / filename, result.stdout)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    output = {'baseline_revision': revision, 'baseline_note': 'checkout HEAD source captured before these uncommitted modifications; 1005v1 is a ZIP identifier, not an assumed ref', 'method': 'separate fresh Python processes; existing success cache disabled via fresh; jobs=1; no profile; OS file cache not flushed; fixtures only',
              'llm_tokens': 'unmeasured', 'llm_wall_time': 'unmeasured', 'metrics_note': 'total Python scan/material/format/save wall includes process startup; LLM and unchanged post-save local loop are unmeasured; model_reads = read_text + read_bytes across input and staged model files; parser calls and actual decode attempts are counted across processes', 'fixtures': {}}
    for label, stack_count, parts in [('small', 1, False), ('multi', 12, True)]:
        with tempfile.TemporaryDirectory(prefix='issues-bench-', dir=logdir) as directory:
            root = Path(directory) / 'project'
            services = ['s3', 'cloudwatch-logs', 'sqs']
            _, template = fixture(root, stack_count, services, parts)
            template['Resources']['Log']['Properties']['RetentionInDays'] = 14
            template['Resources']['Queue']['Properties']['VisibilityTimeout'] = {'Fn::Length': [1, 2]}
            mutate_template(root, template)
            contract = task(root, services, name='benchmark')
            contract.__enter__()
            write(root / 'issues/dev/123456789012/issues.md', '# 問題一覧\n\nhuman確認: fixtureの承認済みcomponent。\n\n## dev／123456789012\n\n### s3\n\n1. fixtureの保持対象問題\n')
            measurements = {variant: [] for variant in 'ABC'}
            # Rotate variant order to avoid consistently favoring a warmed OS cache.
            for repeat in range(repeats):
                for variant in 'ABC'[repeat % 3:] + 'ABC'[:repeat % 3]:
                    report = root / 'issues/dev/123456789012/issues.md'
                    write(report, '# 問題一覧\n\nhuman確認: fixtureの承認済みcomponent。\n\n## dev／123456789012\n\n### s3\n\n1. fixtureの保持対象問題\n')
                    (report.parent / 'iac-issues.md').unlink(missing_ok=True)
                    for filename in ('model_files.py', 'model_design.py', 'validate-blueprint.py'):
                        shutil.copyfile((baseline if variant in 'AB' else ROOT / 'framework/scripts') / filename, root / 'framework/scripts' / filename)
                    launch_started = time.perf_counter()
                    completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', variant, '--fixture', str(root), '--services', ','.join(services)], capture_output=True, text=True)
                    assert completed.returncode == 0, completed.stderr + completed.stdout
                    measured = json.loads(completed.stdout)
                    measured['worker_seconds'] = measured['wall_seconds']
                    measured['wall_seconds'] = time.perf_counter() - launch_started
                    measurements[variant].append(measured)
                    write(logdir / f'{label}-{variant}-{repeat + 1}.json', json.dumps(measured, ensure_ascii=False, indent=2) + '\n')
            for b, c in zip(measurements['B'], measurements['C']):
                assert b['coverage'] == c['coverage'], (b['coverage'], c['coverage'])
                assert b['ordinary'] == c['ordinary'], (b['ordinary'], c['ordinary'])
            medians = {variant: {key: statistics.median(item[key] for item in runs) for key in ('wall_seconds', 'mechanical_seconds', 'iac_seconds', 'save_seconds', 'processes', 'llm_input_bytes', 'llm_input_chars', 'llm_output_bytes')}
                       | {'counts_all_processes': {key: statistics.median(item['counts_all_processes'].get(key, 0) for item in runs) for key in ('model_reads', 'model_text_reads', 'model_byte_reads', 'model_parses', 'template_decodes')},
                          'ordinary_count': len(runs[0]['ordinary']), 'iac_counts': runs[0]['iac_counts']} for variant, runs in measurements.items()}
            assert medians['C']['wall_seconds'] < medians['B']['wall_seconds'], medians
            assert medians['C']['llm_input_bytes'] < medians['B']['llm_input_bytes'], medians
            output['fixtures'][label] = {'repeats': repeats, 'medians': medians, 'runs': measurements}
            contract.__exit__(None, None, None)
    write(logdir / 'benchmark.json', json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'benchmark': str(logdir / 'benchmark.json'), 'fixtures': {key: value['medians'] for key, value in output['fixtures'].items()}}, ensure_ascii=False))

def summary_fixture():
    from issues_reports import identifier
    unknown = [dict(category='difference', service=['s3', 'iam', 'glue'][i % 3], resource=f'u{i:04d}',
                    property='Setting', reason='cause and repair target unknown', stack=None, desired=None, actual=None) for i in range(1000)]
    incomplete = [dict(category='uncompared', service='s3', resource=f'c{i:04d}', property='Role',
                       reason='Export reference unresolved', stack='consumer', cause={'kind': 'import-unresolved', 'export': 'shared-export', 'relationship': 'import'}) for i in range(1000)]
    differences = [dict(category='difference', service='glue', resource=f'v{i:04d}', property=f'Glue.Job.Settings{i % 20}',
                        reason='value mismatch', stack=f'stack{i % 7}', iac={'path': 'infra/shared.yaml'},
                        desired={f'field{j}': j for j in range(20)}, actual={f'field{j}': j + 1 for j in range(20)}) for i in range(100)]
    errors = [dict(category='error', service='iam', resource=f'e{i:04d}', property='Role', reason='Ref attribute resolution failed', stack=None) for i in range(93)]
    records = unknown + incomplete + differences + errors
    display = {identifier(item): value_differences(item['desired'], item['actual'], item['property']) for item in differences}
    names = [dict(id=identifier(['name', i]), service='s3', resource=f'{i:04d}', property='BucketName', value=f'bucket-app-dev-data{i}', resourceMode='CREATE', comment='human-confirmed application=app', pattern_review='required') for i in range(1000)]
    judgments = [dict(id=identifier(['judgment', i]), kind='human-components/exceptions', service='s3', materials='Confirm application component and exception scope') for i in range(100)]
    artifact = dict(version=1, environment='dev', target='cde', services=['glue', 'iam', 's3'], iac=records, iac_display=display,
                    ordinary=[], naming=dict(names=names, rules={}, target_context={}, review_policy='review all'),
                    judgments=judgments, human_confirmations=[], checks=1, executed_at='2026-10-08T00:00:00Z')
    return artifact

@pytest.fixture(scope="module", autouse=True)
def protected_sources():
    protected = [ROOT / 'framework/scripts' / name for name in
                 ('issues_iac.py', 'issue_gate.py', 'comparison_rows.py', 'iac_values.py', 'iac_evaluation.py', 'script_loader.py', 'model_design.py', 'policy_tables.py')]
    before = {path: path.read_bytes() for path in protected if path.exists()}
    yield
    assert before == {path: path.read_bytes() if path.exists() else None for path in before}, 'checks changed protected source'

@pytest.fixture
def scan_project(tmp_path):
    root = tmp_path / "project"
    values, template = fixture(root, stacks=3, parts=True)
    return root, values, template


__all__ = ['Comparison', 'Counter', 'Path', 'ROOT', 'SELECTOR', 'argparse', 'baseline_input', 'benchmark', 'blocks', 'compare', 'sequential_reports', 'contextmanager', 'detail_payload', 'entries', 'expect_error', 'fixture', 'hashlib', 'iac_dataset', 'iac_report', 'iac_summary', 'identifier', 'input_scope', 'issue_errors', 'json', 'legacy_mechanical', 'load_model', 'markdown_for', 'mechanical', 'model_file_contents', 'module', 'mutate_template', 'naming_materials', 'naming_target_matches', 'naming_targets', 'numbered', 'os', 'patch', 'properties', 'protected_sources', 'pytest', 'pytestmark', 're', 'read_model', 'render_iac', 'required_context', 'resource_name_fields', 'resource_row_index', 'review_payload', 'run', 'same', 'save', 'save_scan', 'scan', 'scan_project', 'selected_same', 'shutil', 'snapshot_model', 'statistics', 'strict_json', 'subprocess', 'summary', 'summary_fixture', 'sys', 'task', 'tempfile', 'time', 'value_differences', 'verify_inputs', 'worker', 'write', 'write_fixture_files', 'write_model', 'write_report']

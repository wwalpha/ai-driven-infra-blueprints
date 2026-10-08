#!/usr/bin/env python3
"""Isolated local-issues regressions and optional A/B/C fixture benchmark."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from issues_iac import Comparison, same, selected_same, strict_json, module
from issues_scan import scan, mechanical, naming_materials, save_scan, summary, verify_inputs, review_payload
from issues_reports import save, blocks, numbered, identifier, iac_merge, iac_state, value_differences, IAC_DATA
from model_design import properties, entries, markdown_for, naming_targets, naming_target_matches
from design_layout import resource_name_fields
from model_files import load_model, read_model, model_file_contents, resource_row_index
from validation_cache import input_scope
from task_contract import SELECTOR
from issue_gate import issue_errors

ROOT = Path(__file__).resolve().parents[2]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def write_report(path, markdown, state=None):
    """Publish fixture pairs; explicit legacy/empty fixtures have no sidecar."""
    from issues_reports import atomic_files
    state_path = path.with_name('iac-issues.state.json')
    if state is None:
        state_path.unlink(missing_ok=True)
        write(path, markdown)
    else:
        atomic_files({path: markdown, state_path: json.dumps(state, ensure_ascii=False)})


def read_iac(result, environment, directory):
    markdown, state = result
    return iac_state(markdown, environment, directory, data=state)


def fixture(root, stacks=1, services=('s3', 'cloudwatch-logs', 'sqs'), parts=False):
    # Only immutable framework inputs/runtime; never copy any consumer/task/report.
    for directory in ('materials', 'rules', 'scripts'):
        shutil.copytree(ROOT / 'framework' / directory, root / 'framework' / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
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
        for file, content in model_file_contents(path, text).items():
            write(file, content)
        write(root / f'docs/designs/dev/123456789012/{service}.md', markdown_for(root / f'docs/designs/dev/123456789012/{service}.md', modelvalues, root))
    write(root / 'docs/designs/dev/123456789012/cloudformation-stacks.md', markdown_for(root / 'docs/designs/dev/123456789012/cloudformation-stacks.md', stackvalues, root))
    return values, template


@contextmanager
def task(root, services, name='save', allowed=None):
    reports = ['issues/dev/123456789012/issues.md', 'issues/dev/123456789012/iac-issues.md', 'issues/dev/123456789012/iac-issues.state.json']
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


def naming_target_scope_cases():
    with tempfile.TemporaryDirectory(prefix='naming-target-path-') as directory:
        root = Path(directory) / 'project'
        fixture(root)
        specifications = {
            'codebuild': ('CodeBuild.Project', [
                ('Name', '`invalid_root_name`'),
                ('Environment.EnvironmentVariables[].Name', '`AWS_REGION`'),
                ('Environment.EnvironmentVariables[].Name', '`BUILD_BUCKET_NAME`'),
                ('Environment.EnvironmentVariables[].Name', '`TARGET`'),
                ('Artifacts.Name', '`artifact-name`'),
            ]),
            'codepipeline': ('CodePipeline.Pipeline', [
                ('Name', '`invalid_root_name`'), ('Stages[].Name', '`Source`'),
                ('Stages[].Actions[].Name', '`SourceAction`'), ('Variables[].Name', '`release`'),
            ]),
            'glue': ('Glue.Job', [('Name', '`invalid_root_name`'), ('Command.Name', '`script`')]),
        }
        for service, (kind, rows) in specifications.items():
            values = {f'desired.service.{service}.serviceId': service,
                      f'desired.resource.001.resourceType': kind,
                      f'desired.resource.001.logicalId': 'Resource',
                      f'desired.resource.001.anchor': service + '-resource'}
            for number, (prop, value) in enumerate(rows, 1):
                key = f'{number:03d}'
                values.update({f'desired.row.001-{key}.property': kind + '.' + prop,
                               f'desired.row.001-{key}.value': value,
                               f'desired.row.001-{key}.comment': 'fixture name'})
            write(root / f'model/dev/123456789012/{service}.properties',
                  '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
        comparison = Comparison(root, 'dev', '123456789012', list(specifications))
        material, _ = naming_materials(comparison)
        selected = {(item['resourceType'], item['property'], item['value']) for item in material['names']}
        for kind in ('CodeBuild.Project', 'CodePipeline.Pipeline', 'Glue.Job'):
            assert (kind, 'Name', '`invalid_root_name`') in selected, kind
        nested = {(kind, prop) for kind, prop, _ in selected if prop.endswith('.Name') or '[]' in prop and prop.endswith('Name')}
        assert not nested, nested
        assert all((('CodeBuild.Project' if service == 'codebuild' else 'CodePipeline.Pipeline' if service == 'codepipeline' else 'Glue.Job'), prop) in {
            (item['resourceType'], item['property']) for item in material['names']
        } for service, (_, rows) in specifications.items() for prop, _ in rows if prop == 'Name')
        targets = {kind: naming_targets(root, kind.partition('.')[0]).get(kind, set()) for kind, _ in specifications.values()}
        before_root = sum(1 for kind, rows in specifications.values() for prop, _ in rows
                          if prop == 'Name' and (prop in resource_name_fields(kind) or prop.rsplit('.', 1)[-1] in targets[kind]))
        after_root = sum(1 for kind, rows in specifications.values() for prop, _ in rows
                         if prop == 'Name' and (prop in resource_name_fields(kind) or naming_target_matches(prop, targets[kind], kind)))
        before_nested = sum(1 for kind, rows in specifications.values() for prop, _ in rows
                            if prop.rsplit('.', 1)[-1] in targets[kind] and '.' in prop)
        after_nested = sum(1 for kind, rows in specifications.values() for prop, _ in rows
                           if prop in targets[kind] or naming_target_matches(prop, targets[kind], kind)
                           if '.' in prop)
        assert before_root == after_root == 3, (before_root, after_root)
        assert before_nested == 8, before_nested
        assert after_nested == 0, after_nested
    print('Naming Target issue candidates: PASS (root candidates 3→3; nested false positives 8→0)')


def compare(root, services):
    @input_scope
    def run():
        comparison = Comparison(root, 'dev', '123456789012', services)
        return comparison, comparison.run()
    return run()


def mutate_template(root, template):
    write(root / 'infra/cloudformation/templates/shared.yaml', json.dumps(template, indent=2) + '\n')


def expect_error(function, phrase=None):
    try:
        function()
    except (ValueError, OSError, RuntimeError) as error:
        assert phrase is None or phrase in str(error), str(error)
    else:
        raise AssertionError('expected rejection')


def checks(root, values, template):
    services = sorted(values)
    comparator, records = compare(root, services)
    assert not [item for item in records if item['category'] in {'difference', 'uncompared', 'error'}], records
    assert comparator.metrics['template_decodes'] == 1
    assert comparator.metrics['stack_evaluations'] == 3
    assert comparator.metrics['model_parses'] == 4
    # Missing explicit templates remain non-blocking differences with readable, unlinked paths.
    template_path = root / 'infra/cloudformation/templates/shared.yaml'
    template_path.unlink()
    try:
        _, missing = compare(root, services)
        assert len(missing) == 9 and all(item['category'] == 'difference' for item in missing), missing
        assert all(item['reason'] == 'モデルに対応するtemplateが存在しない（CREATE未実装）' for item in missing)
        report, report_state = iac_merge(root, root / 'issues/dev/123456789012/iac-issues.md', 'dev', '123456789012', services, missing)
        assert '差分 9件; 未比較 0件; 処理error 0件' in report
        assert '`infra/cloudformation/templates/shared.yaml`（ファイルが存在しない）' in report
        assert '[infra/cloudformation/templates/shared.yaml]' not in report
        comparison = Comparison(root, 'dev', '123456789012', ['s3'])
        comparison.resources['s3']['001']['resourceMode'] = 'IMPORT'
        comparison.resources['s3']['002']['cfn-logicalId'] = 'undeclared-stack-Bucket'
        categories = {item['resource']: item for item in comparison.run()}
        assert categories['001']['category'] == 'excluded'
        assert categories['002']['category'] == 'uncompared' and 'stack is not declared' in categories['002']['reason']
        assert categories['003']['category'] == 'difference'
    finally:
        mutate_template(root, template)
    from issues_iac import safe_value
    assert safe_value([{'Name': 'SECRET_TOKEN', 'Value': 'confidential'}])[0]['Value'] == '<masked>'
    assert same(1, True) is False and same('1', 1) is False
    assert not same([1, 2], [2, 1]) and not same([1, 1], [1])
    assert selected_same({'a': 1}, {'a': 1, 'b': 2})
    assert selected_same([{'Key': 'Name', 'Value': 'a'}], [{'Key': 'owner', 'Value': 'b'}, {'Key': 'Name', 'Value': 'a'}], 'Tags')
    assert not selected_same([{'Key': 'Name', 'Value': 'a'}], [{'Key': 'Name', 'Value': 'a'}, {'Key': 'Name', 'Value': 'a'}], 'Tags')
    loaded = load_model(root / 'model/dev/123456789012/s3.properties')
    assert any(path.name.startswith('part-') for path, line in loaded.locations.values())
    for key, (path, line) in loaded.locations.items():
        assert path.read_text(encoding='utf-8').splitlines()[line - 1].partition('=')[0] == key
    indexed = resource_row_index(loaded.values)
    oldrows = entries(loaded.values, 'desired.row.')
    for identity in indexed:
        assert indexed[identity] == [(rid, row) for rid, row in oldrows if rid.startswith(identity + '-')]
    legacy = {'desired.resource.legacy-id.resourceType': 'S3.Bucket', 'desired.row.legacy-id-001.property': 'S3.Bucket.BucketName',
              'desired.row.legacy-id-001.value': '`bucket`', 'desired.row.legacy-id-001.comment': '設定'}
    assert list(resource_row_index(legacy)) == ['legacy-id']
    legacy['desired.resource.legacy.resourceType'] = 'S3.Bucket'
    expect_error(lambda: resource_row_index(legacy), 'ambiguous')
    @input_scope
    def shared_parse():
        import model_design
        with patch.object(model_design, 'properties', wraps=model_design.properties) as parse:
            path = root / 'model/dev/123456789012/s3.properties'
            one, two = load_model(path), load_model(path)
            assert one is two and read_model(path) == one.text
            assert parse.call_count == 1
    shared_parse()
    # Different parameter files must remain different evaluations of a shared template.
    assert len({item['stack'] for item in records if item['category'] == 'matched'}) == 3
    changed = strict_json(json.dumps(template))
    changed['Resources']['Log']['Properties']['RetentionInDays'] = '7'
    changed['Resources']['Queue']['Properties'].pop('QueueName')
    changed['Resources'].pop('Bucket')
    mutate_template(root, changed)
    _, differences = compare(root, services)
    assert sum(item['category'] == 'difference' for item in differences) == 9, differences
    assert not any(item['service'] == 'OtherService' for item in differences)
    changed = strict_json(json.dumps(template))
    changed['Resources']['Log']['Condition'] = 'Active'
    changed['Resources']['Log']['Properties']['RetentionInDays'] = {'Fn::If': ['Active', 7, 14]}
    changed['Resources']['Queue']['Properties']['VisibilityTimeout'] = {'Fn::Length': [1, 2]}
    mutate_template(root, changed)
    _, partial = compare(root, services)
    assert sum(item['category'] == 'uncompared' for item in partial) == 3
    assert not any(item['category'] == 'difference' for item in partial)
    changed['Transform'] = 'AWS::Serverless-2016-10-31'
    mutate_template(root, changed)
    _, transform = compare(root, services)
    assert any('Transform' in item['reason'] for item in transform)
    mutate_template(root, template)
    write(root / 'infra/cloudformation/parameters/dev/123456789012/stack-2.json', json.dumps([{'ParameterKey': 'Name', 'ParameterValue': 'app-dev-different'}]))
    _, unequal = compare(root, services)
    assert sum(item['category'] == 'difference' for item in unequal) == 3
    assert {item['stack'] for item in unequal if item['category'] == 'difference'} == {'cfn-stack-app-dev-data2'}
    write(root / 'infra/cloudformation/parameters/dev/123456789012/stack-2.json', json.dumps([{'ParameterKey': 'Name', 'ParameterValue': 'app-dev-data2'}]))
    # CRLF entrance and parts must hash the same bytes that were decoded.
    source = root / 'model/dev/123456789012/s3.properties'
    originals = load_model(source).files.copy()
    for path, text in originals.items():
        path.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
    crlf = load_model(source)
    assert crlf.values == loaded.values
    assert all(text.encode('utf-8') == path.read_bytes() for path, text in crlf.files.items())
    # Existing diagnostics and all successful names stay available. No network/provider calls.
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        artifact = scan(root, 'dev', '123456789012', services, fresh=True, jobs=1)
    assert artifact['checks'] > 0
    assert not artifact['ordinary'] and not any('message' in item for item in artifact['judgments']), (artifact['ordinary'], artifact['judgments'])
    names = artifact['naming']['names']
    assert {item['service'] for item in names} == set(services)
    assert len([item for item in names if item['property'] != '(no selected naming property)']) == 9
    review = {'reviewed_names': [item['id'] for item in names], 'reviewed_judgments': [item['id'] for item in artifact['judgments']]}
    with task(root, services):
        expect_error(lambda: save_scan(root, artifact, {}), 'all naming')
        paths = save_scan(root, artifact, review)
        assert all(path.exists() for path in paths)
        assert not issue_errors(root, {('dev', '123456789012', 's3')})
        with patch.object(Comparison, 'run', side_effect=AssertionError('save must not compare')):
            save_scan(root, artifact, review)
        ordinary = paths[0]
        write(ordinary, '# 問題一覧\n\nhuman確認: 既存確認を保持。\n適用例外: このresourceだけ。\n\n## dev／123456789012\n\n### s3\n\n1. 既存未解消問題\n\n### sqs\n\n1. 別serviceの問題\n')
        save(root, 'dev', '123456789012', ['s3'], additions=[{'service': 's3', 'message': '追加された具体的問題'}])
        text = ordinary.read_text(encoding='utf-8')
        assert 'human確認' in text and '適用例外' in text and '既存未解消' in text and '別service' in text
        assert issue_errors(root, {('dev', '123456789012', 's3')})
        assert issue_errors(root, {('dev', '123456789012', 'sqs')})
        assert not issue_errors(root, {('prod', '123456789012', 's3')})
        # Legacy display headings use the unchanged gate's exact evidence ownership.
        write(ordinary, '# 問題一覧\n\nhuman確認: 保持。\n\n## dev／123456789012\n\n### Amazon S3\n\n1. 旧問題 [model](../../../model/dev/123456789012/s3.properties)\n')
        save(root, 'dev', '123456789012', ['s3'], additions=[{'service': 's3', 'message': '診断にlinkがない新問題'}])
        assert not any('ambiguous' in error for error in issue_errors(root, {('dev', '123456789012', 's3')}))
        previous = ordinary.read_bytes()
        with patch('issues_reports.os.replace', side_effect=OSError('fixture save failure')):
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], additions=[{'service': 's3', 'message': '保存不可'}]))
        assert ordinary.read_bytes() == previous
        write(ordinary, 'malformed report without inventory\n')
        expect_error(lambda: save(root, 'dev', '123456789012', ['s3']), 'malformed')
        assert ordinary.read_text() == 'malformed report without inventory\n'
        write(ordinary, previous.decode())
        parameter = root / 'infra/cloudformation/parameters/dev/123456789012/stack-1.json'
        original = parameter.read_text()
        write(parameter, original + ' ')
        expect_error(lambda: save_scan(root, artifact, review), 'stale scan')
        write(parameter, original)
        record = dict(next(item for item in records if item['category'] == 'matched'), category='difference', reason='fixture difference', desired='old', actual='new')
        save(root, 'dev', '123456789012', services, iac=[record])
        report = paths[1]
        marker = f'<!-- issue-service: {record["service"]} -->'
        write(report, report.read_text().replace(marker, marker + '\n\nhuman確認: IaC側の既存例外。'))
        uncertain = dict(record, category='uncompared', reason='fixture no longer comparable', desired=None, actual=None)
        save(root, 'dev', '123456789012', services, iac=[uncertain])
        partial = report.read_text()
        assert 'human確認: IaC側の既存例外。' in partial
        retained_entries = iac_state(partial, 'dev', '123456789012', data=json.loads(paths[2].read_text()))[0]
        assert any(entry['retained'] and entry['record'].get('desired') == 'old' and entry['record'].get('actual') == 'new' for entry in retained_entries)
        assert '保持未確認: 1件' in partial and '未比較 1件' in partial
        save(root, 'dev', '123456789012', services, iac=[uncertain])
        assert sum(entry['record']['reason'] == 'fixture no longer comparable' for entry in iac_state(report.read_text(), 'dev', '123456789012', data=json.loads(report.with_name("iac-issues.state.json").read_text()))[0]) == 1
        save(root, 'dev', '123456789012', services, iac=[])
        assert '未確認（今回の比較では解消を確定していない）' in paths[1].read_text()
        write(paths[1], 'invalid iac report\n')
        expect_error(lambda: save(root, 'dev', '123456789012', services, iac=[]), 'malformed')
        paths[1].unlink()
    with task(root, ['s3'], name='unreserved', allowed=['issues/dev/123456789012/diff.md']):
        expect_error(lambda: save(root, 'dev', '123456789012', ['s3']), 'Allowed paths')
    with task(root, ['s3'], name='mixed', allowed=['issues/dev/123456789012/issues.md', 'model/dev/123456789012/s3.properties']):
        expect_error(lambda: save(root, 'dev', '123456789012', ['s3']), 'save-only')
    # Cache hits cannot erase actual model/Markdown mismatches, schema, link or JSON policy errors.
    doc = root / 'docs/designs/dev/123456789012/s3.md'
    original = doc.read_text()
    write(doc, original.replace('bucket-app-dev-data1', 'wrong-name'))
    errors, _, _ = mechanical(root, {('dev', '123456789012', 's3')}, fresh=True, jobs=1)
    assert errors and any('model' in item or 'generated' in item for item in errors), errors
    write(doc, original)
    # Save-only never enters scan/naming/comparison.
    with task(root, ['s3'], name='saveonly'):
        with patch('issues_scan.scan', side_effect=AssertionError('rescan forbidden')), patch.object(Comparison, 'run', side_effect=AssertionError('compare forbidden')):
            save(root, 'dev', '123456789012', ['s3'], additions=[{'service': 's3', 'message': '取得済みの具体的診断'}])


def resource_cases(root):
    # Compact independent fixture edits, not consumer data.
    values = load_model(root / 'model/dev/123456789012/s3.properties').values.copy()
    source = root / 'model/dev/123456789012/s3.properties'
    original_files = {path: text for path, text in load_model(source).files.items()}
    def publish(model):
        for part in source.with_suffix('').glob('*.properties'):
            part.unlink()
        for path, text in model_file_contents(source, '\n'.join(f'{key}={value}' for key, value in model.items()) + '\n').items():
            write(path, text)
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    publish(values)
    comparator, records = compare(root, ['s3'])
    assert next(item for item in records if item['resource'] == '001')['category'] == 'excluded'
    values['desired.resource.001.resourceMode'] = 'CREATE'
    values['desired.resource.002.cfn-logicalId'] = values['desired.resource.001.cfn-logicalId']
    publish(values)
    _, records = compare(root, ['s3'])
    assert any(item['category'] == 'uncompared' and 'duplicate' in item['reason'] for item in records)
    values['desired.resource.002.cfn-logicalId'] = 'cfn-stack-app-dev-data2-Bucket'
    # Symbolic reference to a not-deployed resource; Ref/GetAtt use identity/attribute.
    values.update({'desired.resource.004.resourceType': 'S3.Bucket', 'desired.resource.004.logicalId': 'ExtraBucket',
                   'desired.resource.004.cfn-logicalId': 'cfn-stack-app-dev-data1-ExtraBucket', 'desired.resource.004.anchor': 's3-extra',
                   'desired.row.004-001.property': 'S3.Bucket.BucketName', 'desired.row.004-001.value': '`bucket-extra`', 'desired.row.004-001.comment': '設定',
                   'desired.row.004-002.property': 'S3.Bucket.BucketName', 'desired.row.004-002.value': '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)', 'desired.row.004-002.comment': '参照'})
    publish(values)
    comparison = Comparison(root, 'dev', '123456789012', ['s3'])
    _, stacks = __import__('model_design').stack_model(comparison.model('cloudformation-stacks').values)
    comparison.stack(stacks[0][1])
    assert comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)') == comparison.evaluate(stacks[0][1]['name'], {'Ref': 'Bucket'})
    assert comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)', 'Arn') == comparison.evaluate(stacks[0][1]['name'], {'Fn::GetAtt': ['Bucket', 'Arn']})
    assert comparison.evaluate(stacks[0][1]['name'], {'Fn::Select': ['1', {'Fn::Split': [',', 'a,b']}]}) == 'b'
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    publish(values)
    comparison = Comparison(root, 'dev', '123456789012', ['s3'])
    expect_error(lambda: comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)'), 'IMPORT')
    # Restore all real part files, then Terraform remains explicit partial without CFn IDs.
    for part in source.with_suffix('').glob('*.properties'):
        part.unlink()
    for path, text in original_files.items():
        write(path, text)
    project = root / 'project.json'
    original = project.read_text()
    write(project, original.replace('cloudformation', 'terraform'))
    _, records = compare(root, ['s3'])
    assert records and all(item['category'] == 'uncompared' for item in records)
    write(project, original)


def extended_cases(root, template):
    source = root / 'model/dev/123456789012/s3.properties'
    originals = load_model(source).files.copy()
    values = load_model(source).values.copy()
    def publish(values):
        for part in source.with_suffix('').glob('*.properties'):
            part.unlink()
        for path, content in model_file_contents(source, '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n').items():
            write(path, content)
    # Inline child stays with its owning parent, even in a mixed-service template.
    policy = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': ['first', 'second']}]}
    values.update({'desired.row.001-090.property': 'S3.BucketPolicy.PolicyDocument',
                   'desired.row.001-090.value': '[Policy](s3/bucket-policy.json)',
                   'desired.row.001-090.document': json.dumps(policy), 'desired.row.001-090.comment': 'policy設定'})
    publish(values)
    changed = strict_json(json.dumps(template))
    changed['Resources']['BucketPolicy'] = {'Type': 'AWS::S3::BucketPolicy', 'Properties': {'Bucket': {'Ref': 'Bucket'}, 'PolicyDocument': policy}}
    mutate_template(root, changed)
    _, records = compare(root, ['s3'])
    assert any(item['property'] == 'S3.BucketPolicy.PolicyDocument' and item['category'] == 'matched' for item in records)
    changed['Resources']['BucketPolicy']['Properties']['PolicyDocument']['Statement'][0]['Resource'].reverse()
    mutate_template(root, changed)
    _, records = compare(root, ['s3'])
    assert any(item['property'] == 'S3.BucketPolicy.PolicyDocument' and item['category'] == 'difference' for item in records)
    changed['Resources']['SecondPolicy'] = changed['Resources']['BucketPolicy']
    mutate_template(root, changed)
    _, records = compare(root, ['s3'])
    assert any('inline child correspondence matches=2' in item['reason'] for item in records)
    # Malformed authoritative policy input becomes a processing error, never a match.
    values['desired.row.001-090.document'] = '{bad json'
    publish(values)
    changed['Resources'].pop('SecondPolicy')
    mutate_template(root, changed)
    _, records = compare(root, ['s3'])
    assert any(item['category'] == 'error' for item in records)
    for part in source.with_suffix('').glob('*.properties'):
        part.unlink()
    for path, content in originals.items():
        write(path, content)
    mutate_template(root, template)
    # Independent grouped child uses its own mode and formal implicit parentReference.
    kms = {'desired.service.kms.serviceId': 'kms', 'desired.service.kms.ownedCatalogResourceTypes': 'KMS.Key,KMS.Alias',
           'desired.resource.001.resourceType': 'KMS.Key', 'desired.resource.001.logicalId': 'Key',
           'desired.resource.001.cfn-logicalId': 'cfn-stack-app-dev-data1-Key', 'desired.resource.001.anchor': 'kms-key',
           'desired.row.001-001.property': 'KMS.Key.Description', 'desired.row.001-001.value': '`fixture-key`', 'desired.row.001-001.comment': '鍵説明',
           'desired.resource.002.resourceType': 'KMS.Alias', 'desired.resource.002.logicalId': 'Alias', 'desired.resource.002.anchor': 'kms-alias',
           'desired.resource.002.parentReference': '[PENDING_DEPLOY](#kms-key)', 'desired.resource.002.parentProperty': 'KMS.Alias.TargetKeyId',
           'desired.resource.002.resourceMode': 'IMPORT',
           'desired.row.002-001.property': 'KMS.Alias.AliasName', 'desired.row.002-001.value': '`alias/HumanActual`', 'desired.row.002-001.comment': 'human例外: IMPORTのactual名称'}
    kmspath = root / 'model/dev/123456789012/kms.properties'
    def publish_kms():
        write(kmspath, '\n'.join(f'{key}={value}' for key, value in kms.items()) + '\n')
    publish_kms()
    changed = strict_json(json.dumps(template))
    changed['Resources']['Key'] = {'Type': 'AWS::KMS::Key', 'Properties': {'Description': 'fixture-key'}}
    mutate_template(root, changed)
    comparison, records = compare(root, ['kms'])
    assert any(item['resource'] == '002' and item['category'] == 'excluded' for item in records)
    material, _ = naming_materials(comparison)
    alias = next(item for item in material['names'] if item['resource'] == '002')
    assert alias['resourceMode'] == 'IMPORT' and alias['value'] == '`alias/HumanActual`' and not alias['required_missing']
    kms['desired.resource.002.resourceMode'] = 'CREATE'
    kms['desired.resource.002.cfn-logicalId'] = 'cfn-stack-app-dev-data1-Alias'
    publish_kms()
    changed['Resources']['Alias'] = {'Type': 'AWS::KMS::Alias', 'Properties': {'AliasName': 'alias/HumanActual', 'TargetKeyId': {'Ref': 'Key'}}}
    mutate_template(root, changed)
    _, records = compare(root, ['kms'])
    assert any(item['property'] == 'KMS.Alias.TargetKeyId' and item['category'] == 'matched' for item in records)
    kmspath.unlink()
    mutate_template(root, template)
    # A singleton model reference to a schema array remains an array, never a scalar.
    modelpath = root / 'model/dev/123456789012/codebuild.properties'
    rows = {'desired.service.codebuild.serviceId': 'codebuild', 'desired.resource.001.resourceType': 'CodeBuild.Project',
            'desired.resource.001.anchor': 'codebuild-one', 'desired.resource.001.logicalId': 'Project',
            'desired.row.001-001.property': 'CodeBuild.Project.VpcConfig.Subnets', 'desired.row.001-001.value': '[PENDING_DEPLOY](vpc.md#vpc-subnet)', 'desired.row.001-001.comment': '参照'}
    refpath = root / 'model/dev/123456789012/vpc.properties'
    write(refpath, 'desired.service.vpc.serviceId=vpc\ndesired.resource.001.resourceType=EC2.Subnet\ndesired.resource.001.logicalId=Subnet\ndesired.resource.001.anchor=vpc-subnet\n')
    write(modelpath, '\n'.join(f'{key}={value}' for key, value in rows.items()) + '\n')
    comparison = Comparison(root, 'dev', '123456789012', ['codebuild'])
    value = comparison.desired_value('codebuild', comparison.rows['codebuild']['001'][0][1], 'CodeBuild.Project')
    assert isinstance(value, list) and len(value) == 1 and value[0]['$attribute'] == 'SubnetId'
    modelpath.unlink(); refpath.unlink()
    # Pattern disagreement, unknown components, required missing Name are separate review material.
    vpc = {'desired.service.vpc.serviceId': 'vpc', 'desired.service.vpc.ownedCatalogResourceTypes': 'EC2.VPC',
           'desired.resource.001.resourceType': 'EC2.VPC', 'desired.resource.001.anchor': 'vpc-one',
           'desired.resource.001.logicalId': 'One', 'desired.resource.001.resourceMode': 'CREATE',
           'desired.resource.002.resourceType': 'EC2.VPC', 'desired.resource.002.anchor': 'vpc-two',
           'desired.resource.002.logicalId': 'Two', 'desired.resource.002.resourceMode': 'IMPORT',
           'desired.resource.003.resourceType': 'EC2.VPC', 'desired.resource.003.anchor': 'vpc-three',
           'desired.resource.003.logicalId': 'Three', 'desired.row.003-001.property': 'EC2.VPC.Name',
           'desired.row.003-001.value': '`bad_pattern_value`', 'desired.row.003-001.comment': 'component根拠未確認'}
    path = root / 'model/dev/123456789012/vpc.properties'
    write(path, '\n'.join(f'{key}={value}' for key, value in vpc.items()) + '\n')
    comparison = Comparison(root, 'dev', '123456789012', ['vpc'])
    material, _ = naming_materials(comparison)
    assert next(item for item in material['names'] if item['resource'] == '001')['required_missing']
    assert not next(item for item in material['names'] if item['resource'] == '002')['required_missing']
    item = next(item for item in material['names'] if item['resource'] == '003')
    assert item['value'] == '`bad_pattern_value`' and item['pattern_review'] == 'required' and '推測しない' in material['review_policy']
    path.unlink()
    # Supported local expression/NoValue and NoEcho redaction.
    changed = strict_json(json.dumps(template))
    changed['Mappings'] = {'Table': {'one': {'value': 7}}}
    changed['Parameters']['Sensitive'] = {'Type': 'String', 'NoEcho': True, 'Default': 'fixture-confidential-value'}
    changed['Resources']['Log']['Properties']['RetentionInDays'] = {'Fn::FindInMap': ['Table', 'one', 'value']}
    changed['Resources']['Log']['Properties']['LogGroupName'] = {'Ref': 'Sensitive'}
    mutate_template(root, changed)
    _, records = compare(root, ['cloudwatch-logs'])
    assert any(item['property'].endswith('RetentionInDays') and item['category'] == 'matched' for item in records)
    assert 'fixture-confidential-value' not in json.dumps(records)
    changed['Resources']['Log']['Properties']['RetentionInDays'] = {'Fn::If': ['Active', {'Ref': 'AWS::NoValue'}, 7]}
    mutate_template(root, changed)
    _, records = compare(root, ['cloudwatch-logs'])
    assert any('omitted' in item['reason'] for item in records)
    mutate_template(root, template)
    # Cache hits retain parse validity but cannot leak mutation between old public callers.
    @input_scope
    def mutation_isolated():
        text = 'desired.note.001.text=confirmed\n'
        properties(text)['desired.note.001.text'] = 'changed'
        assert properties(text)['desired.note.001.text'] == 'confirmed'
        expect_error(lambda: properties('bad\n'), 'invalid')
        expect_error(lambda: properties('same=1\nsame=2\n'), 'duplicate')
    mutation_isolated()
    # All syntax and reference diagnostics remain normal validation failures.
    doc = root / 'docs/designs/dev/123456789012/s3.md'
    original_doc = doc.read_text()
    write(doc, original_doc.replace('`Enabled`', '`invalid-status`'))
    errors, _, _ = mechanical(root, {('dev', '123456789012', 's3')}, fresh=True, jobs=1)
    assert errors
    write(doc, original_doc)
    # Diff alone does not fail the CLI or register a blocking issue.
    changed = strict_json(json.dumps(template))
    changed['Resources']['Log']['Properties']['RetentionInDays'] = 14
    mutate_template(root, changed)
    artifact_path = root.parent / 'diff-scan.json'
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'framework/scripts/issues_scan.py'), '--repository-root', str(root), 'scan',
                             '--environment', 'dev', '--target-directory', '123456789012', '--service', 'cloudwatch-logs', '--artifact', str(artifact_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['summary']['iac_differences'] == 3
    assert not issue_errors(root, {('dev', '123456789012', 'cloudwatch-logs')})
    mutate_template(root, template)


def comparison_repair_cases():
    from cloudformation_inputs import load_template_inputs
    with tempfile.TemporaryDirectory(prefix='comparison-repair-') as directory:
        root = Path(directory) / 'project'
        _, template = fixture(root, services=['cloudwatch-logs'])
        name = 'cfn-stack-app-dev-data1'
        role = {'desired.service.iam.serviceId': 'iam', 'desired.resource.001.resourceType': 'IAM.Role',
                'desired.resource.001.cfn-logicalId': name + '-Role', 'desired.resource.001.anchor': 'iam-role',
                'desired.row.001-001.property': 'IAM.Role.RoleName', 'desired.row.001-001.value': '`BuildRole`'}
        project = {'desired.service.codebuild.serviceId': 'codebuild', 'desired.resource.001.resourceType': 'CodeBuild.Project',
                   'desired.resource.001.cfn-logicalId': name + '-Build', 'desired.row.001-001.property': 'CodeBuild.Project.ServiceRole',
                   'desired.row.001-001.value': '[PENDING_DEPLOY](iam.md#iam-role)'}
        for service, model in [('iam', role), ('codebuild', project)]:
            write(root / f'model/dev/123456789012/{service}.properties', '\n'.join(f'{key}={value}' for key, value in model.items()) + '\n')
        template['Resources']['Role'] = {'Type': 'AWS::IAM::Role', 'Properties': {'RoleName': 'BuildRole'}}
        template['Resources']['Build'] = {'Type': 'AWS::CodeBuild::Project', 'Properties': {'ServiceRole': {'Fn::GetAtt': ['Role', 'Arn']}}}
        template['Mappings'] = {'Table': {'one': {'text': 'resolved', 'number': 7}}}
        mutate_template(root, template)
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, records = compare(root, ['codebuild'])
            assert len(records) == 1 and records[0]['category'] == 'matched', records
            # Other role properties still use the default RoleName attribute.
            assert comparison.desired_value('codebuild', {'property': 'IAM.ManagedPolicy.Roles', 'value': '[role](iam.md#iam-role)'}, 'IAM.ManagedPolicy')[0]['$attribute'] == 'RoleName'
            for field, expected in [('text', 'resolved'), ('number', '7')]:
                assert comparison.evaluate(name, {'Fn::Sub': ['${X}-${AWS::Region}-${!literal}',
                       {'X': {'Fn::FindInMap': ['Table', 'one', field]}}]}) == expected + '-ap-northeast-1-${literal}'
            expect_error(lambda: comparison.evaluate(name, {'Fn::Sub': ['${X}', {'X': {'Fn::ImportValue': 'unknown'}}]}), 'handoff')
            for region, partition in [('ap-northeast-1', 'aws'), ('cn-north-1', 'aws-cn'), ('us-gov-west-1', 'aws-us-gov'),
                                      ('us-iso-east-1', 'aws-iso'), ('eusc-de-east-1', 'aws-eusc'), ('ap-fake-1', None)]:
                candidate = Comparison(root, 'dev', '123456789012', ['cloudwatch-logs'])
                candidate.target['awsRegion'] = region
                candidate.stack(candidate.templates()[0][1])
                if partition is None:
                    expect_error(lambda: candidate.evaluate(name, {'Ref': 'AWS::Partition'}), 'pseudo parameter')
                else:
                    assert candidate.evaluate(name, {'Ref': 'AWS::Partition'}) == partition

        parameter = root / 'infra/cloudformation/parameters/dev/123456789012/stack-1.json'
        template_path = root / 'infra/cloudformation/templates/shared.yaml'
        original_parameters = parameter.read_text()
        definitions = template['Parameters']
        # Validate supplied values and Defaults with the same opt-in loader used by comparison.
        for kind, default, expected in [('String', 'abc', 'abc'), ('Number', '7', 7),
                                         ('Number', '9007199254740993', 9007199254740993),
                                         ('Number', '0.5', 0.5), ('CommaDelimitedList', 'a, b', ['a', 'b']),
                                         ('List<Number>', '1, 2.5', [1, 2.5])]:
            definitions['Extra'] = {'Type': kind, 'Default': default}
            mutate_template(root, template)
            assert load_template_inputs(template_path, parameter, strict_parameters=True)[1]['Extra'] == expected
        cases = [({'Type': 'String', 'Default': 'bad', 'AllowedValues': ['dev', 'stg']}, 'AllowedValues'),
                 ({'Type': 'String', 'Default': 'prefix-good-suffix', 'AllowedPattern': 'good'}, 'AllowedPattern'),
                 ({'Type': 'String', 'Default': 'a', 'MinLength': 2}, 'MinLength'),
                 ({'Type': 'String', 'Default': 'abcd', 'MaxLength': 3}, 'MaxLength'),
                 ({'Type': 'Number', 'Default': '1', 'MinValue': 2}, 'MinValue'),
                 ({'Type': 'Number', 'Default': '3', 'MaxValue': 2}, 'MaxValue'),
                 ({'Type': 'Number', 'Default': 'NaN'}, 'Number'),
                 ({'Type': 'Number', 'Default': True}, 'Number'),
                 ({'Type': 'String', 'Default': []}, 'String'),
                 ({'Type': 'String'}, 'required parameter'),
                 ({'Type': 'CommaDelimitedList', 'Default': 'a,bad', 'AllowedValues': ['a']}, 'AllowedValues'),
                 ({'Type': 'CommaDelimitedList', 'Default': 'a,1', 'AllowedPattern': '[a-z]+'}, 'AllowedPattern')]
        for definition, reason in cases:
            definitions['Extra'] = definition
            mutate_template(root, template)
            _, records = compare(root, ['cloudwatch-logs'])
            assert len(records) == 1 and records[0]['category'] == 'error' and reason in records[0]['reason'], records
        # Existing deploy/observed callers keep their permissive, string-valued behavior.
        assert load_template_inputs(template_path, parameter)[1]['Extra'] == 'a,1'
        definitions.pop('Extra')
        mutate_template(root, template)
        for text, reason in [('[]', 'required parameter'),
                             ('[{"ParameterKey":"Unknown","ParameterValue":"x"}]', 'undeclared'),
                             ('[{"ParameterKey":"Name","ParameterValue":7}]', 'explicit'),
                             ('[{"ParameterKey":"Name","ParameterValue":"a"},{"ParameterKey":"Name","ParameterValue":"b"}]', 'duplicate'),
                             ('[{"ParameterKey":"Name","ParameterValue":"a","ParameterValue":"b"}]', 'duplicate')]:
            write(parameter, text)
            _, records = compare(root, ['cloudwatch-logs'])
            assert len(records) == 1 and records[0]['category'] == 'error' and reason in records[0]['reason'], records
        write(parameter, original_parameters)

        # A unique usable legacy candidate cannot establish uniqueness with unread/malformed/ambiguous inputs.
        modelpath = root / 'model/dev/123456789012/cloudwatch-logs.properties'
        modeltext = modelpath.read_text()
        write(modelpath, modeltext.replace('desired.resource.001.cfn-logicalId=' + name + '-Log\n', '').replace('logicalId=Log1', 'logicalId=Log'))
        stackpath = root / 'model/dev/123456789012/cloudformation-stacks.properties'
        stacktext = stackpath.read_text()
        write(stackpath, stacktext + 'desired.stack.002.name=second-stack\ndesired.stack.002.template=second.yaml\ndesired.stack.002.parameters=second.json\ndesired.stack.002.deployOrder=2\ndisplay.stack.002.comment=候補\n')
        second_template = template_path.with_name('second.yaml')
        second_parameter = parameter.with_name('second.json')
        for available in ['none', 'template', 'both']:
            if available != 'none':
                write(second_template, 'Resources: {}\n')
            if available == 'both':
                write(second_parameter, '[]\n')
            candidate, records = compare(root, ['cloudwatch-logs'])
            if available == 'both':
                assert all(item['category'] == 'matched' for item in records), records
            else:
                assert len(records) == 1 and records[0]['category'] == 'uncompared' and 'input missing' in records[0]['reason'], records
                assert candidate.metrics['template_decodes'] == 1
        write(second_template, 'Resources: {Unknown: {Type: "AWS::Logs::LogGroup"}}\n')
        _, records = compare(root, ['cloudwatch-logs'])
        assert len(records) == 1 and records[0]['category'] == 'uncompared' and 'incomplete legacy' in records[0]['reason'], records
        write(second_template, 'Resources: [\n')
        _, records = compare(root, ['cloudwatch-logs'])
        assert len(records) == 1 and records[0]['category'] == 'error', records
        # Explicit IDs do not read unrelated candidate stacks; missing explicit CREATE still differs.
        write(modelpath, modeltext)
        _, records = compare(root, ['cloudwatch-logs'])
        assert all(item['category'] == 'matched' for item in records), records
        template_path.unlink()
        _, records = compare(root, ['cloudwatch-logs'])
        assert len(records) == 1 and records[0]['category'] == 'difference' and 'CREATE未実装' in records[0]['reason'], records


def local_reference_cases():
    from cloudformation_inputs import Blocked
    with tempfile.TemporaryDirectory(prefix='local-references-') as directory:
        root = Path(directory) / 'project'
        _, template = fixture(root, stacks=2, services=['s3'])
        consumer, producer = 'cfn-stack-app-dev-data1', 'cfn-stack-app-dev-data2'
        template['Outputs'] = {'BucketArn': {'Value': {'Fn::GetAtt': ['Bucket', 'Arn']},
                                          'Export': {'Name': {'Fn::Sub': '${Name}-BucketArn'}}}}
        mutate_template(root, template)
        def candidate():
            comparison, _ = compare(root, ['s3'])
            return comparison
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison = candidate()
            assert comparison.evaluate(consumer, {'Fn::Sub': '${Bucket}/*'}) == 'bucket-app-dev-data1/*'
            assert comparison.evaluate(producer, {'Fn::Sub': '${Bucket}'}) == 'bucket-app-dev-data2'
            assert comparison.evaluate(consumer, {'Fn::Sub': ['${Bucket}-${Name}-${AWS::Region}-${!Bucket}',
                   {'Bucket': 'override', 'Name': 'mapped', 'AWS::Region': 'override-region'}]}) == 'override-mapped-override-region-${Bucket}'
            assert comparison.evaluate(consumer, {'Fn::Sub': ['${X}', {'X': {'Ref': 'Bucket'}}]}) == 'bucket-app-dev-data1'
            for value in ({'Fn::Sub': '${Missing}'},
                          {'Fn::Sub': ['${X}', {'X': ['not', 'a string']}]}):
                try:
                    comparison.evaluate(consumer, value)
                except Blocked:
                    pass
                else:
                    raise AssertionError('unproven Sub must be blocked')
            imported = {'Fn::ImportValue': {'Fn::Join': ['', ['app-dev-data2', '-BucketArn']]}}
            assert comparison.evaluate(consumer, imported) == {'$resource': ['s3', '002'], '$attribute': 'Arn'}
            expect_error(lambda: comparison.evaluate(consumer, {'Fn::ImportValue': 'missing'}), 'matches=0')
            # Generated identifiers remain symbolic; missing and ambiguous ownership never infer a value.
            document = comparison.stack_inputs[producer][0]
            document['Resources']['Bucket']['Condition'] = 'Inactive'
            document['Conditions']['Inactive'] = {'Fn::Equals': ['yes', 'no']}
            comparison.symbols.clear()
            expect_error(lambda: comparison.evaluate(consumer, imported), 'inactive')
            mutate_template(root, template)
            template['Outputs']['Duplicate'] = dict(template['Outputs']['BucketArn'])
            mutate_template(root, template)
            expect_error(lambda: candidate().evaluate(consumer, imported), 'matches=2')
            del template['Outputs']['Duplicate']
            template['Conditions']['Inactive'] = {'Fn::Equals': ['yes', 'no']}
            template['Outputs']['BucketArn']['Condition'] = 'Inactive'
            mutate_template(root, template)
            expect_error(lambda: candidate().evaluate(consumer, imported), 'matches=0')
            del template['Outputs']['BucketArn']['Condition']
            template['Resources']['Bucket']['Properties']['BucketName'] = {'Fn::Sub': '${Bucket}'}
            mutate_template(root, template)
            expect_error(lambda: candidate().evaluate(consumer, {'Fn::Sub': '${Bucket}'}), 'cyclic')
            template['Resources']['Bucket']['Properties']['BucketName'] = {'Ref': 'Bucket'}
            mutate_template(root, template)
            expect_error(lambda: candidate().evaluate(consumer, {'Fn::Sub': '${Bucket}'}), 'cyclic')
            template['Resources']['Bucket']['Properties']['BucketName'] = {'Fn::Sub': 'bucket-${Name}'}
            # Cross-stack import cycles also remain uncompared.
            template['Outputs']['BucketArn']['Value'] = {'Fn::ImportValue': {'Fn::If': ['First', 'app-dev-data2-BucketArn', 'app-dev-data1-BucketArn']}}
            template['Conditions']['First'] = {'Fn::Equals': [{'Ref': 'Name'}, 'app-dev-data1']}
            mutate_template(root, template)
            expect_error(lambda: candidate().evaluate(consumer, imported), 'cyclic')
            template['Outputs']['BucketArn']['Value'] = {'Fn::GetAtt': ['Bucket', 'Arn']}
            template['Outputs']['BucketArn']['Export']['Name'] = {'Fn::Sub': '${Bucket}'}
            mutate_template(root, template)
            expect_error(lambda: candidate().evaluate(consumer, imported), 'resource/import')
            template['Outputs']['BucketArn']['Export']['Name'] = {'Fn::Sub': '${Name}-BucketArn'}
            mutate_template(root, template)
            # Duplicate correspondence blocks even an otherwise evaluable export.
            model = root / 'model/dev/123456789012/s3.properties'
            original = model.read_text(encoding='utf-8')
            write(model, original + 'desired.resource.003.resourceType=S3.Bucket\ndesired.resource.003.cfn-logicalId=' + producer + '-Bucket\n')
            expect_error(lambda: candidate().evaluate(consumer, imported), 'correspondence')
            write(model, original)
            comparison = candidate()
            policy = {'Statement': [{'Condition': {'Bool': {'aws:SecureTransport': 'false'}},
                                     'Resource': {'Fn::GetAtt': ['AppKey', 'Arn']}}]}
            row = {'property': 'S3.BucketPolicy.PolicyDocument', 'value': 'policy.json', 'document': json.dumps(policy)}
            expect_error(lambda: comparison.desired_value('s3', row, 'S3.BucketPolicy'), 'AppKey')
            del policy['Statement'][0]['Resource']
            assert comparison.desired_value('s3', dict(row, document=json.dumps(policy)), 'S3.BucketPolicy') == policy
            # Shared deploy repair callers never run Comparison.run(): retain their original behavior.
            deploy = Comparison(root, 'dev', '123456789012', ['s3'])
            deploy.stack(deploy.templates()[0][1])
            expect_error(lambda: deploy.evaluate(consumer, {'Fn::Sub': '${Bucket}'}), 'variable')
            expect_error(lambda: deploy.evaluate(consumer, imported), 'handoff')
            assert deploy.desired_value('s3', row, 'S3.BucketPolicy')['Statement'][0]['Resource'] == {'Fn::GetAtt': ['AppKey', 'Arn']}
            # A missing declared stack prevents proof of export uniqueness.
            (root / 'infra/cloudformation/parameters/dev/123456789012/stack-2.json').unlink()
            expect_error(lambda: candidate().evaluate(consumer, imported), 'search incomplete')



@patch('socket.socket', side_effect=AssertionError('network forbidden'))
def symbolic_string_cases(_network):
    from issues_iac import Expression
    with tempfile.TemporaryDirectory(prefix='symbolic-strings-') as directory:
        root = Path(directory) / 'project'
        _, template = fixture(root, stacks=2, services=['cloudwatch-logs'])
        comparison, _ = compare(root, ['cloudwatch-logs'])
        name, other = 'cfn-stack-app-dev-data1', 'cfn-stack-app-dev-data2'
        ref = {'Fn::GetAtt': ['Log', 'Arn']}
        split = {'Fn::Split': [':*', ref]}
        select = {'Fn::Select': [0, split]}
        joined = {'Fn::Join': ['', [select, ':log-stream:account_*']]}
        symbol = comparison.evaluate(name, ref)
        # Preserve resource identity, attributes and every operation without ARN retrieval.
        result = comparison.evaluate(name, select)
        assert same(result, Expression('Select', [0, Expression('Split', [':*', symbol])]))
        assert not same(symbol, dict(symbol))
        assert same(result, comparison.evaluate(name, {'Fn::Select': ['0', split]}))
        assert not same(result, comparison.evaluate(other, select))
        assert same(comparison.evaluate(name, joined), comparison.evaluate(name, joined))
        assert comparison.evaluate(name, {'Fn::Split': [',', 'a,,b,']}) == ['a', '', 'b', '']
        assert comparison.evaluate(name, {'Fn::Select': [0, {'Fn::Split': [':*', 'literal:*']}]}) == 'literal'
        for value in ({'Fn::Split': [',', 42]}, {'Fn::Split': [1, 'text']},
                      {'Fn::Split': [',']}, {'Fn::Split': ['', 'text']}):
            try:
                comparison.evaluate(name, value)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid Split must remain error')
        resource = comparison.resources['cloudwatch-logs']['001']
        prop = 'LogGroupName'
        def category(actual, desired):
            comparison.results = []
            with patch.object(comparison, 'desired_value', return_value=desired):
                comparison.compare_rows('cloudwatch-logs', '001', resource, name, 'Log',
                    root / 'infra/cloudformation/templates/shared.yaml',
                    {'Properties': {prop: actual}}, template)
            records = [record for record in comparison.results if record['property'].endswith('.' + prop)]
            assert len(records) == 1, records
            return records[0]['category']
        # Inject already bound desired expressions, never grant raw model intrinsics a binding.
        assert category(joined, comparison.evaluate(name, joined)) == 'matched'
        assert category(joined, comparison.evaluate(other, joined)) == 'uncompared'
        assert category(select, result) == 'matched'
        assert category(select, symbol) == 'uncompared'
        assert category('literal', 'literal') == 'matched'
        assert category({'Fn::Join': ['-', ['a', 'b']]}, 'a:b') == 'difference'
        assert category({'Fn::Split': [',', 42]}, []) == 'error'
        assert category({'Fn::Split': [':*', dict(symbol)]}, result) == 'error'
        assert category({'Fn::Join': ['', [dict(symbol), ':log-stream:account_*']]}, comparison.evaluate(name, joined)) == 'error'
        assert category({'Fn::Split': [',', {'Fn::GetAtt': ['Missing', 'Arn']}]}, []) == 'uncompared'
        assert category({'Fn::Select': [1, split]}, result) == 'uncompared'
        changed = {'Fn::Join': [':', [select, 'different']]}
        assert category(changed, comparison.evaluate(name, joined)) == 'uncompared'
        sub = {'Fn::Sub': ['${Arn}:log-stream:${Suffix}-${!literal}', {'Arn': select, 'Suffix': 'account_*'}]}
        assert category(sub, comparison.evaluate(name, sub)) == 'matched'
        assert not same(comparison.evaluate(name, sub), comparison.evaluate(other, sub))
        assert category({'Fn::Join': ['', [select, 42]]}, result) == 'error'
        assert category({'Fn::Select': [True, split]}, result) == 'error'
        assert category({'Fn::Select': [-1, split]}, result) == 'error'
        assert category({'Fn::Select': [ref, split]}, result) == 'uncompared'
        assert not same(result, comparison.evaluate(name, {'Fn::Select': [0, {'Fn::Split': [',', ref]}]}))
        assert same({'Resource': [result, result]}, {'Resource': [result, result]})
        assert not selected_same({'Resource': [result, result]}, {'Resource': [result]})
        assert not selected_same({'Resource': [result]}, {'Resource': [comparison.evaluate(other, select)]})
        assert category({'Fn::Select': [1, ['only']]}, 'only') == 'error'
        assert category({'Fn::Split': [{'Ref': 'Name'}, 'text']}, []) == 'error'
        assert not same(comparison.evaluate(name, joined), json.loads(json.dumps(comparison.redacted(comparison.evaluate(name, joined)))))
        assert comparison.evaluate(name, {'Fn::Sub': '${Log.Arn}'}) == symbol
        assert not same(comparison.evaluate(name, {'Fn::Join': ['', [{'Ref': 'Log'}, '/*']]}),
                        comparison.evaluate(name, {'Fn::Join': ['', [ref, '/*']]}))
        # Real model→Policy comparison: links bind identities, raw template refs do not.
        policy = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': 'logs:PutLogEvents', 'Resource': joined}]}
        template['Resources']['Policy'] = {'Type': 'AWS::IAM::ManagedPolicy', 'Properties': {'PolicyDocument': policy}}
        mutate_template(root, template)
        def publish(desired):
            model = {'desired.service.iam.serviceId': 'iam', 'desired.resource.001.resourceType': 'IAM.ManagedPolicy',
                     'desired.resource.001.cfn-logicalId': name + '-Policy',
                     'desired.row.001-001.property': 'IAM.ManagedPolicy.PolicyDocument',
                     'desired.row.001-001.value': 'policy.json', 'desired.row.001-001.document': json.dumps(desired)}
            write(root / 'model/dev/123456789012/iam.properties', '\n'.join(f'{key}={value}' for key, value in model.items()) + '\n')
            _, records = compare(root, ['iam'])
            assert len(records) == 1, records
            return records[0]['category']
        link = '[PENDING_DEPLOY](cloudwatch-logs.md#cloudwatch-logs-cwlogs-app-dev-data1)'
        model_join = {'Fn::Join': ['', [{'Fn::Select': [0, {'Fn::Split': [':*', link]}]}, ':log-stream:account_*']]}
        def desired_policy(expression):
            return dict(policy, Statement=[dict(policy['Statement'][0], Resource=expression)])
        assert publish(desired_policy(model_join)) == 'matched'
        model_sub = {'Fn::Sub': ['${Arn}:log-stream:account_*', {'Arn': {'Fn::Select': [0, {'Fn::Split': [':*', link]}]}}]}
        # Different equivalent syntaxes remain conservative until a rewrite is proven.
        assert publish(desired_policy(model_sub)) == 'uncompared'
        template['Resources']['Policy']['Properties']['PolicyDocument'] = desired_policy(
            {'Fn::Sub': ['${Arn}:log-stream:account_*', {'Arn': select}]})
        mutate_template(root, template)
        assert publish(desired_policy(model_sub)) == 'matched'
        assert publish(desired_policy({'Fn::Sub': '${Log.Arn}'})) == 'uncompared'
        assert publish(desired_policy(joined)) == 'uncompared'
        different_link = link.replace('data1', 'data2')
        assert publish(desired_policy({'Fn::Sub': ['${Arn}:log-stream:account_*',
            {'Arn': {'Fn::Select': [0, {'Fn::Split': [':*', different_link]}]}}]})) == 'uncompared'
    print('Symbolic string evaluation: PASS (GetAtt/Split/Select/Join/Sub, typed equality and classifications)')


def reference_identity_report_cases():
    from issues_iac import Expression
    from issues_reports import iac_key, iac_actions
    with tempfile.TemporaryDirectory(prefix='reference-identity-') as directory:
        root = Path(directory)
        _, template = fixture(root, stacks=2, services=['cloudwatch-logs', 's3'])
        consumer, producer = 'cfn-stack-app-dev-data1', 'cfn-stack-app-dev-data2'
        kms = {'desired.service.kms.serviceId': 'kms'}
        for identity, logical, kind in [('001', 'Key', 'KMS.Key'), ('002', 'OtherKey', 'KMS.Key'), ('003', 'Alias', 'KMS.Alias')]:
            kms.update({f'desired.resource.{identity}.resourceType': kind,
                        f'desired.resource.{identity}.cfn-logicalId': producer + '-' + logical,
                        f'desired.resource.{identity}.anchor': logical.lower()})
            template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
        template['Resources']['Alias']['Properties'] = {'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}}
        write(root / 'model/dev/123456789012/kms.properties', '\n'.join(f'{k}={v}' for k, v in kms.items()) + '\n')
        logmodel = root / 'model/dev/123456789012/cloudwatch-logs.properties'
        original = logmodel.read_text()
        link = '[key](kms.md#key)'
        write(logmodel, original + 'desired.row.001-010.property=Logs.LogGroup.KmsKeyId\ndesired.row.001-010.value=' + link + '\n')
        template['Outputs'] = {'KeyArn': {'Value': {'Fn::GetAtt': ['Key', 'Arn']}, 'Export': {'Name': {'Fn::Sub': '${Name}-KeyArn'}}}}
        template['Outputs']['OtherKeyArn'] = {'Value': {'Fn::GetAtt': ['OtherKey', 'Arn']}, 'Export': {'Name': {'Fn::Sub': '${Name}-OtherKeyArn'}}}
        template['Outputs']['KeyId'] = {'Value': {'Ref': 'Key'}, 'Export': {'Name': {'Fn::Sub': '${Name}-KeyId'}}}
        template['Resources']['Log']['Properties']['KmsKeyId'] = {'Fn::ImportValue': {'Fn::Join': ['', ['app-dev-data2', '-KeyArn']]}}
        mutate_template(root, template)
        def kms_result():
            comparison, records = compare(root, ['cloudwatch-logs'])
            return comparison, next(i for i in records if i['resource'] == '001' and i['property'] == 'Logs.LogGroup.KmsKeyId')
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, record = kms_result()
            assert record['category'] == 'matched', record
            keyid = comparison.reference('cloudwatch-logs', link)
            arn = comparison.evaluate(producer, {'Fn::GetAtt': ['Key', 'Arn']})
            assert keyid['$attribute'] == 'KeyId' and arn['$attribute'] == 'Arn'
            callback = lambda l, r, path: comparison.reference_same(l, r, 'KMS.Alias', path)
            assert same(keyid, arn, reference=callback, path='TargetKeyId') is True
            assert same(keyid, arn) is False  # Attributes are never globally collapsed.
            assert comparison.reference_same(keyid, arn, 'Logs.LogGroup', 'KmsKeyId') is False
            assert comparison.reference_same(keyid, arn, 'SQS.Queue', 'KmsMasterKeyId') is None
            assert same(keyid, dict(keyid)) is False  # JSON-shaped values cannot forge evidence.
            alias = comparison.reference('cloudwatch-logs', '[alias](kms.md#alias)')
            assert comparison.reference_same(alias, arn, 'S3.Bucket', 'BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID') is False
            template['Resources']['Log']['Properties']['KmsKeyId'] = {'Fn::ImportValue': 'app-dev-data2-OtherKeyArn'}
            mutate_template(root, template)
            assert kms_result()[1]['category'] == 'difference'
            template['Resources']['Log']['Properties']['KmsKeyId'] = {'Fn::ImportValue': 'app-dev-data2-KeyId'}
            mutate_template(root, template)
            assert kms_result()[1]['category'] == 'difference'  # Same key, invalid ARN form.
            template['Resources']['Log']['Properties']['KmsKeyId'] = 'unknown-key-arn'
            mutate_template(root, template)
            assert kms_result()[1]['category'] == 'uncompared'
            template['Resources']['Log']['Properties']['KmsKeyId'] = {'Fn::ImportValue': 'missing-export'}
            mutate_template(root, template)
            comparison, record = kms_result()
            assert record['category'] == 'uncompared' and record['cause']['export'] == 'missing-export'
            # A true nested difference wins even when another leaf cannot be proven.
            assert same({'key': keyid, 'flag': True}, {'key': 'unknown', 'flag': False}, reference=callback) is False
            assert same({'key': keyid, 'flag': True}, {'key': 'unknown', 'flag': True}, reference=callback) is None
            expression = Expression('Sub', ['${X}', {'X': arn}])
            assert same({'key': expression, 'flag': True}, {'key': 'unknown', 'flag': False}, reference=callback) is False
            assert same({'key': expression, 'flag': True}, {'key': 'unknown', 'flag': True}, reference=callback) is None
            fields = value_differences({'key': expression, 'flag': True}, {'key': 'unknown', 'flag': False},
                                      'KMS.Alias.Config', exact=True, reference=callback)
            assert fields == [{'path': 'flag', 'model': 'true', 'iac': 'false'}]
            # An unrelated missing DataZone template never discards a healthy export.
            stacks = root / 'model/dev/123456789012/cloudformation-stacks.properties'
            write(stacks, stacks.read_text() + 'desired.stack.003.name=datazone-stack\ndesired.stack.003.template=datazone.yaml\ndesired.stack.003.parameters=datazone.json\ndesired.stack.003.deployOrder=1\n')
            datazone = {'desired.service.datazone.serviceId': 'datazone', 'desired.resource.001.resourceType': 'DataZone.Domain',
                        'desired.resource.001.cfn-logicalId': 'datazone-stack-Domain'}
            write(root / 'model/dev/123456789012/datazone.properties', '\n'.join(f'{k}={v}' for k, v in datazone.items()) + '\n')
            template['Resources']['Log']['Properties']['KmsKeyId'] = {'Fn::ImportValue': 'app-dev-data2-KeyArn'}
            mutate_template(root, template)
            comparison, records = compare(root, ['cloudwatch-logs', 'datazone'])
            assert any(i['property'] == 'Logs.LogGroup.KmsKeyId' and i['resource'] == '001' and i['category'] == 'matched' for i in records)
            assert any(i['service'] == 'datazone' and i['category'] == 'difference' and i['cause']['relationship'] == 'direct' for i in records)
            cached = comparison.metrics.copy()
            with patch.object(comparison, 'templates', side_effect=AssertionError('repeat stack scan')):
                for _ in range(3):
                    assert comparison.evaluate(consumer, {'Fn::ImportValue': 'app-dev-data2-KeyArn'}) == comparison.reference('cloudwatch-logs', link, 'Arn')
                    expect_error(lambda: comparison.evaluate(consumer, {'Fn::ImportValue': 'missing-export'}), 'search incomplete')
            assert comparison.metrics == cached and len(comparison.export_failures) == 1
            # A bad output is isolated from healthy outputs in that same stack.
            template['Outputs']['Broken'] = {'Value': 'x', 'Export': {'Name': {'Ref': 'Key'}}}
            mutate_template(root, template)
            assert kms_result()[1]['category'] == 'matched'
        # Partial revalidation preserves true differences; proven matches retire only their own Issue.
        path = root / 'issues/dev/123456789012/iac-issues.md'
        difference = dict(category='difference', service='cloudwatch-logs', resource='001', property='Logs.LogGroup.KmsKeyId',
                          stack=consumer, reason='value mismatch', iac={'path': 'infra/cloudformation/templates/shared.yaml'}, desired='a', actual='b')
        other = dict(difference, property='Logs.LogGroup.RetentionInDays', desired=7, actual=14)
        write_report(path, *iac_merge(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [difference, other]))
        uncertain = dict(difference, category='uncompared', reason='reference unproven')
        report, state = iac_merge(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [uncertain, other])
        retained = iac_state(report, 'dev', '123456789012', data=state)[0]
        assert any(e['retained'] and e['id'] == iac_key(difference) and e['record']['category'] == 'difference' for e in retained)
        assert any(not e['retained'] and e['id'] == iac_key(other) and e['record']['category'] == 'difference' for e in retained)
        matched = dict(difference, category='matched', reason='reference expression equivalent')
        report, state = iac_merge(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [matched, other])
        resolved = iac_state(report, 'dev', '123456789012', data=state)[0]
        assert not any(e['record']['category'] == 'difference' and e['id'] == iac_key(difference) for e in resolved)
        assert '参照表現差分（意味的同一性を確認済み）: 1件' in report
        write_report(path, report, state)
        assert iac_state(path.read_text(), 'dev', '123456789012', data=json.loads(path.with_name('iac-issues.state.json').read_text()))[0] == resolved
        # Older comparison errors omitted stack identity; a unique proof for the
        # same Model resource/property also clears those legacy unresolved records.
        legacy_pending = dict(difference, category='uncompared', stack=None, reason='ImportValue handoff search incomplete')
        write_report(path, *iac_merge(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [legacy_pending, other]))
        report, state = iac_merge(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [matched, other])
        entries = iac_state(report, 'dev', '123456789012', data=state)[0]
        assert not any(e['retained'] and e['id'] == iac_key(legacy_pending) for e in entries)
        # Conflicting incomplete evidence cannot retire an earlier true difference.
        report, state = iac_merge(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [matched, uncertain, other])
        assert any(e['retained'] and e['id'] == iac_key(legacy_pending) for e in iac_state(report, 'dev', '123456789012', data=state)[0])
        # One unresolved import shared by many consumers is one investigation, not many repairs.
        pending = [dict(uncertain, resource=str(i), cause={'kind': 'import-unresolved', 'export': 'missing-export', 'relationship': 'import'}) for i in range(40)]
        entries = [{'id': iac_key(i), 'record': i, 'retained': False} for i in pending]
        groups = iac_actions(entries, 'dev', '123456789012')
        assert len(groups) == 1 and groups[0]['classification'] == '比較未完了' and groups[0]['status'] == '要調査'
        assert '修正要否は未確定' in groups[0]['remedy']
        missing = dict(pending[0], cause={'kind': 'template-missing', 'path': 'datazone.yaml', 'relationship': 'export-search-incomplete'})
        group = iac_actions([{'id': iac_key(missing), 'record': missing, 'retained': False}], 'dev', '123456789012')[0]
        assert group['classification'] == '比較未完了' and group['status'] == '要調査'
    print('Reference identity/report regressions: PASS (KMS forms/identity, isolated cached exports, partial retention/resolution)')


def concurrency(root):
    # Same-worktree report writes wait for file acquisition, then merge latest contents.
    from task_contract import refresh, complete, reservations, contracts, status
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
        entries = reservations(root, contracts(root))
        assert report in entries[names[0]].active and report in entries[names[1]].deferred
        first = subprocess.run(commands[0], capture_output=True, text=True, timeout=30)
        assert first.returncode == 0, first.stderr
        # Exercise the actual CLI worker with a test clock. It releases the owner
        # on retry 3; the same save invocation must acquire and publish automatically.
        driver = """
import runpy, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.argv = sys.argv[2:]
import task_contract as tasks
root = Path(sys.argv[sys.argv.index('--repository-root') + 1])
count = 0
def sleep(seconds):
    global count
    assert seconds == 30
    count += 1
    if count == 3:
        tasks.complete(root, 'tasks/parallel-s3.md')
    assert count <= 3
tasks.time.sleep = sleep
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        result = subprocess.run([sys.executable, '-B', '-c', driver,
                                 str(ROOT / 'framework/scripts'), *commands[1][2:]],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert 'Acquired deferred reservation' in result.stdout, result.stdout
        assert status((root / names[1]).read_text()) == 'running'
        assert not reservations(root, contracts(root))[names[1]].deferred
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
        texts.extend(file.read_text() for file in sorted({path, *model_parts(path)}))
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
    original_properties, original_model_read = __import__('model_design').properties, __import__('model_files').read_model
    if variant in 'AB':
        modules = []
        for name in ('model_design', 'model_files'):
            spec = importlib.util.spec_from_file_location('baseline_' + name, root / 'framework/scripts' / (name + '.py'))
            loaded = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded)
            modules.append(loaded)
        original_parse = modules[0].properties
        __import__('model_files').read_model = modules[1].read_model
    else:
        original_parse = __import__('model_design')._parse_properties
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
import model_design
counts=Counter(); old_read=Path.read_text; old_bytes=Path.read_bytes; parse_name='_parse_properties' if hasattr(model_design,'_parse_properties') else 'properties'; old_parse=getattr(model_design,parse_name)
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
Path.read_text=read; Path.read_bytes=read_bytes; setattr(model_design,parse_name,parse)
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
    with patch.object(Path, 'read_text', read), patch.object(Path, 'read_bytes', read_bytes), patch('model_design.properties' if variant in 'AB' else 'model_design._parse_properties', parse), patch.object(subprocess, 'run', run):
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
                    (report.parent / 'iac-issues.state.json').unlink(missing_ok=True)
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


def action_report_cases():
    from issues_reports import iac_key, iac_state, iac_actions
    with tempfile.TemporaryDirectory(prefix='iac-actions-') as directory:
        root = Path(directory)
        path = root / 'issues/dev/cde/iac-issues.md'
        missing = 'infra/cloudformation/templates/cde/datazone.yaml'
        direct = [dict(category='difference', service='datazone', resource=f'{i:03d}', property='*',
                       reason='モデルに対応するtemplateが存在しない（CREATE未実装）', stack='datazone-stack',
                       iac={'path': missing}, model=None,
                       cause={'kind': 'template-missing', 'path': missing, 'stack': 'datazone-stack', 'relationship': 'direct'})
                  for i in range(6)]
        cascade = [dict(category='uncompared', service=['athena', 's3', 'iam'][i % 3], resource=f'{i:04d}',
                        property='Setting', reason='ImportValue handoff search incomplete: stack input missing: ' + missing,
                        stack=None, model=None, iac={'path': f'infra/cloudformation/templates/cde/consumer-{i % 3}.yaml'},
                        cause={'kind': 'template-missing', 'path': missing, 'stack': 'datazone-stack',
                               'consumer_stack': f'consumer-{i % 3}', 'relationship': 'export-search-incomplete'})
                   for i in range(1236)]
        # Trace the real failure path: only exception provenance may join the cascade.
        fixture_root = root / 'comparison'
        _, template = fixture(fixture_root, stacks=2, services=['s3'])
        stack_model_path = fixture_root / 'model/dev/123456789012/cloudformation-stacks.properties'
        write(stack_model_path, stack_model_path.read_text().replace('desired.stack.002.template=shared.yaml', 'desired.stack.002.template=datazone.yaml'))
        template['Resources']['Bucket']['Properties']['BucketName'] = {'Fn::ImportValue': 'export-unknown'}
        mutate_template(fixture_root, template)
        _, traced = compare(fixture_root, ['s3'])
        missing_record = next(item for item in traced if item['category'] == 'difference' and item.get('cause'))
        cascade_record = next(item for item in traced if item['category'] == 'uncompared' and item.get('cause'))
        assert cascade_record['cause']['relationship'] == 'export-search-incomplete'
        assert missing_record['cause']['path'] == cascade_record['cause']['path']
        assert cascade_record['stack'] is None  # Legacy diagnostic identity is unchanged.
        assert cascade_record['reason'] == 'ImportValue handoff search incomplete: stack input missing: infra/cloudformation/templates/datazone.yaml'
        traced_entries = [{'id': iac_key(item), 'record': item, 'retained': False} for item in traced]
        joined = [group for group in iac_actions(traced_entries, 'dev', '123456789012') if group['target'] == cascade_record['cause']['path']]
        assert len(joined) == 1 and len(joined[0]['members']) == 2
        from cloudformation_inputs import Blocked
        legacy_comparison = Comparison(fixture_root, 'dev', '123456789012', ['s3'])
        legacy_comparison.resources['s3']['001'].pop('cfn-logicalId')
        # One known missing candidate input proves a comparison cascade.
        legacy_results = legacy_comparison.run()
        legacy_record = next(item for item in legacy_results if item['resource'] == '001')
        assert legacy_record['cause']['relationship'] == 'legacy-search-incomplete'
        assert legacy_record['cause']['path'] == missing_record['cause']['path']
        # A second unknown failure (or a different missing path) prevents a single-cause claim.
        for second_error in (Blocked('unknown failure'), Blocked('another input missing')):
            if str(second_error).startswith('another'):
                second_error.iac_cause = {'kind': 'template-missing', 'path': 'another.yaml', 'relationship': 'stack-input'}
            ambiguous = Comparison(fixture_root, 'dev', '123456789012', ['s3'])
            ambiguous.resources['s3']['001'].pop('cfn-logicalId')
            missing_error = Blocked('stack input missing')
            missing_error.iac_cause = dict(missing_record['cause'])
            def fail_stack(unit):
                raise missing_error if unit['name'].endswith('data1') else second_error
            with patch.object(ambiguous, 'stack', side_effect=fail_stack):
                ambiguous_results = ambiguous.run()
            assert not next(item for item in ambiguous_results if item['resource'] == '001').get('cause')
        records = direct + cascade
        original = json.loads(json.dumps(records))
        services = ['datazone', 'athena', 's3', 'iam']
        report, report_state = iac_merge(root, path, 'dev', 'cde', services, records)
        entries, notes = iac_state(report, 'dev', 'cde', data=report_state)
        groups = iac_actions(entries, 'dev', 'cde')
        assert len(groups) == 1 and len(groups[0]['members']) == 1242
        assert '- 独立Issue数: 1\n' in report and '直接差分 6リソース' in report
        assert 'iac-report-data' not in report and len(json.dumps(report_state)) > len(report) * 10
        assert '未比較 1236件' in report and '未比較 1236項目' in report
        assert '直接Import依存は未確定' in report and 'model=null; IaC=null' not in report
        assert Counter(json.dumps(entry['record'], sort_keys=True) for entry in entries) == Counter(json.dumps(item, sort_keys=True) for item in records)
        assert records == original and not notes
        assert Counter(item['category'] for item in records) == Counter(entry['record']['category'] for entry in entries)
        assert {entry['id'] for entry in entries} == {iac_key(item) for item in records}
        # Timestamp is the only input-independent rendering change.
        reversed_report, reversed_report_state = iac_merge(root, path, 'dev', 'cde', services[::-1], records[::-1])
        assert re.sub(r'更新日時:.*', '', report) == re.sub(r'更新日時:.*', '', reversed_report)
        assert groups[0]['id'] != iac_actions(entries, 'stg', 'cde')[0]['id']
        # Identical prose cannot prove the same cause; different repair paths stay separate.
        other = dict(cascade[0], resource='other', cause=dict(cascade[0]['cause'], path='infra/cloudformation/templates/cde/other.yaml'))
        unknown = dict(cascade[0], resource='unknown')
        unknown.pop('cause')
        parameter = dict(cascade[1], resource='parameter', cause=dict(cascade[1]['cause'], kind='parameters-missing'))
        extra = [other, unknown, parameter, dict(unknown, resource='unknown2')]
        separated = read_iac(iac_merge(root, path, 'dev', 'cde', services, records + extra), 'dev', 'cde')[0]
        assert len(iac_actions(separated, 'dev', 'cde')) == 5
        # Value differences never merge different stacks/resources/properties/targets/actions.
        difference = dict(category='difference', service='s3', resource='001', property='S3.Bucket.BucketName',
                          stack='stack1', iac={'path': 'infra/cloudformation/templates/cde/shared.yaml'},
                          reason='value mismatch', desired='a', actual='b')
        differences = [difference, dict(difference, stack='stack2'), dict(difference, resource='002'),
                       dict(difference, property='S3.Bucket.Tags'), dict(difference, reason='property missing'),
                       dict(difference, iac={'path': 'infra/cloudformation/templates/cde/other.yaml'})]
        diff_report, diff_report_state = iac_merge(root, path, 'dev', 'cde', ['s3'], differences)
        assert 'IaC側の候補。Model側も根拠から確認して決める' in diff_report
        diff_entries = iac_state(diff_report, 'dev', 'cde', data=diff_report_state)[0]
        assert len(iac_actions(diff_entries, 'dev', 'cde')) == 6
        write_report(path, report, report_state)
        # Scoped saves keep other services; metadata joins still point to every diagnostic.
        partial, partial_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [item for item in cascade if item['service'] == 's3'])
        partial_entries = iac_state(partial, 'dev', 'cde', data=partial_state)[0]
        assert len(partial_entries) == len(records) and len(iac_actions(partial_entries, 'dev', 'cde')) == 1
        assert not issue_errors(root, {('dev', 'cde', service) for service in services})
        uncertain = dict(direct[0], category='uncompared', reason='unknown resolution')
        uncertain.pop('cause')
        second, second_state = iac_merge(root, path, 'dev', 'cde', services, [uncertain])
        write_report(path, second, second_state)
        third, third_state = iac_merge(root, path, 'dev', 'cde', services, [uncertain])
        second_entries = iac_state(second, 'dev', 'cde', data=second_state)[0]
        third_entries = iac_state(third, 'dev', 'cde', data=third_state)[0]
        assert second_entries == third_entries
        assert sum(entry['retained'] for entry in third_entries) == len(records)
        write_report(path, third, third_state)
        matched = dict(direct[0], category='matched')
        preserved = read_iac(iac_merge(root, path, 'dev', 'cde', services, [matched]), 'dev', 'cde')[0]
        # Explicit matched evidence retires this old Issue; absence still retains all others.
        assert not any(entry['id'] == iac_key(direct[0]) and entry['record']['category'] == 'difference' for entry in preserved)
        assert any(entry['retained'] and entry['id'] == iac_key(direct[1]) for entry in preserved)
        # Migrate legacy IDs/content/prose verbatim, conservatively without causal guessing.
        legacy_item = f'差分: 001 / S3.Bucket.BucketName / stack1: value mismatch; model="a"; IaC="b" <!-- iac-id: {iac_key(difference)} -->'
        legacy = '# model → IaC比較の非阻害結果\n\nhuman確認: 旧例外\n\n### s3\n\n<!-- issue-service: s3 -->\n\n1. ' + legacy_item + '\n'
        write_report(path, legacy)
        migrated, migrated_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [])
        migrated_entries, annotations = iac_state(migrated, 'dev', 'cde', data=migrated_state)
        assert len(migrated_entries) == 1 and migrated_entries[0]['legacy'] == legacy_item and migrated_entries[0]['retained']
        assert 'human確認: 旧例外' in annotations and '要調査' in migrated
        expect_error(lambda: iac_state(migrated, 'stg', 'cde', data=migrated_state), 'scope')
        write_report(path, migrated.replace('<!-- issue-service: s3 -->', '<!-- issue-service: s3 -->\n\nhuman確認: 新しい注記'), migrated_state)
        annotated, annotated_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [])
        assert any('ISSUE-' in note and 'human確認: 新しい注記' in note for note in iac_state(annotated, 'dev', 'cde', data=annotated_state)[1])
        # Raw diagnostic text is retained in state without embedding machine data in Markdown.
        dangerous = dict(unknown, reason='--> <script>bad</script> <!--')
        write_report(path, '')
        escaped, escaped_state = iac_merge(root, path, 'dev', 'cde', services, [dangerous])
        assert '<!-- iac-report-data:' not in escaped
        assert iac_state(escaped, 'dev', 'cde', data=escaped_state)[0][0]['record'] == dangerous
        # Separate lossless storage must not bypass existing report redaction.
        secret = dict(difference, property='SecretsManager.Secret.SecretString', desired='secret-data', actual='other-secret')
        secret_report, secret_report_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [secret])
        assert 'secret-data' not in secret_report and 'other-secret' not in secret_report
        assert 'secret-data' not in json.dumps(secret_report_state) and 'other-secret' not in json.dumps(secret_report_state)
        # Old source locations may disappear; retention never fabricates a current link.
        source = root / 'model/dev/cde/s3.properties'
        write(source, 'line1\nline2\n')
        located = dict(difference, reason='property missing', model={'path': 'model/dev/cde/s3.properties', 'line': 2})
        write_report(path, *iac_merge(root, path, 'dev', 'cde', ['s3'], [located]))
        write(source, 'line1\n')
        stale_report, stale_report_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [])
        assert '保存済み根拠・今回未再確認' in stale_report
        assert any(entry['retained'] for entry in iac_state(stale_report, 'dev', 'cde', data=stale_report_state)[0])
        # Equal diagnostics remain two original records, also after repeated retention.
        write_report(path, '')
        duplicates, duplicates_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [difference, difference])
        duplicate_entries = iac_state(duplicates, 'dev', 'cde', data=duplicates_state)[0]
        assert len(duplicate_entries) == 2
        assert len(iac_actions(duplicate_entries, 'dev', 'cde')) == 1
        write_report(path, duplicates, duplicates_state)
        retained_duplicates, retained_duplicates_state = iac_merge(root, path, 'dev', 'cde', ['s3'], [])
        write_report(path, retained_duplicates, retained_duplicates_state)
        again = read_iac(iac_merge(root, path, 'dev', 'cde', ['s3'], []), 'dev', 'cde')[0]
        assert len(again) == 2 and all(entry['retained'] for entry in again)
        assert again == iac_state(retained_duplicates, 'dev', 'cde', data=retained_duplicates_state)[0]
    print('IaC action reports: PASS (1236 cascading + 6 direct records → 1 Issue; lossless IDs/scope/retention/gates)')


def mismatch_display_cases():
    from issues_iac import safe_value
    from issues_reports import iac_actions, iac_key

    def fields(left, right, name='Setting', exact=False):
        return value_differences(left, right, name, exact=exact)

    role = {'$resource': ['iam', '089'], '$attribute': 'RoleName'}
    arn_role = dict(role, **{'$attribute': 'Arn'})
    assert fields(role, arn_role) == [{'path': '$attribute', 'model': 'RoleName', 'iac': 'Arn'}]
    assert [item['path'] for item in fields({'a': 1, 'b': 2}, {'a': 3, 'b': 4})] == ['a', 'b']
    assert fields({'Settings': {'Timeout': 1, 'Enabled': True}}, {'Settings': {'Timeout': 2, 'Enabled': True}}) == [
        {'path': 'Settings.Timeout', 'model': '1', 'iac': '2'}]
    assert fields({'a': 1}, {'a': 1, 'extra': 2}) == []
    assert fields({'a': 1}, {'a': 1, 'extra': 2}, exact=True) == [{'path': 'extra', 'model': '欠落', 'iac': '2'}]
    assert fields({'a': None}, {}) == [{'path': 'a', 'model': 'null', 'iac': '欠落'}]
    for left, right, model, iac in [(None, False, 'null', 'false'), (True, 1, 'true', '1'),
                                   (1, '1', '1', '"1"'), (False, 'false', 'false', '"false"')]:
        assert fields(left, right)[0] == {'path': 'Setting', 'model': model, 'iac': iac}
    assert fields([1, 2], [2, 1], 'Items') == [
        {'path': 'Items[0]', 'model': '1', 'iac': '2'}, {'path': 'Items[1]', 'model': '2', 'iac': '1'}]
    assert fields([None], [], 'Items') == [{'path': 'Items[0]', 'model': 'null', 'iac': '欠落'}]
    assert fields([], [None], 'Items') == [{'path': 'Items[0]', 'model': '欠落', 'iac': 'null'}]
    tags = [{'Key': 'Name', 'Value': 'one'}]
    reordered = [{'Key': 'owner', 'Value': 'other'}, *tags]
    assert fields(tags, reordered, 'Tags') == []
    assert fields(tags, [{'Key': 'owner', 'Value': 'other'}, {'Key': 'Name', 'Value': 'two'}], 'Tags') == [
        {'path': 'Tags[Key=Name].Value', 'model': 'one', 'iac': 'two'}]
    assert fields(tags, [], 'HostedZoneTags')[0]['iac'] == '欠落'
    assert fields(tags, tags * 2, 'Tags') == [{'path': 'Tags[Key=Name].要素数（キー重複）', 'model': '1', 'iac': '2'}]
    assert fields(tags * 2, tags * 2, 'Tags')[0]['model'] == '2'
    assert fields(tags, reordered, 'Tags', exact=True)  # Exact whole-property arrays retain order/membership.
    long_value = 'x' * 1000
    assert fields({'Config': long_value + 'A'}, {'Config': long_value + 'B'})[0]['model'].endswith('A')
    secrets = fields({'Password': 'first', 'Same': 'unchanged'}, {'Password': 'second', 'Same': 'unchanged'})
    assert secrets == [{'path': 'Password', 'model': '"<masked>"', 'iac': '"<masked>"'}]
    assert 'first' not in json.dumps(secrets) and 'second' not in json.dumps(secrets)
    assert fields(tags, [{'Key': 'Name', 'Value': 'one'}], 'Tags') == []
    secret_tags = fields([{'Key': 'SECRET_TOKEN', 'Value': 'first'}], [{'Key': 'SECRET_TOKEN', 'Value': 'second'}], 'Tags')
    assert secret_tags[0]['model'] == '"<masked>"' and secret_tags[0]['iac'] == '"<masked>"'
    assert fields('arn:aws:iam::123456789012:role/a', 'arn:aws:iam::123456789012:role/b')[0]['model'] == '"<masked ARN/secret>"'
    assert fields('{{resolve:secretsmanager:first}}', '{{resolve:secretsmanager:second}}')[0]['iac'] == '"<masked ARN/secret>"'

    with tempfile.TemporaryDirectory(prefix='mismatch-display-') as directory:
        root = Path(directory)
        path = root / 'issues/dev/cde/iac-issues.md'
        base = dict(category='difference', service='glue', resource='019', property='Glue.Job.Role',
                    reason='value mismatch', stack='stack1', desired=role, actual=arn_role,
                    model={'path': 'model/dev/cde/glue.properties', 'line': 999},
                    model_sources=[{'path': 'model/dev/cde/glue.properties', 'line': 999, 'key': 'desired.row.019.value'}],
                    iac={'path': 'infra/cloudformation/templates/shared.yaml', 'line': 999})
        secret = dict(base, resource='020', property='Glue.Job.Password', desired='<masked>', actual='<masked>')
        long_record = dict(base, resource='021', property='Glue.Job.Config', desired=long_value + 'A', actual=long_value + 'B')
        records = [base, secret, long_record]
        original = json.loads(json.dumps(records))
        display = {identifier(base): fields(role, arn_role), identifier(secret): fields('first', 'second', 'Glue.Job.Password'),
                   identifier(long_record): fields(long_record['desired'], long_record['actual'], 'Glue.Job.Config')}
        # No source/evidence reads, even when saved line numbers are invalid.
        with patch('issues_reports.evidence', side_effect=AssertionError('mismatch evidence read forbidden')):
            report, report_state = iac_merge(root, path, 'dev', 'cde', ['glue'], records, display)
        visible = re.sub(IAC_DATA, '', report)
        assert '- 相違項目: $attribute\n  - Model: ` RoleName `\n  - IaC: ` Arn `' in visible
        assert '$resource' not in visible and '修正対象:' not in visible and '根拠（代表例）:' not in visible
        assert 'glue.properties' not in visible and 'shared.yaml' not in visible and ':999' not in visible
        assert long_value + 'A' in visible and long_value + 'B' in visible and '240' not in visible
        assert '不一致の検出結果を保持' in visible and 'first' not in report and 'second' not in report
        entries, notes = iac_state(report, 'dev', 'cde', data=report_state)
        assert Counter(json.dumps(entry['record'], sort_keys=True) for entry in entries) == Counter(json.dumps(record, sort_keys=True) for record in original)
        assert {entry['id'] for entry in entries} == {iac_key(record) for record in original}
        expected_entries = [{'id': iac_key(record), 'record': record, 'retained': False} for record in records]
        expected_entries.sort(key=lambda entry: (entry['record']['service'], entry['id'], entry['retained'], identifier(entry)))
        expected_groups = iac_actions(expected_entries, 'dev', 'cde')
        assert iac_actions(entries, 'dev', 'cde') == expected_groups and records == original and not notes
        assert report_state['value_differences'] == display
        unsafe_display = {identifier(secret): [{'path': 'Password', 'model': 'first', 'iac': 'second'}]}
        masked_report, masked_report_state = iac_merge(root, path, 'dev', 'cde', ['glue'], [secret], unsafe_display)
        assert 'first' not in masked_report and 'second' not in masked_report
        expect_error(lambda: iac_merge(root, path, 'dev', 'cde', ['glue'], [base], {identifier(base): [{}]}), 'malformed')
        duplicates = [dict(base, actual=dict(arn_role, **{'$attribute': f'Arn{i}'})) for i in range(5)]
        duplicate_display = {identifier(record): fields(record['desired'], record['actual']) for record in duplicates}
        limited, limited_state = iac_merge(root, path, 'dev', 'cde', ['glue'], duplicates, duplicate_display)
        assert re.sub(IAC_DATA, '', limited).count('- 不一致箇所:') == 1
        assert len(iac_state(limited, 'dev', 'cde', data=limited_state)[0]) == 5
        write_report(path, report.replace('- 分類: Model/IaC差分', '- 分類: Model/IaC差分\n\nhuman確認: 注記を保持', 1), report_state)
        regenerated, regenerated_state = iac_merge(root, path, 'dev', 'cde', ['glue'], records, display)
        assert iac_state(regenerated, 'dev', 'cde', data=regenerated_state)[0] == entries
        assert any('注記を保持' in note for note in iac_state(regenerated, 'dev', 'cde', data=regenerated_state)[1])
        write_report(path, regenerated, regenerated_state)
        retained, retained_state = iac_merge(root, path, 'dev', 'cde', ['glue'], [])
        assert all(entry['retained'] for entry in iac_state(retained, 'dev', 'cde', data=retained_state)[0])
        assert retained_state['value_differences'] == display
        assert '- 相違項目: $attribute' in retained
        write_report(path, '')
        legacy_masked, legacy_masked_state = iac_merge(root, path, 'dev', 'cde', ['glue'], [secret])
        assert '特定不可（検出結果は不一致' in legacy_masked

        # Real detection -> artifact JSON -> save: preserve original records and sensitive NoEcho redaction.
        fixture_root = root / 'pipeline'
        _, template = fixture(fixture_root, services=['s3'])
        template['Resources']['Bucket']['Properties']['BucketName'] = 'changed-bucket'
        mutate_template(fixture_root, template)
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            artifact = json.loads(json.dumps(scan(fixture_root, 'dev', '123456789012', ['s3'])))
        mismatch = next(item for item in artifact['iac'] if item['reason'] == 'value mismatch')
        assert identifier(mismatch) in artifact['iac_display']
        with task(fixture_root, ['s3']):
            saved = save_scan(fixture_root, artifact, {'issues': [], 'resolved': [],
                'reviewed_names': [item['id'] for item in artifact['naming']['names']],
                'reviewed_judgments': [item['id'] for item in artifact['judgments']]})
        saved_report = next(file for file in saved if file.name == 'iac-issues.md').read_text()
        assert 'changed-bucket' in saved_report and 'bucket-app-dev-data1' in saved_report
        assert '<!-- iac-report-data:' not in saved_report
        assert json.loads(next(file for file in saved if file.name == 'iac-issues.state.json').read_text())['value_differences'] == artifact['iac_display']
        # NoEcho masking survives the new display side-channel.
        comparison = Comparison(fixture_root, 'dev', '123456789012', ['s3'])
        comparison.sensitive_values.add('confidential')
        hidden = value_differences({'Value': 'prefix-confidential-A'}, {'Value': 'prefix-confidential-B'}, redact=comparison.redacted)
        assert hidden[0]['model'] == '"<masked sensitive parameter>"'
        assert 'confidential' not in json.dumps(hidden)
    print('IaC mismatch display: PASS (fields/types/arrays/Tags/masks/long values/IDs/data/annotations/pipeline)')


def state_report_cases():
    from issues_reports import iac_key
    from task_contract import refresh, complete, DeferredExhausted
    with tempfile.TemporaryDirectory(prefix='iac-state-') as directory:
        root = Path(directory)
        path = root / 'issues/dev/123456789012/iac-issues.md'
        state_path = path.with_name('iac-issues.state.json')
        ordinary = path.with_name('issues.md')
        record = dict(category='difference', service='s3', resource='001', property='S3.Bucket.Setting',
                      reason='value mismatch', stack='stack1', desired={'Settings': {'Timeout': 1}},
                      actual={'Settings': {'Timeout': 2}}, iac={'path': 'infra/shared.yaml', 'line': 20})
        other = dict(record, service='sqs', property='SQS.Queue.Setting')
        records = [record, other, dict(record, resource='002', category='matched', reason='equal', desired=None, actual=None),
                   dict(record, resource='003', category='excluded', reason='identifier output', desired=None, actual=None)]
        s3_records = [item for item in records if item['service'] == 's3']
        display = {identifier(item): value_differences(item['desired'], item['actual'], item['property']) for item in records}
        markdown, original_state = iac_merge(root, path, 'dev', '123456789012', ['s3', 'sqs'], records, display)
        old_data = dict(original_state)
        old_data.pop('report_digest')
        embedded = markdown + '\n<!-- iac-report-data: ' + json.dumps(old_data, ensure_ascii=False) + ' -->\n'
        embedded = embedded.replace('- 状態:', 'human確認: 移行注記\n- 状態:', 1)
        write_report(path, embedded)
        outputs = [ordinary, path, state_path]
        def snapshot():
            return {file: file.read_bytes() if file.exists() else None for file in outputs}

        with task(root, ['s3', 'sqs']):
            # Migration failure at any publication position restores the entire batch,
            # including the original embedded JSON and previously missing files.
            for error_type, after_replace in ((OSError, False), (OSError, True),
                                               (KeyboardInterrupt, False), (KeyboardInterrupt, True)):
                for failed_output in outputs:
                    before = snapshot()
                    replace = os.replace
                    failed = False
                    def fail_once(source, destination):
                        nonlocal failed
                        if Path(destination) == failed_output and not failed:
                            failed = True
                            if after_replace:
                                replace(source, destination)
                            raise error_type('fixture pair publication failure')
                        return replace(source, destination)
                    with patch('issues_reports.os.replace', side_effect=fail_once):
                        try:
                            save(root, 'dev', '123456789012', ['s3', 'sqs'], iac=records, display=display)
                        except error_type:
                            pass
                        else:
                            raise AssertionError('partial publication cannot succeed')
                    assert failed and snapshot() == before
                    assert set(path.parent.iterdir()) == {path}  # No leaked staging files.
            with patch.object(Comparison, 'run', side_effect=AssertionError('save comparison forbidden')), \
                    patch('issues_iac.load_model', side_effect=AssertionError('save model parse forbidden')), \
                    patch('socket.socket', side_effect=AssertionError('network forbidden')):
                assert save(root, 'dev', '123456789012', ['s3', 'sqs'], iac=records, display=display) == outputs
            migrated = path.read_text()
            state = json.loads(state_path.read_text())
            assert 'iac-report-data' not in migrated and 'generated_line_ids' not in migrated
            assert '- 相違項目: Settings.Timeout\n  - Model: ` 1 `\n  - IaC: ` 2 `' in migrated
            assert 'shared.yaml' not in migrated
            assert '- 根拠（代表例）:' not in migrated and '- 修正対象:' not in migrated
            assert state['entries'] == original_state['entries'] and state['actions'] == original_state['actions']
            assert state['value_differences'] == display and any('移行注記' in note for note in state['annotations'])
            assert {entry['id'] for entry in state['entries']} == {iac_key(item) for item in records}
            # Reruns use state only and preserve all IDs, memberships and contextual notes.
            save(root, 'dev', '123456789012', ['s3', 'sqs'], iac=records, display=display)
            repeated = json.loads(state_path.read_text())
            for key in ('entries', 'actions', 'annotations', 'value_differences'):
                assert repeated[key] == state[key], key
            # Human additions to Markdown survive subsequent partial saves.
            write(path, path.read_text().replace('- 状態:', 'human確認: 追加注記\n- 状態:', 1))
            save(root, 'dev', '123456789012', ['s3'], iac=s3_records, display=display)
            partial = json.loads(state_path.read_text())
            assert next(entry for entry in partial['entries'] if entry['record']['service'] == 'sqs') == next(
                entry for entry in repeated['entries'] if entry['record']['service'] == 'sqs')
            assert any('追加注記' in note for note in partial['annotations'])
            assert len(partial['entries']) == 4 and len(partial['actions']) == 2
            # A post-migration state write failure restores both existing files too.
            before = snapshot()
            failed = False
            failed_output = state_path
            error_type = OSError
            with patch('issues_reports.os.replace', side_effect=fail_once):
                expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[dict(record, actual='new')]))
            assert snapshot() == before
            # Missing/corrupt state and mismatched pairs stop saving without data loss.
            valid_state = state_path.read_bytes()
            valid_markdown = path.read_bytes()
            for bad_state in (None, b'{bad', b'null', json.dumps(dict(partial, scope=['stg', 'wrong'])).encode()):
                if bad_state is None:
                    state_path.unlink()
                else:
                    state_path.write_bytes(bad_state)
                before = snapshot()
                expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[record]))
                assert snapshot() == before
                state_path.write_bytes(valid_state)
            write(path, path.read_text().replace('Settings.Timeout', 'Settings.Changed'))
            before = snapshot()
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[record]), 'inconsistent')
            assert snapshot() == before
            path.write_bytes(valid_markdown)
            write(path, embedded)  # Embedded data plus sidecar is never silently discarded.
            before = snapshot()
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[record]), 'inconsistent')
            assert snapshot() == before
            path.write_bytes(valid_markdown)

        # Omitting the sidecar from the contract cannot publish Markdown alone.
        relative = [file.relative_to(root).as_posix() for file in outputs]
        with task(root, ['s3'], allowed=relative[:2]):
            before = snapshot()
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[record]), 'Allowed paths')
            assert snapshot() == before
        # A reservation on only state defers the indivisible batch until acquired.
        with task(root, ['s3'], name='state-owner', allowed=[relative[2]]):
            refresh(root, 'tasks/state-owner.md')
            with task(root, ['s3'], name='state-writer'):
                before = snapshot()
                with patch('task_contract.time.sleep') as sleep:
                    try:
                        save(root, 'dev', '123456789012', ['s3'], iac=[record])
                    except DeferredExhausted:
                        pass
                    else:
                        raise AssertionError('reserved state must defer the whole publication')
                assert sleep.call_count == 20 and snapshot() == before
                complete(root, 'tasks/state-owner.md')
                save(root, 'dev', '123456789012', ['s3'], iac=[record])
                assert 'iac-report-data' not in path.read_text()
    print('IaC sidecar state: PASS (migration/pair rollback/interruption/IDs/annotations/scope/reservations/integrity)')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--log-dir', type=Path)
    parser.add_argument('--worker', choices=list('ABC'))
    parser.add_argument('--reference', action='store_true')
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--services')
    args = parser.parse_args()
    if args.reference:
        comparison, records = compare(args.fixture, [args.services])
        print(json.dumps({'records': records, 'counts': {'model_reads': sum(len(model.files) for model in comparison.models.values()),
                                                       'model_text_reads': sum(len(model.files) for model in comparison.models.values()), 'model_byte_reads': 0,
                                                       'model_parses': comparison.metrics['model_parses'], 'template_decodes': comparison.metrics['template_decodes']}}))
        return
    if args.worker:
        print(json.dumps(worker(args.fixture, args.worker, args.services.split(','))))
        return
    if args.benchmark:
        benchmark(args.log_dir or Path(tempfile.mkdtemp(prefix='issues-performance-')))
        return
    with tempfile.TemporaryDirectory(prefix='issues-checks-') as directory:
        root = Path(directory) / 'project'
        values, template = fixture(root, stacks=3, parts=True)
        checks(root, values, template)
        naming_target_scope_cases()
        resource_cases(root)
        extended_cases(root, template)
        concurrency(root)
    action_report_cases()
    mismatch_display_cases()
    state_report_cases()
    comparison_repair_cases()
    local_reference_cases()
    reference_identity_report_cases()
    symbolic_string_cases()
    assert not subprocess.run(['git', 'diff', '--', 'framework/scripts/issue_gate.py'], cwd=ROOT, capture_output=True).stdout
    assert not subprocess.run(['git', 'diff', '--cached', '--', 'framework/scripts/issue_gate.py'], cwd=ROOT, capture_output=True).stdout
    print('Local issues scan checks: PASS (isolated gate/save/comparison/reuse/concurrency fixtures)')


if __name__ == '__main__':
    main()

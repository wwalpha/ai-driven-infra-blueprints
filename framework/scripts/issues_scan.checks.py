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
from issues_reports import save, blocks, numbered, identifier, iac_merge
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
        report = iac_merge(root, root / 'issues/dev/123456789012/iac-issues.md', 'dev', '123456789012', services, missing)
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
        write(report, report.read_text().replace('<!-- issue-service: s3 -->', '<!-- issue-service: s3 -->\n\nhuman確認: IaC側の既存例外。'))
        uncertain = dict(record, category='uncompared', reason='fixture no longer comparable', desired=None, actual=None)
        save(root, 'dev', '123456789012', services, iac=[uncertain])
        partial = report.read_text()
        assert 'human確認: IaC側の既存例外。' in partial and 'model="old"; IaC="new"' in partial
        assert '保持未確認: 1件' in partial and '未比較 1件' in partial
        save(root, 'dev', '123456789012', services, iac=[uncertain])
        assert report.read_text().count('fixture no longer comparable') == 1
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
    comparison_repair_cases()
    assert not subprocess.run(['git', 'diff', '--', 'framework/scripts/issue_gate.py'], cwd=ROOT, capture_output=True).stdout
    assert not subprocess.run(['git', 'diff', '--cached', '--', 'framework/scripts/issue_gate.py'], cwd=ROOT, capture_output=True).stdout
    print('Local issues scan checks: PASS (isolated gate/save/comparison/reuse/concurrency fixtures)')


if __name__ == '__main__':
    main()

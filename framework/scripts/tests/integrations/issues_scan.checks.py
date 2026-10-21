#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.issues_scan_fixtures import *

@it_case
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


@it_case
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
        report, report_state = render_iac(root, root / 'issues/dev/123456789012/iac-issues.md', 'dev', '123456789012', services, missing)
        assert '差分 9件 / 未比較 0項目 / 処理エラー 0項目' in report
        assert '修正対象: 不足入力: shared.yaml' in report
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
    from iac_values import safe_value
    assert safe_value([{'Name': 'SECRET_TOKEN', 'Value': 'confidential'}])[0]['Value'] == '<masked>'
    assert same(1, True) is False and same('1', 1) is False
    assert not same([1, 2], [2, 1]) and not same([1, 1], [1])
    assert selected_same({'a': 1}, {'a': 1, 'b': 2})
    assert selected_same([{'Key': 'Name', 'Value': 'a'}], [{'Key': 'owner', 'Value': 'b'}, {'Key': 'Name', 'Value': 'a'}], 'Tags')
    assert not selected_same([{'Key': 'Name', 'Value': 'a'}], [{'Key': 'Name', 'Value': 'a'}, {'Key': 'Name', 'Value': 'a'}], 'Tags')
    loaded = load_model(root / 'model/dev/123456789012/s3.properties')
    assert any(path.name.startswith('part-') for path in loaded.files)
    for key, (path, line) in loaded.locations.items():
        assert path in loaded.files
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
        import model.sources as sources
        with patch.object(sources, '_read_model', wraps=sources._read_model) as parse:
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
        if path in loaded.files:
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
        write(report, report.read_text() + '\n## 人間注記\n\nhuman確認: IaC側の既存例外。\n')
        uncertain = dict(record, category='uncompared', reason='fixture no longer comparable', desired=None, actual=None)
        save(root, 'dev', '123456789012', services, iac=[uncertain])
        partial = report.read_text()
        assert 'human確認: IaC側の既存例外。' not in partial
        assert '未比較 1項目' in partial and 'fixture difference' not in partial
        save(root, 'dev', '123456789012', services, iac=[uncertain])
        assert '元レコード数: 1' in report.read_text()
        save(root, 'dev', '123456789012', services, iac=[])
        assert '元レコード数: 0' in report.read_text() and 'no compared records' in report.read_text()
        write(paths[1], 'invalid iac report\n')
        save(root, 'dev', '123456789012', services, iac=[])
        assert 'invalid iac report' not in paths[1].read_text()
        paths[1].unlink()
    with task(root, ['s3'], name='unreserved', allowed=['issues/dev/123456789012/iac-issues.md']):
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
        prompt = root / 'tasks/saveonly.md'
        running = prompt.read_text()
        report = root / 'issues/dev/123456789012/issues.md'
        before = report.read_bytes()
        iac = report.with_name('iac-issues.md')
        for state in ('completed', 'suspend'):
            prompt.write_text(running.replace('`running`', f'`{state}`') +
                              ('\n## Suspension reason\nExplicit test stop\n' if state == 'suspend' else ''))
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[]),
                         'running report-only' if state == 'completed' else 'suspend task')
            assert report.read_bytes() == before and not iac.exists()
        prompt.write_text(running)
    expect_error(lambda: save(root, 'dev', '123456789012', ['s3']))
    assert report.read_bytes() == before and not iac.exists()


@it_case
def resource_cases(root):
    # Compact independent fixture edits, not consumer data.
    values = load_model(root / 'model/dev/123456789012/s3.properties').values.copy()
    source = root / 'model/dev/123456789012/s3.properties'
    original_files = {path: text for path, text in load_model(source).files.items()}
    def publish(model):
        remove_model(source)
        write_model(source, model)
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    publish(values)
    comparator, records = compare(root, ['s3'])
    assert any(item['resource'] == '001' and item['category'] == 'excluded' for item in records), records
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
    _, stacks = __import__('model.core', fromlist=['stack_model']).stack_model(comparison.model('cloudformation-stacks').values)
    comparison.stack(stacks[0][1])
    assert comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)') == comparison.evaluate(stacks[0][1]['name'], {'Ref': 'Bucket'})
    assert comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)', 'Arn') == comparison.evaluate(stacks[0][1]['name'], {'Fn::GetAtt': ['Bucket', 'Arn']})
    assert comparison.evaluate(stacks[0][1]['name'], {'Fn::Select': ['1', {'Fn::Split': [',', 'a,b']}]}) == 'b'
    values['desired.resource.001.resourceMode'] = 'IMPORT'
    publish(values)
    comparison = Comparison(root, 'dev', '123456789012', ['s3'])
    expect_error(lambda: comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)'), 'IMPORT reference is PENDING_DEPLOY')
    rid = next(rid for rid, row in comparison.rows['s3']['001'] if row['property'] == 'S3.Bucket.BucketName')
    key = f'observed.row.{rid}.value'
    comparison.models['s3'] = comparison.models['s3']._replace(values=dict(comparison.models['s3'].values))
    original = comparison.models['s3'].values.get(key)
    comparison.models['s3'].values[key] = '`PENDING_DEPLOY`'
    expect_error(lambda: comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)'), 'IMPORT reference is PENDING_DEPLOY')
    comparison.models['s3'].values[key] = '`observed-bucket`'
    expect_error(lambda: comparison.reference('s3', '[PENDING_DEPLOY](#s3-bucket-app-dev-data1)'), 'IMPORT reference requires approved handoff')
    if original is None:
        comparison.models['s3'].values.pop(key)
    else:
        comparison.models['s3'].values[key] = original
    # Restore all real part files, then Terraform remains explicit partial without CFn IDs.
    for part in source.with_suffix('').glob('*.properties'):
        part.unlink()
    from sync_files import save_files
    save_files(original_files)
    project = root / 'project.json'
    original = project.read_text()
    write(project, original.replace('cloudformation', 'terraform'))
    _, records = compare(root, ['s3'])
    assert records and all(item['category'] == 'uncompared' for item in records)
    write(project, original)


@it_case
def extended_cases(root, template):
    source = root / 'model/dev/123456789012/s3.properties'
    originals = load_model(source).files.copy()
    values = load_model(source).values.copy()
    def publish(values):
        remove_model(source)
        write_model(source, values)
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
    source.write_text(re.sub(r'^desired\.row\.001-090\.document=.*$', 'desired.row.001-090.document={bad json', source.read_text(), flags=re.M))
    changed['Resources'].pop('SecondPolicy')
    mutate_template(root, changed)
    _, records = compare(root, ['s3'])
    assert any(item['category'] == 'error' for item in records)
    for part in source.with_suffix('').glob('*.properties'):
        part.unlink()
    from sync_files import save_files
    save_files(originals)
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
    remove_model(kmspath)
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
    remove_model(modelpath); remove_model(refpath)
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
    remove_model(path)
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
                   'desired.resource.001.cfn-logicalId': name + '-Build', 'desired.resource.001.anchor': 'codebuild-fixture', 'desired.row.001-001.property': 'CodeBuild.Project.ServiceRole',
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
        modeltext = read_model(modelpath)
        write(modelpath, modeltext.replace('desired.resource.001.cfn-logicalId=' + name + '-Log\n', '').replace('logicalId=Log1', 'logicalId=Log'))
        stackpath = root / 'model/dev/123456789012/cloudformation-stacks.properties'
        stacktext = read_model(stackpath)
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
                with pytest.raises(Blocked):
                    comparison.evaluate(consumer, value)
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
            original = read_model(model)
            write(model, original + 'desired.resource.003.resourceType=S3.Bucket\ndesired.resource.003.anchor=s3-duplicate\ndesired.resource.003.cfn-logicalId=' + producer + '-Bucket\n')
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
    from iac_values import Expression
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
            with pytest.raises(ValueError):
                comparison.evaluate(name, value)
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
                     'desired.resource.001.cfn-logicalId': name + '-Policy', 'desired.resource.001.anchor': 'iam-policy-fixture',
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


def reference_property_contract_cases():
    with tempfile.TemporaryDirectory(prefix='reference-contract-') as directory:
        root = Path(directory) / 'project'
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        specs = [('lambda', '001', 'Lambda.Function', 'Function'),
                 ('codecommit', '001', 'CodeCommit.Repository', 'Repository'),
                 ('quicksight', '001', 'QuickSight.VPCConnection', 'VpcConnection'),
                 ('quicksight', '053', 'QuickSight.DataSource', 'DataSource'),
                 ('cloudtrail', '001', 'CloudTrail.Trail', 'Trail'),
                 ('codepipeline', '001', 'CodePipeline.Pipeline', 'Pipeline')]
        models = {}
        for service, identity, kind, logical in specs:
            model = models.setdefault(service, {f'desired.service.{service}.serviceId': service})
            model.update({f'desired.resource.{identity}.resourceType': kind,
                          f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical,
                          f'desired.resource.{identity}.anchor': logical.lower()})
            template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
        function = '[PENDING_DEPLOY](lambda.md#function)'
        repository = '[PENDING_DEPLOY](codecommit.md#repository)'
        connection = '[PENDING_DEPLOY](#vpcconnection)'
        event = [{'DataResources': [{'Type': 'AWS::Lambda::Function', 'Values': [function]}]}]
        action = dict(Category='Source', Owner='AWS', Provider='CodeCommit', Version='1')
        stages = [{'Name': 'Source', 'Actions': [{'Name': 'Source', 'ActionTypeId': action,
                                               'Configuration': {'RepositoryName': repository}}]}]
        selections = [('cloudtrail', '001', 'CloudTrail.Trail.EventSelectors', event),
                      ('codepipeline', '001', 'CodePipeline.Pipeline.Stages', stages),
                      ('quicksight', '053', 'QuickSight.DataSource.VpcConnectionProperties.VpcConnectionArn', connection)]
        for service, identity, prop, value in selections:
            models[service].update({f'desired.row.{identity}-001.property': prop,
                                   f'desired.row.{identity}-001.value': value if isinstance(value, str) else '`' + json.dumps(value) + '`'})
        def publish():
            for service, model in models.items():
                write(root / f'model/dev/123456789012/{service}.properties', '\n'.join(f'{key}={value}' for key, value in model.items()) + '\n')
            mutate_template(root, template)
        template['Resources']['Trail']['Properties']['EventSelectors'] = [dict(DataResources=[dict(Type='AWS::Lambda::Function', Values=[{'Fn::GetAtt': ['Function', 'Arn']}])])]
        template['Resources']['Pipeline']['Properties']['Stages'] = json.loads(json.dumps(stages))
        template['Resources']['Pipeline']['Properties']['Stages'][0]['Actions'][0]['Configuration']['RepositoryName'] = {'Fn::GetAtt': ['Repository', 'Name']}
        template['Resources']['DataSource']['Properties']['VpcConnectionProperties'] = {'VpcConnectionArn': {'Fn::GetAtt': ['VpcConnection', 'Arn']}}
        publish()
        def records():
            comparison, results = compare(root, ['cloudtrail', 'codepipeline', 'quicksight'])
            return comparison, {item['service']: item for item in results if item['property'] in {
                'CloudTrail.Trail.EventSelectors', 'CodePipeline.Pipeline.Stages', 'QuickSight.DataSource.VpcConnectionProperties'}}
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, results = records()
            assert len(results) == 3 and all(item['category'] == 'matched' for item in results.values()), results
            # Ref remains a different attribute even when the primaryIdentifier changes.
            comparison.catalog.schema('CodeCommit.Repository')['primaryIdentifier'] = ['/properties/Name']
            assert comparison.evaluate(stack, {'Ref': 'Repository'})['$attribute'] == 'RepositoryId'
            assert comparison.evaluate(stack, {'Ref': 'Function'})['$attribute'] == 'FunctionName'
            expect_error(lambda: comparison.evaluate(stack, {'Ref': 'VpcConnection'}), 'Ref return attribute is unproven')
            expect_error(lambda: comparison.evaluate(stack, {'Fn::GetAtt': ['VpcConnection', 'VPCConnectionId']}), 'GetAtt return attribute')
            expect_error(lambda: comparison.desired_reference('cloudtrail', function, 'CloudTrail.Trail', 'UnknownName'), 'property contract unproven')
            expect_error(lambda: comparison.desired_reference('codepipeline', repository, 'CodePipeline.Pipeline', 'Stages[].Actions[].Configuration.UnknownArn', context={'ActionTypeId': action}), 'contract unproven')
            for service, logical, path, wrong in [
                ('cloudtrail', 'Trail', 'EventSelectors', [{'DataResources': [{'Type': 'AWS::Lambda::Function', 'Values': [{'Ref': 'Function'}]}]}]),
                ('codepipeline', 'Pipeline', 'Stages', [{'Name': 'Source', 'Actions': [{'Name': 'Source', 'ActionTypeId': action, 'Configuration': {'RepositoryName': {'Ref': 'Repository'}}}]}]),
                ('quicksight', 'DataSource', 'VpcConnectionProperties', {'VpcConnectionArn': {'Ref': 'VpcConnection'}})]:
                original = template['Resources'][logical]['Properties'][path]
                template['Resources'][logical]['Properties'][path] = wrong
                mutate_template(root, template)
                result = records()[1][service]
                assert result['category'] == ('uncompared' if service == 'quicksight' else 'difference'), result
                template['Resources'][logical]['Properties'][path] = original
            # Every action condition is required; other actions cannot provide it.
            for field, wrong in [('Category', 'Build'), ('Owner', 'ThirdParty'), ('Provider', 'GitHub'), ('Version', '2')]:
                bad = json.loads(json.dumps(stages))
                bad[0]['Actions'][0]['ActionTypeId'][field] = wrong
                row = {'property': 'CodePipeline.Pipeline.Stages', 'value': '`' + json.dumps(bad) + '`'}
                expect_error(lambda: comparison.desired_value('codepipeline', row, 'CodePipeline.Pipeline'), 'ActionTypeId')
                del bad[0]['Actions'][0]['ActionTypeId'][field]
                row['value'] = '`' + json.dumps(bad) + '`'
                expect_error(lambda: comparison.desired_value('codepipeline', row, 'CodePipeline.Pipeline'), 'ActionTypeId')
            bad = json.loads(json.dumps(stages))
            bad[0]['Actions'][0]['Configuration']['RepositoryName'] = function
            expect_error(lambda: comparison.desired_value('codepipeline', {'property': 'CodePipeline.Pipeline.Stages', 'value': '`' + json.dumps(bad) + '`'}, 'CodePipeline.Pipeline'), 'reference attribute not confirmed: Name')
            # Explicit row indexes bind configuration to its own action, independent of row order.
            model = models['codepipeline']
            for key in list(model):
                if key.startswith('desired.row.'):
                    del model[key]
            indexed = [('Stages[1].Actions[1].Configuration', '`' + json.dumps({'RepositoryName': repository}) + '`')]
            indexed += [('Stages[1].Actions[1].ActionTypeId.' + key, '`' + value + '`') for key, value in action.items()]
            indexed += [('Stages[1].Actions[1].Name', '`Source`'), ('Stages[1].Name', '`Source`')]
            for number, (prop, value) in enumerate(indexed, 1):
                model.update({f'desired.row.001-{number:03d}.property': 'CodePipeline.Pipeline.' + prop,
                              f'desired.row.001-{number:03d}.value': value,
                              f'desired.row.001-{number:03d}.comment': 'RepositoryName: repository' if prop.endswith('.Configuration') else ''})
            publish()
            assert records()[1].get('codepipeline', {}).get('category') == 'matched', compare(root, ['codepipeline'])[1]
            for key in list(model):
                if key.endswith('.property'):
                    model[key] = re.sub(r'\[\d+\]', '[]', model[key])
            publish()
            _, result = compare(root, ['codepipeline'])
            assert any(item['category'] == 'matched' and item['property'] == 'CodePipeline.Pipeline.Stages' for item in result), result
    print('Reference property contracts: PASS (3 positive examples; wrong attributes/unknown Ref/conditions/target types/indexed siblings)')


def reference_diagnostic_cases():
    from iac_values import ResourceReference
    field = 'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey'
    prop = 'Athena.WorkGroup.' + field
    with tempfile.TemporaryDirectory(prefix='reference-diagnostics-') as directory:
        root = Path(directory)
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        kms = {'desired.service.kms.serviceId': 'kms'}
        for identity, logical, kind in [('001', 'Key', 'KMS.Key'), ('002', 'Alias', 'KMS.Alias')]:
            kms.update({f'desired.resource.{identity}.resourceType': kind,
                        f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical,
                        f'desired.resource.{identity}.anchor': logical.lower()})
            template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
        template['Resources']['Alias']['Properties'] = {'AliasName': 'alias/fixture', 'TargetKeyId': {'Ref': 'Key'}}
        write(root / 'model/dev/123456789012/kms.properties', '\n'.join(f'{k}={v}' for k, v in kms.items()) + '\n')
        model = {'desired.service.athena.serviceId': 'athena', 'desired.resource.001.resourceType': 'Athena.WorkGroup',
                 'desired.resource.001.anchor': 'workgroup',
                 'desired.resource.001.cfn-logicalId': stack + '-WorkGroup', 'desired.row.001-001.property': prop,
                 'desired.row.001-001.value': '[alias](kms.md#alias)'}
        template['Resources']['WorkGroup'] = {'Type': 'AWS::Athena::WorkGroup', 'Properties': {
            'WorkGroupConfiguration': {'ResultConfiguration': {'EncryptionConfiguration': {'KmsKey': {'Ref': 'Alias'}}}}}}
        modelpath = root / 'model/dev/123456789012/athena.properties'
        def publish():
            write(modelpath, '\n'.join(f'{k}={v}' for k, v in model.items()) + '\n')
            mutate_template(root, template)
        publish()
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison, records = compare(root, ['athena'])
            assert next(item for item in records if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')['category'] == 'difference'
            encryption = template['Resources']['WorkGroup']['Properties']['WorkGroupConfiguration']['ResultConfiguration']['EncryptionConfiguration']
            encryption['KmsKey'] = 'alias/fixture'
            publish()
            assert next(item for item in compare(root, ['athena'])[1] if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')['category'] == 'difference'
            encryption['KmsKey'] = 'alias/other'
            publish()
            assert next(item for item in compare(root, ['athena'])[1] if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')['category'] == 'difference'
            model['desired.row.001-001.value'] = '[key](kms.md#key)'
            encryption['KmsKey'] = {'Ref': 'Key'}
            publish()
            comparison, records = compare(root, ['athena'])
            assert any(item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration' for item in records), records
            record = next(item for item in records if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')
            diagnostic = record['reference_diagnostics'][0]
            assert record['category'] == 'difference' and diagnostic['path'] == prop
            assert diagnostic['identity'] == 'same' and diagnostic['allowed_forms'] == ['KeyArn']
            assert diagnostic['format'] == dict(model='allowed', iac='outside allowed forms')
            assert diagnostic['model'] == {'$resource': ['kms', '001'], '$attribute': 'Arn'}
            assert diagnostic['iac'] == {'$resource': ['kms', '001'], '$attribute': 'KeyId'}
            assert 'outside allowed forms' in diagnostic['reason']
            model.update({'desired.row.001-002.property': 'Athena.WorkGroup.WorkGroupConfiguration.EnforceWorkGroupConfiguration',
                          'desired.row.001-002.value': 'true'})
            template['Resources']['WorkGroup']['Properties']['WorkGroupConfiguration']['EnforceWorkGroupConfiguration'] = True
            publish()
            single = compare(root, ['athena'])[1]
            parent = next(item for item in single if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')
            assert parent['category'] == 'difference' and parent['stack'] == stack
            assert parent['reference_diagnostics'] == [diagnostic]
            stats = iac_summary(single, 'dev', 'cde', ['athena'])
            assert stats['issue_count'] == 1 and stats['records']['difference'] == 1
            assert all('KeyId' in group['cause'] and 'KmsKey' in group['cause'] for group in stats['groups'])
            assert 'outside allowed forms' in iac_report('dev', 'cde', ['athena'], single)
            model.update({'desired.row.001-003.property': 'Athena.WorkGroup.WorkGroupConfiguration.ExecutionRole',
                          'desired.row.001-003.value': '[missing](kms.md#missing)',
                          'desired.row.001-004.property': 'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner',
                          'desired.row.001-004.value': '[missing](kms.md#missing)'})
            publish()
            multiple = compare(root, ['athena'])[1]
            parent = next(item for item in multiple if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')
            assert len(parent['deferred_children']) == 2
            assert {child['property'] for child in parent['deferred_children']} == {'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner', 'Athena.WorkGroup.WorkGroupConfiguration.ExecutionRole'}
            assert all(child['reason'] for child in parent['deferred_children'])
            stats = iac_summary([parent], 'dev', 'cde', ['athena'])
            example = stats['groups'][0]['examples'][0]
            assert len(example['deferred_children']) == 2 and example['omitted_deferred_children'] == 0
            assert stats['groups'][0]['target'] is None
            assert '省略保留原因:' not in iac_report('dev', 'cde', ['athena'], [parent])
            # Real child failures are redacted before being copied into the parent.
            model['desired.row.001-003.value'] = '[confidential](kms.md#confidential)'
            publish()
            original_compare_rows = Comparison.compare_rows
            def sensitive_compare_rows(instance, *args, **kwargs):
                instance.sensitive_values.add('confidential')
                return original_compare_rows(instance, *args, **kwargs)
            with patch.object(Comparison, 'compare_rows', sensitive_compare_rows):
                masked_records = compare(root, ['athena'])[1]
            masked_parent = next(item for item in masked_records if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')
            rendered = json.dumps(masked_parent) + json.dumps(iac_summary([masked_parent], 'dev', 'cde', ['athena'])) + iac_report('dev', 'cde', ['athena'], [masked_parent])
            assert 'confidential' not in rendered
            for rid in ('001-002', '001-003', '001-004'):
                del model[f'desired.row.{rid}.property'], model[f'desired.row.{rid}.value']
            alias = ResourceReference({'$resource': ['kms', '002'], '$attribute': 'AliasName'})
            diagnostics = []
            assert comparison.reference_same(alias, alias, 'Athena.WorkGroup', field, diagnostics) is False
            assert diagnostics[0]['allowed_forms'] == ['KeyArn']
            diagnostics.clear()
            alias_arn = ResourceReference(dict(alias, **{'$attribute': 'AliasArn'}))
            assert comparison.reference_same(alias_arn, alias_arn, 'Athena.WorkGroup', field, diagnostics) is False
            assert diagnostics[0]['identity'] == 'same' and 'outside allowed forms' in diagnostics[0]['reason']
            keyid = ResourceReference({'$resource': ['kms', '001'], '$attribute': 'KeyId'})
            arn = ResourceReference(dict(keyid, **{'$attribute': 'Arn'}))
            assert comparison.reference_same(arn, arn, 'Athena.WorkGroup', field) is True
            assert comparison.reference_same(keyid, keyid, 'Athena.WorkGroup', field) is False
            assert comparison.reference_same(keyid, arn, 'Athena.WorkGroup', field) is False
            assert comparison.reference_same(alias, arn, 'Athena.WorkGroup', field) is False
            comparison.sensitive_values = {'confidential'}
            for secret in ['arn:aws:kms:ap-northeast-1:123456789012:key/example', '{{resolve:secretsmanager:example}}', 'confidential']:
                hidden = []
                assert comparison.reference_same(arn, secret, 'Athena.WorkGroup', field, hidden) is (None if '{{resolve:' in secret else False)
                masked = dict(record, reference_diagnostics=hidden * 3)
                artifact = dict(environment='dev', target='cde', services=['athena'], iac=[masked])
                rendered = json.dumps(artifact) + json.dumps(detail_payload(artifact, 'iac')) + iac_report('dev', 'cde', ['athena'], [masked])
                assert secret not in rendered
                example = iac_summary([masked], 'dev', 'cde', ['athena'])['groups'][0]['examples'][0]
                assert len(example['reference_diagnostics']) == 3 and example['omitted_reference_fields'] == 0
            model['desired.row.001-001.value'] = '[key](kms.md#key)'
            for value in [{'Ref': 'Key'}, {'Fn::GetAtt': ['Key', 'Arn']}]:
                template['Resources']['WorkGroup']['Properties']['WorkGroupConfiguration']['ResultConfiguration']['EncryptionConfiguration']['KmsKey'] = value
                publish()
                assert next(item for item in compare(root, ['athena'])[1] if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')['category'] == ('difference' if 'Ref' in value else 'matched')
            template['Parameters']['Name']['NoEcho'] = True
            template['Resources']['WorkGroup']['Properties']['WorkGroupConfiguration']['ResultConfiguration']['EncryptionConfiguration']['KmsKey'] = {'Ref': 'Name'}
            publish()
            records = compare(root, ['athena'])[1]
            record = next(item for item in records if item['property'] == 'Athena.WorkGroup.WorkGroupConfiguration')
            assert record['category'] == 'difference' and record['reference_diagnostics'][0]['identity'] == 'unproven'
            assert 'app-dev-data1' not in json.dumps(record['reference_diagnostics'])
    print('Reference diagnostics: PASS (Athena KeyArn only, rejected KeyId/AliasName/AliasArn, identity/form separation, masking and bounded detail)')


check_reference_diagnostics = reference_diagnostic_cases


def reference_identity_report_cases():
    from iac_values import Expression
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
        original = read_model(logmodel)
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
            assert kms_result()[1]['category'] == 'difference'
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
            write(stacks, read_model(stacks) + 'desired.stack.003.name=datazone-stack\ndesired.stack.003.template=datazone.yaml\ndesired.stack.003.parameters=datazone.json\ndesired.stack.003.deployOrder=1\n')
            datazone = {'desired.service.datazone.serviceId': 'datazone', 'desired.resource.001.resourceType': 'DataZone.Domain',
                        'desired.resource.001.cfn-logicalId': 'datazone-stack-Domain', 'desired.resource.001.anchor': 'datazone-domain-fixture'}
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
        # Current-run partial reports preserve membership without restoring older records.
        path = root / 'issues/dev/123456789012/iac-issues.md'
        difference = dict(category='difference', service='cloudwatch-logs', resource='001', property='Logs.LogGroup.KmsKeyId',
                          stack=consumer, reason='value mismatch', iac={'path': 'infra/cloudformation/templates/shared.yaml'}, desired='a', actual='b')
        other = dict(difference, property='Logs.LogGroup.RetentionInDays', desired=7, actual=14)
        write_report(path, render_iac(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [difference, other])[0])
        uncertain = dict(difference, category='uncompared', reason='reference unproven')
        report, data = render_iac(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [uncertain, other])
        assert len(data['entries']) == 2 and not any('retained' in entry for entry in data['entries'])
        assert data['entries'][0]['id'] in {iac_key(uncertain), iac_key(other)}
        matched = dict(difference, category='matched', reason='reference expression equivalent')
        report, data = render_iac(root, path, 'dev', '123456789012', ['cloudwatch-logs'], [matched, other])
        assert '一致 1 / 除外 0' in report
        assert [entry['record'] for entry in data['entries'] if entry['record']['category'] == 'difference'] == [other]
        # One unresolved import shared by many consumers is one investigation, not many repairs.
        pending = [dict(uncertain, resource=str(i), cause={'kind': 'import-unresolved', 'export': 'missing-export', 'relationship': 'import'}) for i in range(40)]
        entries = [{'id': iac_key(i), 'record': i, 'retained': False} for i in pending]
        groups = iac_actions(entries, 'dev', '123456789012')
        assert len(groups) == 1 and groups[0]['classification'] == '比較未完了' and groups[0]['status'] == '要調査'
        assert '修正要否は未確定' in groups[0]['remedy']
        missing = dict(pending[0], cause={'kind': 'template-missing', 'path': 'datazone.yaml', 'relationship': 'export-search-incomplete'})
        group = iac_actions([{'id': iac_key(missing), 'record': missing, 'retained': False}], 'dev', '123456789012')[0]
        assert group['classification'] == '比較未完了' and group['status'] == '要調査'
    print('Reference identity/report regressions: PASS (KMS forms/identity, isolated cached exports, current-run scope/membership)')


def action_report_cases():
    from issues_reports import iac_key, iac_actions
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
        write(stack_model_path, read_model(stack_model_path).replace('desired.stack.002.template=shared.yaml', 'desired.stack.002.template=datazone.yaml'))
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
        report, data = render_iac(root, path, 'dev', 'cde', services, records)
        entries = data['entries']
        groups = iac_actions(entries, 'dev', 'cde')
        assert len(groups) == 1 and len(groups[0]['members']) == 1242
        assert '問題: 1件（原因・必要対応単位）\n' in report and '直接差分 6リソース' in report
        assert '差分 6件 / 未比較 1236項目 / 処理エラー 0項目' in report
        assert '直接Import依存は未確定' in report and 'model=null; IaC=null' not in report
        assert Counter(json.dumps(entry['record'], sort_keys=True) for entry in entries) == Counter(json.dumps(item, sort_keys=True) for item in records)
        assert records == original
        assert {entry['id'] for entry in entries} == {iac_key(item) for item in records}
        reversed_report, reversed_data = render_iac(root, path, 'dev', 'cde', services[::-1], records[::-1])
        assert re.sub(r'実行日時:.*', '', report) == re.sub(r'実行日時:.*', '', reversed_report)
        assert [entry['id'] for entry in reversed_data['entries']] == [entry['id'] for entry in entries]
        assert groups[0]['id'] != iac_actions(entries, 'stg', 'cde')[0]['id']
        other = dict(cascade[0], resource='other', cause=dict(cascade[0]['cause'], path='other.yaml'))
        unknown = dict(cascade[0], resource='unknown'); unknown.pop('cause')
        parameter = dict(cascade[1], resource='parameter', cause=dict(cascade[1]['cause'], kind='parameters-missing'))
        _, separated = render_iac(root, path, 'dev', 'cde', services, records + [other, unknown, parameter, dict(unknown, resource='unknown2')])
        assert len(separated['actions']) == 5
        difference = dict(category='difference', service='s3', resource='001', property='S3.Bucket.BucketName',
                          stack='stack1', iac={'path': 'infra/shared.yaml'}, reason='value mismatch', desired='a', actual='b')
        differences = [difference, dict(difference, stack='stack2'), dict(difference, resource='002'),
                       dict(difference, property='S3.Bucket.Tags'), dict(difference, reason='property missing'),
                       dict(difference, iac={'path': 'infra/other.yaml'})]
        diff_report, diff_data = render_iac(root, path, 'dev', 'cde', ['s3'], differences)
        assert len(diff_data['actions']) == 6 and '人間の判断が必要' in diff_report
        write_report(path, report)
        selected = [item for item in cascade if item['service'] == 's3']
        partial, partial_data = render_iac(root, path, 'dev', 'cde', ['s3'], selected)
        assert len(partial_data['entries']) == len(selected)
        assert '対象外Serviceは今回未検証' in partial and '探索中断:' in partial
        assert not issue_errors(root, {('dev', 'cde', service) for service in services})
        secret = dict(difference, property='SecretsManager.Secret.SecretString', desired='secret-data', actual='other-secret')
        secret_report, secret_data = render_iac(root, path, 'dev', 'cde', ['s3'], [secret])
        assert all(word not in secret_report + json.dumps(secret_data) for word in ('secret-data', 'other-secret'))
        duplicate_report, duplicate_data = render_iac(root, path, 'dev', 'cde', ['s3'], [difference, difference])
        assert len(duplicate_data['entries']) == 2 and len(duplicate_data['actions']) == 1
        assert 'iac-report-data' not in duplicate_report
    print('IaC action reports: PASS (causal grouping/cascades/independent IDs/current scope/duplicates/masks)')


def mismatch_display_cases():
    with tempfile.TemporaryDirectory(prefix='mismatch-pipeline-') as directory:
        root = Path(directory)

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
        assert detail_payload(artifact, 'iac', issue_id=next(group['id'] for group in artifact['iac_issues'] if group['category'] == '要判断'))['items'][0]['value_differences'] == artifact['iac_display'][identifier(mismatch)]
        # NoEcho masking survives the new display side-channel.
        comparison = Comparison(fixture_root, 'dev', '123456789012', ['s3'])
        comparison.sensitive_values.add('confidential')
        hidden = value_differences({'Value': 'prefix-confidential-A'}, {'Value': 'prefix-confidential-B'}, redact=comparison.redacted)
        assert hidden[0]['model'] == '"<masked sensitive parameter>"'
        assert 'confidential' not in json.dumps(hidden)
    print('IaC mismatch display: PASS (fields/types/arrays/Tags/masks/long values/IDs/data/annotations/pipeline)')


def state_report_cases():
    with tempfile.TemporaryDirectory(prefix='iac-current-run-') as directory:
        root = Path(directory)
        path = root / 'issues/dev/123456789012/iac-issues.md'
        state = path.with_name('iac-issues.state.json')
        ordinary = path.with_name('issues.md')
        record = dict(category='difference', service='s3', resource='001', property='S3.Bucket.Setting',
                      reason='value mismatch', stack='stack1', desired=1, actual=2, iac={'path': 'infra/shared.yaml'})
        display = {identifier(record): value_differences(1, 2, record['property'])}
        outputs = [ordinary, path]
        def snapshot():
            return {file: file.read_bytes() if file.exists() else None for file in [*outputs, state]}
        with task(root, ['s3', 'sqs']):
            save(root, 'dev', '123456789012', ['s3', 'sqs'],
                 additions=[{'service': 'sqs', 'message': 'human確認: unresolved queue issue'}], iac=[record, dict(record, service='sqs')])
            assert 'sqs / 001' in path.read_text()
        old_ordinary = ordinary.read_bytes()
        # Opaque Markdown, embedded JSON, human notes and out-of-scope results are never restored.
        for old in ('legacy opaque sqs report', '<!-- iac-report-data: {bad} -->\nhuman確認: old note', path.read_text()):
            for stale in ('{bad', '{}', '{"annotations":["old note"],"digest":"inconsistent"}'):
                write_report(path, old); write(state, stale)
                read_text = Path.read_text
                def guarded_read(file, *args, **kwargs):
                    assert file not in {path, state}, 'old IaC text/state read forbidden'
                    return read_text(file, *args, **kwargs)
                with task(root, ['s3']), patch.object(Path, 'read_text', guarded_read), \
                     patch.object(Comparison, 'run', side_effect=AssertionError('save comparison forbidden')), \
                     patch('issues_iac.load_model', side_effect=AssertionError('save parse forbidden')), \
                     patch('socket.socket', side_effect=AssertionError('network forbidden')):
                    assert save(root, 'dev', '123456789012', ['s3'], iac=[record], display=display, stamp='fixed') == outputs
                text = path.read_text()
                assert state.read_text() == stale and 'old note' not in text and 'sqs / 001' not in text
                assert '今回指定した範囲: dev／123456789012／s3' in text and '対象外Serviceは今回未検証' in text
                assert 'human確認: unresolved queue issue' in ordinary.read_text()
                assert not issue_errors(root, {('dev', '123456789012', 's3')})
                assert issue_errors(root, {('dev', '123456789012', 'sqs')})
        with task(root, ['s3']):
            for error_type in (OSError, KeyboardInterrupt):
                for failed_output in outputs:
                    for after in (False, True):
                        before = snapshot(); replace = os.replace; failed = False
                        def fail_replace(source, destination):
                            nonlocal failed
                            if Path(destination) == failed_output and not failed:
                                failed = True
                                if after: replace(source, destination)
                                raise error_type('fixture publication failure')
                            return replace(source, destination)
                        with patch('issues_reports.os.replace', side_effect=fail_replace):
                            with pytest.raises(error_type):
                                save(root, 'dev', '123456789012', ['s3'], iac=[record], display=display)
                        assert failed and snapshot() == before
                        assert set(path.parent.iterdir()) == {*outputs, state}
            before = snapshot()
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[record],
                                     guard=lambda: (_ for _ in ()).throw(ValueError('inputs changed'))), 'inputs changed')
            assert snapshot() == before
            save(root, 'dev', '123456789012', ['s3'], iac=[])
            assert '元レコード数: 0' in path.read_text() and 'no compared records' in path.read_text()
        # State is not an authorized save output, nor a dependency of the new batch.
        with task(root, ['s3'], allowed=[*map(lambda file: file.relative_to(root).as_posix(), outputs), state.relative_to(root).as_posix()]):
            before = snapshot()
            expect_error(lambda: save(root, 'dev', '123456789012', ['s3'], iac=[]), 'save-only exception')
            assert before == snapshot()
        assert 'human確認: unresolved queue issue' in ordinary.read_text() and old_ordinary
    print('IaC current-run publication: PASS (ignored state/old Markdown/partial scope/ordinary retention/rollback)')


def check_nested_membership(scan_project):
    root, _, _ = scan_project
    comparison = Comparison(root, 'dev', '123456789012', ['s3'])
    comparison.local_comparison = True
    comparison.stack_inputs['stack'] = ({}, {}, {})
    kind = 'CodePipeline.Pipeline'
    resource = {'resourceType': kind}
    rows = [('RestartExecutionOnUpdate', '`false`'), ('Stages[].Actions[].Name', '`a`'),
            ('Stages[].Actions[].InputArtifacts[].Name', '`same`'),
            ('Stages[].Actions[].OutputArtifacts[].Name', '`same`'),
            ('Stages[].Name', '`first`'), ('Stages[].Name', '`last`')]
    comparison.rows['codepipeline'] = {'001': [(f'001-{number:03d}', {'property': kind + '.' + prop,
                                      'value': value}) for number, (prop, value) in enumerate(rows, 1)]}
    template = root / 'infra/cloudformation/templates/shared.yaml'
    # An independent property still reports its real difference.
    definition = {'Properties': {'RestartExecutionOnUpdate': True, 'Stages': [{'Name': 'first'}]}}
    comparison.source = lambda *args: {'path': 'synthetic-model'}
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        comparison.compare_rows('codepipeline', '001', resource, 'stack', 'Pipeline', template, definition, {})
    stages = [item for item in comparison.results if '.Stages' in item['property']]
    assert len(stages) == 1 and stages[0]['category'] == 'difference', stages
    assert stages[0]['desired'] == [
        {'Actions': [{'Name': 'a', 'InputArtifacts': [{'Name': 'same'}],
                      'OutputArtifacts': [{'Name': 'same'}]}], 'Name': 'first'},
        {'Name': 'last'}], stages
    assert any(item['category'] == 'difference' and item['property'] == kind + '.RestartExecutionOnUpdate' for item in comparison.results), comparison.results


def check_cloudtrail_membership(scan_project):
    root, _, template = scan_project
    stack = 'cfn-stack-app-dev-data1'
    kind = 'CloudTrail.Trail'
    function = '[function](lambda.md#function)'
    other = '[other](lambda.md#other)'
    lambda_model = {'desired.service.lambda.serviceId': 'lambda'}
    for identity, logical in [('001', 'Function'), ('002', 'Other')]:
        lambda_model.update({f'desired.resource.{identity}.resourceType': 'Lambda.Function',
                             f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical,
                             f'desired.resource.{identity}.anchor': logical.lower()})
        template['Resources'][logical] = {'Type': 'AWS::Lambda::Function', 'Properties': {}}
    write_model(root / 'model/dev/123456789012/lambda.properties', lambda_model)
    fields = [
        ('IsLogging', '`true`'),
        ('EventSelectors[].IncludeManagementEvents', '`true`'),
        ('EventSelectors[].ReadWriteType', '`All`'),
        ('EventSelectors[].DataResources[].Type', '`AWS::S3::Object`'),
        ('EventSelectors[].DataResources[].Values', '`["arn:aws:s3"]`'),
        ('EventSelectors[].DataResources[].Type', '`AWS::Lambda::Function`'),
        ('EventSelectors[].DataResources[].Values', function),
        ('EventSelectors[].IncludeManagementEvents', '`false`'),
        ('EventSelectors[].DataResources[].Type', '`AWS::Lambda::Function`'),
        ('EventSelectors[].DataResources[].Values', other),
        ('EventSelectors[].DataResources[].Type', '`AWS::Lambda::Function`'),
        ('EventSelectors[].DataResources[].Values', function),
        ('EventSelectors[].DataResources[].Type', '`AWS::Lambda::Function`'),
        ('EventSelectors[].DataResources[].Values', function),
    ]
    model = {'desired.service.cloudtrail.serviceId': 'cloudtrail',
             'desired.resource.001.resourceType': kind,
             'desired.resource.001.cfn-logicalId': stack + '-Trail',
             'desired.resource.001.anchor': 'trail'}
    for number, (prop, value) in enumerate(fields, 1):
        model.update({f'desired.row.001-{number:03d}.property': kind + '.' + prop,
                      f'desired.row.001-{number:03d}.value': value, f'desired.row.001-{number:03d}.comment': '合成設定'})
    write_model(root / 'model/dev/123456789012/cloudtrail.properties', model)
    selectors = [
        {'IncludeManagementEvents': True, 'ReadWriteType': 'All', 'DataResources': [
            {'Type': 'AWS::S3::Object', 'Values': ['arn:aws:s3']},
            {'Type': 'AWS::Lambda::Function', 'Values': [{'Fn::GetAtt': ['Function', 'Arn']}]}]},
        {'IncludeManagementEvents': False, 'DataResources': [
            {'Type': 'AWS::Lambda::Function', 'Values': [{'Fn::GetAtt': ['Other', 'Arn']}]},
            {'Type': 'AWS::Lambda::Function', 'Values': [{'Fn::GetAtt': ['Function', 'Arn']}]},
            {'Type': 'AWS::Lambda::Function', 'Values': [{'Fn::GetAtt': ['Function', 'Arn']}]}]},
    ]
    template['Resources']['Trail'] = {'Type': 'AWS::CloudTrail::Trail',
                                     'Properties': {'IsLogging': True, 'EventSelectors': selectors}}
    mutate_template(root, template)

    def records(actual=selectors, order=lambda rows: rows, invalid=False):
        template['Resources']['Trail']['Properties']['EventSelectors'] = actual
        mutate_template(root, template)
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            comparison = Comparison(root, 'dev', '123456789012', ['cloudtrail'])
            rows = comparison.rows['cloudtrail']['001']
            original = json.dumps(rows)
            if invalid:
                rows = [(rid, row) for rid, row in rows if rid != '001-005']
            comparison.rows['cloudtrail']['001'] = order(rows)
            result = comparison.run()
            assert json.dumps(comparison.rows['cloudtrail']['001']) == json.dumps(order(rows)), 'comparison changed Model rows'
            if not invalid:
                assert json.dumps(rows) == original
            event = [item for item in result if item['property'] == kind + '.EventSelectors']
            assert len(event) == 1, result
            return event[0], result

    for order in (lambda rows: rows, lambda rows: rows[::-1], lambda rows: rows[::2] + rows[1::2]):
        event, result = records(order=order)
        assert event['category'] == 'matched' and all(item['category'] == 'matched' for item in result), result
    # Preserve flattened leaf values while moving a child to another parent.
    moved = json.loads(json.dumps(selectors))
    moved[0]['DataResources'].append(moved[1]['DataResources'].pop(0))
    assert records(moved)[0]['category'] == 'difference'
    missing = json.loads(json.dumps(selectors))
    missing[1]['DataResources'].pop()
    assert records(missing)[0]['category'] == 'difference', 'duplicate multiplicity lost'
    extra_parent = [*selectors, {'IncludeManagementEvents': False}]
    assert records(extra_parent)[0]['category'] == 'difference'
    changed = json.loads(json.dumps(selectors))
    changed[1]['DataResources'][0]['Type'] = 'AWS::S3::Object'
    assert records(changed)[0]['category'] == 'difference'
    template['Resources']['Trail']['Properties']['IsLogging'] = False
    event, result = records(invalid=True)
    assert event['category'] == 'uncompared' and 'membership unresolved' in event['reason'], result
    assert any(item['property'] == kind + '.IsLogging' and item['category'] == 'difference' for item in result), result


def check_condition_diagnostics():
    with tempfile.TemporaryDirectory(prefix='condition-diagnostics-') as directory:
        root = Path(directory)
        _, template = fixture(root, services=['s3'])
        template['Parameters']['Enable'] = {'Type': 'String', 'Default': 'false'}
        template['Conditions']['IsEnabled'] = {'Fn::Equals': [{'Ref': 'Enable'}, 'true']}
        template['Resources']['Bucket']['Condition'] = 'IsEnabled'
        parameters_path = root / 'infra/cloudformation/parameters/dev/123456789012/stack-1.json'
        name_input = {'ParameterKey': 'Name', 'ParameterValue': 'app-dev-data1'}

        def candidate(parameters=(), condition='IsEnabled'):
            template['Resources']['Bucket']['Condition'] = condition
            mutate_template(root, template)
            write(parameters_path, json.dumps([name_input, *parameters]))
            with patch('socket.socket', side_effect=AssertionError('network forbidden')):
                comparison, records = compare(root, ['s3'])
            return records

        def disabled(records):
            assert len(records) == 1 and records[0]['category'] == 'difference', records
            record = records[0]
            cause = record['cause']
            assert cause['kind'] == 'condition-disabled' and cause['result'] is False
            assert cause['stack'] == record['stack'] == 'cfn-stack-app-dev-data1'
            assert cause['logical'] == 'Bucket' and record['iac']['line'] > 0
            assert record['iac']['key'] == 'Resources.Bucket.Condition'
            assert cause['conditions'][cause['condition']]['result'] is False
            summary = iac_summary(records, 'dev', '123456789012', ['s3'])
            assert summary['issue_count'] == summary['proven_causes'] == 1
            assert summary['categories']['要判断'] == 1 and summary['categories']['原因未確定'] == 0
            report = iac_report('dev', '123456789012', ['s3'], records)
            assert 'Condition' in report and 'false' in report and 'Bucket' in report
            assert '意図的な無効化か設計との不整合か' in report
            entries, actions, _ = iac_dataset(records, 'dev', '123456789012', ['s3'])
            assert actions[0]['classification'] == 'ConditionによるCREATE無効化'
            artifact = {'environment': 'dev', 'target': '123456789012', 'services': ['s3'], 'iac': records}
            detail = detail_payload(artifact, 'iac', issue_id=actions[0]['id'])
            assert detail['items'][0]['cause'] == cause
            return cause, report

        cause, report = disabled(candidate([{'ParameterKey': 'Enable', 'ParameterValue': 'false'}]))
        assert cause['condition'] == 'IsEnabled'
        assert cause['inputs'] == [{'name': 'Enable', 'value': 'false', 'source': {
            'kind': 'parameter-file', 'path': parameters_path.relative_to(root).as_posix(), 'key': 'ParameterKey=Enable'}}]
        assert 'parameter-file' in report and 'stack-1.json' in report
        active = candidate([{'ParameterKey': 'Enable', 'ParameterValue': 'true'}])
        assert any(item['category'] == 'matched' for item in active) and not any(item.get('cause', {}).get('kind') == 'condition-disabled' for item in active)
        cause, report = disabled(candidate())
        assert cause['inputs'][0]['source'] == {'kind': 'template-default', 'path': 'infra/cloudformation/templates/shared.yaml', 'key': 'Parameters.Enable.Default'}
        assert 'template-default' in report
        template['Parameters']['Other'] = {'Type': 'String', 'Default': 'yes'}
        template['Conditions']['OtherEnabled'] = {'Fn::Equals': [{'Ref': 'Other'}, 'yes']}
        template['Conditions']['Combined'] = {'Fn::And': [{'Condition': 'IsEnabled'},
            {'Fn::Or': [{'Condition': 'OtherEnabled'}, {'Fn::Not': [{'Condition': 'IsEnabled'}]}]}]}
        cause, _ = disabled(candidate(condition='Combined'))
        assert set(cause['conditions']) == {'Combined', 'IsEnabled', 'OtherEnabled'}
        assert {item['name'] for item in cause['inputs']} == {'Enable', 'Other'}
        assert any(item['category'] == 'matched' for item in candidate([{'ParameterKey': 'Enable', 'ParameterValue': 'true'}], 'Combined'))
        for expression, reason in [({'Condition': 'Missing'}, 'unresolved'), ({'Condition': 'Broken'}, 'cyclic'),
                                   ('false', 'non-boolean'), ({'Fn::Equals': [{'Ref': 'Unknown'}, 'x']}, 'unsupported')]:
            template['Conditions']['Broken'] = expression
            records = candidate(condition='Broken')
            assert len(records) == 1 and records[0]['category'] == 'uncompared', records
            assert reason in records[0]['reason'], records
            assert 'cause' not in records[0]
            assert iac_summary(records, 'dev', '123456789012', ['s3'])['proven_causes'] == 0
        assert candidate(condition='Missing')[0]['category'] == 'uncompared'
        for supplied in (False, True):
            secret = 'fixture-confidential-condition'
            template['Parameters']['Confidential'] = {'Type': 'String', 'NoEcho': True, 'Default': secret}
            template['Conditions']['Private'] = {'Fn::Equals': [{'Ref': 'Confidential'}, 'other']}
            records = candidate([{'ParameterKey': 'Confidential', 'ParameterValue': secret}] if supplied else [], 'Private')
            cause, report = disabled(records)
            assert cause['inputs'][0]['value'] == '<masked sensitive parameter>'
            assert secret not in json.dumps(records) + json.dumps(iac_summary(records, 'dev', '123456789012', ['s3'])) + report
        template['Parameters']['SecretToken'] = {'Type': 'String', 'Default': 'fixture-token-condition'}
        template['Conditions']['NamedInputOff'] = {'Fn::Equals': [{'Ref': 'SecretToken'}, 'other']}
        records = candidate(condition='NamedInputOff')
        cause, report = disabled(records)
        assert 'fixture-token-condition' not in json.dumps(records) + report
        template['Parameters']['Numeric'] = {'Type': 'Number', 'NoEcho': True, 'Default': 8912}
        template['Conditions']['NumericOff'] = {'Fn::Equals': [{'Ref': 'Numeric'}, 1]}
        cause, report = disabled(candidate(condition='NumericOff'))
        assert cause['inputs'][0]['value'] == '<masked sensitive parameter>' and '8912' not in report
        template['Conditions']['Branch'] = {'Fn::If': ['IsEnabled', {'Condition': 'Missing'}, False]}
        cause, _ = disabled(candidate(condition='Branch'))
        assert set(cause['conditions']) == {'Branch', 'IsEnabled'}
        template['Conditions']['SubOff'] = {'Fn::Equals': [{'Fn::Sub': '${Enable}'}, 'true']}
        cause, _ = disabled(candidate(condition='SubOff'))
        assert cause['inputs'][0]['name'] == 'Enable'
        template['Conditions']['RegionOff'] = {'Fn::Equals': [{'Ref': 'AWS::Region'}, 'elsewhere']}
        cause, _ = disabled(candidate(condition='RegionOff'))
        assert cause['inputs'][0]['source']['path'] == 'project.json'
        assert cause['inputs'][0]['source']['key'] == 'awsRegion'
        for invalid in (True, 'false', None, 0):
            forged = dict(records[0], cause=dict(cause, result=invalid))
            assert iac_summary([forged], 'dev', '123456789012', ['s3'])['proven_causes'] == 0
        model = root / 'model/dev/123456789012/s3.properties'
        write(model, read_model(model) + 'desired.row.001-099.property=S3.BucketPolicy.PolicyDocument\n'
              'desired.row.001-099.value=policy.json\n'
              'desired.row.001-099.document={"Version":"2012-10-17","Statement":[]}\n')
        template['Resources']['Bucket'].pop('Condition')
        template['Resources']['Policy'] = {'Type': 'AWS::S3::BucketPolicy', 'Condition': 'IsEnabled',
                                           'Properties': {'Bucket': {'Ref': 'Bucket'}, 'PolicyDocument': {}}}
        mutate_template(root, template)
        write(parameters_path, json.dumps([name_input]))
        _, records = compare(root, ['s3'])
        child = next(item for item in records if item.get('cause', {}).get('kind') == 'condition-disabled')
        assert child['cause']['logical'] == 'Policy' and child['property'] == 'S3.BucketPolicy'
        assert child['iac']['key'] == 'Resources.Policy.Condition'
    print('Condition diagnostics: PASS (false/true/default/composite/unresolved/cyclic/non-boolean/masking)')


def check_scan_workflow(scan_project):
    root, values, template = scan_project
    checks(root, values, template)
    naming_target_scope_cases()
    resource_cases(root)
    extended_cases(root, template)
    sequential_reports(root)
    # Exercise the real scan boundary after five findings, without rerunning comparison.
    from model.core import ReferenceResolutionError
    for exception in (ReferenceResolutionError, OSError, ValueError, KeyError, ImportError, TypeError):
        retained = []
        def interrupted(comparison):
            comparison.sensitive_values.add('exception-secret')
            for index in range(5):
                comparison.record('difference', 's3', str(index), 'Setting', 'value mismatch', desired=1, actual=2)
            retained.extend(comparison.results)
            raise exception('interrupted exception-secret')
        with patch.object(Comparison, 'run', autospec=True, side_effect=interrupted) as invoked:
            partial = scan(root, 'dev', '123456789012', ['s3'])
        assert invoked.call_count == 1 and partial['iac'][:5] == retained
        assert len(partial['iac']) == 6 and partial['iac'][-1]['comparison_incomplete']
        category = 'uncompared' if exception is ReferenceResolutionError else 'error'
        assert partial['iac'][-1]['category'] == category
        status = summary(partial)
        assert status['iac_differences'] == 5 and status['comparison_incomplete']
        assert status['iac_status'] == ('partial' if category == 'uncompared' else 'error')
        report = iac_report('dev', '123456789012', ['s3'], partial['iac'], partial['iac_display'])
        assert '比較途中終了' in report
        assert 'exception-secret' not in json.dumps(partial) + report + json.dumps(detail_payload(partial, 'iac'))
        assert sum(len(group['members']) for group in partial['iac_issues']) == 6
        if exception is ReferenceResolutionError:
            assert any(warning['code'] == 'reference.unresolved' for warning in partial['warnings'])


check_action_report = action_report_cases


check_mismatch_display = mismatch_display_cases


check_state_report = state_report_cases


def check_summary_detail_cli():
    artifact = summary_fixture()
    entries, actions, _ = iac_dataset(artifact['iac'], 'dev', 'cde', artifact['services'], artifact['iac_display'])
    artifact['iac_issues'] = [dict(group, members=[entries[i]['record_index'] for i in group['members']]) for group in actions]
    pending = detail_payload(artifact, 'iac_issues', category='比較未完了')['items'][0]
    with tempfile.TemporaryDirectory(prefix='iac-detail-cli-') as temporary:
        file = Path(temporary) / 'artifact.json'; write(file, json.dumps(artifact))
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'framework/scripts/issues_scan.py'), 'detail',
            '--artifact', str(file), '--section', 'iac', '--issue-id', pending['id'], '--offset', '950', '--limit', '50'],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        cli = json.loads(result.stdout)
        assert cli['total'] == 1000 and cli['offset'] == 950 and len(cli['items']) == 50




check_comparison_repair = comparison_repair_cases


check_local_reference = local_reference_cases


check_reference_identity_report = reference_identity_report_cases


check_reference_property_contract = reference_property_contract_cases


check_symbolic_string = symbolic_string_cases


@patch('socket.socket', side_effect=AssertionError('network forbidden'))
def glue_secret_reference_cases(_network):
    from cloudformation_inputs import Blocked
    with tempfile.TemporaryDirectory(prefix='glue-secret-references-') as directory:
        root = Path(directory) / 'project'
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        link = '[PENDING_DEPLOY](#glue-one)'
        secret = '[PENDING_DEPLOY](secrets-manager.md#secret-one)'
        specifications = {
            'glue': [
                ('Connection1', 'Glue.Connection', 'glue-one', [
                    ('Name', '[PENDING_DEPLOY](#glue-one)'),
                    ('CatalogId', '`123456789012`'), ('ConnectionInput.Name', '`connection`'),
                    ('ConnectionInput.AuthenticationConfiguration.SecretArn', secret)]),
                ('Connection2', 'Glue.Connection', 'glue-two', [('ConnectionInput.Name', '`connection`')]),
                ('Job', 'Glue.Job', 'glue-job', [('Connections', '`' + json.dumps({'Connections': [link]}) + '`')]),
            ],
            'secrets-manager': [
                ('Secret1', 'SecretsManager.Secret', 'secret-one', [('Name', '`app/dev/secret`')]),
                ('Secret2', 'SecretsManager.Secret', 'secret-two', [('Name', '`app/dev/secret`')]),
            ],
            'iam': [('Role', 'IAM.Role', 'iam-role', [
                ('Policies[].PolicyName', '`secret`'),
                ('Policies[].PolicyDocument', '`' + json.dumps({'Statement': [{'Resource': secret}]}) + '`')])],
        }
        for service, resources in specifications.items():
            values = {f'desired.service.{service}.serviceId': service}
            for number, (logical, kind, anchor, rows) in enumerate(resources, 1):
                identity = f'{number:03d}'
                values.update({f'desired.resource.{identity}.resourceType': kind,
                               f'desired.resource.{identity}.logicalId': logical,
                               f'desired.resource.{identity}.anchor': anchor,
                               f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical})
                for index, (prop, value) in enumerate(rows, 1):
                    prefix = f'desired.row.{identity}-{index:03d}'
                    values.update({prefix + '.property': kind + '.' + prop,
                                   prefix + '.value': value, prefix + '.comment': '参照fixture'})
                template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
            write(root / f'model/dev/123456789012/{service}.properties',
                  '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
        actual = template['Resources']
        actual['Connection1']['Properties'] = {'CatalogId': '123456789012', 'ConnectionInput': {
            'Name': 'connection', 'AuthenticationConfiguration': {'SecretArn': {'Ref': 'Secret1'}}}}
        actual['Connection2']['Properties'] = {'ConnectionInput': {'Name': 'connection'}}
        actual['Job']['Properties'] = {'Connections': {'Connections': [{'Ref': 'Connection1'}]}}
        for logical in ('Secret1', 'Secret2'):
            actual[logical]['Properties'] = {'Name': 'app/dev/secret'}
        actual['Role']['Properties'] = {'Policies': [{'PolicyName': 'secret', 'PolicyDocument': {
            'Statement': [{'Resource': {'Ref': 'Secret1'}}]}}]}
        mutate_template(root, template)
        comparison, records = compare(root, list(specifications))
        tested = {'Glue.Job.Connections', 'Glue.Connection.ConnectionInput', 'IAM.Role.Policies'}
        selected = [item for item in records if item['property'] in tested and not (item['service'] == 'glue' and item['resource'] == '002')]
        assert len(selected) == 3 and all(item['category'] == 'matched' for item in selected), selected
        connection = comparison.reference('glue', link)
        assert connection['$attribute'] == 'Name'
        assert same(connection, comparison.evaluate(stack, {'Ref': 'Connection1'}))
        assert same(connection, comparison.evaluate(stack, {'Fn::GetAtt': ['Connection1', 'Name']}))
        arn = comparison.reference('glue', secret, 'Arn')
        assert arn['$attribute'] == 'Id'
        assert same(arn, comparison.evaluate(stack, {'Ref': 'Secret1'}))
        assert same(arn, comparison.evaluate(stack, {'Fn::GetAtt': ['Secret1', 'Id']}))
        with pytest.raises((Blocked, KeyError)):
            comparison.evaluate(stack, {'Fn::GetAtt': ['Secret1', 'Arn']})
        with pytest.raises(Blocked, match='not confirmed'):
            comparison.reference('glue', link, 'Arn')
        actual['Job']['Properties']['Connections']['Connections'] = [{'Fn::GetAtt': ['Connection1', 'Name']}]
        actual['Connection1']['Properties']['ConnectionInput']['AuthenticationConfiguration']['SecretArn'] = {'Fn::GetAtt': ['Secret1', 'Id']}
        actual['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'][0]['Resource'] = {'Fn::GetAtt': ['Secret1', 'Id']}
        mutate_template(root, template)
        _, records = compare(root, list(specifications))
        selected = [item for item in records if item['property'] in tested and not (item['service'] == 'glue' and item['resource'] == '002')]
        assert len(selected) == 3 and all(item['category'] == 'matched' for item in selected), selected
        # Identical names/labels cannot merge distinct logical resources.
        actual['Job']['Properties']['Connections']['Connections'] = [{'Ref': 'Connection2'}]
        actual['Connection1']['Properties']['ConnectionInput']['AuthenticationConfiguration']['SecretArn'] = {'Ref': 'Secret2'}
        actual['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'][0]['Resource'] = {'Ref': 'Secret2'}
        mutate_template(root, template)
        _, records = compare(root, list(specifications))
        selected = [item for item in records if item['property'] in tested and not (item['service'] == 'glue' and item['resource'] == '002')]
        assert len(selected) == 3 and all(item['category'] == 'difference' for item in selected), selected
        actual['Connection1']['Properties']['ConnectionInput']['AuthenticationConfiguration']['SecretArn'] = {'Fn::GetAtt': ['Secret1', 'Arn']}
        mutate_template(root, template)
        _, records = compare(root, list(specifications))
        assert next(item for item in records if item['property'] == 'Glue.Connection.ConnectionInput')['category'] == 'uncompared'


check_glue_secret_reference = glue_secret_reference_cases


def check_arn_array_reference_forms():
    with tempfile.TemporaryDirectory(prefix='arn-array-reference-') as directory:
        root = Path(directory) / 'project'
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        values = {'desired.service.iam.serviceId': 'iam'}
        for identity, kind, logical in [('001', 'IAM.Role', 'Role'),
                                        ('002', 'IAM.ManagedPolicy', 'Policy'),
                                        ('003', 'IAM.ManagedPolicy', 'OtherPolicy')]:
            values.update({f'desired.resource.{identity}.resourceType': kind,
                           f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical,
                           f'desired.resource.{identity}.anchor': logical.lower()})
            template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
        # Equal display names do not establish resource identity.
        for logical in ('Policy', 'OtherPolicy'):
            template['Resources'][logical]['Properties']['ManagedPolicyName'] = 'same-name'
        prop = 'IAM.Role.ManagedPolicyArns'
        link = '[same-name](#policy)'
        values['desired.row.001-001.property'] = prop
        values['desired.row.001-001.value'] = '`' + json.dumps([link]) + '`'

        def publish():
            write(root / 'model/dev/123456789012/iam.properties',
                  '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
            mutate_template(root, template)

        def record():
            comparison, results = compare(root, ['iam'])
            return comparison, next(item for item in results if item['property'] == prop)

        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            template['Resources']['Role']['Properties']['ManagedPolicyArns'] = [{'Ref': 'Policy'}]
            publish()
            comparison, result = record()
            assert result['category'] == 'matched', result
            from iac_values import ResourceReference
            policy = ResourceReference({'$resource': ['iam', '002'], '$attribute': 'PolicyArn'})
            other = ResourceReference({'$resource': ['iam', '003'], '$attribute': 'PolicyArn'})
            # The receiving ARN form uses the producer's formal PolicyArn attribute.
            with patch.object(comparison, 'reference', return_value=policy) as reference:
                row = {'property': prop, 'value': values['desired.row.001-001.value']}
                assert comparison.desired_value('iam', row, 'IAM.Role') == [policy]
                reference.assert_called_once_with('iam', link, 'Arn')
            assert comparison.reference_same(policy, policy, 'IAM.Role', 'ManagedPolicyArns[]') is True
            assert comparison.reference_same(policy, other, 'IAM.Role', 'ManagedPolicyArns[]') is False
            assert comparison.reference_forms('IAM.Role', 'ManagedPolicyArns[]') == {'Arn'}
            template['Resources']['Role']['Properties']['ManagedPolicyArns'] = [{'Ref': 'OtherPolicy'}]
            publish()
            assert record()[1]['category'] == 'difference'
            assert comparison.reference_forms('IAM.Role', 'ManagedPolicyArns') is None
            assert comparison.reference_forms('IAM.Role', 'UnknownPolicyArns[]') is None
            assert comparison.reference_forms('IAM.Role', 'Description[]') is None
            assert comparison.reference_forms('IAM.Role', 'Tags[].Value') is None
            assert comparison.reference_forms('IAM.Role', 'ArnLikeNames[]') is None
            assert comparison.reference_forms('IAM.User', 'Groups[]') is None
            expect_error(lambda: comparison.desired_reference('iam', link, 'IAM.User', 'Groups[]'),
                         'reference property contract unproven')
            for unresolved, reason in (('[same-name](#missing-policy)', 'reference mapping matches=0'),
                                       ('`PENDING_DEPLOY`', 'desired value is unresolved')):
                row = {'property': prop, 'value': unresolved}
                expect_error(lambda: comparison.desired_value('iam', row, 'IAM.Role'), reason)


def check_eventbridge_reference_literals():
    from iac_values import ResourceReference
    with tempfile.TemporaryDirectory(prefix='eventbridge-reference-') as directory:
        root = Path(directory)
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        functions = {'desired.service.lambda.serviceId': 'lambda'}
        for identity, logical in [('001', 'Function'), ('002', 'OtherFunction')]:
            functions.update({f'desired.resource.{identity}.resourceType': 'Lambda.Function',
                              f'desired.resource.{identity}.anchor': logical.lower(),
                              f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical})
            template['Resources'][logical] = {'Type': 'AWS::Lambda::Function', 'Properties': {
                'FunctionName': {'Fn::If': ['Active', {'Fn::Sub': 'function-${Name}'}, 'inactive']}}}
        write(root / 'model/dev/123456789012/lambda.properties', '\n'.join(f'{k}={v}' for k, v in functions.items()) + '\n')
        mutate_template(root, template)
        comparison, _ = compare(root, ['s3', 'lambda'])
        bucket = comparison.evaluate(stack, {'Ref': 'Bucket'})
        name = comparison.reference_literal(bucket)
        callback = lambda left, right, path: comparison.reference_same(left, right, 'Events.Rule', path)
        assert same(name, bucket, reference=callback, path='EventPattern.detail.requestParameters.bucketName[]')
        assert same(bucket, name, reference=callback)
        assert same('wrong', bucket, reference=callback) is False
        function = comparison.reference('lambda', '[function](#function)', 'Arn')
        arn = comparison.reference_literal(function)
        assert arn == 'arn:aws:lambda:ap-northeast-1:123456789012:function:function-' + comparison.stack_inputs[stack][1]['Name']
        assert same(function, arn, reference=callback)
        for wrong in [arn.replace('arn:aws:', 'arn:aws-cn:'), arn.replace('ap-northeast-1', 'us-east-1'),
                      arn.replace('123456789012', '999999999999'), arn + ':1', arn + ':alias',
                      arn.replace(':function:', ':layer:'), arn + '-other']:
            assert same(function, wrong, reference=callback) is False
        other = comparison.reference('lambda', '[other](#otherfunction)', 'Arn')
        assert same(function, other, reference=callback) is False
        function_name = ResourceReference(dict(function, **{'$attribute': 'FunctionName'}))
        assert same(function, function_name, reference=callback) is False
        assert not same([bucket, function], [function, bucket], reference=callback)
        assert not same([bucket, bucket], [bucket], reference=callback)
        assert selected_same({'Arn': function}, {'Arn': arn, 'Id': 'extra'}, reference=callback)
        assert comparison.redacted(arn) == '<masked ARN/secret>'
        properties = comparison.stack_inputs[stack][0]['Resources']['Function']['Properties']
        del properties['FunctionName']
        assert same(function, arn, reference=callback) is None
        properties['FunctionName'] = 'function:alias'
        assert same(function, arn, reference=callback) is None
        properties['FunctionName'] = 'function-explicit'
        comparison.resources['lambda']['001']['cfn-logicalId'] = stack + '-Missing'
        assert same(function, arn, reference=callback) is None
        comparison.resources['lambda']['001']['cfn-logicalId'] = stack + '-Function'
        comparison.stack_inputs[stack][0]['Resources']['Function']['Condition'] = 'Inactive'
        comparison.stack_inputs[stack][0]['Conditions']['Inactive'] = {'Fn::Equals': ['yes', 'no']}
        comparison.symbols.clear()
        assert same(function, arn, reference=callback) is None
        # Execution account comes from target inputs, never the model link label.
        del comparison.stack_inputs[stack][0]['Resources']['Function']['Condition']
        comparison.stack_inputs[stack][2]['AWS::AccountId'] = '999999999999'
        assert same(function, arn, reference=callback) is False


@patch('socket.socket', side_effect=AssertionError('network forbidden'))
def check_glue_connection_names(_network):
    from cloudformation_inputs import Blocked
    with tempfile.TemporaryDirectory(prefix='glue-connection-names-') as directory:
        root = Path(directory)
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        values = {'desired.service.glue.serviceId': 'glue'}
        for identity, logical, kind in [('001', 'Connection', 'Glue.Connection'),
                                        ('002', 'OtherConnection', 'Glue.Connection'), ('003', 'Job', 'Glue.Job'),
                                        ('004', 'Project', 'CodeBuild.Project')]:
            values.update({f'desired.resource.{identity}.resourceType': kind,
                           f'desired.resource.{identity}.anchor': logical.lower(),
                           f'desired.resource.{identity}.cfn-logicalId': stack + '-' + logical})
            template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
        values.update({'desired.row.003-001.property': 'Glue.Job.Connections',
                       'desired.row.003-001.value': '`{"Connections":["[PENDING_DEPLOY](#connection)"]}`'})
        write(root / 'model/dev/123456789012/glue.properties', '\n'.join(f'{k}={v}' for k, v in values.items()) + '\n')
        template['Resources']['Job']['Properties'] = {'Connections': {'Connections': ['app-dev-data1']}}
        template['Resources']['Project']['Properties'] = {'Name': {'Fn::Sub': 'project-${Name}'}}
        template['Mappings'] = {'Names': {'dev': {'Connection': 'app-dev-data1'}}}
        properties = template['Resources']['Connection']['Properties']
        for name in ['app-dev-data1', {'Ref': 'Name'}, {'Fn::Sub': '${Name}'},
                     {'Fn::Join': ['-', ['app', 'dev', 'data1']]},
                     {'Fn::If': ['Active', {'Ref': 'Name'}, 'inactive']},
                     {'Fn::FindInMap': ['Names', 'dev', 'Connection']},
                     {'Fn::Select': [0, {'Fn::Split': [',', 'app-dev-data1,other']}]}]:
            properties['ConnectionInput'] = {'Name': name}
            mutate_template(root, template)
            comparison, records = compare(root, ['glue'])
            record = next(item for item in records if item['property'] == 'Glue.Job.Connections')
            assert record['category'] == 'matched', (name, record)
            assert comparison.evaluate(stack, {'Fn::Sub': 'prefix-${Connection}'}) == 'prefix-app-dev-data1'
            assert comparison.evaluate(stack, {'Fn::Sub': '${Connection.Name}'}) == 'app-dev-data1'
        for name, expected in [('different', 'difference'), ({'Ref': 'Missing'}, 'uncompared'),
                               ({'Ref': 'Connection'}, 'uncompared'), ({'Fn::Sub': '${Connection}'}, 'uncompared'),
                               ({'Ref': 'OtherConnection'}, 'uncompared'), ('UNSET', 'uncompared')]:
            properties['ConnectionInput'] = {'Name': name}
            template['Resources']['OtherConnection']['Properties'] = {'ConnectionInput': {'Name': {'Ref': 'Connection'}}}
            mutate_template(root, template)
            comparison, records = compare(root, ['glue'])
            record = next(item for item in records if item['property'] == 'Glue.Job.Connections')
            assert record['category'] == expected, (name, record)
        # A stray top-level Name cannot supply Glue ConnectionInput.Name.
        properties.clear()
        properties['Name'] = 'app-dev-data1'
        mutate_template(root, template)
        comparison, records = compare(root, ['glue'])
        record = next(item for item in records if item['property'] == 'Glue.Job.Connections')
        assert record['category'] == 'uncompared', record
        assert 'explicit name property' in record['reference_diagnostics'][0]['reason'], record
        properties.clear()
        properties['ConnectionInput'] = {'Name': {'Ref': 'Connection'}}
        mutate_template(root, template)
        comparison, _ = compare(root, ['glue'])
        with pytest.raises(Blocked, match='cyclic resource substitution'):
            comparison.evaluate(stack, {'Fn::Sub': '${Connection}'})
        # Existing direct name properties still use the same evaluator.
        bucket = comparison.evaluate(stack, {'Ref': 'Bucket'})
        assert comparison.reference_literal(bucket) == 'bucket-app-dev-data1'
        project = comparison.evaluate(stack, {'Ref': 'Project'})
        assert comparison.reference_literal(project) == 'project-app-dev-data1'
        assert comparison.evaluate(stack, {'Fn::Sub': '${Project}'}) == 'project-app-dev-data1'


@patch('socket.socket', side_effect=AssertionError('network forbidden'))
def check_added_reference_properties(_network):
    from cloudformation_inputs import Blocked
    from iac_values import ResourceReference
    with tempfile.TemporaryDirectory(prefix='added-reference-properties-') as directory:
        root = Path(directory)
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        models = {}
        specs = [('vpc', 'Vpc', 'EC2.VPC', 'VpcId'), ('vpc', 'Subnet', 'EC2.Subnet', 'SubnetId'),
                 ('vpc', 'RouteTable', 'EC2.RouteTable', 'RouteTableId'),
                 ('security-group', 'Group', 'EC2.SecurityGroup', 'GroupId'),
                 ('iam', 'Role', 'IAM.Role', 'RoleName'), ('iam', 'Profile', 'IAM.InstanceProfile', 'InstanceProfileName'),
                 ('glue', 'Security', 'Glue.SecurityConfiguration', 'Name'),
                 ('lambda', 'Function', 'Lambda.Function', 'FunctionName'),
                 ('cloudwatch-logs', 'Log', 'Logs.LogGroup', 'LogGroupName'),
                 ('route53', 'Zone', 'Route53.HostedZone', 'Id'), ('sqs', 'Queue', 'SQS.Queue', 'QueueUrl'),
                 ('secrets-manager', 'Secret', 'SecretsManager.Secret', 'Id'),
                 ('kms', 'Key', 'KMS.Key', 'KeyId'), ('kms', 'Alias', 'KMS.Alias', 'AliasName')]
        links, symbols = {}, {}
        for service, logical, kind, attr in specs:
            model = models.setdefault(service, {f'desired.service.{service}.serviceId': service})
            for suffix in ('', 'Other'):
                identity = logical + suffix
                model.update({f'desired.resource.{identity}.resourceType': kind,
                              f'desired.resource.{identity}.anchor': identity.lower(),
                              f'desired.resource.{identity}.cfn-logicalId': stack + '-' + identity})
                template['Resources'][identity] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
            links[logical] = f'[PENDING_DEPLOY]({service}.md#{logical.lower()})'
            symbols[logical] = ResourceReference({'$resource': [service, logical], '$attribute': attr})
        for service, model in models.items():
            write(root / f'model/dev/123456789012/{service}.properties', '\n'.join(f'{k}={v}' for k, v in model.items()) + '\n')
        template['Resources']['Group']['Properties']['VpcId'] = {'Ref': 'Vpc'}
        mutate_template(root, template)
        comparison, _ = compare(root, list(models) + ['s3'])
        links['Bucket'] = '[PENDING_DEPLOY](s3.md#s3-bucket-app-dev-data1)'
        symbols['Bucket'] = comparison.evaluate(stack, {'Ref': 'Bucket'})
        cases = {
            'Bucket': ['CloudTrail.Trail.S3BucketName', 'CodePipeline.Pipeline.ArtifactStore.Location', 'Lambda.Function.Code.S3Bucket'],
            'Log': ['CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName', 'Lambda.Function.LoggingConfig.LogGroup', 'EC2.FlowLog.LogGroupName'],
            'Vpc': ['CodeBuild.Project.VpcConfig.VpcId', 'EC2.Subnet.VpcId', 'EC2.SecurityGroup.VpcId',
                    'EC2.RouteTable.VpcId', 'EC2.VPCEndpoint.VpcId', 'Route53.HostedZone.VPCs[].VPCId'],
            'Subnet': ['EC2.Instance.SubnetId', 'CodeBuild.Project.VpcConfig.Subnets[]', 'Lambda.Function.VpcConfig.SubnetIds[]',
                       'EC2.VPCEndpoint.SubnetIds[]', 'Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SubnetId',
                       'MWAA.Environment.NetworkConfiguration.SubnetIds[]', 'QuickSight.VPCConnection.SubnetIds[]'],
            'Group': ['CodeBuild.Project.VpcConfig.SecurityGroupIds[]', 'EC2.Instance.SecurityGroupIds[]',
                      'EC2.SecurityGroupIngress.GroupId', 'EC2.SecurityGroupIngress.SourceSecurityGroupId',
                      'EC2.SecurityGroupEgress.GroupId', 'EC2.SecurityGroupEgress.DestinationSecurityGroupId',
                      'EC2.SecurityGroup.SecurityGroupEgress[].DestinationSecurityGroupId',
                      'EC2.VPCEndpoint.SecurityGroupIds[]', 'Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList[]',
                      'Lambda.Function.VpcConfig.SecurityGroupIds[]', 'MWAA.Environment.NetworkConfiguration.SecurityGroupIds[]',
                      'QuickSight.VPCConnection.SecurityGroupIds[]'],
            'RouteTable': ['EC2.SubnetRouteTableAssociation.RouteTableId', 'EC2.VPCEndpoint.RouteTableIds[]'],
            'Role': ['Glue.Job.Role', 'IAM.InstanceProfile.Roles[]'],
            'Profile': ['EC2.Instance.IamInstanceProfile'], 'Security': ['Glue.Job.SecurityConfiguration'],
            'Function': ['Lambda.Permission.FunctionName'], 'Zone': ['Route53.RecordSet.HostedZoneId'],
            'Secret': ['SecretsManager.RotationSchedule.SecretId'], 'Queue': ['SQS.QueuePolicy.Queues[]'],
            'Alias': ['CodeCommit.Repository.KmsKeyId', 'EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId',
                      'MWAA.Environment.KmsKey', 'SecretsManager.Secret.KmsKeyId'],
            'Key': ['KMS.Alias.TargetKeyId'],
        }
        for logical, properties in cases.items():
            for prop in properties:
                kind, path = '.'.join(prop.split('.')[:2]), '.'.join(prop.split('.')[2:])
                symbol = comparison.desired_reference('s3', links[logical], kind, path)
                assert same(symbol, symbols[logical]), prop
                assert comparison.reference_same(symbol, comparison.evaluate(stack, {'Ref': logical}), kind, path), prop
                other = ResourceReference(dict(symbol, **{'$resource': [symbol['$resource'][0], logical + 'Other']}))
                if logical != 'Bucket':
                    assert comparison.reference_same(symbol, other, kind, path) is False, prop
                wrong = 'Role' if logical != 'Role' else 'Secret'
                with pytest.raises(Blocked):
                    comparison.desired_reference('s3', links[wrong], kind, path)
                with pytest.raises(Blocked):
                    comparison.desired_reference('s3', links[logical], kind, path, 'Unknown')
                with pytest.raises(Blocked, match='mapping matches=0'):
                    comparison.desired_reference('s3', links[logical].replace('#', '#missing'), kind, path)
                service, identity = symbol['$resource']
                comparison.resources[service][identity]['resourceMode'] = 'IMPORT'
                with pytest.raises(Blocked, match='IMPORT'):
                    comparison.desired_reference('s3', links[logical], kind, path)
                comparison.resources[service][identity].pop('resourceMode')
        # Multiple accepted forms prove equivalence only for the same logical resource.
        for logical, kind, path in [('Role', 'Glue.Job', 'Role'), ('Function', 'Lambda.Permission', 'FunctionName')]:
            arn = comparison.evaluate(stack, {'Fn::GetAtt': [logical, 'Arn']})
            assert comparison.reference_same(symbols[logical], arn, kind, path)
            with pytest.raises(Blocked):
                comparison.desired_reference('s3', links[logical], kind, path, 'RoleId' if logical == 'Role' else 'Version')
        assert comparison.reference_same(symbols['Role'], 'arn:aws:iam::123456789012:role/example', 'Glue.Job', 'Role') is None
        for logical in ('Alias', 'Key'):
            for prop in cases['Alias']:
                kind, path = '.'.join(prop.split('.')[:2]), '.'.join(prop.split('.')[2:])
                symbol = comparison.desired_reference('s3', links[logical], kind, path)
                assert same(symbol, symbols[logical])
                assert comparison.reference_same(symbols['Alias'], symbols['Key'], kind, path) is False
        alias_arn = comparison.desired_reference('s3', links['Alias'], 'CodePipeline.Pipeline', 'ArtifactStore.EncryptionKey.Id')
        assert alias_arn['$attribute'] == 'AliasArn'
        assert comparison.reference_same(symbols['Key'], comparison.evaluate(stack, {'Fn::GetAtt': ['Key', 'Arn']}),
                                         'CodePipeline.Pipeline', 'ArtifactStore.EncryptionKey.Id') is False
        callback = lambda a, b, p: comparison.reference_same(a, b, 'EC2.VPCEndpoint', p)
        assert same([symbols['Subnet'], symbols['Group']], [symbols['Group'], symbols['Subnet']], reference=callback) is False
        assert same([symbols['Subnet'], symbols['Subnet']], [symbols['Subnet']], reference=callback) is False
        # Missing/conditional VpcId cannot turn a group name into a group ID; cycles stop.
        document = comparison.stack_inputs[stack][0]
        group = document['Resources']['Group']['Properties']
        for vpc in [None, {'Ref': 'AWS::NoValue'}, {'Fn::If': ['Active', {'Ref': 'AWS::NoValue'}, {'Ref': 'Vpc'}]},
                    {'Ref': 'Role'}, {'Ref': 'Group'}, 'UNSET']:
            group['VpcId'] = vpc
            comparison.symbols.clear()
            with pytest.raises(Blocked):
                comparison.evaluate(stack, {'Ref': 'Group'})
            assert same(comparison.evaluate(stack, {'Fn::GetAtt': ['Group', 'GroupId']}), symbols['Group'])
        group['VpcId'] = {'Fn::If': ['Active', {'Ref': 'Vpc'}, {'Ref': 'AWS::NoValue'}]}
        comparison.symbols.clear()
        assert same(comparison.evaluate(stack, {'Ref': 'Group'}), symbols['Group'])
        group['VpcId'] = 'vpc-0123456789abcdef0'
        comparison.symbols.clear()
        assert same(comparison.evaluate(stack, {'Ref': 'Group'}), symbols['Group'])
        # The API catalog does not prove this Group ARN as a CFn return attribute.
        write(root / 'model/dev/123456789012/quicksight.properties', '\n'.join([
            'desired.service.quicksight.serviceId=quicksight',
            'desired.resource.001.resourceType=QuickSight.Group',
            'desired.resource.001.anchor=group',
            'desired.row.001-001.property=QuickSight.Group.Arn',
            'desired.row.001-001.value=[PENDING_DEPLOY](#group)',
        ]) + '\n')
        with pytest.raises(Blocked, match='reference attribute not confirmed: Arn'):
            comparison.desired_reference('s3', '[PENDING_DEPLOY](quicksight.md#group)',
                                         'QuickSight.DataSource', 'Permissions[].Principal')
        with pytest.raises(Blocked, match='reference target must be'):
            comparison.desired_reference('s3', links['Role'], 'QuickSight.DataSource', 'Permissions[].Principal')
        assert same(comparison.desired_reference('s3', links['Vpc'], 'EC2.FlowLog', 'ResourceId',
                                                context={'ResourceType': 'VPC'}), symbols['Vpc'])
        for context in ({}, {'ResourceType': 'Subnet'}, {'ResourceType': 'UNSET'}):
            with pytest.raises(Blocked, match='ResourceType=VPC'):
                comparison.desired_reference('s3', links['Vpc'], 'EC2.FlowLog', 'ResourceId', context=context)
        with pytest.raises(Blocked):
            comparison.desired_reference('s3', links['Subnet'], 'EC2.FlowLog', 'ResourceId', context={'ResourceType': 'VPC'})
        with pytest.raises(Blocked):
            comparison.desired_reference('s3', links['Vpc'], 'EC2.FlowLog', 'ResourceId', 'CidrBlock', context={'ResourceType': 'VPC'})
        # Context-dependent fields stay unproven without a confirmed property contract.
        for kind, path in [('EC2.FlowLog', 'ResourceId'), ('CodeBuild.Project', 'Environment.EnvironmentVariables[].Value'),
                           ('Route53.RecordSet', 'ResourceRecords[]')]:
            with pytest.raises(Blocked, match='property contract unproven'):
                comparison.desired_reference('s3', links['Role'], kind, path)


@patch('socket.socket', side_effect=AssertionError('network forbidden'))
def check_aws_standard_comparison(_network):
    from cloudformation_inputs import Blocked
    from iac_values import ResourceReference, unordered_same
    with tempfile.TemporaryDirectory(prefix='aws-standard-comparison-') as directory:
        root = Path(directory)
        _, template = fixture(root, services=['s3'])
        stack = 'cfn-stack-app-dev-data1'
        role = '[role](iam.md#role)'
        policy = '[policy](iam.md#policy)'
        secret = '[secret](secrets-manager.md#secret)'
        bucket = '[bucket](s3.md#s3-bucket-app-dev-data1)'
        specs = {
            'iam': [('Role', 'IAM.Role', 'role', [('RoleName', '`role`'), ('ManagedPolicyArns', policy)]),
                    ('Policy', 'IAM.ManagedPolicy', 'policy', [('Roles', role)])],
            'secrets-manager': [('Secret', 'SecretsManager.Secret', 'secret', [('Name', '`app/secret`')])],
            'codebuild': [('Project', 'CodeBuild.Project', 'project', [
                ('Environment.EnvironmentVariables[].Name', '`BUCKET`'),
                ('Environment.EnvironmentVariables[].Value', bucket),
                ('Environment.EnvironmentVariables[].Type', '`PLAINTEXT`'),
                ('Environment.EnvironmentVariables[].Name', '`SECRET`'),
                ('Environment.EnvironmentVariables[].Value', secret),
                ('Environment.EnvironmentVariables[].Type', '`SECRETS_MANAGER`')])],
        }
        for service, resources in specs.items():
            values = {f'desired.service.{service}.serviceId': service}
            for logical, kind, anchor, rows in resources:
                values.update({f'desired.resource.{logical}.resourceType': kind,
                               f'desired.resource.{logical}.anchor': anchor,
                               f'desired.resource.{logical}.cfn-logicalId': stack + '-' + logical})
                for index, (prop, value) in enumerate(rows, 1):
                    prefix = f'desired.row.{logical}-{index:03d}'
                    values.update({prefix + '.property': kind + '.' + prop, prefix + '.value': value})
                template['Resources'][logical] = {'Type': 'AWS::' + kind.replace('.', '::'), 'Properties': {}}
            write(root / f'model/dev/123456789012/{service}.properties',
                  '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
        resources = template['Resources']
        resources['Role']['Properties'] = {'RoleName': 'role', 'ManagedPolicyArns': [{'Ref': 'Policy'}]}
        resources['Secret']['Properties'] = {'Name': 'app/secret'}
        environment = {'EnvironmentVariables': [{'Name': 'BUCKET', 'Value': {'Ref': 'Bucket'}, 'Type': 'PLAINTEXT'},
                                                {'Name': 'SECRET', 'Value': 'app/secret', 'Type': 'SECRETS_MANAGER'}]}
        resources['Project']['Properties']['Environment'] = environment
        mutate_template(root, template)
        comparison, records = compare(root, list(specs))
        tested = {'IAM.Role.ManagedPolicyArns', 'IAM.ManagedPolicy.Roles', 'CodeBuild.Project.Environment'}
        selected = [item for item in records if item['property'] in tested]
        assert len(selected) == 3 and all(item['category'] == 'matched' for item in selected), selected
        symbol = comparison.reference('iam', policy, 'Arn')
        assert symbol['$attribute'] == 'PolicyArn'
        assert same(symbol, comparison.evaluate(stack, {'Ref': 'Policy'}))
        assert same(symbol, comparison.evaluate(stack, {'Fn::GetAtt': ['Policy', 'PolicyArn']}))
        with pytest.raises((Blocked, KeyError)):
            comparison.evaluate(stack, {'Fn::GetAtt': ['Policy', 'Arn']})
        # Both attachment locations deduplicate one proven edge; disabled/missing edges cannot match.
        document = comparison.stack_inputs[stack][0]
        definition = document['Resources']['Role']
        assert len(comparison.managed_policy_roles('iam', 'Policy', stack, [{'Ref': 'Role'}])) == 1
        definition['Properties']['ManagedPolicyArns'] = []
        assert comparison.managed_policy_roles('iam', 'Policy', stack, []) == []
        definition['Properties']['ManagedPolicyArns'] = [{'Ref': 'Policy'}]
        definition['Condition'] = 'Inactive'
        document['Conditions']['Inactive'] = {'Fn::Equals': ['yes', 'no']}
        assert comparison.managed_policy_roles('iam', 'Policy', stack, []) == []
        definition.pop('Condition')
        definition['Properties']['ManagedPolicyArns'] = [{'Ref': 'Unknown'}]
        with pytest.raises(Blocked):
            comparison.managed_policy_roles('iam', 'Policy', stack, [])
        definition['Properties']['ManagedPolicyArns'] = [{'Ref': 'Policy'}]
        # Secret name/ARN identities are contextual; selectors and wrong Type remain distinct.
        desired = {'Name': 'SECRET', 'Type': 'SECRETS_MANAGER', 'Value': comparison.reference('iam', secret)}
        path = 'Environment.EnvironmentVariables[]'
        callback = lambda a, b, p: comparison.reference_same(a, b, 'CodeBuild.Project', p)
        assert same(desired, dict(desired, Value='app/secret'), path=path, reference=callback)
        assert same(desired, dict(desired, Value='app/secret:key:AWSPREVIOUS'), path=path, reference=callback) is False
        assert same(desired, dict(desired, Type='PLAINTEXT'), path=path, reference=callback) is False
        for context in ({}, {'Type': 'PARAMETER_STORE'}, {'Type': 'PLAINTEXT'}):
            with pytest.raises(Blocked):
                comparison.desired_reference('iam', secret, 'CodeBuild.Project', path + '.Value', context=context)
        # Whole-object input binds each variable's own Type, too.
        row = {'property': 'CodeBuild.Project.Environment', 'value': '`' + json.dumps({
            'EnvironmentVariables': [{'Name': 'SECRET', 'Type': 'SECRETS_MANAGER', 'Value': secret}]}) + '`'}
        assert comparison.desired_value('codebuild', row, 'CodeBuild.Project', stack=stack)['EnvironmentVariables'][0]['Value'] == desired['Value']
        # Only confirmed parameters/pseudo or explicit variables bind Model Sub.
        def sub(argument):
            row = {'property': 'IAM.ManagedPolicy.PolicyDocument', 'value': '',
                   'document': json.dumps({'Statement': [{'Resource': {'Fn::Sub': argument}}]})}
            return comparison.desired_value('iam', row, 'IAM.ManagedPolicy', stack=stack)['Statement'][0]['Resource']
        assert sub('arn:${AWS::Partition}:s3:::${Name}/${!aws:username}') == 'arn:aws:s3:::app-dev-data1/${aws:username}'
        assert sub('${AWS::Region}/${AWS::AccountId}') == 'ap-northeast-1/123456789012'
        assert sub(['${AWS::Region}', {'AWS::Region': 'explicit'}]) == 'explicit'
        for unknown in ('${Unknown}', '${Role}', '${Role.Arn}', '${aws:username}'):
            with pytest.raises(Blocked, match='explicit bindings'):
                sub(unknown)
        # Unordered Statement comparison uses a bijection, not sorting or Sid-only matching.
        callback = lambda a, b, p: comparison.reference_same(a, b, 'IAM.Role', p)
        path = 'Policies[].PolicyDocument.Statement'
        first = {'Sid': 'One', 'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': '*'}
        second = dict(first, Sid='Two', Action='s3:PutObject')
        assert same([first, second], [second, first], path=path, reference=callback)
        assert same([first, first], [first, second], path=path, reference=callback) is False
        assert same([first], [first, first], path=path, reference=callback) is False
        assert same([first], [dict(first, Effect='Deny')], path=path, reference=callback) is False
        assert same(first, first, path=path, reference=callback)
        assert same([first, second], [second, first], path='Unrelated', reference=callback) is False
        comparison.resources.setdefault('kms', {})['Key'] = {'resourceType': 'KMS.Key'}
        symbolic = ResourceReference({'$resource': ['kms', 'Key'], '$attribute': 'Arn'})
        assert same([dict(first, Resource=symbolic), second], [second, first], path=path, reference=callback) is None
        assert same([dict(first, Resource=symbolic), second], [dict(second, Effect='Deny'), first], path=path, reference=callback) is False
        # Augmenting paths preserve ambiguous and duplicate matches without factorial permutations.
        pairs = {(1, 3): True, (1, 4): True, (2, 3): True}
        assert unordered_same([1, 2], [3, 4], reference=lambda a, b, p: pairs.get((a, b), False))
        assert unordered_same([1, 2], [3, 4], reference=lambda a, b, p: None) is None


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
    return run(__file__, message='Local issues scan checks: PASS (isolated gate/save/comparison/reuse/concurrency fixtures)')


if __name__ == '__main__':
    raise SystemExit(main())


#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.issues_scan_fixtures import *

def check_mismatch_rendering():
    from iac_values import safe_value
    from issues.aggregate import iac_actions
    from issues.records import iac_key

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
        with patch('issues.reports.evidence', side_effect=AssertionError('mismatch evidence read forbidden')):
            report, report_state = render_iac(root, path, 'dev', 'cde', ['glue'], records, display)
        assert '相違項目: $attribute\n- Model: RoleName\n- IaC: Arn' in report
        assert '$resource' not in report and '修正対象: Model／IaC（修正先は要判断）' in report and '根拠（代表例）:' not in report
        assert 'glue.properties' not in report and 'shared.yaml' in report and ':999' not in report
        assert long_value + 'A' not in report and '全文はartifact' in report
        assert '不一致の検出結果を保持' in report and 'first' not in report and 'second' not in report
        entries = report_state['entries']
        assert Counter(json.dumps(entry['record'], sort_keys=True) for entry in entries) == Counter(json.dumps(record, sort_keys=True) for record in original)
        assert {entry['id'] for entry in entries} == {iac_key(record) for record in original}
        expected_entries = [{'id': iac_key(record), 'record': record, 'retained': False} for record in records]
        expected_entries.sort(key=lambda entry: (entry['record']['service'], entry['id'], identifier(entry['record'])))
        assert iac_actions(entries, 'dev', 'cde') == iac_actions(expected_entries, 'dev', 'cde')
        assert records == original and report_state['value_differences'] == display
        unsafe_display = {identifier(secret): [{'path': 'Password', 'model': 'first', 'iac': 'second'}]}
        masked_report, masked_data = render_iac(root, path, 'dev', 'cde', ['glue'], [secret], unsafe_display)
        assert 'first' not in masked_report and 'second' not in masked_report
        expect_error(lambda: render_iac(root, path, 'dev', 'cde', ['glue'], [base], {identifier(base): [{}]}), 'malformed')
        duplicates = [dict(base, actual=dict(arn_role, **{'$attribute': f'Arn{i}'})) for i in range(12)]
        duplicate_display = {identifier(record): fields(record['desired'], record['actual']) for record in duplicates}
        limited, limited_data = render_iac(root, path, 'dev', 'cde', ['glue'], duplicates, duplicate_display)
        assert limited.count('相違項目:') == 10 and len(limited_data['entries']) == 12
        assert '省略代表例: 2レコード' in limited
        no_fields, _ = render_iac(root, path, 'dev', 'cde', ['glue'], [secret])
        assert 'マスク済み値から相違項目を復元できない' in no_fields



def summary_scale_cases():
    from issues.records import iac_key
    from issues.aggregate import MAX_GROUPS
    artifact = summary_fixture()
    def with_records(records, services=artifact['services'], display=None):
        return dict(artifact, services=services, **aggregate(records, 'dev', 'cde', services, display))

    records = artifact['iac']
    original = json.dumps(artifact, sort_keys=True)
    assert hashlib.sha256(original.encode()).hexdigest() == 'edd38257633c96366b7e60fdc793ec191419da4ad93e3cfd370bf4edb523c627'
    entries, actions, fields = iac_dataset(records, 'dev', 'cde', artifact['services'], artifact['iac_display'])
    stats = iac_summary(records, 'dev', 'cde', artifact['services'], artifact['iac_display'])
    signature = sorted((group['id'], sorted(identifier(entries[i]['record']) for i in group['members'])) for group in actions)
    assert hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest() == '2c4ff24d8644f2244287b0b238c6f0c73a8445fd59d8e717a647ef5e97b70a0e'
    assert len(entries) == 2193 and len(actions) == 1194
    assert stats['categories'] == {'要対応': 0, '要判断': 100, '比較未完了': 1, 'CFn非対応・比較対象外': 0, '処理エラー': 93, '原因未確定': 1000}
    assert stats['record_count'] == 2193 and stats['direct_resources'] == 1100 and stats['proven_causes'] == 1
    assert stats['records'] == dict(difference=1100, uncompared=1000, error=93, matched=0, excluded=0)
    assert len(stats['groups']) == MAX_GROUPS and stats['omitted_groups'] > 0
    assert sum(len(action['members']) for action in actions) == len(records)
    assert sorted(entries[i]['record_index'] for action in actions for i in action['members']) == list(range(len(records)))
    assert {entry['id'] for entry in entries} == {iac_key(record) for record in records}
    with patch.object(Comparison, 'run', side_effect=AssertionError('detail must not compare')), patch('issues.inputs.load_model', side_effect=AssertionError('detail must not parse')):
        for category, count in stats['categories'].items():
            assert detail_payload(artifact, 'iac_issues', category=category)['total'] == count
        pending = detail_payload(artifact, 'iac_issues', category='比較未完了')['items'][0]
        assert detail_payload(artifact, 'iac', issue_id=pending['id'], offset=900, limit=100)['total'] == 1000
        assert len(detail_payload(artifact, 'iac', issue_id=pending['id'], offset=900, limit=100)['items']) == 100
        for section in ('naming', 'judgments'):
            total = 1000 if section == 'naming' else 100
            ids = [item['id'] for offset in range(0, total, 50) for item in detail_payload(artifact, section, offset, 50)['items']]
            assert len(set(ids)) == total
        expect_error(lambda: detail_payload(artifact, 'iac', issue_id='ISSUE-absent'), 'not found')
        expect_error(lambda: detail_payload(artifact, 'naming', category='要判断'), 'IaC filters')
        expect_error(lambda: detail_payload(artifact, 'iac', offset=-1), 'range')
    report = iac_report('dev', 'cde', artifact['services'], records, artifact['iac_display'], stamp='fixed')
    assert {group['category'] for group in stats['groups']} == {category for category, count in stats['categories'].items() if count}
    stdout = json.dumps(review_payload(artifact, '/tmp/fixture-scan.json'), ensure_ascii=False)
    assert stats['group_count'] == 1194  # Unknown causes remain separate despite identical prose.
    assert stats['omitted_issues'] == 1178 and stats['omitted_records'] == 1178
    assert stats['omitted_categories'] == {'要対応': 0, '要判断': 87, '比較未完了': 0, 'CFn非対応・比較対象外': 0, '処理エラー': 92, '原因未確定': 999}
    assert stats['omitted_record_categories'] == dict(difference=1086, uncompared=0, error=92)
    assert '表示16／全1194対応単位、未表示1178' in report and '処理エラー 93項目' in report
    assert len(re.findall(r'^\| ISSUE-', report, re.M)) == 1194
    assert len(re.findall(r'^### ISSUE-', report, re.M)) == 16
    assert all('| ' + action['id'] + ' |' in report for action in actions)
    assert 'index' not in json.loads(stdout)['iac_summary'] and 'stack0' not in report
    # Rendering/order and IDs are deterministic; source lists are never mutated.
    reverse = iac_report('dev', 'cde', artifact['services'][::-1], records[::-1], artifact['iac_display'], stamp='fixed')
    assert reverse == report
    assert '2026-10-08 09:00:00 Asia/Tokyo' in iac_report('dev', 'cde', artifact['services'], [], stamp=artifact['executed_at'])
    again_entries, again_actions, _ = iac_dataset(records[::-1], 'dev', 'cde', artifact['services'], artifact['iac_display'])
    assert [group['id'] for group in again_actions] == [group['id'] for group in actions]
    assert [[again_entries[i]['id'] for i in group['members']] for group in again_actions] == [[entries[i]['id'] for i in group['members']] for group in actions]
    assert json.dumps(artifact, sort_keys=True) == original
    # Matching/excluded records are preserved but never become independent Issues.
    extra = [dict(records[0], category='matched'), dict(records[1], category='excluded')]
    assert iac_summary(records + extra, 'dev', 'cde', artifact['services'])['record_count'] == 2195
    assert iac_summary(records + extra, 'dev', 'cde', artifact['services'])['issue_count'] == 1194
    # Full fields stay masked in artifact, even when summary truncates compound values.
    secret = dict(records[2000], property='Glue.Job.Settings', desired={'Password': 'first', 'Role': 'arn:aws:iam::123456789012:role/a', 'Value': 'prefix-confidential-A'}, actual={'Password': 'second', 'Role': 'arn:aws:iam::123456789012:role/b', 'Value': 'prefix-confidential-B'})
    safe = Comparison.__new__(Comparison); safe.sensitive_values = {'confidential'}
    hidden = dict(secret, desired=safe.redacted(secret['desired']), actual=safe.redacted(secret['actual']))
    hidden_fields = {identifier(hidden): value_differences(secret['desired'], secret['actual'], secret['property'], redact=safe.redacted)}
    secret_artifact = with_records([hidden], display=hidden_fields)
    for word in ('first', 'second', 'confidential', 'arn:aws:'):
        assert word not in json.dumps(secret_artifact) + iac_report('dev', 'cde', artifact['services'], [hidden], hidden_fields) + json.dumps(detail_payload(secret_artifact, 'iac'))
    for category, expected in [('matched', 'complete match'), ('uncompared', 'partial'), ('excluded', 'no compared records'), ('error', 'error')]:
        current = dict(records[0], category=category)
        assert summary(with_records([current]))['iac_status'] == expected
        assert '今回の判定: ' + expected in iac_report('dev', 'cde', artifact['services'], [current])
    assert summary(with_records([]))['iac_status'] == 'no compared records'
    # Limits are presentation-only; all IDs and members remain retrievable.
    base = dict(records[2000], service='glue', category='difference', reason='value mismatch',
                stack='shared', iac={'path': 'infra/shared.yaml'}, resource='shared', property='Setting')
    independent = [dict(base, resource=str(i)) for i in range(20)]
    report20 = iac_report('dev', 'cde', ['glue'], independent)
    assert len(re.findall(r'^\| ISSUE-', report20, re.M)) == 20
    assert len(re.findall(r'^### ISSUE-', report20, re.M)) == 16
    common = [dict(base, resource=str(i), service='glue' if i % 2 else 's3',
                   cause={'kind': 'template-missing', 'path': 'infra/shared.yaml', 'relationship': 'direct'}) for i in range(50)]
    small = with_records(common, ['glue', 's3'])
    units = detail_payload(small, 'iac_issues')['items']
    assert len(units) == 1 and len(units[0]['members']) == 50
    pages = [item for offset in range(0, 50, 10) for item in detail_payload(small, 'iac', offset, 10, issue_id=units[0]['id'])['items']]
    assert len(pages) == 50 and {item['record_index'] for item in pages} == set(range(50))
    compact = iac_summary(common, 'dev', 'cde', small['services'])['groups'][0]
    assert len(compact['examples']) == 10 and compact['omitted_examples'] == 40
    twelve = with_records(common[:12], small['services'])
    assert len(detail_payload(twelve, 'iac', 10, 10, issue_id=units[0]['id'])['items']) == 2
    expect_error(lambda: iac_report('dev', 'cde', ['glue'], common), 'outside selected services')
    left, right = {f'field{i}': i for i in range(12)}, {f'field{i}': i + 1 for i in range(12)}
    record = dict(base, desired=left, actual=right)
    shown = {identifier(record): value_differences(left, right, 'Setting')}
    twelve_fields = with_records([record], ['glue'], shown)
    report12 = iac_report('dev', 'cde', ['glue'], [record], shown)
    assert report12.count('相違項目:') == 10 and '省略相違フィールド: 2件' in report12
    assert len(detail_payload(twelve_fields, 'iac')['items'][0]['value_differences']) == 12
    diagnostic = dict(path='field', model='model', iac='iac', identity='unknown', allowed_forms='Arn', format='unknown', reason='unresolved')
    deferred = dict(record, category='uncompared', deferred_children=[dict(property=f'child{i}', reason='unresolved', category='uncompared') for i in range(12)],
                    reference_diagnostics=[dict(diagnostic, path=f'field{i}') for i in range(12)])
    example = iac_summary([deferred], 'dev', 'cde', ['glue'])['groups'][0]['examples'][0]
    assert len(example['deferred_children']) == len(example['reference_diagnostics']) == 10
    assert example['omitted_deferred_children'] == example['omitted_reference_fields'] == 2
    print(f'IaC bounded output: PASS ({len(report.splitlines())} lines; stdout {len(stdout)} characters; 2193 records / 1194 action units)')


check_summary_scale = summary_scale_cases


def check_operation_pass_cache():
    import issues.integrity as issues_scan
    from validation_cache import PassCache, digest_files

    def baseline(root, artifact):
        for entry, key in artifact.get('service_keys', {}).items():
            if key is not None and PassCache(root).service_key(tuple(entry.split('/'))) != key:
                raise ValueError('stale scan: validation/reference dependency changed')

    def outcome(call):
        try:
            return call()
        except (ValueError, OSError) as error:
            return type(error), str(error)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        common = root / 'project.json'
        project = json.dumps({'projectName': 'fixture', 'targets': [{'environment': 'dev', 'alias': 'team',
            'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n'
        write(common, project)
        docs = root / 'docs/designs/dev/team'
        for service in ('first', 'second', 'producer'):
            write_model(root / f'model/dev/team/{service}.properties', {
                f'desired.service.{service}.serviceId': service,
                f'desired.service.{service}.ownedCatalogResourceTypes': 'S3.Bucket',
                'display.service.title': '# 合成入力'})
            write(docs / f'{service}.md', '# 合成入力\n')
        write(docs / 'first.md', '[producer](producer.md)\n[policy](policy.json)\n')
        write(docs / 'policy.json', '{}\n')
        orphan = docs / 'first/extra.json'
        write(orphan, '{}\n')
        entries = [('dev', 'team', service) for service in ('first', 'second')]

        def artifact():
            return {'service_keys': {'/'.join(entry): PassCache(root).service_key(entry) for entry in entries},
                    'fingerprint': {'paths': [], 'digest': digest_files(root, []),
                                    'file_sets': {}, 'framework': PassCache(root).common_key()}}

        saved = artifact()
        calls = []
        original_common = PassCache.common_key

        def counted(cache, *args, **kwargs):
            calls.append(cache)
            return original_common(cache, *args, **kwargs)

        with patch.object(PassCache, 'common_key', counted):
            assert baseline(root, saved) is None
            assert len(calls) == len(entries)
            calls.clear()
            assert issues_scan.verify_service_keys(root, saved) is None
            assert len(calls) == 2 and calls[0] is calls[1]
            calls.clear()
            assert issues_scan.verify_inputs(root, saved) is None
            assert len(calls) == 2 and calls[-1] is calls[0]
        # Three services also demonstrate fewer common hashes, without a timing threshold.
        saved['service_keys']['dev/team/producer'] = PassCache(root).service_key(('dev', 'team', 'producer'))
        with patch.object(PassCache, 'common_key', counted):
            calls.clear()
            baseline(root, saved)
            assert len(calls) == 3
            calls.clear()
            issues_scan.verify_service_keys(root, saved)
            assert len(calls) == 2

        paths = [common, docs / 'first.md', root / 'model/dev/team/first.properties',
                 root / 'model/dev/team/producer.properties', docs / 'producer.md',
                 docs / 'policy.json', orphan]
        paths += sorted((root / 'model/dev/team/first').rglob('*.properties'))
        for path in paths:
            original = path.read_bytes()
            for replacement in (original + b'\n', None):
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                expected = outcome(lambda: baseline(root, saved))
                assert expected is not None
                assert outcome(lambda: issues_scan.verify_service_keys(root, saved)) == expected
                path.write_bytes(original)
        for path in (docs / 'first/new.json', docs / 'producer/new.json',
                     root / 'model/dev/team/first/new.properties'):
            write(path, '{}\n')
            assert outcome(lambda: issues_scan.verify_service_keys(root, saved)) == outcome(lambda: baseline(root, saved))
            assert outcome(lambda: baseline(root, saved)) is not None
            path.unlink()
        for target in (docs / 'policy.json', docs / 'first.md', root / 'model/dev/team/first.properties', common):
            original = target.read_bytes()
            target.unlink()
            target.symlink_to(orphan)
            assert outcome(lambda: issues_scan.verify_service_keys(root, saved)) == outcome(lambda: baseline(root, saved))
            assert outcome(lambda: baseline(root, saved)) is not None
            target.unlink()
            target.write_bytes(original)

        service_key = PassCache.service_key
        seen = []

        def mutate(cache, entry):
            key = service_key(cache, entry)
            seen.append(entry)
            if len(seen) == 1:
                write(common, project + '\n')
            return key

        first = next(iter(saved['service_keys']))
        single = {'service_keys': {first: saved['service_keys'][first]}}
        with patch.object(PassCache, 'service_key', mutate):
            assert outcome(lambda: issues_scan.verify_service_keys(root, single)) == (
                ValueError, 'stale scan: validation/reference dependency changed')
        # A new operation must observe the new common inputs rather than reuse the previous key.
        assert outcome(lambda: issues_scan.verify_service_keys(root, saved)) == outcome(lambda: baseline(root, saved))
        refreshed = artifact()
        assert issues_scan.verify_inputs(root, refreshed) is None
        with patch.object(issues_scan, 'PassCache', side_effect=AssertionError('None key must not construct a cache')):
            assert issues_scan.verify_service_keys(root, {'service_keys': {'missing/service/key': None}}) is None
            assert issues_scan.verify_service_keys(root, {}) is None
        ordered = {'service_keys': {'dev/team/missing': 'bad', 'dev/team/first': 'bad'}}
        assert outcome(lambda: issues_scan.verify_service_keys(root, ordered)) == outcome(lambda: baseline(root, ordered))
        refreshed['fingerprint']['paths'] = ['docs/designs/dev/team/policy.json']
        refreshed['fingerprint']['digest'] = digest_files(root, [docs / 'policy.json'])
        write(docs / 'policy.json', '{"changed": true}\n')
        assert outcome(lambda: issues_scan.verify_inputs(root, refreshed)) == (
            ValueError, 'stale scan: scoped model/IaC/parameter/reference input changed; rescan affected scope')
        write(docs / 'policy.json', '{}\n')
        # Keep verify_inputs' earlier file-set guard and its final independent framework guard.
        refreshed['fingerprint']['file_sets'] = {'docs/designs/dev/team/first': []}
        assert outcome(lambda: issues_scan.verify_inputs(root, refreshed)) == (ValueError, 'stale scan: input file set changed')
        refreshed['fingerprint']['file_sets'] = {}
        with patch.object(issues_scan, 'verify_service_keys', side_effect=lambda *_, **kwargs: write(common, '{}\n')):
            assert outcome(lambda: issues_scan.verify_inputs(root, refreshed)) == (ValueError, 'stale scan: framework/project input changed')

@pytest.mark.parametrize('failure', ['entrance', 'part', 'reference', 'decode', 'permission'])
def check_failed_model_input_guards(tmp_path, failure):
    from types import SimpleNamespace
    from model.sources import FileReads, load_model as real_load
    from model.format import FORMAT, INDEX, PART
    from issues.inputs import model, templates
    from issues.integrity import fingerprint
    from validation_cache import digest_files
    root = tmp_path
    (root / 'project.json').write_text(json.dumps({'projectName': 'fixture', 'targets': [
        dict(environment='dev', awsAccountId='123456789012', awsRegion='ap-northeast-1', iacEngine='cloudformation')]}))
    entrance = root / 'model/dev/123456789012/cloudformation-stacks.properties'
    entrance.parent.mkdir(parents=True)
    dependency = entrance
    if failure == 'part':
        dependency = entrance.with_suffix('') / 'part-001.properties'
        entrance.write_text(FORMAT + '\n' + INDEX + '\n' + PART + 'cloudformation-stacks/part-001.properties\n')
    elif failure in {'decode', 'permission'}:
        entrance.write_bytes(b'\xff')
    elif failure == 'reference':
        dependency = entrance.with_name('producer.properties')
        entrance.write_text(FORMAT + '\n')
    comparison = SimpleNamespace(root=root, environment='dev', directory='123456789012', services=[],
        models={}, model_reads=FileReads(), inputs=set(), read_hashes={}, unreadable_inputs=False,
        warnings=[], resources={}, rows={}, symbols={}, metrics={'model_loads': 0, 'model_parses': 0}, sensitive_values=set())
    def read_reference(path, reads):
        reads.read(path)
        reads.kind(dependency)
        reads.read(dependency)
        raise ValueError('reference unavailable')
    def denied(path):
        if path == entrance:
            raise PermissionError('input body must not escape')
        return original_read(path)
    original_read = Path.read_bytes
    with patch('issues.inputs.load_model', side_effect=read_reference if failure == 'reference' else real_load), \
         patch.object(Path, 'read_bytes', denied if failure == 'permission' else original_read):
        with pytest.raises((OSError, ValueError)):
            model(comparison, 'cloudformation-stacks')
    artifact = dict(fingerprint=fingerprint(comparison, common_key='common'))
    cache = SimpleNamespace(common_key=lambda: 'common')
    if failure == 'permission':
        with pytest.raises(ValueError, match='freshness unprovable'):
            verify_inputs(root, artifact, cache=cache)
        return
    verify_inputs(root, artifact, cache=cache)
    dependency.parent.mkdir(parents=True, exist_ok=True)
    dependency.write_text(FORMAT + '\n')
    with pytest.raises(ValueError, match='stale scan'):
        verify_inputs(root, artifact, cache=cache)
    # A templates() absence check must be guarded even without a successful Model load.
    if failure == 'entrance':
        dependency.unlink()
        comparison._templates = None
        assert templates(comparison) == []
        artifact = dict(fingerprint=fingerprint(comparison, common_key='common'))
        dependency.write_text(FORMAT + '\n')
        with pytest.raises(ValueError, match='stale scan'):
            verify_inputs(root, artifact, cache=cache)


def check_first_model_observation_is_not_replaced(tmp_path):
    from types import SimpleNamespace
    from model.sources import FileReads
    from issues.inputs import model, retain_hash
    from issues.integrity import fingerprint
    root = tmp_path
    path = root / 'model/dev/team/s3.properties'
    path.parent.mkdir(parents=True)
    path.write_text('first')
    comparison = SimpleNamespace(root=root, environment='dev', directory='team', services=['s3'], models={},
        model_reads=FileReads(), inputs=set(), read_hashes={}, unreadable_inputs=False)
    def interrupted(entrance, reads):
        reads.read(entrance)
        (entrance.with_suffix('') / 'part-001.properties').parent.mkdir()
        (entrance.with_suffix('') / 'part-001.properties').write_text('added during read')
        raise ValueError('parse interrupted')
    with patch('issues.inputs.load_model', side_effect=interrupted), pytest.raises(ValueError):
        model(comparison, 's3')
    artifact = dict(fingerprint=fingerprint(comparison, common_key='common'))
    with pytest.raises(ValueError, match='selection changed'):
        verify_inputs(root, artifact, cache=SimpleNamespace(common_key=lambda: 'common'))
    with pytest.raises(ValueError, match='contradictory'):
        retain_hash(comparison, path, 'later bytes')
    with pytest.raises(ValueError, match='contradictory'):
        fingerprint(comparison, common_key='common')


def check_notice_resolution_and_update_series(tmp_path):
    from issues.materials import existing_materials
    from issues.reports import normal_merge, notice_report, split_notices
    from datetime import datetime as real_datetime
    from unittest.mock import Mock
    root = tmp_path
    path = root / 'issues/dev/team/issues.md'
    path.parent.mkdir(parents=True)
    legacy = '<!-- reference-warnings:start -->\n## 旧参照\n- legacy warning\n<!-- reference-warnings:end -->\n'
    ordinary = '# 問題一覧\n\nHuman確認済み\n<!-- human-comment -->\n\n## dev／team\n\n### s3\n\n1. selected issue\n\n### sqs\n\n1. outside issue\n'
    text = notice_report(ordinary + legacy, 'dev', 'team', ['sqs'], {'warnings': [{'message': 'outside warning'}]})
    path.write_text(text)
    ids = []
    for index, channels in enumerate(({'warnings': [{'message': 'current warning'}]},
                                      {'unverified': [{'message': 'not run'}]},
                                      {'unverified': [{'message': 'not run'}]}, {}), 1):
        clock = Mock()
        clock.now.return_value = real_datetime(2026, 10, 23, 0, 0, index)
        with patch('issues.reports.datetime', clock):
            merged = normal_merge(root, path, 'dev', 'team', ['s3'], [], [], [])
        assert f'更新日時: 2026-10-23 00:00:0{index} Asia/Tokyo' in split_notices(merged)[0]
        assert '今回確認した範囲: dev／team／s3' in split_notices(merged)[0]
        text = notice_report(merged, 'dev', 'team', ['s3'], channels, preserve_prior=index in {2, 3})
        path.write_text(text)
        issues, human = existing_materials(root, 'dev', 'team', ['s3'])
        assert len(issues) == 1 and human == ['Human確認済み', '<!-- human-comment -->']
        ids.append(issues[0]['id'])
        assert 'legacy warning' in text and 'outside warning' in text
        assert text.count('current warning') == int(index < 4) and text.count('not run') <= 1
        assert 'outside issue' in text and len(split_notices(text)[1]) == 3
    assert len(set(ids)) == 1
    resolution = dict(id=ids[0], reason='explicit revalidation', evidence='confirmed fixture')
    merged = normal_merge(root, path, 'dev', 'team', ['s3'], [], [], [resolution])
    assert 'selected issue' not in merged and 'outside issue' in merged
    assert 'legacy warning' in merged and 'outside warning' in merged and '<!-- human-comment -->' in merged
    # save-results does not invoke notice_report, comparison, lint or aggregation.
    with patch('issues.publication.save_authority', return_value=[path]), \
         patch('issues.publication.atomic_files') as atomic, \
         patch('issues.reports.notice_report', side_effect=AssertionError('notice rerun')), \
         patch('issues.comparison.Comparison.run', side_effect=AssertionError('comparison rerun')), \
         patch('issues.cfn_lint.run_lint', side_effect=AssertionError('lint rerun')):
        save(root, 'dev', 'team', ['s3'], resolutions=[resolution], artifact=None, warnings=())
    saved = atomic.call_args.args[0][path]
    assert split_notices(saved)[1] == split_notices(merged)[1]
    assert "selected issue" not in saved and "outside issue" in saved



def check_view_read_failure_policy(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from issues.inputs import view_text
    from issues.integrity import fingerprint
    from validation.runner import Validator
    from validation_cache import PassCache
    root = tmp_path
    docs = root / 'docs/designs/dev/team'
    docs.mkdir(parents=True)
    bad, good = docs / 's3.md', docs / 'sqs.md'
    bad.write_bytes(b'\xff private body')
    good.write_text('independent view')
    comparison = SimpleNamespace(root=root, inputs=set(), read_hashes={}, view_errors={}, unreadable_inputs=False,
                                 services=['s3', 'sqs'], environment='dev', directory='team')
    assert view_text(comparison, bad, phase='view-preflight') is None
    assert view_text(comparison, good, phase='view-preflight') == 'independent view'
    assert comparison.view_errors[bad]['exception'] == 'UnicodeDecodeError'
    assert 'private body' not in json.dumps(comparison.view_errors[bad])
    cache = SimpleNamespace(common='common', service_key=lambda entry: str(entry), load=lambda _: None, save=Mock())
    validator = Validator(root, {('dev', 'team', 's3'), ('dev', 'team', 'sqs')}, workers=1)
    validator.cache = cache
    generated = []
    source_checks = Mock(return_value=SimpleNamespace(errors=[], warnings=[], checks=7))
    def ownership(instance, paths):
        if bad in paths:
            raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'bad input')
        return {}, set(), {}, {}
    def generation(instance):
        generated.append(instance.scope)
        instance.findings.result('framework.generated-service-model', instance.scope).status = 'PASS'
    def service(instance):
        assert instance.scope == {('dev', 'team', 'sqs')}
        instance.check(False, 'independent sqs diagnostic')
        instance.check_design_links({})
    with patch.object(Validator, 'check_design_service_ownership', ownership), \
         patch.object(Validator, 'check_stack_designs', return_value={}), \
         patch.object(Validator, 'check_generated_service_models', generation), \
         patch.object(Validator, 'check_designs', service), \
         patch.object(Validator, 'check_observed_values'), \
         patch('model.sources.load_model', return_value=SimpleNamespace(authoritative={}, warnings=[])), \
         patch('model.validation.check_model_inputs', source_checks):
        validator.check_scoped_designs(defer_cache=True, view_errors=comparison.view_errors)
        assert 'independent sqs diagnostic' in validator.errors
        assert source_checks.call_count == 1 and generated == [{('dev', 'team', 'sqs')}]
        assert validator.checks >= 8 and validator.findings.unverified
        assert not validator.service_cache_pending
        assert validator.findings.result('design.service', {('dev', 'team', 's3')}).status == 'NOT_RUN'
        assert validator.findings.result('framework.generated-service-model', validator.scope).status == 'NOT_RUN'
        default = Validator(root, validator.scope, workers=1)
        with pytest.raises(UnicodeDecodeError):
            default.check_scoped_designs()
    artifact = dict(fingerprint=fingerprint(comparison, common_key='common'))
    verify_inputs(root, artifact, cache=SimpleNamespace(common_key=lambda: 'common'))
    bad.write_bytes(b'changed bytes')
    with pytest.raises(ValueError, match='stale scan'):
        verify_inputs(root, artifact, cache=SimpleNamespace(common_key=lambda: 'common'))
    with patch.object(Path, 'read_bytes', side_effect=PermissionError('private exception body')):
        assert view_text(comparison, good, phase='review-prose') is None
    artifact = dict(fingerprint=fingerprint(comparison, common_key='common'))
    with pytest.raises(ValueError, match='freshness unprovable'):
        verify_inputs(root, artifact, cache=SimpleNamespace(common_key=lambda: 'common'))


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

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
            report, report_state = render_iac(root, path, 'dev', 'cde', ['glue'], records, display)
        assert '相違項目: $attribute\n- Model: RoleName\n- IaC: Arn' in report
        assert '$resource' not in report and '修正対象: Model／IaC（修正先は要判断）' in report and '根拠（代表例）:' not in report
        assert 'glue.properties' not in report and 'shared.yaml' not in report and ':999' not in report
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
        duplicates = [dict(base, actual=dict(arn_role, **{'$attribute': f'Arn{i}'})) for i in range(5)]
        duplicate_display = {identifier(record): fields(record['desired'], record['actual']) for record in duplicates}
        limited, limited_data = render_iac(root, path, 'dev', 'cde', ['glue'], duplicates, duplicate_display)
        assert limited.count('相違項目:') == 3 and len(limited_data['entries']) == 5
        assert '省略代表例: 2レコード' in limited
        no_fields, _ = render_iac(root, path, 'dev', 'cde', ['glue'], [secret])
        assert 'マスク済み値から相違項目を復元できない' in no_fields



def summary_scale_cases():
    from issues_reports import iac_key, MAX_GROUPS
    artifact = summary_fixture()
    records = artifact['iac']
    original = json.dumps(artifact, sort_keys=True)
    assert hashlib.sha256(original.encode()).hexdigest() == '8fdf987e881faec5843aeb876d30e769f3fd15eb206a5cafdd3fd6fd25ce47fb'
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
    artifact['iac_issues'] = [dict(group, members=[entries[i]['record_index'] for i in group['members']]) for group in actions]
    with patch.object(Comparison, 'run', side_effect=AssertionError('detail must not compare')), patch('issues_iac.load_model', side_effect=AssertionError('detail must not parse')):
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
    assert stats['omitted_issues'] == 1186 and stats['omitted_records'] == 1186
    assert stats['omitted_categories'] == {'要対応': 0, '要判断': 95, '比較未完了': 0, 'CFn非対応・比較対象外': 0, '処理エラー': 92, '原因未確定': 999}
    assert stats['omitted_record_categories'] == dict(difference=1094, uncompared=0, error=92)
    assert '表示8／全1194対応単位、未表示1186' in report and '処理エラー 93項目' in report
    assert len(report.splitlines()) <= 160 and 'ISSUE-' not in report and 'stack0' not in report
    # Rendering/order and IDs are deterministic; source lists are never mutated.
    reverse = iac_report('dev', 'cde', artifact['services'][::-1], records[::-1], artifact['iac_display'], stamp='fixed')
    assert reverse == report
    assert '2026-10-08 09:00:00 Asia/Tokyo' in iac_report('dev', 'cde', artifact['services'], [], stamp=artifact['executed_at'])
    again_entries, again_actions, _ = iac_dataset(records[::-1], 'dev', 'cde', artifact['services'], artifact['iac_display'])
    assert [group['id'] for group in again_actions] == [group['id'] for group in actions]
    assert [[again_entries[i]['id'] for i in group['members']] for group in again_actions] == [[entries[i]['id'] for i in group['members']] for group in actions]
    artifact.pop('iac_issues')
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
    secret_artifact = dict(artifact, iac=[hidden], iac_display=hidden_fields)
    for word in ('first', 'second', 'confidential', 'arn:aws:'):
        assert word not in json.dumps(secret_artifact) + iac_report('dev', 'cde', artifact['services'], [hidden], hidden_fields) + json.dumps(detail_payload(secret_artifact, 'iac'))
    for category, expected in [('matched', 'complete match'), ('uncompared', 'partial'), ('excluded', 'no compared records'), ('error', 'error')]:
        current = dict(records[0], category=category)
        assert summary(dict(artifact, iac=[current]))['iac_status'] == expected
        assert '今回の判定: ' + expected in iac_report('dev', 'cde', artifact['services'], [current])
    assert summary(dict(artifact, iac=[]))['iac_status'] == 'no compared records'
    print(f'IaC bounded output: PASS ({len(report.splitlines())} lines; stdout {len(stdout)} characters; 2193 records / 1194 action units)')


check_summary_scale = summary_scale_cases

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

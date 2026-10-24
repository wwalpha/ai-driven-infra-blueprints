#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from contextlib import nullcontext
from datetime import datetime as real_datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace as _CallbackState
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import issues.integrity as issues_scan
import issues.publication as publication
import issues.runner as scan_runner
import model.sources as sources
import support.issues_scan_fixtures as _exports_support_issues_scan_fixtures
import support.issues_scan_fixtures as _retained_fixture_protected_sources
import support.issues_scan_fixtures as _retained_fixture_scan_project
import sync_runtime
from comparison.inputs import Inputs
from issue_gate import issue_errors, unresolved_services
from issues.aggregate import MAX_GROUPS, iac_actions
from issues.inputs import view_text
from issues.integrity import fingerprint
from issues.materials import existing_materials
from issues.records import iac_key
from issues.reports import attach_notices, normal_merge, notice_report, split_notices
from model.core import ReferenceResolutionError, resource_row_index
from model.format import FORMAT, INDEX, PART, split
from model.sources import load_model as real_load
from support.issues_scan_fixtures import (
    Comparison,
    Counter,
    Path,
    aggregate,
    detail_payload,
    expect_error,
    hashlib,
    iac_dataset,
    iac_report,
    iac_summary,
    identifier,
    json,
    os,
    patch,
    pytest,
    re,
    render_iac,
    review_payload,
    run,
    save,
    summary,
    summary_fixture,
    sys,
    tempfile,
    value_differences,
    verify_inputs,
    write,
    write_model,
)
from support.issues_scan_fixtures import pytestmark as pytestmark
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import digest_files, input_context
from utils.source_reads import FileReads
from validation.runner import Validator
from validation_cache import PassCache

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

protected_sources = _retained_fixture_protected_sources.protected_sources
scan_project = _retained_fixture_scan_project.scan_project

_CALLBACK_DEFAULT = object()


# Preserve shared fixtures and compatibility exports under their historical names.
entries = _exports_support_issues_scan_fixtures.entries



def _callback_check_mismatch_rendering_fields(left, right, name='Setting', exact=False):
    return value_differences(left, right, name, exact=exact)


def check_mismatch_rendering():

    fields = _callback_check_mismatch_rendering_fields

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



def _callback_summary_scale_cases_with_records_161(artifact, _default_services, _default_display, /, records, services=_CALLBACK_DEFAULT, display=_CALLBACK_DEFAULT):
    if services is _CALLBACK_DEFAULT:
        services = _default_services
    if display is _CALLBACK_DEFAULT:
        display = _default_display
    return dict(artifact, services=services, **aggregate(records, 'dev', 'cde', services, display))


def summary_scale_cases():
    artifact = summary_fixture()
    with_records = _bind_framework_callback(_callback_summary_scale_cases_with_records_161, artifact, artifact['services'], None)

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
    with patch.object(Comparison, 'run', side_effect=AssertionError('detail must not compare')), patch('comparison.inputs.load_model', side_effect=AssertionError('detail must not parse')):
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
    safe = Comparison.__new__(Comparison)
    safe.sensitive_values = {'confidential'}
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




def _check_operation_pass_cache_outcome(call):
    try:
        return call()
    except (ValueError, OSError) as error:
        return (type(error), str(error))


def _callback_check_operation_pass_cache_baseline(root, artifact):
    for entry, key in artifact.get('service_keys', {}).items():
        if key is not None and PassCache(root).service_key(tuple(entry.split('/'))) != key:
            raise ValueError('stale scan: validation/reference dependency changed')


def _callback_check_operation_pass_cache_artifact(entries, root, /):
    return {'service_keys': {'/'.join(entry): PassCache(root).service_key(entry) for entry in entries},
            'fingerprint': {'paths': [], 'digest': digest_files(root, []),
                            'file_sets': {}, 'framework': PassCache(root).common_key()}}


def _callback_check_operation_pass_cache_counted(calls, original_common, /, cache, *args, **kwargs):
    calls.append(cache)
    return original_common(cache, *args, **kwargs)


def _callback_check_operation_pass_cache_mutate(common, project, seen, service_key, /, cache, entry):
    key = service_key(cache, entry)
    seen.append(entry)
    if len(seen) == 1:
        write(common, project + '\n')
    return key


def check_operation_pass_cache():

    baseline = _callback_check_operation_pass_cache_baseline

    outcome = _check_operation_pass_cache_outcome

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

        artifact = _bind_framework_callback(_callback_check_operation_pass_cache_artifact, entries, root)

        saved = artifact()
        calls = []
        original_common = PassCache.common_key

        counted = _bind_framework_callback(_callback_check_operation_pass_cache_counted, calls, original_common)

        with patch.object(PassCache, 'common_key', counted):
            assert baseline(root, saved) is None
            assert len(calls) == len(entries)
            calls.clear()
            assert issues_scan.verify_service_keys(root, saved) is None
            assert len(calls) == 2 and calls[0] is calls[1]
            calls.clear()
            assert issues_scan.verify_inputs(root, saved) is None
            assert len(calls) == 1
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

        mutate = _bind_framework_callback(_callback_check_operation_pass_cache_mutate, common, project, seen, service_key)

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

def _callback_check_failed_model_input_guards_read_reference(dependency, /, path, reads):
    reads.read(path)
    reads.kind(dependency)
    reads.read(dependency)
    raise ValueError('reference unavailable')


def _callback_check_failed_model_input_guards_denied(_state_check_failed_model_input_guards_423, entrance, /, path):
    if path == entrance:
        raise PermissionError('input body must not escape')
    return _state_check_failed_model_input_guards_423.original_read(path)


@pytest.mark.parametrize('failure', ['entrance', 'part', 'reference', 'decode', 'permission'])
def check_failed_model_input_guards(tmp_path, failure):

    _state_check_failed_model_input_guards_423 = _CallbackState()
    model, templates = Inputs.model, Inputs.templates
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
    comparison.retain_reads = lambda: Inputs.retain_reads(comparison)
    comparison.retain_hash = lambda path, value: Inputs.retain_hash(comparison, path, value)
    read_reference = _bind_framework_callback(_callback_check_failed_model_input_guards_read_reference, dependency)
    denied = _bind_framework_callback(_callback_check_failed_model_input_guards_denied, _state_check_failed_model_input_guards_423, entrance)
    _state_check_failed_model_input_guards_423.original_read = Path.read_bytes
    with patch('comparison.inputs.load_model', side_effect=read_reference if failure == 'reference' else real_load), \
         patch.object(Path, 'read_bytes', denied if failure == 'permission' else _state_check_failed_model_input_guards_423.original_read):
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




def _check_first_model_observation_is_not_replaced_interrupted(entrance, reads):
    reads.read(entrance)
    (entrance.with_suffix('') / 'part-001.properties').parent.mkdir()
    (entrance.with_suffix('') / 'part-001.properties').write_text('added during read')
    raise ValueError('parse interrupted')


def check_first_model_observation_is_not_replaced(tmp_path):

    model, retain_hash = Inputs.model, Inputs.retain_hash
    root = tmp_path
    path = root / 'model/dev/team/s3.properties'
    path.parent.mkdir(parents=True)
    path.write_text('first')
    comparison = SimpleNamespace(root=root, environment='dev', directory='team', services=['s3'], models={},
        model_reads=FileReads(), inputs=set(), read_hashes={}, unreadable_inputs=False)
    comparison.retain_reads = lambda: Inputs.retain_reads(comparison)
    comparison.retain_hash = lambda path, value: Inputs.retain_hash(comparison, path, value)
    interrupted = _check_first_model_observation_is_not_replaced_interrupted
    with patch('comparison.inputs.load_model', side_effect=interrupted), pytest.raises(ValueError):
        model(comparison, 's3')
    artifact = dict(fingerprint=fingerprint(comparison, common_key='common'))
    with pytest.raises(ValueError, match='selection changed'):
        verify_inputs(root, artifact, cache=SimpleNamespace(common_key=lambda: 'common'))
    with pytest.raises(ValueError, match='contradictory'):
        retain_hash(comparison, path, 'later bytes')
    with pytest.raises(ValueError, match='contradictory'):
        fingerprint(comparison, common_key='common')


def check_notice_resolution_and_update_series(tmp_path):

    root = tmp_path
    path = root / 'issues/dev/team/issues.md'
    path.parent.mkdir(parents=True)
    ordinary = '# 問題一覧\n\nHuman確認済み\n<!-- human-comment -->\n\n## dev／team\n\n### s3\n\n1. selected issue\n\n### sqs\n\n1. outside issue\n'
    text = notice_report(ordinary, 'dev', 'team', ['sqs'], {'warnings': [{'message': 'outside warning'}]})
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
        assert 'outside warning' in text
        assert text.count('current warning') == int(index < 4) and text.count('not run') <= 1
        assert 'outside issue' in text and len(split_notices(text)[1]) == 2
    assert len(set(ids)) == 1
    resolution = dict(id=ids[0], reason='explicit revalidation', evidence='confirmed fixture')
    merged = normal_merge(root, path, 'dev', 'team', ['s3'], [], [], [resolution])
    assert 'selected issue' not in merged and 'outside issue' in merged
    assert 'outside warning' in merged and '<!-- human-comment -->' in merged
    # save-results does not invoke notice_report, comparison, lint or aggregation.
    with patch('issues.publication.save_authority', return_value=[path]), \
         patch('issues.publication.atomic_files') as atomic, \
         patch('issues.reports.notice_report', side_effect=AssertionError('notice rerun')), \
         patch('comparison.Comparison.run', side_effect=AssertionError('comparison rerun')), \
         patch('issues.cfn_lint.run_lint', side_effect=AssertionError('lint rerun')):
        save(root, 'dev', 'team', ['s3'], resolutions=[resolution], artifact=None, warnings=())
    saved = atomic.call_args.args[0][path]
    assert split_notices(saved)[1] == split_notices(merged)[1]
    assert "selected issue" not in saved and "outside issue" in saved



@pytest.mark.parametrize('fence', ['```', '~~~~'])
def check_notice_fenced_roundtrip(tmp_path, fence):
    root = tmp_path
    path = root / 'issues/dev/team/issues.md'
    path.parent.mkdir(parents=True)
    example = (f'{fence}text\n<!-- issues-notices:sample:start -->\n- scoped example\n<!-- issues-notices:sample:end -->\n'
               + ('```\n' if fence.startswith('~') else '~~~\n') + fence + '\n')
    human = 'Human確認済み\n\n' + example + '\nHuman後続\n'
    old = '<!-- issue-service: s3 -->\n1. existing s3 problem\n\n'
    path.write_text(old)
    before = unresolved_services(root, path)
    gate = issue_errors(root, {('dev', 'team', 'sqs')})
    issues, _ = existing_materials(root, 'dev', 'team', ['s3'])
    assert len(issues) == 1 and issues[0]['service'] == 's3'
    merged = normal_merge(root, path, 'dev', 'team', ['sqs'], [], [], [])
    merged = notice_report(merged, 'dev', 'team', ['sqs'], {'warnings': ['current']})
    path.write_text(merged)
    assert unresolved_services(root, path) == before
    assert issue_errors(root, {('dev', 'team', 'sqs')}) == gate == []
    assert existing_materials(root, 'dev', 'team', ['s3'])[0][0]['id'] == issues[0]['id']
    # Keep a Human example in the preamble and real notices for two scopes.
    path.write_text(human + merged)
    merged = normal_merge(root, path, 'dev', 'team', ['s3'], [], [], [])
    merged = notice_report(merged, 'dev', 'team', ['s3'], {'unverified': ['selected']})
    assert example in split_notices(merged)[0] and len(split_notices(merged)[1]) == 2
    assert merged.index('Human確認済み') < merged.index(example) < merged.index('Human後続')
    path.write_text(merged)
    with patch('issues.publication.save_authority', return_value=[path]), \
         patch('issues.publication.atomic_files') as atomic:
        save(root, 'dev', 'team', ['s3'], artifact=None)
    saved = atomic.call_args.args[0][path]
    assert example in split_notices(saved)[0]
    assert saved.index('Human確認済み') < saved.index(example) < saved.index('Human後続')
    assert split_notices(saved)[1] == split_notices(merged)[1]
    path.write_text(saved)
    resolution = dict(id=issues[0]['id'], reason='explicit revalidation', evidence='fixture')
    resolved = normal_merge(root, path, 'dev', 'team', ['s3'], [], [], [resolution])
    assert 'existing s3 problem' not in resolved and example in resolved
    assert 'current' in resolved


def check_notice_marker_boundaries():
    human = ('<!-- ordinary comment -->\n<!-- issues-notices:one:start -->\n'
             '- incomplete\n<!-- issues-notices:two:end -->\n'
             'ordinary unfinished comment\n')
    assert split_notices(human) == (human, [])
    block = '<!-- issues-notices:scope:start -->\n## Warning\n- valid\n<!-- issues-notices:scope:end -->'
    ordinary, notices = split_notices('before\n' + block + '\nafter\n')
    assert ordinary == 'before\n\nafter\n' and notices == [('scope', block)]
    assert split_notices(attach_notices(ordinary, notices))[1] == notices
    longer = '````text\n```\n' + block + '\n````\n'
    assert split_notices(longer) == (longer, [])




def _check_view_read_failure_policy_service(instance):
    assert instance.scope == {('dev', 'team', 'sqs')}
    instance.check(False, 'independent sqs diagnostic')
    instance.check_design_links({})


def _callback_check_view_read_failure_policy_ownership(bad, /, instance, paths):
    if bad in paths:
        raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'bad input')
    return {}, set(), {}, {}


def _callback_check_view_read_failure_policy_generation(generated, /, instance):
    generated.append(instance.scope)
    instance.findings.result('framework.generated-service-model', instance.scope).status = 'PASS'


def check_view_read_failure_policy(tmp_path):
    real_load_model = sources.load_model
    assert sync_runtime.load_model is real_load_model

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
    ownership = _bind_framework_callback(_callback_check_view_read_failure_policy_ownership, bad)
    generation = _bind_framework_callback(_callback_check_view_read_failure_policy_generation, generated)
    service = _check_view_read_failure_policy_service
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
    assert sources.load_model is sync_runtime.load_model is real_load_model
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


def interrupt_comparison(comparison, exception):
    comparison.sensitive_values.add('exception-secret')
    for index in range(5):
        comparison.record('difference', 's3', str(index), 'Setting', 'value mismatch', desired=1, actual=2)
    raise exception('interrupted exception-secret')


@pytest.mark.parametrize('exception', [ReferenceResolutionError, OSError, ValueError, KeyError, ImportError, TypeError])
def check_scan_exception_classification(tmp_path, exception):
    comparison = Comparison.__new__(Comparison)
    comparison.root, comparison.environment, comparison.directory = tmp_path, 'dev', 'team'
    comparison.sensitive_values, comparison.results, comparison.warnings = set(), [], []
    comparison.view_errors, comparison.read_hashes, comparison.metrics = {}, {}, {}
    comparison.models, comparison.display_differences, comparison.catalog = {}, {}, None
    comparison.source = Mock(return_value=None)
    comparison.track = Mock()
    cache = SimpleNamespace(common=None, common_key=Mock(return_value='common'))
    validator = SimpleNamespace(checks=1, findings=SimpleNamespace(unverified=[],
        result=Mock(return_value=SimpleNamespace(metadata={}))), finalize_service_cache=Mock())
    lint = dict(jobs=[], coverage=[], status='not_applicable', lint_dependencies={},
        **{name: [] for name in ('ordinary', 'judgments', 'warnings', 'information', 'unverified', 'processing_errors')})
    with patch.object(scan_runner, 'Comparison', return_value=comparison), \
         patch.object(scan_runner, 'PassCache', return_value=cache), \
         patch.object(scan_runner, 'fingerprint', return_value={'paths': [], 'file_sets': {}, 'digest': digest_files(tmp_path, [])}), \
         patch.object(scan_runner, 'view_text', return_value=None), \
         patch.object(scan_runner, 'mechanical', side_effect=partial(mechanical_result, validator)), \
         patch.object(scan_runner, 'naming_materials', return_value=({'names': []}, [])), \
         patch.object(scan_runner, 'existing_materials', return_value=([], [])), \
         patch('issues.cfn_lint.run_lint', return_value=lint), \
         patch.object(scan_runner, 'verify_inputs'), \
         patch.object(comparison, 'run', side_effect=partial(interrupt_comparison, comparison, exception)) as invoked:
        artifact = scan_runner.scan(tmp_path, 'dev', 'team', ['s3'])
    invoked.assert_called_once_with()
    assert artifact['iac'][:5] == comparison.results and len(artifact['iac']) == 6
    tail = artifact['iac'][-1]
    category = 'uncompared' if exception is ReferenceResolutionError else 'error'
    assert tail['category'] == category and tail['comparison_incomplete']
    status = summary(artifact)
    assert status['iac_differences'] == 5 and status['comparison_incomplete']
    assert status['iac_status'] == ('partial' if category == 'uncompared' else 'error')
    report = iac_report('dev', 'team', ['s3'], artifact['iac'], artifact['iac_display'])
    assert '比較途中終了' in report
    assert 'exception-secret' not in json.dumps(artifact) + report + json.dumps(detail_payload(artifact, 'iac'))
    assert sum(len(group['members']) for group in artifact['iac_issues']) == 6
    assert any(warning['code'] == 'reference.unresolved' for warning in artifact['warnings']) == (exception is ReferenceResolutionError)


def mechanical_result(validator, *args, **kwargs):
    kwargs['validator_out'].append(validator)
    return [], 1, ''


@pytest.mark.parametrize('state,scope,allowed,saveonly', [
    ('completed', True, True, True), ('suspend', True, True, True),
    ('running', False, True, True), ('running', True, False, True), ('running', True, True, False),
])
def check_save_authority_rejections(tmp_path, state, scope, allowed, saveonly):
    text = '## Task contract\n- Task status: `' + state + '`\n'
    with patch.object(publication, 'task_snapshot', return_value=SimpleNamespace(text=text)), \
         patch.object(publication, 'active_scope', return_value={('dev', 'team', 's3')} if scope else set()), \
         patch.object(publication, 'paths_in', return_value=['issues/dev/team/issues.md'] if allowed else []), \
         patch.object(publication, 'issues_save_only', return_value=saveonly), \
         patch.object(publication, 'atomic_files', side_effect=AssertionError('rejected save wrote outputs')):
        with pytest.raises(ValueError):
            publication.save_authority(tmp_path, 'dev', 'team', ['s3'], ['issues.md'])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('failure', ['review-id', 'context', 'names', 'judgments', 'types', 'owner'])
def check_save_review_rejections(tmp_path, failure):
    artifact = dict(version=2, root=str(tmp_path), scan_id='a'*32, naming_context_id=identifier({}), naming_context={},
        environment='dev', target='team', services=['s3'], naming={'names': [{'id': 'name'}]},
        judgments=[dict(id='judgment', message='diagnostic')], ordinary=[], **aggregate([], 'dev', 'team', ['s3']))
    review = dict(scan_id=artifact['scan_id'], reviewed_naming_context_id=artifact['naming_context_id'],
        reviewed_names=['name'], reviewed_judgments=['judgment'], diagnostic_assignments={'judgment': 's3'}, issues=[], resolved=[])
    key, value = {'review-id': ('scan_id', 'wrong'), 'context': ('reviewed_naming_context_id', 'wrong'),
        'names': ('reviewed_names', []), 'judgments': ('reviewed_judgments', []),
        'types': ('issues', {}), 'owner': ('diagnostic_assignments', {'judgment': 'sqs'})}[failure]
    review[key] = value
    with patch.object(publication, 'save', side_effect=AssertionError('invalid review published')):
        with pytest.raises(ValueError):
            publication.save_scan(tmp_path, artifact, review)


@pytest.mark.parametrize('input_name', ['parameters.json', 's3.properties', 'template.yaml', 'project.json'])
def check_saved_input_bytes_and_revision_independence(tmp_path, input_name):
    path = tmp_path / input_name
    path.write_bytes(b'original\r\n')
    artifact = dict(fingerprint={'paths': [input_name], 'digest': digest_files(tmp_path, [path]),
        'file_sets': {}, 'framework': 'common'}, git_head='old')
    cache = SimpleNamespace(common_key=Mock(return_value='common'))
    with patch('subprocess.run', side_effect=AssertionError('content guard must not inspect Git revision')):
        verify_inputs(tmp_path, artifact, cache=cache)
        path.write_bytes(b'changed\r\n')
        with pytest.raises(ValueError, match='stale scan'):
            verify_inputs(tmp_path, artifact, cache=cache)
        path.write_bytes(b'original\r\n')
        verify_inputs(tmp_path, artifact, cache=cache)


@pytest.mark.parametrize('input_state', ['missing', 'empty', 'malformed'])
def check_ordinary_merge_preserves_human_and_scope(tmp_path, input_state):
    path = tmp_path / 'issues/dev/team/issues.md'
    path.parent.mkdir(parents=True)
    if input_state != 'missing':
        path.write_text('' if input_state == 'empty' else 'malformed report', encoding='utf-8')
    if input_state == 'malformed':
        with pytest.raises(ValueError, match='malformed'):
            normal_merge(tmp_path, path, 'dev', 'team', ['s3'], [], [], [])
        assert path.read_text(encoding='utf-8') == 'malformed report'
        return
    text = normal_merge(tmp_path, path, 'dev', 'team', ['s3'], [], [{'service': 's3', 'message': 'new issue'}], [])
    path.write_text(text + '\n### sqs\n\n1. other service issue\n', encoding='utf-8')
    result = normal_merge(tmp_path, path, 'dev', 'team', ['s3'], [], [{'service': 's3', 'message': 'additional issue'}], [])
    assert 'new issue' in result and 'additional issue' in result and 'other service issue' in result


def check_causal_report_grouping():
    direct = dict(category='difference', service='datazone', resource='001', property='*', reason='template missing',
        stack='stack', cause=dict(kind='template-missing', path='missing.yaml', stack='stack', relationship='direct'))
    cascade = dict(category='uncompared', service='s3', resource='001', property='Setting', reason='search incomplete',
        cause=dict(direct['cause'], relationship='export-search-incomplete'))
    records = [direct, cascade]
    entries, actions, _ = iac_dataset(records, 'dev', 'team', ['datazone', 's3'])
    assert len(actions) == 1 and len(actions[0]['members']) == 2
    assert actions[0]['id'] != iac_actions(entries, 'stg', 'team')[0]['id']
    other = dict(cascade, resource='other', cause=dict(cascade['cause'], path='other.yaml'))
    unknown = dict(cascade, resource='unknown')
    unknown.pop('cause')
    parameter = dict(cascade, resource='parameter', cause=dict(cascade['cause'], kind='parameters-missing'))
    _, separated, _ = iac_dataset(records + [other, unknown, parameter, dict(unknown, resource='unknown2')], 'dev', 'team', ['datazone', 's3'])
    assert len(separated) == 5
    base = dict(category='difference', service='s3', resource='001', property='S3.Bucket.BucketName',
        stack='stack1', iac={'path': 'shared.yaml'}, reason='value mismatch', desired='a', actual='b')
    distinct = [base, dict(base, stack='stack2'), dict(base, resource='002'), dict(base, property='S3.Bucket.Tags'),
                dict(base, reason='property missing'), dict(base, iac={'path': 'other.yaml'})]
    assert len(iac_dataset(distinct, 'dev', 'team', ['s3'])[1]) == 6
    assert len(iac_dataset([base, base], 'dev', 'team', ['s3'])[1]) == 1
    assert len(iac_dataset([base, base], 'dev', 'team', ['s3'])[0]) == 2
    for invalid in (True, 'false', None, 0):
        forged = dict(base, cause=dict(kind='condition-disabled', result=invalid))
        assert iac_summary([forged], 'dev', 'team', ['s3'])['proven_causes'] == 0


def fail_report_publication(state, real_replace, selected, after, source, destination):
    if Path(destination) == selected and not state.failed:
        state.failed = True
        if after:
            real_replace(source, destination)
        raise KeyboardInterrupt()
    return real_replace(source, destination)


@pytest.mark.parametrize('output,after', [('issues.md', False), ('issues.md', True), ('iac-issues.md', False), ('iac-issues.md', True)])
def check_report_publication_interruptions(tmp_path, output, after):
    paths = [tmp_path / name for name in ('issues.md', 'iac-issues.md')]
    originals = {path: b'original\r\n' for path in paths}
    for path, content in originals.items():
        path.write_bytes(content)
    state = SimpleNamespace(failed=False)
    with patch.object(publication._imports_model_sources, 'publication_lock', return_value=nullcontext()), \
         patch.object(publication, 'save_authority', return_value=paths), \
         patch.object(publication, 'normal_merge', return_value='new ordinary'), \
         patch.object(publication, 'iac_report', return_value='new iac'), \
         patch('utils.file_operations.os.replace', side_effect=partial(fail_report_publication, state, os.replace, tmp_path / output, after)):
        with pytest.raises(KeyboardInterrupt):
            publication.save(tmp_path, 'dev', 'team', ['s3'], iac=[])
    assert state.failed and {path: path.read_bytes() for path in paths} == originals
    assert set(tmp_path.iterdir()) == set(paths)


def check_current_run_report_and_guard(tmp_path):
    paths = [tmp_path / name for name in ('issues.md', 'iac-issues.md')]
    record = dict(category='difference', service='s3', resource='001', property='Setting', reason='value mismatch', desired=1, actual=2)
    with patch.object(publication._imports_model_sources, 'publication_lock', return_value=nullcontext()), \
         patch.object(publication, 'save_authority', return_value=paths), \
         patch.object(publication, 'normal_merge', return_value='human確認: kept ordinary issue'), \
         patch.object(Comparison, 'run', side_effect=AssertionError('save-only comparison')):
        paths[1].write_text('invalid previous iac report', encoding='utf-8')
        publication.save(tmp_path, 'dev', 'team', ['s3'], iac=[record])
        uncertain = dict(record, category='uncompared', reason='not comparable')
        publication.save(tmp_path, 'dev', 'team', ['s3'], iac=[uncertain])
        text = paths[1].read_text(encoding='utf-8')
        assert '未比較 1項目' in text and 'value mismatch' not in text and 'invalid previous' not in text
        before = {path: path.read_bytes() for path in paths}
        with pytest.raises(ValueError, match='inputs changed'):
            publication.save(tmp_path, 'dev', 'team', ['s3'], iac=[], guard=Mock(side_effect=ValueError('inputs changed')))
        assert {path: path.read_bytes() for path in paths} == before
        publication.save(tmp_path, 'dev', 'team', ['s3'], iac=[])
        assert '元レコード数: 0' in paths[1].read_text(encoding='utf-8')
        assert 'no compared records' in paths[1].read_text(encoding='utf-8')




def check_model_part_bytes_and_legacy_rows(tmp_path):
    source = tmp_path / 'model/dev/team/s3.properties'
    write(tmp_path / 'project.json', json.dumps({'projectName': 'fixture', 'targets': [dict(environment='dev', alias='team',
        awsAccountId='123456789012', awsRegion='ap-northeast-1', iacEngine='cloudformation')]}))
    values = {'desired.service.s3.serviceId': 's3', 'desired.resource.legacy-id.resourceType': 'S3.Bucket',
        'desired.row.legacy-id-001.property': 'S3.Bucket.BucketName', 'desired.row.legacy-id-001.value': '`bucket`',
        'desired.row.legacy-id-001.comment': 'fixture', 'desired.resource.legacy.resourceType': 'S3.Bucket'}
    values.update({"desired.resource.legacy-id.logicalId": "S3_Bucket_001",
        "desired.resource.legacy.logicalId": "S3_Bucket_002",
        "desired.service.identity.lastAllocated": "{\"S3.Bucket\":2}"})
    outputs = split(source, values, limit=3)
    assert len(outputs) > 1
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
    with input_context(), patch.object(sources, '_read_model', wraps=sources._read_model) as parser:
        one, two = real_load(source), real_load(source)
        assert one is two and parser.call_count == 1
    assert one.values == values
    assert all(text.encode('utf-8') == path.read_bytes() for path, text in one.files.items())
    assert all(path.read_text(encoding='utf-8').splitlines()[line-1].partition('=')[0] == key
               for key, (path, line) in one.locations.items())
    assert resource_row_index(one.values)['legacy'] == []
    assert len(resource_row_index(one.values)['legacy-id']) == 1


def check_missing_template_report():
    record = dict(category='difference', service='s3', resource='001', property='*', stack='stack',
        reason='モデルに対応するtemplateが存在しない（CREATE未実装）', iac={'path': 'infra/cloudformation/templates/shared.yaml'},
        cause=dict(kind='template-missing', path='infra/cloudformation/templates/shared.yaml', stack='stack', relationship='direct'))
    report = iac_report('dev', 'team', ['s3'], [record])
    assert '差分 1件 / 未比較 0項目 / 処理エラー 0項目' in report
    assert '修正対象: 不足入力: shared.yaml' in report
    assert '[infra/cloudformation/templates/shared.yaml]' not in report


if __name__ == '__main__':
    raise SystemExit(run(__file__))

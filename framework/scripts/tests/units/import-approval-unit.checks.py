#!/usr/bin/env python3
"""Synthetic review/pre-save units; no trusted Human approval is simulated as success."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import import_approval as approval
import import_guard
from model_templates import Expansion
from script_loader import module

m = module('import-model.py', 'import_approval_cli')


def schema(prop):
    return {'type': 'boolean' if prop.endswith('EnableDnsSupport') else 'string'}


def proposal():
    old = {'desired.resource.001.resourceType': 'EC2.VPC',
           'desired.resource.001.resourceMode': 'IMPORT', 'desired.resource.001.anchor': 'main',
           'desired.row.001-001.property': 'EC2.VPC.VpcId',
           'desired.row.001-001.value': '[Main](#main)', 'desired.row.001-001.comment': '合成ID',
           'observed.row.001-001.value': '`vpc-one`',
           'desired.row.001-002.property': 'EC2.VPC.CidrBlock',
           'desired.row.001-002.value': '`10.0.0.0/16`', 'desired.row.001-002.comment': '合成CIDR'}
    new = {**old, 'desired.row.001-002.value': '`10.1.0.0/16`'}
    record = {'record': 'r1', 'kind': 'EC2.VPC', 'identity': 'vpc-one', 'identityProperty': 'EC2.VPC.VpcId',
              'properties': {'EC2.VPC.VpcId': {'status': 'captured', 'value': 'vpc-one'},
                             'EC2.VPC.CidrBlock': {'status': 'captured', 'value': '10.1.0.0/16'}}}
    acquisition = {'version': 2, 'task': 'tasks/import-fixture.md', 'root': '/synthetic/worktree',
                   'scope': ['dev', 'cde', 'vpc'], 'connection': {'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'},
                   'acquiredAt': datetime.now(timezone.utc).isoformat(), 'sources': {'synthetic': 'baseline'},
                   'records': [record], 'inventory': {'EC2.VPC': {'status': 'complete'}}}
    selection = {'resources': [{'record': 'r1', 'resource': '001', 'action': 'refresh', 'reason': 'Human review proposal', 'basis': []}],
                 'excluded': [], 'unreflected': []}
    return acquisition, selection, Expansion(old, {}, {}), new, {'r1': []}


def review(data):
    return approval.build_review(*data, schema)


def check_complete_typed_before_after_and_digest():
    data = proposal()
    result = review(data)
    entry = result['dispositions'][0]
    assert entry['matching']['existingResources'] == ['001'] and entry['matching']['status'] == 'confirmed'
    cidr, identifier = entry['properties']
    assert cidr['before'][0]['desired'] == '10.0.0.0/16' and cidr['after'][0]['desired'] == '10.1.0.0/16'
    assert cidr['after'][0]['nativeType'] == 'string'
    assert identifier['after'][0]['reference'] == '[Main](#main)' and identifier['after'][0]['observed'] == 'vpc-one'
    assert entry['name'] == {'status': 'not-acquired'}
    approval.verify_review(result, review(data))
    assert result['approvalBoundary'] == 'unavailable'


@pytest.mark.parametrize('field', ['disposition', 'risk', 'inventory'])
def check_full_inventory_required(field):
    data = proposal()
    if field == 'disposition':
        data[1]['resources'].clear()
    elif field == 'risk':
        data[4].clear()
    else:
        data[0]['inventory'] = {'EC2.Subnet': {'status': 'empty'}}
    with pytest.raises(ValueError, match='every acquired'):
        review(data)


@pytest.mark.parametrize('change', ['target', 'operation', 'property', 'reference', 'risk', 'baseline', 'scope', 'task', 'worktree', 'type'])
def check_changed_review_needs_new_review(change):
    expected = review(proposal())
    changed = copy.deepcopy(expected)
    entry = changed['dispositions'][0]
    if change == 'target':
        entry['targetResource'] = '009'
    elif change == 'operation':
        entry['operation'] = 'replace'
    elif change in {'property', 'reference', 'type'}:
        entry['properties'][0]['after'][0]['desired'] = {'property': '10.2.0.0/16', 'reference': '[Other](vpc.md#other)', 'type': False}[change]
    elif change == 'risk':
        entry['risks'] = ['possible duplicate']
    else:
        changed[{'baseline': 'sourceBaselineDigest'}.get(change, change)] = 'different'
    # Even recomputing a local digest cannot reuse reviewed content or authorize saving.
    changed['reviewDigest'] = import_guard.digest({k: v for k, v in changed.items() if k != 'reviewDigest'})
    with pytest.raises(ValueError, match='Review changed'):
        approval.verify_review(changed, expected)


def check_unknown_identity_risk_is_bound():
    data = proposal()
    data[2].values.pop('observed.row.001-001.value')
    new = {**data[2].values, **{k.replace('001', '009'): v.replace('#main', '#extra') if k.endswith('.value') else
           'extra' if k.endswith('.anchor') else v for k, v in data[3].items()}}
    data[1]['resources'][0].update(resource='009', action='add')
    result = review((*data[:3], new, data[4]))
    entry = result['dispositions'][0]
    assert entry['matching']['status'] == 'unresolved'
    assert entry['risks'][0]['existingResources'] == ['001']
    assert 'duplicate' in entry['risks'][0]['reason']


@pytest.mark.parametrize('state', ['failed', 'permission_denied', 'requires_filter', 'empty', 'complete'])
def check_inventory_status_and_exclusions_remain_visible(state):
    data = proposal()
    data[0]['inventory']['EC2.Subnet'] = {'status': state}
    data[1]['resources'].clear()
    data[1]['excluded'].append({'record': 'r1', 'reason': 'Keep existing resource'})
    result = review((*data[:3], data[2].values, data[4]))
    assert result['inventory']['EC2.Subnet']['status'] == state
    assert result['dispositions'][0]['operation'] == 'excluded'
    assert result['dispositions'][0]['matching']['existingResources'] == ['001']


def check_array_boolean_name_and_unreflected_values():
    acquisition, selection, _, proposed, risks = proposal()
    selection['resources'][0]['action'] = 'add'
    for index, (prop, value) in enumerate([('EnableDnsSupport', True), ('Tags[].Key', ['Name', 'Project']),
                                         ('Tags[].Value', ['main', 'fixture'])], 3):
        acquisition['records'][0]['properties']['EC2.VPC.' + prop] = {'status': 'captured', 'value': value}
        prefix = 'desired.row.001-' + str(index).zfill(3) + '.'
        proposed.update({prefix + 'property': 'EC2.VPC.' + prop, prefix + 'value': '`' + json.dumps(value) + '`',
                         prefix + 'comment': '合成取得値'})
    acquisition['records'][0]['properties']['EC2.VPC.EnableDnsHostnames'] = {'status': 'captured', 'value': False}
    result = review((acquisition, selection, Expansion({}, {}, {}), proposed, risks))
    item = result['dispositions'][0]
    props = {p['property']: p for p in item['properties']}
    assert props['EC2.VPC.EnableDnsSupport']['after'][0]['desired'] is True
    assert props['EC2.VPC.Tags[].Value']['after'][0]['nativeType'] == 'array'
    assert item['name']['Tags[Name]'] == ['main']
    assert item['unreflected'][0]['property'] == 'EC2.VPC.EnableDnsHostnames'


def check_composite_identity_and_secret_omission():
    data = proposal()
    record = data[0]['records'][0]
    record['identityComponents'] = [{'property': 'EC2.VPC.VpcId', 'value': 'vpc-one'},
                                    {'property': 'EC2.VPC.CidrBlock', 'value': '10.0.0.0/16'}]
    record['identityStatus'] = 'known'
    record['properties']['EC2.VPC.CidrBlock']['value'] = '10.0.0.0/16'
    data[3]['desired.row.001-002.value'] = '`10.0.0.0/16`'
    # Existing secret content is never copied into the proposal or the Review.
    data[2].values.update({'desired.row.001-003.property': 'EC2.VPC.Password',
                          'desired.row.001-003.value': '`synthetic-secret-value`',
                          'desired.row.001-003.comment': 'secret'})
    record['properties']['EC2.VPC.Password'] = {'status': 'unavailable', 'reason': 'sensitive Property'}
    result = review(data)
    assert result['dispositions'][0]['physicalId'] == record['identityComponents']
    assert 'synthetic-secret-value' not in json.dumps(result)


@pytest.mark.parametrize('observed', ['`10.1.0.0/16`', '`true`', '`0`'])
def check_configuration_is_not_observed(observed):
    data = proposal()
    data[3]['observed.row.001-002.value'] = observed
    with pytest.raises(ValueError, match='desired logical reference'):
        review(data)


def check_valid_observation_and_nonblocking_reference_warning():
    data = proposal()
    data[3]['desired.row.001-001.value'] = '[DifferentLabel](#main)'
    result = review(data)
    assert result['warnings'] and result['dispositions'][0]['properties'][1]['after'][0]['observed'] == 'vpc-one'
    # An unrelated old literal observation is not a new gate on the selected change.
    data[2].values['observed.row.001-002.value'] = '`10.0.0.0/16`'
    data[3].update(data[2].values)
    data[1]['resources'].clear()
    data[1]['excluded'] = [{'record': 'r1', 'reason': 'unchanged legacy data'}]
    review(data)


@pytest.mark.parametrize('claim', [None, {'approved': True}, {'wholeReview': True}, {'records': ['r1']},
                                    {'signature': 'agent-local-HMAC'}, {'expiresAt': '2099-01-01'}])
def check_no_local_claim_can_publish(tmp_path, claim):
    evidence = tmp_path / 'acquisition.json'
    evidence.write_text('{}')
    (tmp_path / 'approval.json').write_text(json.dumps(claim))
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    with patch.object(m, 'candidate_sources') as candidates, patch.object(m, 'publish') as save:
        with pytest.raises(ValueError, match='Human approval unavailable'):
            m.publish_selected(tmp_path, ('dev', 'cde', 'vpc'), evidence, {'approved': claim}, False)
        with pytest.raises(ValueError, match='Human approval unavailable'):
            import_guard.record_import(tmp_path, {}, evidence, {'approved': claim})
        candidates.assert_not_called()
        save.assert_not_called()
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def check_alternate_source_guard_rejects_legacy_receipt(tmp_path):
    (tmp_path / '.git').mkdir()
    task = tmp_path / 'tasks/import.md'
    text = '## Task contract\n- Workflow: `import`\n'
    with patch.object(import_guard, 'changed_sources', return_value={'model/templates/cde/vpc.properties.tpl'}), \
            patch.object(import_guard, 'task_path', return_value=task), \
            patch.object(import_guard, 'contracts', return_value={'tasks/import.md': text}), \
            patch.object(import_guard, 'read_proof') as receipt:
        with pytest.raises(ValueError, match='Human approval unavailable'):
            import_guard.require_import_changes(tmp_path, output={tmp_path / 'model/templates/cde/vpc.properties.tpl': 'forged'})
        receipt.assert_not_called()


def check_expiry_and_digest_tampering():
    data = proposal()
    result = review(data)
    result['reviewDigest'] = 'forged'
    with pytest.raises(ValueError, match='Review changed'):
        approval.verify_review(result, review(data))
    data[0]['acquiredAt'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with pytest.raises(ValueError, match='expired'):
        review(data)


def check_unselected_reference_changes_are_not_reviewed_as_selected():
    data = proposal()
    data[2].values.update({'desired.resource.002.resourceType': 'EC2.VPC',
                          'desired.resource.002.resourceMode': 'IMPORT',
                          'desired.row.002-001.property': 'EC2.VPC.VpcId',
                          'desired.row.002-001.value': '[Other](#other)',
                          'desired.row.002-001.comment': '未選択'})
    data[3]['desired.row.002-001.value'] = '[Changed](#changed)'
    with pytest.raises(ValueError, match='unselected Resource'):
        review(data)


@pytest.mark.parametrize('failure', [None, 'source', 'input', 'secret'])
def check_review_command_is_read_only(tmp_path, failure):
    acquisition, selection, before, proposed, risks = proposal()
    root = tmp_path / 'repo'
    root.mkdir()
    source = root / 'baseline'
    source.write_text('unchanged source')
    directory = tmp_path / 'evidence'
    directory.mkdir()
    evidence = directory / 'acquisition.json'
    evidence.write_text('retained acquisition')
    acquisition.update(root=str(root), sources={'baseline': import_guard.file_hash(source)})
    # Only changed fields are authored; unchanged values are read from the baseline in memory.
    draft = {'proposedValues': {k: v for k, v in proposed.items() if before.values.get(k) != v}, 'risks': risks}
    if failure == 'source':
        source.write_text('concurrent change')
    if failure == 'input':
        draft['approved'] = True
    if failure == 'secret':
        acquisition['records'][0]['properties']['EC2.VPC.CidrBlock']['value'] = {'password': 'never-output'}
        draft['proposedValues']['desired.row.001-002.value'] = '`{"password":"never-output"}`'
    (directory / 'review-input.json').write_text(json.dumps(draft))
    (directory / 'selection.json').write_text(json.dumps(selection))
    original = source.read_bytes()
    with patch.object(m, 'target_for', return_value={'directory': 'cde'}), \
            patch.object(m, 'read_acquisition', return_value=acquisition), \
            patch.object(m, 'load_for_edit', return_value=before), \
            patch.object(m, 'property_schema', side_effect=schema), patch.object(m, 'publish') as save:
        if failure:
            with pytest.raises(ValueError):
                m.review_acquisition(root, 'dev', 'vpc', evidence, 'cde')
            assert not (directory / 'review.json').exists()
        else:
            result = m.review_acquisition(root, 'dev', 'vpc', evidence, 'cde')
            assert result['status'] == 'reviewed' and result['model'] == 'unchanged'
            assert json.loads((directory / 'review.json').read_text()) == result['review']
            assert result['review']['dispositions'][0]['properties'][0]['after'][0]['desired'] == '10.1.0.0/16'
        save.assert_not_called()
    assert source.read_bytes() == original and evidence.read_text() == 'retained acquisition'


@pytest.mark.parametrize('failure', [None, 'load', 'render'])
def check_preflight_before_any_save(tmp_path, failure):
    import import_references
    import sync_runtime
    acquisition, selection, before, proposed, _ = proposal()
    source = tmp_path / 'model/templates/cde/vpc.properties.tpl'
    source.parent.mkdir(parents=True)
    source.write_text('original')
    evidence = tmp_path / 'evidence/acquisition.json'
    evidence.parent.mkdir()
    evidence.write_text('retained evidence')
    (evidence.parent / 'selection.json').write_text(json.dumps(selection))
    acquisition.update(sources={source.relative_to(tmp_path).as_posix(): import_guard.file_hash(source)},
                       consumers=[['dev', 'cde', 'vpc']])
    after = Expansion(values=proposed, provenance={}, files={source: 'candidate'})
    calls = []

    def load(path, output=None, *, display=False):
        if display:
            calls.append('display')
            if failure == 'load':
                raise ValueError('synthetic display structure error')
        return after if output else before

    def plan(*args):
        calls.append('render')
        if failure == 'render':
            raise ValueError('synthetic JSON structure error')
        return {}, {}

    resolver = SimpleNamespace(warnings=[], files={}, metrics={}, verify_resource=lambda *a, **k: None)
    with patch.object(m, 'load_for_edit', side_effect=load), \
            patch.object(m, 'candidate_sources', return_value={source: 'candidate'}), \
            patch.object(m, 'preserve_consumers', return_value=({}, set(), False)), \
            patch.object(m, 'replacement_inputs', return_value=({}, ())), \
            patch.object(m, 'property_schema', side_effect=schema), \
            patch.object(import_references, 'Resolver', return_value=resolver), \
            patch.object(sync_runtime, 'owned_artifacts', return_value=set()), \
            patch.object(sync_runtime, 'view_plan', side_effect=plan), patch.object(m, 'publish') as save:
        if failure:
            with pytest.raises(ValueError, match='structure error'):
                m.publish_selected(tmp_path, ('dev', 'cde', 'vpc'), evidence, acquisition, True)
        else:
            result = m.publish_selected(tmp_path, ('dev', 'cde', 'vpc'), evidence, acquisition, True)
            assert result['model'] == 'unchanged' and result['status'] == 'dry-run'
        save.assert_not_called()
    assert calls == (['display'] if failure == 'load' else ['display', 'render'])
    assert source.read_text() == 'original' and evidence.read_text() == 'retained evidence'


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

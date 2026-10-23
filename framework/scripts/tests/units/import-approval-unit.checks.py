#!/usr/bin/env python3
"""Synthetic Review/publication integrity units; conversational consent is an agent responsibility."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import import_guard
import model.format as _imports_model_format
import pytest
from model.format import serialize
from model.importing import approval
from model.importing import cli as m
from model.operations import operation_values
from model.sources import load_model
from script_loader import module as module
from support.model_v2_fixtures import value_snapshot as Expansion

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def schema(prop):
    return {'type': 'boolean' if prop.endswith('EnableDnsSupport') else 'string'}


def proposal():
    old = {'desired.resource.001.resourceType': 'EC2.VPC', 'desired.resource.001.anchor': 'vpc-one',
           'desired.resource.001.resourceMode': 'IMPORT', 'desired.resource.001.logicalId': 'EC2_VPC_001',
           'desired.service.identity.lastAllocated': '{"EC2.VPC":1}',
           'desired.row.001-001.property': 'EC2.VPC.VpcId',
           'desired.row.001-001.value': '[vpc](vpc.md#vpc-one)', 'desired.row.001-001.comment': '合成ID',
           'observed.row.001-001.value': '`vpc-one`',
           'desired.row.001-002.property': 'EC2.VPC.CidrBlock',
           'desired.row.001-002.value': '`10.0.0.0/16`', 'desired.row.001-002.comment': '合成CIDR'}
    new = {**old, 'desired.row.001-002.value': '`10.1.0.0/16`'}
    record = {'record': 'r1', 'kind': 'EC2.VPC', 'identity': 'vpc-one', 'identityProperty': 'EC2.VPC.VpcId',
              'properties': {'EC2.VPC.VpcId': {'status': 'captured', 'value': 'vpc-one'},
                             'EC2.VPC.CidrBlock': {'status': 'captured', 'value': '10.1.0.0/16'}}}
    acquisition = {'version': 3, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1, 'sourceSets': [], 'task': 'tasks/import-fixture.md', 'root': '/synthetic/worktree',
                   'scope': ['dev', 'cde', 'vpc'], 'connection': {'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'},
                   'acquiredAt': datetime.now(timezone.utc).isoformat(), 'sources': {'synthetic': 'baseline'},
                   'records': [record], 'inventory': {'EC2.VPC': {'status': 'complete'}}}
    selection = {'resources': [{'record': 'r1', 'resource': '001', 'action': 'refresh', 'reason': 'Human review proposal', 'basis': []}],
                 'excluded': [], 'unreflected': []}
    return acquisition, selection, Expansion(old, {}, {}), new, {'r1': []}


def review(data):
    acquisition, selected, before, proposed, risks = data
    return approval.build_review(acquisition, selected, Expansion(before.authoritative), proposed, risks, schema)


def check_complete_typed_before_after_and_digest():
    data = proposal()
    result = review(data)
    entry = result['dispositions'][0]
    assert entry['matching']['existingResources'] == ['001'] and entry['matching']['status'] == 'confirmed'
    cidr, identifier = entry['properties']
    assert cidr['before'][0]['desired'] == '10.0.0.0/16' and cidr['after'][0]['desired'] == '10.1.0.0/16'
    assert cidr['after'][0]['nativeType'] == 'string'
    assert identifier['after'][0]['reference'] == '[vpc](vpc.md#vpc-one)' and identifier['after'][0]['observed'] == 'vpc-one'
    assert entry['name'] == {'status': 'not-acquired'}
    approval.verify_review(result, review(data))
    assert result['approvalBoundary'] == 'llm-explicit-consent'


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
        entry['properties'][0]['after'][0]['desired'] = {'property': '10.2.0.0/16', 'reference': '[vpc](vpc.md#vpc-two)', 'type': False}[change]
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
    data[2].authoritative.pop('observed.row.001-001.value')
    new = {**data[2].authoritative, **{k.replace('.001', '.009', 1): v.replace('#main', '#extra') if k.endswith('.value') else
           'extra' if k.endswith('.anchor') else v for k, v in data[3].items()}}
    new['desired.resource.009.logicalId'] = 'EC2_VPC_002'
    new['desired.row.009-001.value'] = '[vpc](vpc.md#vpc-two)'
    new['desired.service.identity.lastAllocated'] = '{"EC2.VPC":2}'
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
    result = review((*data[:3], data[2].authoritative, data[4]))
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
    data[2].authoritative.update({'desired.row.001-003.property': 'EC2.VPC.Password',
                          'desired.row.001-003.value': '`synthetic-secret-value`',
                          'desired.row.001-003.comment': 'secret'})
    data[3].update({key: value for key, value in data[2].authoritative.items() if key.startswith('desired.row.001-003.')})
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
    data[3]['desired.row.001-001.value'] = '[vpc](vpc.md#vpc-two)'
    result = review(data)
    assert result['warnings'] and result['dispositions'][0]['properties'][1]['after'][0]['observed'] == 'vpc-one'
    # An unrelated old literal observation is not a new gate on the selected change.
    data[2].authoritative['observed.row.001-002.value'] = '`10.0.0.0/16`'
    data[3].update(data[2].authoritative)
    data[1]['resources'].clear()
    data[1]['excluded'] = [{'record': 'r1', 'reason': 'unchanged legacy data'}]
    review(data)


@pytest.mark.parametrize('claim', [None, {'approved': True}, {'wholeReview': True}, {'records': ['r1']},
                                    {'signature': 'agent-local-HMAC'}, {'expiresAt': '2099-01-01'}])
def check_local_claim_cannot_replace_review_binding(tmp_path, claim):
    evidence = tmp_path / 'acquisition.json'
    evidence.write_text('{}')
    (tmp_path / 'approval.json').write_text(json.dumps(claim))
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='Review binding'):
        import_guard.record_import(tmp_path, {}, evidence, {}, review_binding=claim)
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def check_alternate_source_guard_rejects_legacy_receipt(tmp_path):
    (tmp_path / '.git').mkdir()
    task = tmp_path / 'tasks/import.md'
    text = ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `import`\n'
            '## Modified files\n- `tasks/import.md`\n- `model/dev/cde/vpc.properties`\n'
            '## Allowed paths\n- `tasks/import.md`\n- `model/dev/cde/vpc.properties`\n'
            '## Validation scope\n- `dev/cde/vpc`\n')
    with patch.object(import_guard, 'changed_sources', return_value={'model/dev/cde/vpc.properties'}), \
            patch.object(import_guard, 'task_path', return_value=task), \
            patch.object(import_guard, 'contracts', return_value={'tasks/import.md': text}), \
            patch.object(import_guard, 'read_proof', side_effect=ValueError('IMPORT change has no verified /import evidence')) as receipt:
        with pytest.raises(ValueError, match='no verified /import evidence'):
            import_guard.require_import_changes(tmp_path, output={tmp_path / 'model/dev/cde/vpc.properties': 'forged'})
        receipt.assert_called_once()


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
    data[2].authoritative.update({'desired.resource.002.resourceType': 'EC2.VPC',
                          'desired.resource.002.resourceMode': 'IMPORT', 'desired.resource.002.logicalId': 'EC2_VPC_002', 'desired.service.identity.lastAllocated': '{"EC2.VPC":2}',
                          'desired.row.002-001.property': 'EC2.VPC.VpcId',
                          'desired.row.002-001.value': '[vpc](vpc.md#vpc-two)',
                          'desired.row.002-001.comment': '未選択'})
    data[3].update(data[2].authoritative)
    data[3]['desired.row.002-001.value'] = '[Changed](#changed)'
    with pytest.raises(ValueError, match='unselected Resource'):
        review(data)


def source_review_case(tmp_path):
    acquisition, selection, before, proposed, risks = proposal()
    root = tmp_path / 'repo'
    source = root / 'model/dev/cde/vpc.properties'
    source.parent.mkdir(parents=True)
    source.write_text(serialize(before.authoritative), encoding='utf-8')
    (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', 'alias': 'cde',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
    directory = tmp_path / 'evidence'
    directory.mkdir()
    evidence = directory / 'acquisition.json'
    evidence.write_text('retained acquisition', encoding='utf-8')
    candidate = directory / 'candidates' / source.relative_to(root)
    candidate.parent.mkdir(parents=True)
    candidate.write_text(serialize(proposed), encoding='utf-8')
    acquisition.update(root=str(root), sources={source.relative_to(root).as_posix(): import_guard.file_hash(source)})
    (directory / 'selection.json').write_text(json.dumps(selection), encoding='utf-8')
    (directory / 'review-input.json').write_text(json.dumps({'risks': risks}), encoding='utf-8')
    return SimpleNamespace(root=root, source=source, candidate=candidate, evidence=evidence,
        acquisition=acquisition, before=before, proposed=proposed, original=source.read_bytes())


@pytest.mark.parametrize('failure', [None, 'source', 'input', 'secret'])
def check_review_command_is_read_only(tmp_path, failure):
    case = source_review_case(tmp_path)
    if failure == 'source':
        case.source.write_bytes(case.source.read_bytes() + b'# concurrent change\n')
    elif failure == 'input':
        file = case.evidence.parent / 'review-input.json'
        file.write_text(json.dumps({'risks': {'r1': []}, 'approved': True}), encoding='utf-8')
    elif failure == 'secret':
        case.acquisition['records'][0]['properties']['EC2.VPC.CidrBlock']['value'] = {'password': 'never-output'}
        candidate = dict(case.proposed)
        candidate['desired.row.001-002.value'] = '`{"password":"never-output"}`'
        serialize = _imports_model_format.serialize
        case.candidate.write_text(serialize(candidate), encoding='utf-8')
    original = case.source.read_bytes()
    with patch.object(m, 'target_for', return_value={'directory': 'cde'}), \
         patch.object(m, 'read_acquisition', return_value=case.acquisition), \
         patch.object(m, 'property_schema', side_effect=schema), patch.object(m, 'publish_edit') as save:
        if failure:
            with pytest.raises(ValueError):
                m.review_acquisition(case.root, 'dev', 'vpc', case.evidence, 'cde')
            assert not (case.evidence.parent / 'review.json').exists()
        else:
            result = m.review_acquisition(case.root, 'dev', 'vpc', case.evidence, 'cde')
            assert result['status'] == 'reviewed' and result['model'] == 'unchanged'
            assert json.loads((case.evidence.parent / 'review.json').read_text()) == result['review']
            assert result['review']['dispositions'][0]['properties'][0]['after'][0]['desired'] == '10.1.0.0/16'
        save.assert_not_called()
    assert case.source.read_bytes() == original and case.evidence.read_text() == 'retained acquisition'


@pytest.mark.parametrize('failure', [None, 'load', 'render', 'review', 'property', 'selection', 'baseline', 'provenance'])
def check_preflight_before_any_save(tmp_path, failure):
    case = source_review_case(tmp_path)
    with patch.object(m, 'target_for', return_value={'directory': 'cde'}), \
         patch.object(m, 'read_acquisition', return_value=case.acquisition), \
         patch.object(m, 'property_schema', side_effect=schema), patch.object(m, 'publish_edit') as save:
        m.review_acquisition(case.root, 'dev', 'vpc', case.evidence, 'cde')
        file = case.evidence.parent / 'review.json'
        if failure in {'property', 'selection', 'baseline', 'provenance'}:
            reviewed = json.loads(file.read_text())
            if failure == 'property':
                reviewed['dispositions'][0]['properties'][0]['after'][0]['desired'] = '10.2.0.0/16'
            elif failure == 'selection':
                reviewed['selection']['resources'][0]['resource'] = '009'
            elif failure == 'baseline':
                reviewed['sourceBaselineDigest'] = 'forged'
            else:
                reviewed['referenceProvenance']['after'] = {'fixed': reference_trace('002')}
            reviewed['reviewDigest'] = import_guard.digest({key: value for key, value in reviewed.items() if key != 'reviewDigest'})
            file.write_text(json.dumps(reviewed), encoding='utf-8')
        elif failure == 'load':
            case.candidate.write_text('invalid properties', encoding='utf-8')
        with patch.object(m, 'view_plan', side_effect=ValueError('synthetic JSON structure error') if failure == 'render' else None,
                          return_value=({}, {})):
            if failure in {'load', 'render', 'property', 'selection', 'baseline', 'provenance'}:
                with pytest.raises(ValueError):
                    m.publish_acquisition(case.root, 'dev', 'vpc', case.evidence, 'cde', dry_run=True)
            else:
                result = m.publish_acquisition(case.root, 'dev', 'vpc', case.evidence, 'cde', dry_run=True)
                assert result['model'] == 'unchanged' and result['status'] == 'dry-run'
        save.assert_not_called()
    assert case.source.read_bytes() == case.original and case.evidence.read_text() == 'retained acquisition'


def check_missing_review_rejected_before_candidate_load(tmp_path):
    case = source_review_case(tmp_path)
    with patch.object(m, 'target_for', return_value={'directory': 'cde'}), \
         patch.object(m, 'read_acquisition', return_value=case.acquisition), \
         patch.object(m, 'candidate_sources') as candidates, patch.object(m, 'publish_edit') as save:
        with pytest.raises(ValueError, match='requires review.json'):
            m.publish_acquisition(case.root, 'dev', 'vpc', case.evidence, 'cde')
        candidates.assert_not_called()
        save.assert_not_called()
    assert case.evidence.read_text() == 'retained acquisition'


def reference_trace(target='001'):
    return {'consumerKey': 'desired.row.001-001.value', 'text': '[vpc](vpc.md#vpc-one)', 'occurrence': '1',
        'producerKind': 'resource', 'producerScope': 'dev/cde/vpc', 'producerLogicalId': 'EC2_VPC_' + target,
        'resourceType': 'EC2.VPC', 'format': 'link', 'labelPolicy': 'fixed'}


@pytest.mark.parametrize('change', ['selector', 'declaration', 'service', 'property', 'resource-type', 'label-policy'])
def check_same_value_reference_meaning_is_bound(change):
    acquisition, selection, before, proposed, risks = proposal()
    original_state = {'fixed': reference_trace()}
    fields = approval.validate_reference_proposal(original_state, before.authoritative)
    before = Expansion(fields)
    proposed = approval.validate_reference_proposal(original_state, proposed)
    original = approval.build_review(acquisition, selection, before, proposed, risks, schema)
    changed = copy.deepcopy(original_state)
    if change == 'selector':
        changed['fixed']['producerLogicalId'] = 'EC2_VPC_002'
    elif change == 'declaration':
        changed['fixed'].update(format='identifier', property='EC2.VPC.VpcId', labelPolicy='none')
    elif change == 'service':
        changed['fixed']['producerScope'] = 'dev/cde/other'
    elif change == 'property':
        changed['fixed'].update(format='name', property='EC2.VPC.Name', labelPolicy='none')
    elif change == 'resource-type':
        changed['fixed']['resourceType'] = 'EC2.Subnet'
    else:
        changed['fixed']['labelPolicy'] = 'resource-id'
    expected = approval.build_review(acquisition, selection, before, proposed, risks, schema, proposed_references=changed)
    assert original['dispositions'][0]['properties'] == expected['dispositions'][0]['properties']
    assert original['dispositions'][0]['changes'] != expected['dispositions'][0]['changes']
    assert original['proposedValuesDigest'] != expected['proposedValuesDigest']
    assert original['reviewDigest'] != expected['reviewDigest']
    with pytest.raises(ValueError, match='Review changed'):
        approval.verify_review(original, expected)
    approval.verify_review(expected, copy.deepcopy(expected))


def check_reference_location_and_description_are_not_meaning():
    fields = approval.validate_reference_proposal({'fixed': reference_trace()}, proposal()[2].authoritative)
    first = Expansion(fields, files={Path('/synthetic/first.properties'): '# original source comment'})
    changed = Expansion(fields, files={Path('/synthetic/other.properties'): '# different source description and position'})
    assert approval.reference_provenance(first) == approval.reference_provenance(changed) == {'fixed': reference_trace()}


@pytest.mark.parametrize('invalid', ['unknown-key', 'invalid-type', 'invalid-selector', 'invalid-fixed-target', 'unknown-field'])
def check_reference_proposal_uses_existing_contract(invalid):
    acquisition, selection, before, proposed, risks = proposal()
    state = {'fixed': reference_trace()}
    if invalid == 'unknown-key':
        state['fixed']['consumerKey'] = 'desired.row.999-001.value'
    elif invalid == 'invalid-type':
        state['fixed']['producerKind'] = 'string'
    elif invalid == 'invalid-selector':
        state['fixed']['producerLogicalId'] = True
    elif invalid == 'invalid-fixed-target':
        state['fixed']['producerScope'] = '../invalid'
    else:
        state['fixed']['unknown'] = 'unsupported'
    with pytest.raises(ValueError):
        approval.build_review(acquisition, selection, before, proposed, risks, schema, proposed_references=state)


def check_unselected_reference_selector_is_rejected():
    acquisition, selection, before, proposed, risks = proposal()
    values = {'desired.resource.002.resourceType': 'EC2.VPC', 'desired.resource.002.resourceMode': 'IMPORT',
              'desired.resource.002.logicalId': 'EC2_VPC_002', 'desired.service.identity.lastAllocated': '{"EC2.VPC":2}', 'desired.row.002-001.property': 'EC2.VPC.VpcId',
              'desired.row.002-001.value': '[vpc](vpc.md#vpc-two)', 'desired.row.002-001.comment': 'unselected'}
    original = {'fixed': {**reference_trace('002'), 'consumerKey': 'desired.row.002-001.value', 'text': '[vpc](vpc.md#vpc-two)'}}
    before = Expansion(approval.validate_reference_proposal(original, {**before.authoritative, **values}))
    proposed = approval.validate_reference_proposal(original, {**proposed, **values})
    changed = {'fixed': {**original['fixed'], 'producerLogicalId': 'EC2_VPC_001'}}
    with pytest.raises(ValueError, match='unselected Resource'):
        approval.build_review(acquisition, selection, before, proposed, risks, schema, proposed_references=changed)


def check_real_loader_retains_unresolved_reference_declaration(tmp_path):
    (tmp_path / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', 'alias': 'cde',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}), encoding='utf-8')
    fields = {'desired.resource.001.resourceType': 'EC2.Subnet', 'desired.resource.001.resourceMode': 'IMPORT',
        'desired.resource.001.logicalId': 'EC2_Subnet_001', 'desired.service.identity.lastAllocated': '{"EC2.Subnet":1}', 'desired.row.001-001.property': 'EC2.Subnet.VpcId',
        'desired.row.001-001.value': 'vpc-unobserved', 'desired.row.001-001.comment': 'Reference'}
    state = {'fixed': {**reference_trace('002'), 'text': 'vpc-unobserved', 'format': 'identifier',
        'property': 'EC2.VPC.VpcId', 'labelPolicy': 'none'}}
    fields = approval.validate_reference_proposal(state, fields)
    path = tmp_path / 'model/dev/cde/subnet.properties'
    path.parent.mkdir(parents=True)
    path.write_text(serialize(fields), encoding='utf-8')
    loaded = load_model(path)
    assert loaded.authoritative['desired.row.001-001.value'] == 'vpc-unobserved'
    assert loaded.warnings and approval.reference_provenance(loaded) == state
    assert approval.validate_reference_proposal(state, loaded.authoritative) == dict(loaded.authoritative)


@pytest.mark.parametrize('failure', [None, 'known', 'stale', 'create', 'type', 'collision', 'duplicate-target',
                                     'duplicate-physical', 'invalid-id', 'anchor', 'row', 'uncaptured'])
def check_explicit_bind_preserves_identity(failure):
    acquisition, selection, before, proposed, risks = proposal()
    before.authoritative.pop('observed.row.001-001.value')
    decision = selection['resources'][0]
    decision.update(action='bind', before={'identity': None, 'model': import_guard.digest(operation_values(before.authoritative, '001'))})
    if failure == 'known':
        before.authoritative['observed.row.001-001.value'] = '`vpc-old`'
    elif failure == 'stale':
        decision['before']['model'] = 'changed'
    elif failure == 'create':
        before.authoritative['desired.resource.001.resourceMode'] = 'CREATE'
    elif failure == 'type':
        before.authoritative['desired.resource.001.resourceType'] = 'EC2.Subnet'
    elif failure == 'invalid-id':
        acquisition['records'][0]['identity'] = 'PENDING_DEPLOY'
    elif failure in {'collision', 'duplicate-target', 'duplicate-physical'}:
        extra = {k.replace('.001', '.002'): 'other' if k.endswith('.anchor') else v.replace('#main', '#other')
                 for k, v in before.authoritative.items()}
        before.authoritative.update(extra)
        proposed.update(extra)
        if failure == 'collision':
            before.authoritative['observed.row.002-001.value'] = '`vpc-one`'
            proposed['observed.row.002-001.value'] = '`vpc-one`'
        else:
            record = copy.deepcopy(acquisition['records'][0])
            record['record'] = 'r2'
            acquisition['records'].append(record)
            risks['r2'] = []
            selection['resources'].append({**decision, 'record': 'r2',
                'resource': '001' if failure == 'duplicate-target' else '002',
                'before': {'identity': None, 'model': import_guard.digest(operation_values(before.authoritative, '002'))}})
    elif failure == 'anchor':
        proposed['desired.resource.001.anchor'] = 'changed'
    elif failure == 'row':
        proposed['desired.row.001-002.property'] = 'EC2.VPC.Other'
    elif failure == 'uncaptured':
        acquisition['records'][0]['properties']['EC2.VPC.CidrBlock'] = {'status': 'unavailable'}
    data = acquisition, selection, before, proposed, risks
    if failure:
        with pytest.raises(ValueError):
            review(data)
    else:
        result = review(data)
        entry = result['dispositions'][0]
        assert entry['operation'] == 'bind' and entry['targetResource'] == '001'
        assert entry['risks'] and 'unknown' in entry['risks'][0]['reason']
        assert entry['beforeResource'] == entry['afterResource']
        assert entry['properties'][1]['after'][0]['row'] == '001-001'
        assert entry['properties'][1]['after'][0]['observed'] == 'vpc-one'


def check_subnet_answers_correction_and_resume(tmp_path):
    acquisition = proposal()[0]
    acquisition['records'] = [{'record': 'subnet-' + str(n), 'kind': 'EC2.Subnet', 'identity': 'subnet-' + str(n)} for n in range(4)]
    acquisition['inventory'] = {'EC2.Subnet': {'status': 'complete'}}
    acquisition['root'] = str(tmp_path)
    baseline = tmp_path / 'baseline'
    baseline.write_text('same source')
    acquisition['sources'] = {'baseline': import_guard.file_hash(baseline)}
    answers = []
    session = tmp_path / 'session'
    session.mkdir()
    evidence = session / 'acquisition.json'
    evidence.write_text('sealed elsewhere in this unit')
    for n, action in enumerate(['bind', 'refresh', 'add', 'excluded']):
        answer = {'record': 'subnet-' + str(n), 'action': action, 'reason': 'Human selected in chat'}
        if action != 'excluded':
            answer.update(resource=str(n + 1).zfill(3), basis=[])
        answers.append(answer)
        checkpoint = approval.checkpoint(acquisition, copy.deepcopy(answers))
        (session / 'checkpoint.json').write_text(json.dumps(checkpoint))
        assert approval.verify_checkpoint(acquisition, checkpoint) == answers
    answers[1] = {'record': 'subnet-1', 'action': 'excluded', 'reason': 'Human corrected the previous answer'}
    saved = approval.checkpoint(acquisition, answers)
    (session / 'checkpoint.json').write_text(json.dumps(saved))
    with patch.object(m, 'target_for', return_value={'directory': 'cde'}), \
            patch.object(m, 'read_acquisition', return_value=acquisition):
        restored = m.resume_acquisition(tmp_path, 'dev', 'vpc', evidence)
        assert restored['answers'] == answers
        assert restored['answers'][0] == checkpoint['answers'][0]
        baseline.write_text('changed Model baseline')
        with pytest.raises(ValueError, match='Model sources changed'):
            m.resume_acquisition(tmp_path, 'dev', 'vpc', evidence)
    assert baseline.read_text() == 'changed Model baseline'


@pytest.mark.parametrize('failure', ['expired', 'baseline', 'task', 'worktree', 'scope', 'acquisition', 'duplicate', 'target'])
def check_checkpoint_rejects_stale_or_competing_answers(failure):
    acquisition = proposal()[0]
    answers = [{'record': 'r1', 'action': 'bind', 'resource': '001', 'reason': 'Human answer'}]
    saved = approval.checkpoint(acquisition, answers)
    if failure == 'expired':
        acquisition['acquiredAt'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    elif failure == 'baseline':
        acquisition['sources']['synthetic'] = 'changed'
    elif failure in {'task', 'worktree', 'scope', 'acquisition'}:
        saved[{'acquisition': 'acquisitionDigest'}.get(failure, failure)] = 'wrong'
    elif failure == 'duplicate':
        answers.append(copy.deepcopy(answers[0]))
    else:
        acquisition['records'].append({**acquisition['records'][0], 'record': 'r2'})
        saved['acquisitionDigest'] = import_guard.digest(acquisition)
        answers.append({**answers[0], 'record': 'r2'})
    with pytest.raises(ValueError):
        approval.verify_checkpoint(acquisition, saved)


@pytest.mark.parametrize('failure', [None, 'decision', 'issuer', 'human', 'expired', 'timezone', 'extension',
                                     'task', 'worktree', 'scope', 'acquisitionDigest', 'sourceBaselineDigest',
                                     'recordsDigest', 'reviewDigest', 'referencesDigest', 'selectionDigest',
                                     'proposedValuesDigest', 'impactDigest', 'sources'])
def check_review_binding_integrity_without_host(failure):
    data = proposal()
    binding = approval.review_binding(review(data), data[0])
    if failure in {'decision', 'issuer', 'human', 'sources'}:
        binding[failure] = 'not part of Review integrity'
    elif failure in {'expired', 'extension', 'timezone'}:
        binding['expiresAt'] = ((datetime.now(timezone.utc) + timedelta(days=8 if failure == 'extension' else -1)).isoformat()
                                if failure != 'timezone' else datetime.now().isoformat())
    elif failure:
        binding[failure] = ''
    if failure:
        with pytest.raises(ValueError, match='Review binding'):
            approval.verify_review_binding(binding)
    else:
        assert approval.verify_review_binding(binding) == binding


def check_unanswered_review_cannot_be_approved():
    data = proposal()
    data[1]['resources'].clear()
    data[1]['unreflected'] = [{'record': 'r1', 'reason': 'waiting for Human'}]
    result = review((*data[:3], data[2].authoritative, data[4]))
    with pytest.raises(ValueError, match='all Resource selections'):
        approval.review_binding(result, data[0])


def check_conversational_consent_contract():
    root = Path(__file__).resolve().parents[4]
    skill = (root / '.agents/skills/import/SKILL.md').read_text(encoding='utf-8')
    prompt = (root / 'framework/prompts/codex/08_import.md').read_text(encoding='utf-8')
    rule = (root / 'framework/rules/model-information.md').read_text(encoding='utf-8')
    assert 'explicit Human final consent in chat' in skill
    for required in ('全件承認して反映', '一部修正', 'キャンセル', '「確認しました」「了解」',
                     'Proceed to Publish only after explicit consent',
                     'rebuild and present', 'renewed explicit final consent',
                     'Direct CLI execution can bypass', 'After merge the Human also'):
        assert required in prompt
    assert 'Python verifies change integrity, not the identity or existence' in rule
    assert 'Host approval, issuers, Human authentication tokens/signatures' in rule
    assert 'verify_host_approval' not in prompt + rule


def check_review_reports_every_canonical_change():
    acquisition, selection, _, proposed, risks = proposal()
    selection['resources'][0]['action'] = 'add'
    proposed.update({'display.resource.001.comment': '全件提示に含める説明',
        'display.service.title': '# 合成サービス', 'desired.service.vpc.serviceId': 'vpc',
        'desired.row.001-002.comment': ''})
    review = approval.build_review(acquisition, selection, Expansion({}), proposed, risks, schema)
    changes = [change for item in review['dispositions'] for change in item['changes']] + review['serviceChanges']
    assert {change['key'] for change in changes} == set(proposed)
    assert all(change['before'] == {'present': False, 'value': None} for change in changes)
    assert {change['key']: change['after'] for change in changes} == {
        key: {'present': True, 'value': value} for key, value in proposed.items()}
    assert any(change['key'] == 'display.resource.001.comment' for change in review['dispositions'][0]['changes'])


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

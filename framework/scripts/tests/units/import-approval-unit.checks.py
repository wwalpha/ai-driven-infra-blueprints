#!/usr/bin/env python3
"""Synthetic Review/publication integrity units; conversational consent is an agent responsibility."""
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
def check_local_claim_cannot_replace_review_binding(tmp_path, claim):
    evidence = tmp_path / 'acquisition.json'
    evidence.write_text('{}')
    (tmp_path / 'approval.json').write_text(json.dumps(claim))
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='invalid Review binding'):
        import_guard.record_import(tmp_path, {}, evidence, {}, review_binding=claim)
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def check_alternate_source_guard_rejects_legacy_receipt(tmp_path):
    (tmp_path / '.git').mkdir()
    task = tmp_path / 'tasks/import.md'
    text = '## Task contract\n- Workflow: `import`\n'
    with patch.object(import_guard, 'changed_sources', return_value={'model/templates/cde/vpc.properties.tpl'}), \
            patch.object(import_guard, 'task_path', return_value=task), \
            patch.object(import_guard, 'contracts', return_value={'tasks/import.md': text}), \
            patch.object(import_guard, 'read_proof', side_effect=ValueError('IMPORT change has no verified /import evidence')) as receipt:
        with pytest.raises(ValueError, match='no verified /import evidence'):
            import_guard.require_import_changes(tmp_path, output={tmp_path / 'model/templates/cde/vpc.properties.tpl': 'forged'})
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


@pytest.mark.parametrize('failure', [None, 'load', 'render', 'review', 'property', 'selection', 'baseline', 'provenance'])
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
    rejected_review = failure in {'property', 'selection', 'baseline', 'provenance'}
    if failure == 'review' or rejected_review:
        if failure == 'provenance':
            before = before._replace(provenance={'desired.row.001-001.value': reference_trace()})
            after = after._replace(provenance={'desired.row.001-001.value': reference_trace('002')})
        draft = {'proposedValues': proposed, 'risks': {'r1': []}}
        reviewed = approval.build_review(acquisition, selection, before, proposed, draft['risks'], schema)
        if failure == 'property':
            reviewed['dispositions'][0]['properties'][0]['after'][0]['desired'] = '10.2.0.0/16'
        elif failure == 'selection':
            reviewed['selection']['resources'][0]['resource'] = '009'
        elif failure == 'baseline':
            reviewed['sourceBaselineDigest'] = 'forged'
        reviewed['reviewDigest'] = import_guard.digest({k: v for k, v in reviewed.items() if k != 'reviewDigest'})
        (evidence.parent / 'review-input.json').write_text(json.dumps(draft))
        (evidence.parent / 'review.json').write_text(json.dumps(reviewed))
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
        if failure in {'load', 'render'} or rejected_review:
            with pytest.raises(ValueError, match='structure error|Review changed'):
                m.publish_selected(tmp_path, ('dev', 'cde', 'vpc'), evidence, acquisition, True)
        else:
            result = m.publish_selected(tmp_path, ('dev', 'cde', 'vpc'), evidence, acquisition, True)
            assert result['model'] == 'unchanged' and result['status'] == 'dry-run'
        save.assert_not_called()
    assert calls == ([] if rejected_review else ['display'] if failure == 'load' else ['display', 'render'])
    assert source.read_text() == 'original' and evidence.read_text() == 'retained evidence'



def check_missing_review_rejected_before_candidate_load(tmp_path):
    evidence = tmp_path / 'acquisition.json'
    evidence.write_text('retained')
    with patch.object(m, 'candidate_sources') as candidates, patch.object(m, 'publish') as save:
        with pytest.raises(ValueError, match='requires review.json'):
            m.publish_selected(tmp_path, ('dev', 'cde', 'vpc'), evidence, {}, False)
        candidates.assert_not_called()
        save.assert_not_called()
    assert evidence.read_text() == 'retained'


def reference_trace(target='001', *, template=False):
    spec = {'type': 'reference', 'service': 'vpc', 'resourceType': 'EC2.VPC',
            'format': 'identifier', 'property': 'EC2.VPC.VpcId'}
    return {'template': '/synthetic/file', 'line': 10, 'definition': 'Main', 'instance': 'main',
            'key': 'desired.row.Vpc-Id.value',
            'references': {'Vpc': {**spec, 'source': 'template', 'target': target}} if template else {},
            'inputs': {} if template else {'Vpc': {**spec, 'source': 'instance', 'value': target}}}


@pytest.mark.parametrize('change', ['selector', 'declaration', 'service', 'property', 'definition', 'input-name'])
def check_same_value_reference_meaning_is_bound(change):
    acquisition, selection, before, proposed, risks = proposal()
    key = 'desired.row.001-001.value'
    trace = reference_trace(template=change == 'declaration')
    before = before._replace(provenance={key: trace})
    original = approval.build_review(acquisition, selection, before, proposed, risks, schema)
    changed = copy.deepcopy(trace)
    if change == 'selector':
        changed['inputs']['Vpc']['value'] = '002'
    elif change == 'declaration':
        changed['references']['Vpc']['target'] = '002'
    elif change in {'service', 'property'}:
        changed['inputs']['Vpc'][change] = 'other' if change == 'service' else 'EC2.VPC.OtherId'
    elif change == 'definition':
        changed['definition'] = 'Other'
    else:
        changed['inputs']['Other'] = changed['inputs'].pop('Vpc')
    after = Expansion(proposed, {key: changed}, {})
    expected = approval.build_review(acquisition, selection, before, proposed, risks, schema,
                                     proposed_references=approval.reference_provenance(after))
    assert original['proposedValuesDigest'] == expected['proposedValuesDigest']
    assert original['reviewDigest'] != expected['reviewDigest']
    with pytest.raises(ValueError, match='Review changed'):
        approval.verify_review(original, expected)
    approval.verify_review(expected, copy.deepcopy(expected))


def check_reference_location_and_description_are_not_meaning():
    key = 'desired.row.001-001.value'
    trace = reference_trace()
    expansion = Expansion({}, {key: trace, 'observed.row.001-001.value': trace}, {})
    original = approval.reference_provenance(expansion)
    trace.update(template='/other/file', line=30, sourceFile='/other/input')
    trace['inputs']['Vpc']['description'] = 'different wording'
    assert approval.reference_provenance(expansion) == original
    assert set(original) == {key}


@pytest.mark.parametrize('invalid', ['unknown-key', 'invalid-type', 'invalid-selector', 'invalid-fixed-target', 'unknown-field'])
def check_reference_proposal_uses_existing_contract(invalid):
    acquisition, selection, before, proposed, risks = proposal()
    key = 'desired.row.001-001.value'
    state = approval.reference_provenance(Expansion(proposed, {key: reference_trace()}, {}))
    if invalid == 'unknown-key':
        state['desired.row.999-001.value'] = state.pop(key)
    elif invalid == 'invalid-type':
        state[key]['inputs']['Vpc']['type'] = 'string'
    elif invalid == 'invalid-selector':
        state[key]['inputs']['Vpc']['value'] = True
    elif invalid == 'invalid-fixed-target':
        state[key] = approval.reference_provenance(Expansion(proposed, {key: reference_trace(template=True)}, {}))[key]
        state[key]['references']['Vpc']['target'] = '../invalid'
    else:
        state[key]['inputs']['Vpc']['unknown'] = True
    with pytest.raises(ValueError):
        approval.build_review(acquisition, selection, before, proposed, risks, schema, proposed_references=state)


def check_unselected_reference_selector_is_rejected():
    acquisition, selection, before, proposed, risks = proposal()
    key = 'desired.row.002-001.value'
    values = {'desired.resource.002.resourceType': 'EC2.VPC',
              'desired.resource.002.resourceMode': 'IMPORT', 'desired.resource.002.anchor': 'other',
              'desired.row.002-001.property': 'EC2.VPC.VpcId', key: '[Other](#other)',
              'desired.row.002-001.comment': 'unselected'}
    before.values.update(values)
    proposed.update(values)
    before = before._replace(provenance={key: reference_trace()})
    after = Expansion(proposed, {key: reference_trace('002')}, {})
    with pytest.raises(ValueError, match='unselected Resource reference'):
        approval.build_review(acquisition, selection, before, proposed, risks, schema,
                              proposed_references=approval.reference_provenance(after))



def check_real_loader_retains_unresolved_reference_declaration(tmp_path):
    from model_templates import load_for_edit
    from support.model_sources import write_fixture_files
    declaration = {'type': 'reference', 'description': 'Vpc selector', 'required': True,
                   'service': 'vpc', 'resourceType': 'EC2.VPC', 'format': 'identifier', 'property': 'EC2.VPC.VpcId'}
    template = '\n'.join(['# model-template: 1', '# definition: Main',
        '# parameter: Vpc ' + json.dumps(declaration), '# resource: R', '# row: Ref R',
        'desired.resource.R.resourceType=EC2.Subnet', 'desired.resource.R.resourceMode=IMPORT',
        'desired.resource.R.anchor=subnet', 'desired.row.Ref.property=EC2.Subnet.VpcId',
        'desired.row.Ref.value=<<Vpc>>', 'desired.row.Ref.comment=Reference', '# end-definition']) + '\n'
    directory = tmp_path / 'model/parameters/dev/cde/subnet'
    write_fixture_files({tmp_path / 'model/templates/cde/subnet.properties.tpl': template,
        directory / 'parameters.yaml': "instances:\n  main:\n    parameters:\n      Vpc: '002'\n",
        directory / 'bindings.json': json.dumps({'instances': {'main': {'definition': 'Main',
            'resources': {'R': '001'}, 'rows': {'Ref': '001-001'}, 'parameters': {}, 'labels': {}}}})})
    expanded = load_for_edit(tmp_path / 'model/dev/cde/subnet.properties')
    assert expanded.values["desired.row.001-001.value"] == "<<Vpc>>"
    state = approval.reference_provenance(expanded)
    actual = state['desired.row.001-001.value']['inputs']['Vpc']
    assert actual == {k: v for k, v in {**declaration, 'source': 'instance', 'value': '002'}.items()
                      if k not in {'description', 'required'}}
    approval.validate_reference_proposal(state, expanded.values)



@pytest.fixture
def publication_case(tmp_path, monkeypatch):
    """Isolate parser/authority adapters; exercise the real file transaction in a temp root."""
    import import_references
    import model_templates
    import sync_runtime
    from unittest.mock import Mock
    acquisition, selection, before, proposed, risks = proposal()
    root = tmp_path / 'repo'
    source = root / 'model/templates/cde/vpc.properties.tpl'
    source.parent.mkdir(parents=True)
    source.write_text('original', encoding='utf-8')
    task = root / acquisition['task']
    task.parent.mkdir()
    task.write_text('## Task contract\n- Task type: `design`\n- Task status: `running`\n'
                    '- Workflow: `import`\n- IMPORT target: `dev/cde/vpc`\n'
                    '## Modified files\n- `tasks/import-fixture.md`\n'
                    '## Allowed paths\n- `tasks/import-fixture.md`\n', encoding='utf-8')
    evidence = tmp_path / 'evidence/acquisition.json'
    evidence.parent.mkdir()
    evidence.write_text('retained acquisition', encoding='utf-8')
    acquisition.update(root=str(root), sources={source.relative_to(root).as_posix(): import_guard.file_hash(source),
                       task.relative_to(root).as_posix(): import_guard.file_hash(task)}, consumers=[['dev', 'cde', 'vpc']])
    for name, value in [('selection.json', selection), ('review-input.json', {'proposedValues': proposed, 'risks': risks}),
                        ('review.json', approval.build_review(acquisition, selection, before, proposed, risks, schema))]:
        (evidence.parent / name).write_text(json.dumps(value), encoding='utf-8')
    after = Expansion(proposed, {}, {source: 'candidate'})
    document = root / 'docs/designs/dev/cde/vpc.md'
    proof = evidence.parent / 'proof.json'
    proof.write_text('previous proof', encoding='utf-8')
    finish = Mock()
    record = Mock(side_effect=lambda *a, **k: proof.write_text('candidate proof', encoding='utf-8'))
    resolver = SimpleNamespace(warnings=[], files={}, metrics={}, verify_resource=lambda *a, **k: None)
    monkeypatch.setattr(m, 'load_for_edit', lambda path, output=None, **kwargs: after if output else before)
    monkeypatch.setattr(m, 'candidate_sources', Mock(return_value={source: 'candidate'}))
    monkeypatch.setattr(m, 'preserve_consumers', lambda *a: ({}, set(), False))
    monkeypatch.setattr(m, 'replacement_inputs', lambda *a: ({}, ()))
    monkeypatch.setattr(m, 'property_schema', schema)
    monkeypatch.setattr(m, 'contract_scope', Mock())
    monkeypatch.setattr(m, 'record_outputs', Mock())
    monkeypatch.setattr(m, 'read_acquisition', lambda *a: copy.deepcopy(acquisition))
    monkeypatch.setattr(m, 'record_import', record)
    monkeypatch.setattr(m, 'finish_import', finish)
    monkeypatch.setattr(import_guard, 'proof_path', lambda *a, **k: proof)
    monkeypatch.setattr(import_references, 'Resolver', lambda *a, **k: resolver)
    monkeypatch.setattr(sync_runtime, 'owned_artifacts', lambda *a: set())
    monkeypatch.setattr(sync_runtime, 'view_plan', lambda *a: ({document: 'generated view'}, {document: None}))
    return SimpleNamespace(root=root, source=source, task=task, evidence=evidence, acquisition=acquisition,
                           after=after, document=document, proof=proof, finish=finish, record=record)


@pytest.mark.parametrize('failure', [None, 'review', 'draft', 'candidate', 'acquisition', 'baseline',
                                    'approval-expired', 'source-save', 'display-save', 'task-baseline'])
def check_publication_transaction_without_host(publication_case, monkeypatch, failure):
    case = publication_case
    def change_inputs(*args):
        if failure in {'review', 'draft'}:
            name = 'review.json' if failure == 'review' else 'review-input.json'
            with (case.evidence.parent / name).open('a', encoding='utf-8') as stream:
                stream.write(' ')
        elif failure == 'candidate':
            m.candidate_sources.return_value = {case.source: 'changed candidate'}
        elif failure == 'acquisition':
            monkeypatch.setattr(m, 'read_acquisition', lambda *a: {**case.acquisition, 'status': 'changed'})
        elif failure == 'approval-expired':
            class ExpiredClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime.now(tz) + timedelta(days=8)
            monkeypatch.setattr(approval, 'datetime', ExpiredClock)
        elif failure == 'baseline':
            case.source.write_text('external edit', encoding='utf-8')
        elif failure == 'task-baseline':
            case.task.write_text(case.task.read_text() + '\n# external Task change', encoding='utf-8')
    m.record_outputs.side_effect = change_inputs
    if failure == 'source-save':
        case.finish.side_effect = ValueError('source completion failure')
    if failure == 'display-save':
        real_publish = m.publish
        def save(root, output, **kwargs):
            if case.document in output:
                raise OSError('display save failure')
            return real_publish(root, output, **kwargs)
        monkeypatch.setattr(m, 'publish', save)
    if failure not in {None, 'display-save'}:
        with pytest.raises((ValueError, OSError)):
            m.publish_selected(case.root, ('dev', 'cde', 'vpc'), case.evidence, case.acquisition, False)
        assert case.source.read_text(encoding='utf-8') == ('external edit' if failure == 'baseline' else 'original')
        assert not case.document.exists()
        assert case.proof.read_text(encoding='utf-8') == 'previous proof'
        assert case.record.call_count == (1 if failure == 'source-save' else 0)
    else:
        result = m.publish_selected(case.root, ('dev', 'cde', 'vpc'), case.evidence, case.acquisition, False)
        assert case.source.read_text(encoding='utf-8') == 'candidate'
        assert result['model'] == 'reflected'
        assert result['status'] == ('display-failed' if failure else 'complete')
        assert result['markdown'] == ('failed' if failure else 'generated')
        assert case.record.call_count == 1
        plan = case.record.call_args.args[3]
        assert plan['sources'] == {'model/templates/cde/vpc.properties.tpl': 'candidate'}
        assert plan['selection']['resources'][0]['record'] == 'r1'
        assert case.proof.read_text(encoding='utf-8') == 'candidate proof'
        assert case.document.exists() is (failure is None)
    assert case.evidence.read_text(encoding='utf-8') == 'retained acquisition'
    assert (case.evidence.parent / 'review.json').exists()


def check_saved_display_recovery_needs_no_new_approval(publication_case, monkeypatch):
    import model_templates
    import sync_runtime
    case = publication_case
    case.source.write_text('candidate', encoding='utf-8')
    saved = case.after._replace(files={case.source: 'candidate'})
    monkeypatch.setattr(model_templates, 'load_for_edit', lambda *a, **k: saved)
    monkeypatch.setattr(import_guard, 'read_proof', lambda *a: {'model': 'reflected', 'ownedArtifacts': []})
    monkeypatch.setattr(import_guard, 'finish_import', case.finish)
    monkeypatch.setattr(sync_runtime, 'definition_root', lambda *a: m.ROOT)
    monkeypatch.setattr(m, 'read_acquisition', lambda *a: (_ for _ in ()).throw(AssertionError('no acquisition')))
    assert sync_runtime._sync(case.root, True, 'dev', 'cde', ['vpc']) == 0
    assert case.source.read_text(encoding='utf-8') == 'candidate'
    assert case.document.read_text(encoding='utf-8') == 'generated view'
    assert case.evidence.read_text(encoding='utf-8') == 'retained acquisition'
    case.finish.assert_called_once_with(case.root, markdown='generated')



@pytest.mark.parametrize('change', ['property', 'destination', 'resource', 'selector'])
def check_candidate_review_mismatch_rejected_without_host(publication_case, change):
    case = publication_case
    if change == 'property':
        case.after.values['desired.row.001-002.value'] = '`10.2.0.0/16`'
    elif change == 'destination':
        selection_file = case.evidence.parent / 'selection.json'
        selection = json.loads(selection_file.read_text(encoding='utf-8'))
        selection['resources'][0]['resource'] = '009'
        selection_file.write_text(json.dumps(selection), encoding='utf-8')
    elif change == 'resource':
        case.after.values.update({'desired.resource.002.resourceType': 'EC2.VPC',
                                  'desired.resource.002.resourceMode': 'IMPORT', 'desired.resource.002.anchor': 'extra'})
    else:
        case.after.provenance['desired.row.001-001.value'] = reference_trace('002')
    with pytest.raises(ValueError):
        m.publish_selected(case.root, ('dev', 'cde', 'vpc'), case.evidence, case.acquisition, False)
    assert case.source.read_text(encoding='utf-8') == 'original'
    assert not case.document.exists()
    assert case.evidence.read_text(encoding='utf-8') == 'retained acquisition'
    assert case.proof.read_text(encoding='utf-8') == 'previous proof'
    case.record.assert_not_called()



@pytest.mark.parametrize('failure', [None, 'known', 'stale', 'create', 'type', 'collision', 'duplicate-target',
                                     'duplicate-physical', 'invalid-id', 'anchor', 'row', 'uncaptured'])
def check_explicit_bind_preserves_identity(failure):
    from model_operation_checks import operation_values
    acquisition, selection, before, proposed, risks = proposal()
    before.values.pop('observed.row.001-001.value')
    decision = selection['resources'][0]
    decision.update(action='bind', before={'identity': None, 'model': import_guard.digest(operation_values(before.values, '001'))})
    if failure == 'known':
        before.values['observed.row.001-001.value'] = '`vpc-old`'
    elif failure == 'stale':
        decision['before']['model'] = 'changed'
    elif failure == 'create':
        before.values['desired.resource.001.resourceMode'] = 'CREATE'
    elif failure == 'type':
        before.values['desired.resource.001.resourceType'] = 'EC2.Subnet'
    elif failure == 'invalid-id':
        acquisition['records'][0]['identity'] = 'PENDING_DEPLOY'
    elif failure in {'collision', 'duplicate-target', 'duplicate-physical'}:
        extra = {k.replace('.001', '.002'): 'other' if k.endswith('.anchor') else v.replace('#main', '#other')
                 for k, v in before.values.items()}
        before.values.update(extra)
        proposed.update(extra)
        if failure == 'collision':
            before.values['observed.row.002-001.value'] = '`vpc-one`'
            proposed['observed.row.002-001.value'] = '`vpc-one`'
        else:
            record = copy.deepcopy(acquisition['records'][0])
            record['record'] = 'r2'
            acquisition['records'].append(record)
            risks['r2'] = []
            selection['resources'].append({**decision, 'record': 'r2',
                'resource': '001' if failure == 'duplicate-target' else '002',
                'before': {'identity': None, 'model': import_guard.digest(operation_values(before.values, '002'))}})
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
    result = review((*data[:3], data[2].values, data[4]))
    with pytest.raises(ValueError, match='all Resource selections'):
        approval.review_binding(result, data[0])



def check_conversational_consent_contract():
    root = Path(__file__).resolve().parents[4]
    skill = (root / '.agents/skills/import/SKILL.md').read_text(encoding='utf-8')
    prompt = (root / 'framework/prompts/codex/08_import.md').read_text(encoding='utf-8')
    rule = (root / 'framework/rules/model-information.md').read_text(encoding='utf-8')
    assert 'explicit Human final consent in chat' in skill
    for required in ('全件承認して反映', '一部修正', 'キャンセル', '「確認しました」「了解」',
                     'Proceed to candidate editing and Publish only after explicit consent',
                     'rebuild and present', 'renewed explicit final consent',
                     'Direct CLI execution can bypass', 'after merge the Human also'):
        assert required in prompt
    assert 'Python verifies change integrity, not the identity or existence' in rule
    assert 'Host approval, issuers, Human authentication tokens/signatures' in rule
    assert 'verify_host_approval' not in prompt + rule


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

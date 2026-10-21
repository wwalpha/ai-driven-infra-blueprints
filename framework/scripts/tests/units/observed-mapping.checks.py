"""Observed mappings retains permissive prefix selection and invocation isolation."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest
from model.adapters import observed
from model.core import entries


@pytest.fixture
def mapping_inputs(tmp_path, monkeypatch):
    loaded = {}
    monkeypatch.setattr(observed, 'models', lambda *args: loaded)
    monkeypatch.setattr(observed, 'model_exists', lambda path: False)
    monkeypatch.setattr(observed, 'require_fixed_stack_names', lambda *args: {})
    monkeypatch.setattr(observed, 'active_scope', lambda root: None)
    monkeypatch.setattr(observed, 'GROUPED', {})
    monkeypatch.setattr(observed, 'catalog_outputs', lambda *args: set())
    class Catalog:
        def __init__(self, root):
            pass
        def cloudformation_type(self, kind):
            return 'AWS::EC2::VPC'
    monkeypatch.setattr(observed, 'DesignSchemaCatalog', Catalog)
    def invoke(resources):
        return observed.mappings(tmp_path, 'dev', 'test', {'Stack': ({'Resources': resources}, {})},
                                 [{'name': 'Stack'}], target={'awsRegion': 'ap-northeast-1'})
    return tmp_path, loaded, invoke


def resource(values, identity, logical):
    values.update({f'desired.resource.{identity}.resourceType': 'EC2.VPC',
                   f'desired.resource.{identity}.logicalId': logical,
                   f'desired.resource.{identity}.cfn-logicalId': 'Stack-' + logical})


def definition():
    return {'Type': 'AWS::EC2::VPC'}


def check_prefix_order_and_dictionary_isolation(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    path = root / 'model/dev/test/vpc.properties'
    values = loaded[path] = {}
    for identity, logical in [('a', 'Parent'), ('a-b', 'Child'), ('', 'Empty'), ('missing', 'Missing')]:
        resource(values, identity, logical)
    for rid in ['orphan-1', 'a-b-2', '-empty', 'a-b-1', 'a-1', 'ab-1', 'plain', 'a--tail', 'a-']:
        values[f'desired.row.{rid}.value'] = rid
        values[f'desired.row.{rid}.property'] = 'EC2.VPC.CidrBlock'
    other = root / 'model/dev/test/other.properties'
    loaded[other] = {}
    resource(loaded[other], 'a', 'Other')
    loaded[other]['desired.row.a-1.value'] = 'other'
    _, result = invoke({name: definition() for name in ['Parent', 'Child', 'Empty', 'Missing', 'Other']})
    assert list(result['Stack']) == ['Parent', 'Child', 'Empty', 'Missing', 'Other']
    for name, identity in [('Parent', 'a'), ('Child', 'a-b'), ('Empty', ''), ('Missing', 'missing')]:
        expected = [(rid, row) for rid, row in entries(values, 'desired.row.') if rid.startswith(identity + '-')]
        actual = result['Stack'][name][3]
        assert actual == expected
        assert [list(row.items()) for _, row in actual] == [list(row.items()) for _, row in expected]
    parent = dict(result['Stack']['Parent'][3])['a-b-1']
    child = dict(result['Stack']['Child'][3])['a-b-1']
    parent['value'] = 'changed'
    assert child['value'] == values['desired.row.a-b-1.value'] == 'a-b-1'
    assert result['Stack']['Other'][3] == [('a-1', {'value': 'other'})]
    values['desired.row.a-b-1.value'] = 'next call'
    assert dict(invoke({'Parent': definition()})[1]['Stack']['Parent'][3])['a-b-1']['value'] == 'next call'


def check_lazy_whole_model_parse_and_error_order(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / 'model/dev/test/vpc.properties'] = {'desired.row.orphan': 'malformed'}
    resource(values, 'a', 'First')
    resource(values, 'b', 'Second')
    assert invoke({})[1] == {'Stack': {}}
    inactive = definition() | {'Condition': 'Never'}
    # No selected resource means no Row parse, including an inactive resource.
    from unittest.mock import patch
    with patch.object(observed, 'condition_active', return_value=False):
        assert invoke({'First': inactive})[1] == {'Stack': {}}
    with pytest.raises(observed.MappingError) as caught:
        invoke({'Unknown': definition(), 'First': definition(), 'Second': definition()})
    assert caught.value.errors == {'Stack': [
        'Stack/Unknown: cfn-logicalId matches=0; explicit mapping required',
        'Stack/First: invalid model entry: desired.row.orphan',
        'Stack/Second: invalid model entry: desired.row.orphan']}
    # A malformed unused model must remain unparsed.
    loaded[root / 'model/dev/test/unused.properties'] = {'desired.row.unused': 'malformed'}
    del values['desired.row.orphan']
    assert invoke({'First': definition()})[1]['Stack']['First'][3] == []


def check_owner_collision_precedes_row_parse(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / 'model/dev/test/vpc.properties'] = {'desired.row.orphan': 'malformed'}
    resource(values, 'a', 'FirstName')
    resource(values, 'b', 'FirstName')
    with pytest.raises(observed.MappingError) as caught:
        invoke({'FirstName': definition()})
    assert caught.value.errors == {'Stack': [
        'Stack/FirstName: cfn-logicalId matches=2; explicit mapping required']}


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='observed mapping prefix checks: PASS'))

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
                   f'desired.resource.{identity}.logicalId': 'EC2_VPC_' + identity,
                   f'desired.resource.{identity}.cfn-logicalId': 'Stack-' + logical})


def definition():
    return {'Type': 'AWS::EC2::VPC'}


def check_fixed_ownership_and_invocation_isolation(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / 'model/dev/test/vpc.properties'] = {}
    resource(values, '001', 'Parent')
    resource(values, '002', 'Child')
    for rid in ['001-002', '002-001', '001-001']:
        values[f'desired.row.{rid}.value'] = rid
        values[f'desired.row.{rid}.property'] = 'EC2.VPC.CidrBlock'
    result = invoke({'Parent': definition(), 'Child': definition()})[1]['Stack']
    assert [rid for rid, row in result['Parent'][3]] == ['001-001', '001-002']
    assert [rid for rid, row in result['Child'][3]] == ['002-001']
    result['Parent'][3][0][1]['value'] = 'changed'
    assert values['desired.row.001-001.value'] == '001-001'
    values['desired.row.001-001.value'] = 'next call'
    assert dict(invoke({'Parent': definition()})[1]['Stack']['Parent'][3])['001-001']['value'] == 'next call'


def check_lazy_whole_model_parse_and_error_order(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / 'model/dev/test/vpc.properties'] = {'desired.row.orphan': 'malformed'}
    resource(values, '001', 'First')
    resource(values, '002', 'Second')
    assert invoke({})[1] == {'Stack': {}}
    from unittest.mock import patch
    with patch.object(observed, 'condition_active', return_value=False):
        assert invoke({'First': definition()})[1] == {'Stack': {}}
    with pytest.raises(observed.MappingError) as caught:
        invoke({'Unknown': definition(), 'First': definition(), 'Second': definition()})
    assert caught.value.errors == {'Stack': [
        'Stack/Unknown: cfn-logicalId matches=0; explicit mapping required',
        'Stack/First: invalid model entry: desired.row.orphan',
        'Stack/Second: invalid model entry: desired.row.orphan']}
    loaded[root / 'model/dev/test/unused.properties'] = {'desired.row.unused': 'malformed'}
    del values['desired.row.orphan']
    assert invoke({'First': definition()})[1]['Stack']['First'][3] == []
    values['desired.row.999-001.value'] = 'orphan'
    with pytest.raises(observed.MappingError, match='orphan desired row'):
        invoke({'First': definition()})


def check_explicit_mapping_uniqueness_and_no_name_inference(mapping_inputs):
    root, loaded, invoke = mapping_inputs
    values = loaded[root / 'model/dev/test/vpc.properties'] = {}
    resource(values, '001', 'First')
    del values['desired.resource.001.cfn-logicalId']
    with pytest.raises(observed.MappingError, match='explicit mapping required'):
        invoke({'First': definition()})
    values['desired.resource.001.cfn-logicalId'] = 'Stack-First'
    resource(values, '002', 'First')
    with pytest.raises(observed.MappingError, match='matches=2'):
        invoke({'First': definition()})
    values['desired.row.orphan'] = 'malformed'
    with pytest.raises(observed.MappingError) as caught:
        invoke({'First': definition()})
    assert caught.value.errors == {'Stack': [
        'Stack/First: cfn-logicalId matches=2; explicit mapping required']}


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='observed explicit mapping checks: PASS'))

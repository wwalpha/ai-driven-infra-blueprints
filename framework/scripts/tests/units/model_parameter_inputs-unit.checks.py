#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_parameter_inputs_fixtures import *

def check_yaml_schema():
    from model_parameter_inputs import values_for
    rejected(lambda: values_for({}, {'AvailabilityZone2': 'b', 'AvailabilityZone1': 'a'}, 'service'), "unknown parameter: service: ['AvailabilityZone1', 'AvailabilityZone2']")
    rejected(lambda: values_for({}, [], 'service'), 'expected an object')
    assert yaml_read('value: on\ndate: 2026-10-11\nnumber: 001\nboolean: true\n')=={'value':'on','date':'2026-10-11','number':'001','boolean':True}
    for text in ['a: 1\na: 2','a: {b: 1, b: 2}','a: !!python/object:bad {}','a: &x {b: 1}\nc: {<<: *x}']:rejected(lambda:yaml_read(text),'YAML')
    rejected(lambda:schema({'type':'integer','description':'test','required':True,'constraints':{'minimum':'x'}}),'numeric constraint')



def check_embedded_parameter_type():
    rejected(lambda:t.resolve('x<<Flag>>',{'Flag':True}),'non-string parameter embedded')




@pytest.mark.parametrize('external', [False, True])
@pytest.mark.parametrize('types,expected', [(['EC2.VPC'], '001'), (['EC2.Subnet'], 'zero matching'),
                                         ([], 'zero candidates'), (['EC2.VPC', 'EC2.VPC'], 'multiple matching')])
def check_reference_target_candidates(tmp_path, external, types, expected):
    from model_parameter_inputs import select_reference_target, parameter_value
    from types import SimpleNamespace
    from model_files import LoadedModel
    template = tmp_path / 'model/templates/team/consumer.properties.tpl'
    spec = {'type': 'reference', 'description': 'target', 'required': True, 'resourceType': 'EC2.VPC'}
    if external:
        spec.update(service='producer', source='template', target='producer', instance='producer')
    consumer = {'id': 'consumer', 'definition': 'Consumer', 'parameters': {'Ref': 'producer'}}
    resources = {f'r{i}': f'{i+1:03d}' for i in range(len(types))}
    values = {f'desired.resource.{local}.resourceType': '<<Type>>' for local in resources}
    values.update({f'desired.resource.{local}.anchor': 'anchor-' + rid for local, rid in resources.items()})
    producer = {'id': 'producer', 'definition': 'Producer', 'resources': resources, 'parameters': {'Type': types[0] if types else 'EC2.VPC'}}
    definitions = {'Consumer': SimpleNamespace(parameters={'Ref': spec}),
                   'Producer': t.Definition({'Type': {'type': 'string', 'description': 'type', 'required': True}},
                                           set(resources), {}, values, {}, set(), {}, {}, {})}
    bindings = {'instances': {'consumer': {}, 'producer': {'resources': resources}}}
    fields = {f'desired.resource.{rid}.resourceType': (producer, definitions['Producer'], '<<Type>>') for rid in resources.values()}
    dependency = tmp_path / 'producer-input'
    inputs = (None, ({}, {dependency: 'input'}, {}, {}, bindings, fields))
    def attributes(path, rid, kind, mode):
        return LoadedModel('', {f'desired.resource.{rid}.resourceType': types[int(rid)-1],
                                f'desired.resource.{rid}.anchor': 'anchor-' + rid}, {}, {dependency: 'input'})
    files = {}
    with patch.object(t, '_reference_inputs', return_value=inputs), patch.object(t, 'reference_values', side_effect=attributes), \
         patch.object(t, 'load_expansion', side_effect=AssertionError('full expansion forbidden')):
        call = lambda: select_reference_target(template, consumer, 'Ref', [consumer, producer], definitions, 'dev', files)
        if expected == '001':
            assert call() == ('001', 'resource')
            if not external:
                assert parameter_value(template, consumer, 'Ref', [consumer, producer], bindings, definitions, 'dev', {}) == '[001](#anchor-001)'
            else:
                assert files[dependency] == 'input'
        else:
            with pytest.raises(ValueError, match=expected) as error:
                call()
            for detail in ('consumerService', 'consumerInstance', 'parameter', 'producerService', 'target',
                           'expectedResourceType', 'candidateIds', 'matchingIds', 'reason'):
                assert detail in str(error.value)
            assert '<<Type>>' not in str(error.value)


@pytest.mark.parametrize('failure', [None, 'collision', 'format'])
def check_stack_target_identity(tmp_path, failure):
    from model_parameter_inputs import select_reference_target, parameter_value
    from types import SimpleNamespace
    from model_files import LoadedModel
    template = tmp_path / 'model/templates/team/consumer.properties.tpl'
    spec = {'type': 'reference', 'description': 'stack', 'required': True, 'service': 'cloudformation-stacks',
            'resourceType': 'CloudFormation.Stack', 'format': 'name'}
    if failure == 'format':
        del spec['format']
    item = {'id': 'consumer', 'definition': 'Consumer', 'parameters': {'Stack': '001'}}
    definitions = {'Consumer': SimpleNamespace(parameters={'Stack': spec})}
    fields = {'desired.stack.001.name': (None, None, 'StackName')}
    if failure == 'collision':
        fields['desired.resource.001.resourceType'] = (None, None, 'CloudFormation.Stack')
    inputs = (None, ({}, {}, {}, {}, {'instances': {}}, fields))
    def attributes(path, rid, kind, mode):
        if mode != 'name':
            raise ValueError('stack reference requires format:name')
        return LoadedModel('', {'desired.stack.001.name': 'StackName'}, {}, {})
    from contextlib import nullcontext
    with patch.object(t, '_reference_inputs', return_value=inputs), patch.object(t, 'reference_values', side_effect=attributes), \
         patch('import_scope.create_reference', return_value=nullcontext()):
        call = lambda: select_reference_target(template, item, 'Stack', [item], definitions, 'dev', {})
        if failure:
            rejected(call, 'ambiguous resource/stack' if failure == 'collision' else 'format:name')
        else:
            assert call() == ('001', 'stack')
            assert parameter_value(template, item, 'Stack', [item], {'instances': {'consumer': {}}}, definitions, 'dev', {}) == 'StackName'


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

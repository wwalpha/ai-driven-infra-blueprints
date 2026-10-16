#!/usr/bin/env python3
"""Offline active-definition shared inputs and save/rejection regression."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
from pathlib import Path
import tempfile
from unittest.mock import patch

import model_templates as t
from model_parameter_inputs import parameter_text, yaml_read
from test_support.model_sources import write_fixture_files as save_files


def rejected(call, phrase):
    try:
        call()
    except ValueError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid input accepted: ' + phrase)


def check(root):
    template = root / 'model/templates/team/security-group.properties.tpl'
    shared = {'type': 'string', 'description': 'Endpoint共通の受信元IPv4範囲',
              'required': True, 'source': 'service', 'constraints': {'cidr': 'ipv4'}}
    text = '# model-template: 1\n# input: EndpointIngressCidr ' + t.json_text(shared) + '\n'
    for name, value in [('Plain', '`fixed`'), ('Endpoint', '`<<EndpointIngressCidr>>`')]:
        text += '\n'.join([
            '# definition: ' + name, '# resource: group', '# row: description group',
            'desired.resource.group.resourceType=EC2.SecurityGroup',
            'desired.resource.group.anchor=security-group-<<Id_group>>',
            'desired.row.description.property=EC2.SecurityGroup.GroupDescription',
            'desired.row.description.value=' + value, '# end-definition', ''])
    save_files({template: text})
    definitions = t.parse_template(template)[0]
    def bindings(definition, count=1):
        return {'instances': {f'group-{n}': {'definition': definition,
            'resources': {'group': str(n)}, 'rows': {'description': str(n) + '-001'},
            'parameters': {}, 'labels': {}} for n in range(1, count + 1)}}
    observed = {'version': 1, 'values': {}}
    plain, human = bindings('Plain'), {'instances': {}}
    before = t.expand(template, human, observed, plain, 'preview')[0]
    serialized = parameter_text(human, definitions, plain)
    assert yaml_read(serialized) == human and 'parameters:' not in serialized
    assert t.expand(template, yaml_read(serialized), observed, plain, 'preview')[0] == before
    rejected(lambda: t.expand(template, {'parameters': {'EndpointIngressCidr': '10.0.0.0/24'},
                                          'instances': {}}, observed, plain, 'preview'), 'human parameters requires exactly')
    endpoint = bindings('Endpoint', 2)
    active = {'parameters': {'EndpointIngressCidr': '10.0.0.0/24'}, 'instances': {}}
    values = t.expand(template, active, observed, endpoint, 'preview')[0]
    assert [values[f'desired.row.{n}-001.value'] for n in (1, 2)] == ['`10.0.0.0/24`'] * 2
    assert parameter_text(active, definitions, endpoint).count('EndpointIngressCidr:') == 1
    for parameters, phrase in [({}, 'missing required parameter'),
                               ({'Value1': 'old'}, 'unknown parameter'),
                               ({'EndpointIngressCidr': 3}, 'type mismatch'),
                               ({'EndpointIngressCidr': '10.0.0.1/24'}, 'constraint cidr')]:
        rejected(lambda: t.expand(template, {'parameters': parameters, 'instances': {}},
                                  observed, endpoint, 'preview'), phrase)
    invalid = copy.deepcopy(plain); invalid['instances']['group-1']['definition'] = 'Missing'
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'unknown definition')
    invalid = copy.deepcopy(plain); invalid['instances']['group-1'] = None
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'internal instance binding')
    invalid = copy.deepcopy(plain); invalid['instances'] = []
    rejected(lambda: t.expand(template, human, observed, invalid, 'preview'), 'instance/internal binding mismatch')
    legacy = {'version': 1, 'instances': [{**plain['instances']['group-1'], 'id': 'group-1'}]}
    legacy['instances'][0].pop('labels')
    rejected(lambda: t.expand(template, legacy, observed, plain, 'preview'), 'human parameters requires exactly')
    path = root / 'model/preview/team/security-group.properties'
    directory = root / 'model/parameters/preview/team/security-group'
    save_files({path: ''.join(k + '=' + v + '\n' for k, v in before.items()),

        directory / 'parameters.yaml': serialized,
        directory / 'bindings.json': t.json_text(plain),
        directory / 'observed.json': t.json_text(observed)})
    def writable(repository, paths):
        assert repository == root and paths == {directory / 'parameters.yaml'}
    with patch('task_contract.require_writable', writable):
        t.save_parameters(path, human)
        first = (directory / 'parameters.yaml').read_bytes()
        t.save_parameters(path, human)
        assert (directory / 'parameters.yaml').read_bytes() == first
        rejected(lambda: t.save_parameters(path, {'parameters': {}, 'instances': {}}), 'human parameters requires exactly')
        assert (directory / 'parameters.yaml').read_bytes() == first
    assert t.expand(template, human, observed, plain, 'preview')[0] == before


with tempfile.TemporaryDirectory(prefix='used-definition-inputs-') as directory:
    check(Path(directory))
print('used-definition-inputs: PASS (unused/active definitions, shared once, rejection, JSON rejection, atomic save rerun)')

#!/usr/bin/env python3
"""Native YAML remains generic; Model references use fixed saved identities."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json

import pytest
from model.core import entries
from model.format import FORMAT, parse
from model.references import usages
from model.sources import load_model
from support.import_model_fixtures import (
    reference_fields,
    resource_values,
    service_values,
)
from support.model_sources import write_model
from utils.yaml_format import yaml_read

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_yaml_schema():
    assert yaml_read('value: on\ndate: 2026-10-11\nnumber: 001\nboolean: true\n') == {'value': 'on', 'date': '2026-10-11', 'number': '001', 'boolean': True}
    for text in ['a: 1\na: 2', 'a: {b: 1, b: 2}', 'a: !!python/object:bad {}', 'a: &x {b: 1}\nc: {<<: *x}']:
        with pytest.raises(ValueError, match='YAML'):
            yaml_read(text)


def check_embedded_parameter_type():
    # Ordinary scalars have no interpolation or type inference in properties v2.
    raw = 'x<<Flag>> \\ " 001'
    assert parse(FORMAT + '\ndesired.note.literal.text=' + raw + '\n').values['desired.note.literal.text'] == raw


@pytest.mark.parametrize('external', [False, True])
@pytest.mark.parametrize('types,expected', [(['EC2.VPC'], '001'), (['EC2.Subnet'], 'zero matching'),
                                         ([], 'zero candidates'), (['EC2.VPC', 'EC2.VPC'], 'multiple matching')])
def check_reference_target_candidates(tmp_path, external, types, expected):
    (tmp_path / 'project.json').write_text(json.dumps({'targets': [{'environment': 'preview', 'alias': 'team',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
    path = tmp_path / 'model/preview/team/consumer.properties'
    producer = path.with_name('producer.properties') if external else path
    values = service_values('producer' if external else 'consumer', types or ['EC2.VPC'])
    for index, kind in enumerate(types, 1):
        rid = f'{index:03d}'
        values.update(resource_values(rid, kind, 'anchor-' + rid, 'CREATE', []))
    if external:
        write_model(producer, values)
        values = service_values('consumer', ['Example.Resource'])
    values.update(resource_values('009', 'Example.Resource', 'consumer', 'CREATE', [('Target', '[resource](' + ('producer' if external else 'consumer') + '.md#anchor-001)')]))
    values.update(reference_fields('fixed', 'desired.row.009-001.value', values['desired.row.009-001.value'],
        'preview/team/' + ('producer' if external else 'consumer') + '/001', kind='EC2.VPC', mode='link'))
    state = {}
    for _, resource in entries(values, 'desired.resource.'):
        state[resource['resourceType']] = max(state.get(resource['resourceType'], 0), int(resource['logicalId'].rsplit('_', 1)[1]))
    values['desired.service.identity.lastAllocated'] = json.dumps(state)
    write_model(path, values)
    snapshot = load_model(path)
    if expected in {'001', 'multiple matching'}:
        # An explicit fixed ID does not become ambiguous when another Resource has the same Type.
        assert not snapshot.warnings
        record, = usages(snapshot)
        assert record.producer_id == '001' and record.metadata_id == 'fixed'
        if external:
            assert producer in snapshot.dependencies
    else:
        assert snapshot.warnings and snapshot.authoritative['desired.reference.fixed.producerLogicalId'] == 'EC2_VPC_001'
        assert any('absent' in warning['message'] if types else 'absent' in warning['message'] for warning in snapshot.warnings)


@pytest.mark.parametrize('failure', [None, 'collision', 'format'])
def check_stack_target_identity(tmp_path, failure):
    (tmp_path / 'project.json').write_text(json.dumps({'targets': [{'environment': 'preview', 'alias': 'team',
        'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
    path = tmp_path / 'model/preview/team/consumer.properties'
    stack = path.with_name('cloudformation-stacks.properties')
    values = {'desired.stack.001.name': 'StackName', 'desired.stack.001.template': 'stack.yaml',
              'desired.stack.001.parameters': 'stack.json', 'desired.stack.001.deployOrder': '1'}
    write_model(stack, values)
    values = service_values('consumer', ['Example.Resource'])
    values.update(resource_values('001', 'Example.Resource', 'consumer', 'CREATE', [('Target', 'StackName')]))
    fields = {'consumerKey': 'desired.row.001-001.value', 'text': 'StackName', 'occurrence': '1', 'producerKind': 'stack',
              'producerScope': 'preview/team/cloudformation-stacks', 'producerId': '001', 'format': 'name',
              'property': 'name', 'labelPolicy': 'none'}
    if failure == 'format':
        fields['format'] = 'link'
    if failure == 'collision':
        fields['resourceType'] = 'CloudFormation.Stack'
    values.update({'desired.reference.stack.' + field: raw for field, raw in fields.items()})
    write_model(path, values)
    if failure:
        with pytest.raises(ValueError, match='stack reference|forbidden'):
            load_model(path)
    else:
        snapshot = load_model(path)
        record, = usages(snapshot)
        assert record.producer_kind == 'stack' and record.producer_id == '001' and record.text == 'StackName'
        assert not snapshot.warnings


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

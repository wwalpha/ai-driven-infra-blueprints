#!/usr/bin/env python3
"""Offline raw typed identifiers: observed authority, rejection and dependency propagation."""
from test_support.model_sources import write_model
from model_files import read_model
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
from pathlib import Path
import tempfile

import model_templates as t
from model_files import load_model
from model_parameter_inputs import reference_schema, schema
from test_support.model_sources import write_fixture_files as save_files


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid identifier reference accepted: ' + phrase)


def check(root):
    catalog = Path(__file__).resolve().parents[2] / 'framework/materials/aws/EC2_VPC.properties'
    producer = root / 'model/preview/team/vpc.properties'
    pdir = root / 'model/parameters/preview/team/vpc'
    ptemplate = root / 'model/templates/team/vpc.properties.tpl'
    desired = {
        'desired.service.vpc.serviceId': 'vpc',
        'desired.resource.001.resourceType': 'EC2.VPC',
        'desired.resource.001.anchor': 'vpc-one',
        'desired.row.001-001.property': 'EC2.VPC.Name',
        'desired.row.001-001.value': '`vpc-one`',
        'desired.row.001-002.property': 'EC2.VPC.VpcId',
        'desired.row.001-002.value': '[vpc-one](#vpc-one)',
    }
    observed = {'version': 1, 'values': {
        'observed.row.001-002.property': 'EC2.VPC.VpcId',
        'observed.row.001-002.value': '`vpc-fixture-one`'}}
    save_files({root / 'framework/materials/aws/EC2_VPC.properties': (catalog).read_text(encoding="utf-8"),
        ptemplate: '# model-template: 1\n# definition: Vpc\n# resource: vpc\n# row: name vpc\n# row: id vpc\n' +
            '\n'.join(k.replace('resource.001.', 'resource.vpc.').replace('row.001-001.', 'row.name.').replace('row.001-002.', 'row.id.') + '=' + v for k,v in desired.items()) + '\n# end-definition\n',
        producer: ''.join(k+'='+v+'\n' for k,v in {**desired, **observed['values']}.items()),
        pdir/'parameters.yaml': 'instances: {}\n',
        pdir/'bindings.json': t.json_text({'instances': {'main': {'definition': 'Vpc', 'resources': {'vpc': '001'}, 'rows': {'name': '001-001', 'id': '001-002'}, 'parameters': {}, 'labels': {}}}}),
        pdir/'observed.json': t.json_text(observed)})
    observed['values'] = {key:value for key,value in observed['values'].items() if key.endswith('.value')}
    (pdir/'observed.json').write_text(t.json_text(observed))
    template = root / 'model/templates/team/vpc-endpoint.properties.tpl'
    ref = {'service':'vpc', 'resource':'001', 'resourceType':'EC2.VPC', 'format':'identifier', 'property':'EC2.VPC.VpcId'}
    text = '\n'.join(['# model-template: 1', '# definition: Endpoint', '# reference: VpcId '+t.json_text(ref),
        '# resource: endpoint', '# row: policy endpoint', 'desired.resource.endpoint.resourceType=EC2.VPCEndpoint',
        'desired.resource.endpoint.anchor=endpoint-<<Id_endpoint>>',
        'desired.row.policy.property=EC2.VPCEndpoint.PolicyDocument',
        'desired.row.policy.document={"Condition":{"StringEquals":{"aws:SourceVpc":"<<VpcId>>"}},"Enabled":true}', '# end-definition'])+'\n'
    template.parent.mkdir(parents=True, exist_ok=True); template.write_text(text)
    bindings = {'instances': {'gateway': {'definition':'Endpoint', 'resources':{'endpoint':'008'}, 'rows':{'policy':'008-001'}, 'parameters':{}, 'labels':{}}}}
    human, empty = {'instances':{}}, {'version':1, 'values':{}}
    values, provenance, files = t.expand(template, human, empty, bindings, 'preview')
    key = 'desired.row.008-001.document'
    assert t.json_read(values[key]) == {'Condition':{'StringEquals':{'aws:SourceVpc':'vpc-fixture-one'}}, 'Enabled':True}
    assert pdir/'observed.json' in files
    path = root/'model/preview/team/vpc-endpoint.properties'
    directory = root/'model/parameters/preview/team/vpc-endpoint'
    save_files({path: ''.join(k+'='+v+'\n' for k,v in values.items()),

        directory/'parameters.yaml':'instances: {}\n', directory/'bindings.json':t.json_text(bindings), directory/'observed.json':t.json_text(empty)})
    assert pdir/'observed.json' in t.source_inputs(path)
    assert 'VpcId' in t.load_expansion(path).provenance[key]['parameters']
    assert t.affected(root, [(pdir/'observed.json').relative_to(root)]) == {('preview','team','vpc'), ('preview','team','vpc-endpoint')}
    before = t.design_source_digest(path)
    for raw in ['`vpc-fixture-two`', '`PENDING_DEPLOY`']:
        changed = copy.deepcopy(observed); changed['values']['observed.row.001-002.value'] = raw
        (pdir/'observed.json').write_text(t.json_text(changed))
        assert t.design_source_digest(path) != before
        assert t.json_read(load_model(path).values[key])['Condition']['StringEquals']['aws:SourceVpc'] == raw.strip('`')
    producer_text = ptemplate.read_text()
    for producer_candidate, observed_values in (
        (producer_text.replace('row.id.property=EC2.VPC.VpcId', 'row.id.property=EC2.Subnet.SubnetId'), observed['values']),
        (producer_text.replace('row.name.property=EC2.VPC.Name', 'row.name.property=EC2.VPC.VpcId'),
         {**observed['values'], 'observed.row.001-001.value':'`duplicate`'}),
    ):
        ptemplate.write_text(producer_candidate)
        (pdir/'observed.json').write_text(t.json_text({'version':1,'values':observed_values}))
        rejected(lambda: load_model(path), 'matching observed identifier')
    ptemplate.write_text(producer_text)
    for change, phrase in [
        ({}, 'matching observed identifier'),
        ({'observed.row.001-002.property':'EC2.Subnet.SubnetId','observed.row.001-002.value':'`subnet-one`'}, 'invalid observed key/value'),
        ({**observed['values'],'observed.row.001-001.property':'EC2.VPC.VpcId','observed.row.001-001.value':'`duplicate`'}, 'invalid observed key/value'),
        ({**observed['values'],'observed.row.001-002.value':False}, 'invalid observed key/value'),
        ({**observed['values'],'observed.row.001-002.value':'``'}, 'nonempty non-ARN string'),
        ({**observed['values'],'observed.row.001-002.value':'arn:aws:fixture'}, 'nonempty non-ARN string')]:
        (pdir/'observed.json').write_text(t.json_text({'version':1,'values':change}))
        rejected(lambda: load_model(path), phrase)
    (pdir/'observed.json').write_text(t.json_text(observed))
    for change, phrase in [({'resource':'002'},'type-mismatched'), ({'resourceType':'EC2.Subnet','property':'EC2.Subnet.SubnetId'},'type-mismatched'), ({'property':'EC2.VPC.Name'},'not a catalog identifier')]:
        template.write_text(text.replace(t.json_text(ref),t.json_text({**ref, **change})))
        rejected(lambda: load_model(path), phrase)
    template.write_text(text)
    producer_template = ptemplate.read_text()
    ptemplate.write_text(producer_template.replace('desired.row.name.property=EC2.VPC.Name', 'desired.row.name.property=EC2.VPC.VpcId'))
    rejected(lambda: load_model(path), 'matching observed identifier')
    ptemplate.write_text(producer_template)
    invalid = copy.deepcopy(bindings); invalid['instances']['gateway']['labels']['VpcId'] = 'override'
    rejected(lambda: t.expand(template,human,empty,invalid,'preview'), 'cannot override label')
    for bad in [{k:v for k,v in ref.items() if k!='property'}, {**ref,'property':'EC2.VPC.Arn'}, {**ref,'property':'EC2.Subnet.SubnetId'}, {'instance':'main','resourceType':'EC2.VPC','format':'identifier','property':'EC2.VPC.VpcId'}]:
        rejected(lambda: reference_schema(bad), 'identifier' if 'service' in bad else 'invalid Model parameter format')
    rejected(lambda: schema({'type':'string','description':'bad','required':True,'format':'identifier','property':'EC2.VPC.VpcId'}), 'invalid Model parameter format')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink(); rejected(lambda:load_model(path),'missing')
    print('Producer identifiers: PASS (typed observed value, JSON type, pending value, rejection, hash/impact)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

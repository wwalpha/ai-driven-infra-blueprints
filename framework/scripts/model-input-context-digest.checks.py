#!/usr/bin/env python3
"""Offline account context and canonical document digest regression."""
import copy
import json
import tempfile
from pathlib import Path

import model_templates as t
from model_files import load_model
from model_parameter_inputs import parameter_text
from model_projection import document_sha256, json_sha256
from test_support.model_sources import write_fixture_files as save_files

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def rejected(call):
    try:
        call()
    except (ValueError, OSError):
        return
    raise AssertionError('invalid context/override accepted')


def check(root):
    project = root/'project.json'
    target = {'environment':'preview','alias':'team','awsAccountId':'111111111111',
              'awsExecutionAccountId':'123456789012','awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}
    topology = {'targets':[target]}
    template = root/'model/templates/team/sqs.properties.tpl'
    text = '\n'.join(['# model-template: 1',
        '# input: Account '+t.json_text({'type':'string','description':'実行account','required':True,'source':'consumer.executionAccountId'}),
        '# definition: Policy','# resource: policy','# row: doc policy',
        'desired.resource.policy.resourceType=SQS.QueuePolicy',
        'desired.resource.policy.anchor=queue-policy',
        'desired.row.doc.property=SQS.QueuePolicy.PolicyDocument',
        'desired.row.doc.value=[policy](sqs/policy.json)',
        'desired.row.doc.document='+t.json_text({'Statement':[{'Action':['sqs:SendMessage','sqs:GetQueueUrl'],
            'Condition':{'StringEquals':{'aws:SourceAccount':'<<Account>>'}},'Enabled':True,'Count':2}]}),
        '# end-definition',''])
    human = {'instances':{}}
    bindings = {'instances':{'policy':{'definition':'Policy','resources':{'policy':'007'},
        'rows':{'doc':'007-002'},'parameters':{},'labels':{}}}}
    observed = {'version':1,'values':{}}
    save_files({project:t.json_text(topology),template:text})
    values,_,files = t.expand(template,human,observed,bindings,'preview')
    key = 'desired.row.007-002.'
    document = json.loads(values[key+'document'])
    assert document['Statement'][0]['Condition']['StringEquals']['aws:SourceAccount']=='123456789012'
    assert document['Statement'][0]['Action']==['sqs:SendMessage','sqs:GetQueueUrl']
    assert document['Statement'][0]['Enabled'] is True and type(document['Statement'][0]['Count']) is int
    assert values[key+'artifactSha256']==document_sha256(document) and project in files
    artifact = root/'policy.json';save_files({artifact:json.dumps(document,indent=2)+'\n'})
    assert json_sha256(artifact)==values[key+'artifactSha256']
    path = root/'model/preview/team/sqs.properties';directory = root/'model/parameters/preview/team/sqs'
    save_files({path:''.join(k+'='+v+'\n' for k,v in values.items()),

        directory/'parameters.yaml':'instances: {}\n',directory/'bindings.json':t.json_text(bindings),
        directory/'observed.json':t.json_text(observed)})
    trace = t.load_expansion(path).provenance[key+'document']
    assert trace['inputs']['Account']['value']=='123456789012' and trace['sourceFile']==str(project)
    assert t.load_expansion(path).provenance[key+'artifactSha256']['derivedFrom']==key+'document'
    assert parameter_text(human,t.parse_template(template)[0],bindings)=='instances: {}\n'
    assert project in t.source_inputs(path) and t.affected(root,['project.json'])=={('preview','team','sqs')}
    before = t.design_source_digest(path)
    target.pop('awsExecutionAccountId');save_files({project:t.json_text(topology)})
    updated = load_model(path).values
    assert '111111111111' in updated[key+'document']
    assert updated[key+'artifactSha256']!=values[key+'artifactSha256'] and t.design_source_digest(path)!=before
    for targets in ([],[target,target],[{**target,'awsExecutionAccountId':123}],[{**target,'awsExecutionAccountId':'bad'}]):
        save_files({project:t.json_text({'targets':targets})})
        rejected(lambda:load_model(path))
    save_files({project:t.json_text(topology)})
    bad = copy.deepcopy(bindings);bad['instances']['policy']['parameters']['Account']='999999999999'
    rejected(lambda:t.expand(template,human,observed,bad,'preview'))
    rejected(lambda:t.expand(template,{'instances':{},'parameters':{'Account':'999999999999'}},observed,bindings,'preview'))
    rejected(lambda:t.expand(template,human,observed,bindings,None))
    # YAML updates recompute a stale document hash with the same type/order contract.
    changed = text.replace(text.splitlines()[1], '').replace('# definition: Policy', '# definition: Policy\n# parameter: Account {"type":"string","description":"account","required":true}')
    changed = changed.replace('# end-definition', 'desired.row.doc.artifactSha256=stale\n# end-definition')
    save_files({template: changed})
    human = {'instances': {'policy': {'parameters': {'Account': '222222222222'}}}}
    first = t.expand(template, human, observed, bindings, 'preview')[0]
    human['instances']['policy']['parameters']['Account'] = '333333333333'
    second = t.expand(template, human, observed, bindings, 'preview')[0]
    assert first[key+'artifactSha256'] == document_sha256(json.loads(first[key+'document']))
    assert second[key+'artifactSha256'] == document_sha256(json.loads(second[key+'document']))
    assert first[key+'artifactSha256'] != second[key+'artifactSha256']
    assert first[key+'document'] != second[key+'document']
    assert t.expand(template, human, observed, bindings, 'preview')[0] == second
    print('Consumer context/document digest: PASS (topology authority; override rejection; trace/hash/impact; canonical types/order; YAML update; rerun)')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

"""Suffix, export/import and Model naming contracts over authored offline inputs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from functools import cache
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model.core import entries, literal
from model.files import load_model
from model.sources import model_paths
from project_targets import load_target_directory as load_target
from support.it_case_receipt import it_case
from support.model_sources import write_model
from utils.cloudformation.format import decode_file as decode
from utils.cloudformation.inputs import checked_parameters, resolve_value
from utils.input_cache import input_scope

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

ROOT = Path(__file__).resolve().parents[4]


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


@cache
def document(path):
    value, errors = decode(str(path))
    assert not errors and isinstance(value, dict), (path, errors)
    return value


def units(path):
    env, alias = path.parent.parent.name, path.parent.name
    result = {}
    # Check implemented IaC templates; designed stacks can intentionally await implementation.
    available = {p.name for p in (ROOT/'infra/cloudformation/templates'/alias).glob('*.yaml')}
    for _, stack in entries(load_model(path).values, 'desired.stack.'):
        if stack['template'] not in available:
            continue
        template = ROOT/'infra/cloudformation/templates'/alias/stack['template']
        parameters = ROOT/'infra/cloudformation/parameters'/env/alias/stack['parameters']
        doc = document(template)
        values = checked_parameters(doc, json.loads(parameters.read_text(encoding='utf-8')))
        result[(stack['template'], stack['parameters'])] = (doc, values)
    assert result, 'no declared stack cases: '+str(path)
    return result


def parameters(doc, original, case):
    values = dict(original)
    if case == 'omitted':
        values['Suffix'] = doc['Parameters']['Suffix']['Default']
    elif case == 'empty':
        values['Suffix'] = ''
    elif case == 'alternate':
        values['Suffix'] = '-check'
    return values


@it_case
def check_imports(collection, producer_name, pseudo):
    producers = [item for (name, _), item in collection.items() if name == producer_name]
    assert producers, 'no export producer: '+producer_name
    producer, supplied = producers[0]
    if producer_name == 'vpc.yaml':
        assert producer['Outputs']['VpcId']['Value'] == {'Ref':'Vpc01'}
    else:
        for key, output in producer['Outputs'].items():
            if key.endswith('Name'):
                resource = key.removesuffix('Name')
                assert output['Value'] == {'Ref':resource}, key
            elif key.endswith('Arn'):
                resource = key.removesuffix('Arn')
                assert output['Value'] == {'Fn::GetAtt':[resource,'Arn']}, key
            else:
                raise AssertionError('unknown bucket output: '+key)
            assert producer['Resources'][resource]['Type'] == 'AWS::S3::Bucket'
    exports = {key: output['Export']['Name'] for key,output in producer['Outputs'].items() if 'Export' in output}
    assert exports
    count = 0
    for (name, _), (consumer, configured) in collection.items():
        for node in walk(consumer):
            if 'Fn::ImportValue' not in node:
                continue
            expression = node['Fn::ImportValue']
            base = next((base for base in exports if base in str(expression)), None)
            if base is None:
                continue
            assert isinstance(expression, dict), (name, expression)
            assert consumer['Parameters']['Suffix']['Default'] == ''
            # Sub and Join are both permitted by the formal YAML validator.
            for case in ('omitted', 'empty', 'configured', 'alternate'):
                incoming = parameters(consumer, configured, case)
                outgoing = parameters(producer, supplied, case)
                expected = resolve_value(exports[base], outgoing, pseudo, conditions=producer.get('Conditions',{}))
                actual = resolve_value(expression, incoming, pseudo, conditions=consumer.get('Conditions',{}))
                assert actual == expected, (name, base, case, actual, expected)
                assert expected == base + outgoing['Suffix'], (base, case, expected)
            count += 1
    assert count, 'no imports checked: '+producer_name
    return count


@it_case
def check_names(collection, path, pseudo):
    env, alias = path.parent.parent.name, path.parent.name
    iam = load_model(path.with_name('iam.properties')).values
    names = {literal(r['value']) for _,r in entries(iam,'desired.row.') if r.get('property') == 'IAM.Role.RoleName'}
    count = 0
    for (name, _), (doc, supplied) in collection.items():
        for resource in doc.get('Resources',{}).values():
            if resource['Type'] in {'AWS::IAM::Role','AWS::IAM::Policy','AWS::IAM::ManagedPolicy'}:
                for item in walk(resource):
                    if 'Resource' in item:
                        assert ':alias/' not in json.dumps(item['Resource']), (name,item)
            if resource['Type'] != 'AWS::IAM::Role':
                continue
            expression = resource.get('Properties',{}).get('RoleName')
            if expression is None or 'VulnerabilityScan02Role' not in str(expression):
                continue
            actual = resolve_value(expression, supplied, pseudo, conditions=doc.get('Conditions',{}))
            assert actual in names, (env,alias,name,actual)
            assert 'RoleNameSuffix' not in doc['Parameters']
            for case in ('omitted','empty','alternate'):
                values = parameters(doc, supplied, case)
                actual = resolve_value(expression, values, pseudo, conditions=doc.get('Conditions',{}))
                assert actual == f'venusinf-{env}-VulnerabilityScan02Role'+values['Suffix']
            count += 1
    if alias == 'non-cde':
        assert count, 'no vulnerability role cases'


@it_case
def check_flow_logs(collection, pseudo):
    named = {name:item for (name,_),item in collection.items()}
    vpc,vpc_parameters = named['vpc.yaml']
    kms,kms_parameters = named['kms.yaml']
    for suffix in ('', '/example'):
        group = resolve_value(vpc['Resources']['VpcFlowLogGroup01']['Properties']['LogGroupName'],dict(vpc_parameters,FlowLogSuffix=suffix),pseudo)
        policy = kms['Resources']['LogKey']['Properties']['KeyPolicy']['Statement'][1]['Condition']['ArnLike']['kms:EncryptionContext:aws:logs:arn'][0]
        arn = resolve_value(policy,dict(kms_parameters,FlowLogSuffix=suffix),pseudo).split(',')[0]
        assert group == '/aws/vpc/flow-logs'+suffix
        assert arn == f"arn:aws:logs:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:log-group:{group}"




def _fixture_export(resource, attribute, key):
    return {'Value': {'Ref': resource} if attribute == 'Name' else {'Fn::GetAtt': [resource, attribute]}, 'Export': {'Name': {'Fn::Sub': key + '${Suffix}'}}}


def fixture(root):
    target = {'environment':'dev','awsRegion':'ap-northeast-1','awsAccountId':'123456789012','iacEngine':'cloudformation'}
    (root/'project.json').write_text(json.dumps({'projectName':'fixture','targets':[target]}),encoding='utf-8')
    parameters = {'Suffix':{'Type':'String','Default':''},'FlowLogSuffix':{'Type':'String','Default':''}}
    export = _fixture_export
    templates = {
        's3.yaml':{'Parameters':parameters,'Resources':{'Bucket':{'Type':'AWS::S3::Bucket'}},'Outputs':{
            'BucketName':export('Bucket','Name','BucketName'),'BucketArn':export('Bucket','Arn','BucketArn')}},
        'vpc.yaml':{'Parameters':parameters,'Resources':{'Vpc01':{'Type':'AWS::EC2::VPC'},'VpcFlowLogGroup01':{
            'Type':'AWS::Logs::LogGroup','Properties':{'LogGroupName':{'Fn::Sub':'/aws/vpc/flow-logs${FlowLogSuffix}'}}}},
            'Outputs':{'VpcId':{'Value':{'Ref':'Vpc01'},'Export':{'Name':{'Fn::Sub':'VpcId${Suffix}'}}}}},
        'consumer.yaml':{'Parameters':parameters,'Resources':{'Role':{'Type':'AWS::IAM::Role','Properties':{
            'RoleName':{'Fn::Sub':'venusinf-${Environment}-VulnerabilityScan02Role${Suffix}'},
            'Vpc':{'Fn::ImportValue':{'Fn::Join':['',['VpcId',{'Ref':'Suffix'}]]}},
            'Bucket':{'Fn::ImportValue':{'Fn::Sub':'BucketName${Suffix}'}}}}}},
        'kms.yaml':{'Parameters':parameters,'Resources':{'LogKey':{'Type':'AWS::KMS::Key','Properties':{
            'KeyPolicy':{'Statement':[{}, {'Condition':{'ArnLike':{'kms:EncryptionContext:aws:logs:arn':[
                {'Fn::Sub':'arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/vpc/flow-logs${FlowLogSuffix}'}]}}}]}}}}}}
    templates['consumer.yaml']['Parameters'] = {**parameters,'Environment':{'Type':'String','Default':'dev'}}
    stacks = {}
    for number,(name,document) in enumerate(templates.items(),1):
        source=root/'infra/cloudformation/templates/123456789012'/name
        params=root/'infra/cloudformation/parameters/dev/123456789012'/name.replace('.yaml','.json')
        source.parent.mkdir(parents=True,exist_ok=True)
        params.parent.mkdir(parents=True,exist_ok=True)
        source.write_text(json.dumps(document),encoding='utf-8')
        params.write_text(json.dumps([{'ParameterKey':'Suffix','ParameterValue':'-fixture'}, {'ParameterKey':'FlowLogSuffix','ParameterValue':''}]),encoding='utf-8')
        stacks.update({f'desired.stack.{number}.name': 'fixture-' + str(number),
                       f'desired.stack.{number}.placementName': 'fixed-' + str(number),
                       f'desired.stack.{number}.template':name, f'desired.stack.{number}.parameters':params.name,
                       f'desired.stack.{number}.deployOrder': str(number)})
    write_model(root/'model/dev/123456789012/cloudformation-stacks.properties',stacks)
    write_model(root/'model/dev/123456789012/iam.properties',{
        'desired.resource.001.resourceType':'IAM.Role','desired.resource.001.logicalId':'IAM_Role_001',
        'desired.service.identity.lastAllocated':'{"IAM.Role":1}',
        'desired.row.001-001.property':'IAM.Role.RoleName','desired.row.001-001.value':'`venusinf-dev-VulnerabilityScan02Role-fixture`',
        'desired.row.001-001.comment':'合成の名前'})


@it_case
@input_scope
def check():
    with TemporaryDirectory(prefix='naming-contracts-') as directory:
        root = Path(directory)
        fixture(root)
        with patch(__name__+'.ROOT', root):
            check_fixtures()


@it_case
def check_fixtures():
    # Preserve the former standalone checks' dev scope; other environments remain covered by the normal validator.
    paths = [p for p in model_paths(ROOT) if p.stem == 'cloudformation-stacks' and p.parent.parent.name == 'dev']
    assert paths, 'no naming contract targets'
    count = 0
    for path in paths:
        target = load_target(ROOT,path.parent.parent.name,path.parent.name)
        pseudo = {'AWS::Partition':'aws','AWS::Region':target['awsRegion'],'AWS::AccountId':target.get('awsExecutionAccountId',target['awsAccountId'])}
        collection = units(path)
        count += check_imports(collection,'s3.yaml',pseudo)
        count += check_imports(collection,'vpc.yaml',pseudo)
        check_names(collection,path,pseudo)
        check_flow_logs(collection,pseudo)
    print(f'CloudFormation naming: PASS ({len(paths)} targets, {count} imports; omitted/empty/configured/alternate suffix, Model role names, FlowLog/KMS ARN)')


if __name__ == '__main__':
    check()

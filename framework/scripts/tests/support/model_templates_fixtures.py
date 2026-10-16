"""YAML service sources, fixed identities, scope and transaction regressions."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy, io, json, os, shutil, subprocess, sys, tempfile

from contextlib import redirect_stdout

from unittest.mock import patch

import model_templates as templates

from model_core import properties, entries

from cloudformation_inputs import Blocked

from model_files import load_model, read_model, model_parts, model_file_contents

from support.model_sources import write_fixture_files as save_files

from support.model_sources import write_model

import sync_runtime

ROOT=Path(__file__).resolve().parents[4]

from support.it_workspace import copy_framework

def rejected(function, phrase=None):
    try:
        function()
    except (ValueError,OSError,KeyError,TypeError,IndexError,Blocked) as error:
        if phrase:
            assert phrase in str(error),(phrase,error)
        return str(error)
    raise AssertionError('invalid input accepted')

def fixture(root, environments=('dev','prod')):
    copy_framework(root / 'framework')
    (root/'project.json').write_text(templates.json_text({'projectName':'app','targets':[
        {'environment':env,'alias':alias,'awsAccountId':account,'awsRegion':'ap-northeast-1','iacEngine':'cloudformation'} for env in environments for alias,account in [('other','210987654321'),('team','123456789012')]]})+'\n',encoding='utf-8')
    (root/'tasks').mkdir()
    (root/'tasks/active.md').write_text('## Task contract\n- Task type: `migration`\n## Validation scope\n'+
        ''.join(f'- `{env}/team/{service}`\n' for env in environments for service in ('iam','config'))+
        '## Allowed paths\n- `model/**`\n- `model/parameters/**`\n- `model/templates/**`\n- `docs/designs/**`\n',encoding='utf-8')

def role_model(env,count):
    result={'desired.service.iam.serviceId':'iam','desired.service.iam.ownedCatalogResourceTypes':'IAM.Role','display.service.title':'# IAM 詳細設計'}
    for number in range(count):
        identity=f'{11+number*7:03d}';name=f'app-{env}-role-{number+1}'
        result.update({f'desired.resource.{identity}.resourceType':'IAM.Role',f'desired.resource.{identity}.anchor':'iam-'+name,
                       f'desired.resource.{identity}.resourceMode':'IMPORT',f'display.resource.{identity}.comment':'共通の処理権限',
                       f'desired.row.{identity}-004.property':'IAM.Role.RoleName',f'desired.row.{identity}-004.value':'`'+name+'`',
                       f'desired.row.{identity}-004.comment':'ロール名',f'desired.row.{identity}-008.property':'IAM.Role.AssumeRolePolicyDocument',
                       f'desired.row.{identity}-008.value':f'[信頼ポリシー](iam/{name}-trust-policy.json)',
                       f'desired.row.{identity}-008.comment':'Lambdaによる引受けを許可',
                       f'desired.row.{identity}-008.document':templates.json_text({'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'lambda.amazonaws.com'},'Action':'sts:AssumeRole'}]})})
    from model_projection import document_sha256
    for key,value in list(result.items()):
        if key.endswith('.document'):
            result[key.removesuffix('.document')+'.artifactSha256']=document_sha256(templates.json_read(value))
    return result

def config_model():
    return {'desired.service.config.serviceId':'config','desired.service.config.ownedCatalogResourceTypes':'Config.ConfigurationRecorder',
            'display.service.title':'# AWS Config 詳細設計','desired.resource.007.resourceType':'Config.ConfigurationRecorder',
            'desired.resource.007.anchor':'config-configuration-recorder-default','desired.resource.007.resourceMode':'IMPORT','display.resource.007.comment':'構成情報を記録',
            'desired.row.007-001.property':'Config.ConfigurationRecorder.Name','desired.row.007-001.value':'`default`','desired.row.007-001.comment':'記録名',
            'desired.row.007-005.property':'Config.ConfigurationRecorder.RoleARN','desired.row.007-005.value':'`AWSServiceRoleForConfig`','desired.row.007-005.comment':'記録する権限',
            'desired.row.007-009.property':'Config.ConfigurationRecorder.Id','desired.row.007-009.value':'[007](#config-configuration-recorder-default)','desired.row.007-009.comment':'記録ID',
            'observed.row.007-009.property':'Config.ConfigurationRecorder.Id','observed.row.007-009.value':'`default`','observed.row.007-009.comment':'記録ID'}

def write_fixture(root, env, service, values):
    path=write_model(root/'model'/env/'team'/(service+'.properties'),values)
    with redirect_stdout(io.StringIO()):
        sync_runtime.sync(root,True,env,'team',services=[service])
    return path

def install_candidate(root, models):
    from model_parameter_inputs import parameter_text
    template=root/'model/templates/team/iam.properties.tpl'
    lines=['# model-template: 1','# definition: Service',
        'desired.service.iam.serviceId=iam','desired.service.iam.ownedCatalogResourceTypes=IAM.Role',
        'display.service.title=# IAM 詳細設計','# end-definition','# definition: Role']
    for name in ('Name','DocumentLink'):
        lines.append('# parameter: '+name+' '+templates.json_text({'type':'string','description':'fixtureの独立入力','required':True}))
    lines += ['# internal: Anchor string','# resource: role','# row: name role','# row: trust role',
        'desired.resource.role.resourceType=IAM.Role','desired.resource.role.anchor=<<Anchor>>',
        'desired.resource.role.resourceMode=IMPORT','display.resource.role.comment=共通の処理権限',
        'desired.row.name.property=IAM.Role.RoleName','desired.row.name.value=<<Name>>','desired.row.name.comment=ロール名',
        'desired.row.trust.property=IAM.Role.AssumeRolePolicyDocument','desired.row.trust.value=<<DocumentLink>>',
        'desired.row.trust.comment=Lambdaによる引受けを許可',
        'desired.row.trust.document='+next(v for k,v in next(iter(models.values())).items() if k.endswith('.document')),
        '# end-definition','']
    save_files({template:'\n'.join(lines)})
    definitions=templates.parse_template(template)[0]
    for env,values in models.items():
        binding={'instances':{'meta':{'definition':'Service','resources':{},'rows':{},'parameters':{},'labels':{}}}}
        human={'instances':{}}
        for rid,_ in entries(values,'desired.resource.'):
            name='role_'+rid
            binding['instances'][name]={'definition':'Role','resources':{'role':rid},'rows':{'name':rid+'-004','trust':rid+'-008'},'parameters':{'Anchor':values[f'desired.resource.{rid}.anchor']},'labels':{}}
            human['instances'][name]={'parameters':{'Name':values[f'desired.row.{rid}-004.value'],'DocumentLink':values[f'desired.row.{rid}-008.value']}}
        path=root/'model'/env/'team/iam.properties';directory=root/'model/parameters'/env/'team/iam'
        expanded=templates.expand(template,human,{'version':1,'values':{}},binding,env)[0]
        assert expanded==values
        save_files({
            directory/'parameters.yaml':parameter_text(human,definitions,binding),directory/'bindings.json':templates.json_text(binding)+'\n',
            directory/'observed.json':templates.json_text({'version':1,'values':{}})+'\n'})
    return template

import pytest

from support.pytest_cli import run

@pytest.fixture
def root(tmp_path):
    return tmp_path.resolve()

def common_shape_template(root):
    template = root/'model/templates/team/shared.properties.tpl'
    template.parent.mkdir(parents=True)
    template.write_text('''# model-template: 1
# definition: Bucket
# internal: HasLogicalId boolean
# internal: LogicalId string
# parameter: HasPolicy {"type":"boolean","description":"Policyを設計するか","required":true}
# parameter: HasExtraStatement {"type":"boolean","description":"追加の権限を設計するか","required":true}
# parameter: ExtraResource {"type":"string","description":"追加権限の対象","required":true}
# parameter: UsesReference {"type":"boolean","description":"名前ではなく参照を表示するか","required":true}
# parameter: AlternateAnchor {"type":"boolean","description":"別の固定anchorを使うか","required":true}
# resource: bucket
# row: name bucket
# row: policy bucket
# row: config bucket
# optional: desired.resource.bucket.logicalId HasLogicalId
# optional: desired.row.policy.property HasPolicy
# optional: desired.row.policy.value HasPolicy
# optional: desired.row.policy.document HasPolicy
# optional-json: desired.row.policy.document /Statement/1 HasExtraStatement
# choice: desired.row.name.value {"parameter":"UsesReference","value":"[<<Id_bucket>>](#<<Anchor_bucket>>)"}
# choice: desired.resource.bucket.anchor {"parameter":"AlternateAnchor","value":"s3-alternate"}
# optional-json: desired.row.config.value /Drop HasExtraStatement
# optional-json: desired.row.config.value /Items/0 HasExtraStatement
# optional-json: desired.row.config.value /Items/2 HasExtraStatement
# choice: desired.row.config.value {"parameter":"UsesReference","pointer":"/Value","value":false}
desired.resource.bucket.resourceType=S3.Bucket
desired.resource.bucket.anchor=s3-fixed
desired.resource.bucket.logicalId=<<LogicalId>>
desired.row.name.property=S3.Bucket.BucketName
desired.row.name.value=`fixed-name`
desired.row.policy.property=S3.BucketPolicy.PolicyDocument
desired.row.policy.value=[policy.json](shared/policy.json)
desired.row.policy.document={"Statement":[{"Resource":"*"},{"Resource":"<<ExtraResource>>"}]}
desired.row.config.property=S3.Bucket.Tags
desired.row.config.value=`{"Drop":null,"Items":[0,1,2,3],"Value":"","Keep":null}`
# end-definition
# definition: Note
# reference: Bucket {"instance":"fixed","resourceType":"S3.Bucket"}
display.service.note=<<Bucket>>
# end-definition
''',encoding='utf-8')
    return template


__all__ = ['Blocked', 'Path', 'ROOT', 'common_shape_template', 'config_model', 'copy', 'entries', 'fixture', 'install_candidate', 'io', 'json', 'load_model', 'model_file_contents', 'model_parts', 'os', 'patch', 'properties', 'pytest', 'read_model', 'redirect_stdout', 'rejected', 'role_model', 'root', 'run', 'save_files', 'shutil', 'subprocess', 'sync_runtime', 'sys', 'tempfile', 'templates', 'write_fixture', 'write_model']

#!/usr/bin/env python3
"""Offline YAML responsibility, projection, dependency and rejection regression."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from model_files import read_model
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import copy
import io
import json
from support.model_sources import write_model, write_fixture_files
import shutil
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

import model_templates as t
from model_parameter_inputs import yaml_read, parameter_text, schema
from model_files import load_model
from support.model_sources import write_fixture_files as save_files
import sync_runtime

ROOT = Path(__file__).resolve().parents[4]


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError, KeyError, TypeError) as error:
        assert phrase in str(error), (phrase, str(error))
    else:
        raise AssertionError('invalid input accepted: '+phrase)


def declaration(name, kind='string', **fields):
    return '# parameter: '+name+' '+t.json_text({'type':kind,'description':'入力 '+name,'required':True,**fields})


def fixture(root):
    shutil.copytree(ROOT/'framework', root/'framework')
    environments = ['preview', 'prod']
    (root/'project.json').write_text(json.dumps({'projectName':'app','targets':[
        {'environment':env,'alias':alias,'awsAccountId':account,'awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}
        for env in environments for alias,account in [('other','210987654321'),('team','123456789012')]]})+'\n', encoding='utf-8')
    (root/'tasks').mkdir()
    (root/'tasks/active.md').write_text('## Task contract\n- Task type: `migration`\n## Validation scope\n'+
        ''.join('- `'+env+'/team/'+service+'`\n' for env in environments for service in ('vpc','iam'))+
        '## Allowed paths\n- `model/**`\n- `model/parameters/**`\n- `model/templates/**`\n- `docs/designs/**`\n', encoding='utf-8')
    template = root/'model/templates/team/vpc.properties.tpl'
    lines = ['# model-template: 1']
    for kind in ['VPC', 'Subnet']:
        lines += ['# definition: '+kind, declaration('Name',format='literal'),declaration('CidrBlock',format='literal',constraints={'cidr':'ipv4'}),
                  '# internal: Anchor string','# internal: LogicalId string','# internal: Comment string',
                  '# resource: resource','# row: name resource','# row: cidr resource','# row: id resource',
                  '# row: vpc resource' if kind=='Subnet' else '# row: dns resource',
                  'desired.resource.resource.resourceType=EC2.'+kind,'desired.resource.resource.resourceMode=IMPORT',
                  'display.resource.resource.comment=既存説明','desired.resource.resource.anchor=<<Anchor>>','desired.resource.resource.logicalId=<<LogicalId>>',
                  'desired.row.name.property=EC2.'+kind+'.Name','desired.row.name.value=<<Name>>','desired.row.name.comment=名前説明',
                  'desired.row.cidr.property=EC2.'+kind+'.CidrBlock','desired.row.cidr.value=<<CidrBlock>>','desired.row.cidr.comment=<<Comment>>',
                  'desired.row.id.property=EC2.'+kind+'.'+('VpcId' if kind=='VPC' else 'SubnetId'),
                  'desired.row.id.value=[<<LogicalId>>](#<<Anchor_resource>>)','desired.row.id.comment=ID説明']
        if kind=='Subnet':
            lines += [declaration('Vpc','reference',resourceType='EC2.VPC'),'desired.row.vpc.property=EC2.Subnet.VpcId',
                      'desired.row.vpc.value=<<Vpc>>','desired.row.vpc.comment=所属VPC説明']
        else:
            lines += [declaration('EnableDnsSupport','boolean',format='literal'),'desired.row.dns.property=EC2.VPC.EnableDnsSupport',
                      'desired.row.dns.value=<<EnableDnsSupport>>','desired.row.dns.comment=DNS説明']
        lines += ['# end-definition']
    lines += ['# definition: Service','desired.service.vpc.serviceId=vpc','desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet',
              'display.service.title=# Amazon VPC 詳細設計','# end-definition']
    original='\n'.join(lines)+'\n';write_fixture_files({template:original})
    records={}
    for env in environments:
        suffix='' if env=='prod' else '-one'
        human={'instances':{}};bindings={'instances':{}};observed={'version':1,'values':{}}
        for rid,kind,identity in [('017','VPC','main-vpc'),('042','Subnet','private-a'),('083','Subnet','private-c')]:
            name=('vpc' if kind=='VPC' else 'sbnt')+'-app-'+env+suffix+('' if kind=='VPC' else '-'+identity[-1])
            public={'Name':name,'CidrBlock':'10.10.0.0/23' if kind=='VPC' else '10.10.0.0/25'}
            public.update({'EnableDnsSupport':True} if kind=='VPC' else {'Vpc':'main-vpc'})
            rows={key:rid+'-'+str(n).zfill(3) for n,key in enumerate(['name','cidr','id','vpc' if kind=='Subnet' else 'dns'],1)}
            human['instances'][identity]={'parameters':public}
            bindings['instances'][identity]={'definition':kind,'resources':{'resource':rid},'rows':rows,
                'parameters':{'Anchor':'vpc-'+name,'LogicalId':'existing-'+identity,'Comment':'環境注記 '+env},'labels':{'Vpc':'existing-main-vpc'} if kind=='Subnet' else {}}
            observed['values'].update({'observed.row.'+rows['id']+'.property':'EC2.'+kind+'.'+('VpcId' if kind=='VPC' else 'SubnetId'),
                                      'observed.row.'+rows['id']+'.value':'`'+('vpc-' if kind=='VPC' else 'subnet-')+rid+'0'*14+'`',
                                      'observed.row.'+rows['id']+'.comment':'ID説明'})
            if kind=='Subnet':
                observed['values'].update({'observed.row.'+rows['vpc']+'.property':'EC2.Subnet.VpcId',
                                          'observed.row.'+rows['vpc']+'.value':'vpc-017'+'0'*14,'observed.row.'+rows['vpc']+'.comment':'所属VPC説明'})
        bindings['instances']['service']={'definition':'Service','resources':{},'rows':{},'parameters':{},'labels':{}}
        observed['values'] = {key:value for key,value in observed['values'].items() if key.endswith('.value')}
        values,_,_=t.expand(template,human,observed,bindings,env)
        directory=root/'model/parameters'/env/'team/vpc'
        write_fixture_files({root/'model'/env/'team/vpc.properties':'# Generated Model\n'+''.join(k+'='+v+'\n' for k,v in values.items()),
                    directory/'parameters.yaml':parameter_text(human,t.parse_template(template)[0],bindings),directory/'bindings.json':t.json_text(bindings),
                    directory/'observed.json':t.json_text(observed)})
        records[env]=(human,bindings,suffix)
    return template,environments,records,original


def check_human(root):
    template,environments,records,old_template=fixture(root)
    with redirect_stdout(io.StringIO()):
        for env in environments:sync_runtime.sync(root,True,env,'team',services=['vpc'])
    before={env:load_model(root/'model'/env/'team/vpc.properties').values for env in environments}
    baseline={p:p.read_bytes() for p in (root/'docs/designs').rglob('*') if p.is_file()}
    # Correct existing YAML directly; no JSON detour or obsolete VPC field selector.
    corrected=old_template.replace(declaration('EnableDnsSupport','boolean',format='literal')+'\n','').replace('<<EnableDnsSupport>>','`true`')
    corrected=corrected.replace(declaration('Name',format='literal')+'\n','').replace('desired.row.name.value=<<Name>>','desired.row.name.value=`vpc-app-<<Environment>><<Suffix>>`',1)
    corrected=corrected.replace('desired.row.name.value=<<Name>>','desired.row.name.value=`sbnt-app-<<Environment>><<Suffix>>-<<NameSuffix>>`')
    corrected=corrected.replace('# definition: Subnet','# definition: Subnet\n'+declaration('NameSuffix',constraints={'enum':['a','c']}))
    corrected=corrected.replace(declaration('Vpc','reference',resourceType='EC2.VPC'),'# reference: Vpc '+t.json_text({'instance':'main-vpc','resourceType':'EC2.VPC'}))
    corrected=corrected.replace('# model-template: 1','# model-template: 1\n# input: Environment '+t.json_text({'type':'string','description':'登録された環境','required':True,'source':'consumer.environment'})+
                                '\n# input: Suffix '+t.json_text({'type':'string','description':'命名の独立した接尾辞','required':True}))
    template.write_text(corrected,encoding='utf-8')
    for env,(human,bindings,suffix) in records.items():
        human['parameters']={'Suffix':suffix}
        for identity,item in human['instances'].items():
            item['parameters'].pop('Name',None);item['parameters'].pop('EnableDnsSupport',None);item['parameters'].pop('Vpc',None)
            if bindings['instances'][identity]['definition']=='Subnet':item['parameters']['NameSuffix']=identity[-1]
        source=root/'model/parameters'/env/'team/vpc/parameters.yaml';source.write_text(parameter_text(human,t.parse_template(template)[0],bindings))
        assert load_model(root/'model'/env/'team/vpc.properties').values==before[env]
    with redirect_stdout(io.StringIO()):
        for env in environments:sync_runtime.sync(root,True,env,'team',services=['vpc'])
    assert all(p.read_bytes()==data for p,data in baseline.items())
    all_bytes={p:p.read_bytes() for base in ('model','model/parameters','model/templates','docs/designs') for p in (root/base).rglob('*') if p.is_file()}
    with redirect_stdout(io.StringIO()):
        for env in environments:
            path=root/'model'/env/'team/vpc.properties';source=root/'model/parameters'/env/'team/vpc/parameters.yaml'
            t.save_parameters(path,yaml_read(source.read_text()));sync_runtime.sync(root,True,env,'team',services=['vpc']);sync_runtime.sync(root,False,env,'team',services=['vpc'])
    assert all(p.read_bytes()==data for p,data in all_bytes.items())
    path=root/'model/preview/team/vpc.properties';directory=root/'model/parameters/preview/team/vpc';source=directory/'parameters.yaml';binding_path=directory/'bindings.json'
    good_yaml,good_binding=source.read_text(),binding_path.read_text();params=yaml_read(good_yaml);bindings=t.json_read(good_binding)
    expansion=t.load_expansion(path);trace=expansion.provenance['desired.row.017-001.value']['inputs']
    assert trace['Environment']['value']=='preview' and trace['Environment']['source']=='consumer.environment' and trace['Suffix']['value']=='-one'
    assert expansion.provenance['desired.resource.017.anchor']['sourceFile']==str(binding_path)
    assert {source,binding_path,template}<=t.source_inputs(path)
    # No-input metadata is instantiated from one explicit internal definition.
    assert 'service' not in params['instances'] and bindings['instances']['service']['definition']=='Service'
    assert expansion.provenance['desired.service.vpc.serviceId']['sourceFile']==str(binding_path)
    hidden_template=corrected.replace(declaration('CidrBlock',format='literal',constraints={'cidr':'ipv4'})+'\n','',1).replace('desired.row.cidr.value=<<CidrBlock>>','desired.row.cidr.value=`10.10.0.0/23`',1)
    hidden=copy.deepcopy(params);hidden['instances'].pop('main-vpc')
    template.write_text(hidden_template);source.write_text(parameter_text(hidden,t.parse_template(template)[0],bindings))
    assert load_model(path).values==before['preview']  # References still resolve the hidden resource, with fixed IDs.
    assert t.load_expansion(path).provenance['desired.row.017-001.value']['sourceFile']==str(binding_path)
    saved_source=source.read_bytes();t.save_parameters(path,hidden);assert source.read_bytes()==saved_source
    assert 'main-vpc' not in yaml_read(source.read_text())['instances']
    template.write_text(corrected);source.write_text(good_yaml);binding_path.write_text(good_binding)
    assert all('definition' not in item for item in params['instances'].values())
    assert all('definition' in item for item in bindings['instances'].values())
    bad=copy.deepcopy(params);bad['instances']['main-vpc']['definition']='Subnet'
    source.write_text(__import__('yaml').safe_dump(bad));rejected(lambda:load_model(path),'definition belongs in bindings');source.write_text(good_yaml)
    rejected(lambda:t.save_parameters(path,bad),'definition belongs in bindings');assert source.read_text()==good_yaml
    for identity in ('main-vpc','service'):
        bad=copy.deepcopy(bindings);bad['instances'][identity].pop('definition');binding_path.write_text(t.json_text(bad))
        rejected(lambda:load_model(path),'internal instance binding');binding_path.write_text(good_binding)
        for unknown in ('unknown',17):
            bad=copy.deepcopy(bindings);bad['instances'][identity]['definition']=unknown;binding_path.write_text(t.json_text(bad))
            rejected(lambda:load_model(path),'unknown definition');binding_path.write_text(good_binding)
    bad=copy.deepcopy(params);bad['instances'].pop('main-vpc');source.write_text(parameter_text(bad,t.parse_template(template)[0],bindings))
    rejected(lambda:load_model(path),'input-bearing instances require YAML');source.write_text(good_yaml)
    bad=copy.deepcopy(params);bad['instances']['service']={'parameters':{}}
    source.write_text(parameter_text(bad,t.parse_template(template)[0],bindings));rejected(lambda:load_model(path),'input-free instances belong in bindings');source.write_text(good_yaml)
    digest=t.design_source_digest(path)
    changed=copy.deepcopy(params);changed['instances']['main-vpc']['parameters']['CidrBlock']='10.11.0.0/23';t.save_parameters(path,changed)
    assert source.read_text().startswith('parameters:\n') and t.design_source_digest(path)!=digest
    assert {k for k in before['preview'] if load_model(path).values[k]!=before['preview'][k]}=={'desired.row.017-002.value'}
    assert load_model(root/'model/prod/team/vpc.properties').values==before['prod']
    assert t.affected(root,[source.relative_to(root)])=={('preview','team','vpc')};source.write_text(good_yaml)
    changed=copy.deepcopy(params);changed['parameters']['Suffix']=''
    t.save_parameters(path,changed)
    values=load_model(path).values
    assert {k for k in before['preview'] if values[k]!=before['preview'][k]}=={f'desired.row.{rid}-001.value' for rid in ('017','042','083')}
    assert values['desired.row.017-001.value']=='`vpc-app-preview`'
    changed['parameters']['Suffix']='/group';t.save_parameters(path,changed)
    assert load_model(path).values['desired.row.017-001.value']=='`vpc-app-preview/group`';source.write_text(good_yaml)
    optional=corrected.replace('"description":"命名の独立した接尾辞","required":true','"description":"命名の独立した接尾辞","required":false,"default":""')
    template.write_text(optional);defaulted=copy.deepcopy(params);defaulted['parameters'].pop('Suffix')
    source.write_text(parameter_text(defaulted,t.parse_template(template)[0],bindings))
    assert load_model(path).values['desired.row.017-001.value']=='`vpc-app-preview`'
    default_trace=t.load_expansion(path).provenance['desired.row.017-001.value']['inputs']['Suffix']
    assert default_trace['value']==default_trace['default']==''
    template.write_text(corrected);source.write_text(good_yaml)
    original_expand=t.expand
    def raced(*args,**kwargs):
        output=original_expand(*args,**kwargs);binding_path.write_text(good_binding+'\n');return output
    with patch.object(t,'expand',side_effect=raced):rejected(lambda:t.save_parameters(path,changed),'changed after validation')
    assert source.read_text()==good_yaml;binding_path.write_text(good_binding)
    reordered=copy.deepcopy(params);reordered['instances']=dict(reversed(list(params['instances'].items())))
    t.save_parameters(path,reordered);assert load_model(path).values==before['preview'];source.write_text(good_yaml)
    renamed=copy.deepcopy(params);renamed['instances']['renamed']=renamed['instances'].pop('main-vpc')
    source.write_text(__import__('yaml').safe_dump(renamed));rejected(lambda:load_model(path),'binding mismatch')
    renamed_binding=copy.deepcopy(bindings);renamed_binding['instances']['renamed']=renamed_binding['instances'].pop('main-vpc');binding_path.write_text(t.json_text(renamed_binding))
    rejected(lambda:load_model(path),'unknown instance reference')
    template.write_text(corrected.replace('"instance":"main-vpc"','"instance":"renamed"'));assert load_model(path).values==before['preview']
    t.save_parameters(path,renamed);assert yaml_read(source.read_text())==renamed
    assert load_model(path).values==before['preview']
    template.write_text(corrected);source.write_text(good_yaml);binding_path.write_text(good_binding)
    changed_binding=copy.deepcopy(bindings);changed_binding['instances']['main-vpc']['parameters']['LogicalId']='retained-id';binding_path.write_text(t.json_text(changed_binding))
    assert t.design_source_digest(path)!=digest and t.affected(root,[binding_path.relative_to(root)])=={('preview','team','vpc')};binding_path.write_text(good_binding)
    template.write_text(corrected.replace('DNS説明','共通DNS説明'))
    assert t.affected(root,[template.relative_to(root)])=={(env,'team','vpc') for env in environments}
    for env in environments:assert load_model(root/'model'/env/'team/vpc.properties').values['desired.row.017-004.comment']=='共通DNS説明'
    template.write_text(corrected)
    ambiguous=corrected.replace('# definition: VPC','# definition: VPC\n# resource: extra\ndesired.resource.extra.resourceType=EC2.VPC\ndesired.resource.extra.anchor=second-vpc')
    template.write_text(ambiguous);bad=copy.deepcopy(bindings);bad['instances']['main-vpc']['resources']['extra']='099';binding_path.write_text(t.json_text(bad))
    rejected(lambda:load_model(path),'ambiguous/type-mismatched');template.write_text(corrected);binding_path.write_text(good_binding)
    selectable=corrected.replace('# reference: Vpc '+t.json_text({'instance':'main-vpc','resourceType':'EC2.VPC'}),declaration('Vpc','reference',resourceType='EC2.VPC'))
    template.write_text(selectable);selected=copy.deepcopy(params)
    for identity,item in selected['instances'].items():
        if bindings['instances'][identity]['definition']=='Subnet':item['parameters']['Vpc']='main-vpc'
    source.write_text(parameter_text(selected,t.parse_template(template)[0],bindings));assert load_model(path).values==before['preview']
    for target_name in ('missing','private-c'):
        selected['instances']['private-a']['parameters']['Vpc']=target_name;source.write_text(parameter_text(selected,t.parse_template(template)[0],bindings))
        rejected(lambda:load_model(path),'unknown instance reference' if target_name=='missing' else 'type-mismatched')
    template.write_text(corrected);source.write_text(good_yaml)
    # Fixed cross-service ID resolves the producer's authoritative name, including its own suffix.
    target=root/'model/preview/team/iam.properties';target.parent.mkdir(parents=True,exist_ok=True)
    role={'desired.service.iam.serviceId':'iam','desired.service.iam.ownedCatalogResourceTypes':'IAM.Role','display.service.title':'# IAM 詳細設計',
          'desired.resource.011.resourceType':'IAM.Role','desired.resource.011.resourceMode':'IMPORT','desired.resource.011.logicalId':'logging-role',
          'desired.resource.011.anchor':'iam-app-preview-role-one','display.resource.011.comment':'ログ配信権限',
          'desired.row.011-001.property':'IAM.Role.RoleName','desired.row.011-001.value':'`app-preview-role-one`','desired.row.011-001.comment':'ログ用権限',
          'desired.row.011-002.property':'IAM.Role.AssumeRolePolicyDocument','desired.row.011-002.value':'[信頼ポリシー](iam/logging-role-trust-policy.json)',
          'desired.row.011-002.comment':'ログ配信を許可','desired.row.011-002.document':t.json_text({'Version':'2012-10-17','Statement':[
              {'Effect':'Allow','Principal':{'Service':'vpc-flow-logs.amazonaws.com'},'Action':'sts:AssumeRole'}]})}
    write_model(target, role)
    with redirect_stdout(io.StringIO()):sync_runtime.sync(root,True,'preview','team',services=['iam']);sync_runtime.sync(root,False,'preview','team',services=['iam'])
    external=corrected.replace('"instance":"main-vpc","resourceType":"EC2.VPC"','"service":"iam","resource":"011","resourceType":"IAM.Role"')
    template.write_text(external);extbindings=copy.deepcopy(bindings)
    for binding in extbindings['instances'].values():binding['labels'].pop('Vpc',None)
    binding_path.write_text(t.json_text(extbindings))
    assert load_model(path).values['desired.row.042-004.value']=='[app-preview-role-one](iam.md#iam-app-preview-role-one)'
    assert set(load_model(target).files) <= set(t.source_inputs(path)) and ('preview','team','vpc') in t.affected(root,[target.relative_to(root)])
    selectable_external=external.replace('# reference: Vpc '+t.json_text({'service':'iam','resource':'011','resourceType':'IAM.Role'}),declaration('Vpc','reference',resourceType='IAM.Role',service='iam'))
    template.write_text(selectable_external);selected=copy.deepcopy(params)
    for identity,item in selected['instances'].items():
        if bindings['instances'][identity]['definition']=='Subnet':item['parameters']['Vpc']='011'
    source.write_text(parameter_text(selected,t.parse_template(template)[0],bindings));assert '[app-preview-role-one]' in load_model(path).values['desired.row.042-004.value']
    selected['instances']['private-a']['parameters']['Vpc']='app-preview-role-one';source.write_text(parameter_text(selected,t.parse_template(template)[0],bindings))
    rejected(lambda:load_model(path),'type-mismatched');template.write_text(external);source.write_text(good_yaml)
    extdigest=t.design_source_digest(path);write_model(target,read_model(target).replace('app-preview-role-one','app-preview-role-two'))
    with redirect_stdout(io.StringIO()):sync_runtime.sync(root,True,'preview','team',services=['iam']);sync_runtime.sync(root,False,'preview','team',services=['iam'])
    assert t.design_source_digest(path)!=extdigest and '[app-preview-role-two]' in load_model(path).values['desired.row.042-004.value']
    write_model(target,read_model(target).replace('IAM.Role','IAM.User'));rejected(lambda:load_model(path),'type-mismatched')
    t.source_paths(target)[2].joinpath('parameters.yaml').unlink();rejected(lambda:load_model(path),'missing')
    template.write_text(corrected);binding_path.write_text(good_binding)
    for mutate,phrase in [
        (lambda p:p['instances']['main-vpc']['parameters'].update(Name='obsolete'),'unknown parameter'),
        (lambda p:p['instances']['main-vpc']['parameters'].update(EnableDnsSupport=True),'unknown parameter'),
        (lambda p:p['instances']['main-vpc']['parameters'].pop('CidrBlock'),'missing required'),
        (lambda p:p['instances']['main-vpc']['parameters'].update(CidrBlock=10),'type mismatch'),
        (lambda p:p['instances']['main-vpc']['parameters'].update(CidrBlock='10.10.0.1/23'),'constraint cidr'),
        (lambda p:p['parameters'].update(Suffix=True),'type mismatch'),
        (lambda p:p['parameters'].update(Environment='invented'),'unknown parameter'),
        (lambda p:p['parameters'].pop('Suffix'),'missing required'),
        (lambda p:p['instances']['private-a']['parameters'].update(Suffix='override'),'ambiguous parameter source'),
        (lambda p:p['instances']['private-a']['parameters'].update(NameSuffix='bad'),'constraint enum'),
    ]:
        bad=copy.deepcopy(params);mutate(bad);source.write_text(__import__('yaml').safe_dump(bad))
        rejected(lambda:load_model(path),phrase);source.write_text(good_yaml)
        rejected(lambda:t.save_parameters(path,bad),phrase);assert source.read_text()==good_yaml
    source.write_text(good_yaml+'instances: {}\n');rejected(lambda:load_model(path),'duplicate YAML key');source.write_text(good_yaml)
    bad=copy.deepcopy(bindings);bad['instances']['private-c']['resources']=bad['instances']['private-a']['resources'];bad['instances']['private-c']['rows']=bad['instances']['private-a']['rows']
    binding_path.write_text(t.json_text(bad));rejected(lambda:load_model(path),'duplicate fixed Model identity');binding_path.write_text(good_binding)
    fallback=directory/'parameters.json';fallback.write_text('{}');rejected(lambda:load_model(path),'unsupported JSON Model inputs')
    source.write_text('invalid: [');rejected(lambda:load_model(path),'unsupported JSON Model inputs');fallback.unlink();rejected(lambda:load_model(path),'invalid parameters YAML');source.write_text(good_yaml)
    template.write_text(corrected.replace('<<Suffix>>','<<Undefined>>'));rejected(lambda:load_model(path),'undeclared template variables');template.write_text(corrected)
    fragment=corrected.replace(declaration('NameSuffix',constraints={'enum':['a','c']}),declaration('NameSuffix',format='literal',constraints={'enum':['a','c']}))
    template.write_text(fragment);rejected(lambda:load_model(path),'literal format requires an entire scalar');template.write_text(corrected)
    late=corrected+'# input: TooLate '+t.json_text({'type':'string','description':'曖昧な再定義','required':True})+'\n'
    template.write_text(late);rejected(lambda:load_model(path),'invalid/duplicate service input');template.write_text(corrected)
    assert yaml_read('value: on\ndate: 2026-10-11\nnumber: 001\nboolean: true\n')=={'value':'on','date':'2026-10-11','number':'001','boolean':True}
    for text in ['a: 1\na: 2','a: {b: 1, b: 2}','a: !!python/object:bad {}','a: &x {b: 1}\nc: {<<: *x}']:rejected(lambda:yaml_read(text),'YAML')
    rejected(lambda:schema({'type':'integer','description':'test','required':True,'constraints':{'minimum':'x'}}),'numeric constraint')
    # YAML inputs retain exact JSON types and meaningful array order before substitution.
    typed_template=template.with_name('typed.properties.tpl')
    kinds={'Number':'number','Integer':'integer','Flag':'boolean','Text':'string','Document':'object','Sequence':'array','Empty':'null'}
    typed_template.write_text('# model-template: 1\n# definition: Typed\n'+'\n'.join(declaration(n,k) for n,k in kinds.items())+
        '\ndesired.note.typed.document='+t.json_text({name:'<<'+name+'>>' for name in kinds})+'\n# end-definition\n')
    raw={'Number':1.5,'Integer':7,'Flag':True,'Text':'001','Document':{'Statement':[{'Flag':False}]},'Sequence':[3,1,2],'Empty':None}
    typed={'instances':{'typed':{'parameters':raw}}};typed_binding={'instances':{'typed':{'definition':'Typed','resources':{},'rows':{},'parameters':{},'labels':{}}}}
    typed=yaml_read(parameter_text(typed,t.parse_template(typed_template)[0],typed_binding));values,_,_=t.expand(typed_template,typed,{'version':1,'values':{}},typed_binding,'preview')
    assert t.json_read(values['desired.note.typed.document'])==raw
    typed['instances']['typed']['parameters']['Integer']=True;rejected(lambda:t.expand(typed_template,typed,{'version':1,'values':{}},typed_binding,'preview'),'type mismatch')
    rejected(lambda:t.resolve('x<<Flag>>',{'Flag':True}),'non-string parameter embedded')
    assert 'EnableDnsSupport' not in t.parse_template(template)[0]['VPC'].parameters
    print('human-inputs: PASS (bindings-only definitions; existing YAML lossless correction; fixed settings; shared fragments; registered environment; producer dependency; readable atomic save; strict rejection; identity; idempotence)')


def check_declared_instance_inputs(root):
    template = root/'model/templates/team/input-contract.properties.tpl'
    text = ['# model-template: 1', '# definition: Optional',
            declaration('Value1', 'integer', required=False, default=3),
            'desired.note.optional.document={"value":"<<Value1>>"}', '# end-definition',
            '# definition: Required', declaration('Enabled', 'boolean'), '# internal: Hidden string',
            'desired.note.required.document={"enabled":"<<Enabled>>","fixed":"<<Hidden>>"}',
            '# end-definition', '# definition: BindingsOnly',
            'desired.note.fixed.value=fixed', '# end-definition']
    save_files({template:'\n'.join(text)+'\n'})
    empty = {'version':1, 'values':{}}
    for identity in ('service', 'Legal_42-name'):
        bindings = {'instances':{
            identity:{'definition':'Optional', 'resources':{}, 'rows':{}, 'parameters':{}},
            'required':{'definition':'Required', 'resources':{}, 'rows':{}, 'parameters':{'Hidden':'fixed'}},
            'bindings-only':{'definition':'BindingsOnly', 'resources':{}, 'rows':{}, 'parameters':{}},
        }}
        human = {'instances':{identity:{'parameters':{}}, 'required':{'parameters':{'Enabled':True}}}}
        expand = lambda h: t.expand(template,h,empty,bindings,'preview')[0]
        values = expand(human)
        assert t.json_read(values['desired.note.optional.document']) == {'value':3}
        assert expand(yaml_read(parameter_text(human,t.parse_template(template)[0],bindings))) == values
        directory = root/'model/parameters/preview/team/input-contract'
        save_files({directory/'parameters.yaml':parameter_text(human,t.parse_template(template)[0],bindings),
                    directory/'bindings.json':t.json_text(bindings)})
        from support import service_contracts
        with patch.object(service_contracts, 'ROOT', root):
            assert len(list(service_contracts.cases('input-contract'))) == 1
        supplied = copy.deepcopy(human)
        supplied['instances'][identity]['parameters']['Value1'] = 7
        assert t.json_read(expand(supplied)['desired.note.optional.document']) == {'value':7}
        for mutate, phrase in [
            (lambda h:h['instances'].update(unregistered={'parameters':{}}), 'binding mismatch'),
            (lambda h:h['instances'][identity]['parameters'].update(ValueUnknown=1), 'unknown parameter'),
            (lambda h:h['instances']['required']['parameters'].pop('Enabled'), 'missing required parameter'),
            (lambda h:h['instances'][identity]['parameters'].update(Value1=True), 'parameter type mismatch'),
            (lambda h:h['instances']['required']['parameters'].update(Hidden='override'), 'internal information'),
            (lambda h:h['instances'].update({'bindings-only':{'parameters':{}}}), 'input-free instances belong in bindings'),
            (lambda h:h['instances'].pop(identity), 'input-bearing instances require YAML'),
        ]:
            invalid = copy.deepcopy(human)
            mutate(invalid)
            rejected(lambda:expand(invalid),phrase)
    from model_parameter_inputs import human_instances
    from support.service_fixtures import typed_services
    with tempfile.TemporaryDirectory(prefix='iam-inputs-') as directory:
        source = Path(directory)
        typed_services(source)
        for environment in ('dev', 'stg'):
            _, template, directory = t.source_paths(source/'model'/environment/'team/iam.properties')
            human = yaml_read((directory/'parameters.yaml').read_text(encoding='utf-8'))
            bindings = t.json_read((directory/'bindings.json').read_text(encoding='utf-8'))
            assert type(human['instances']['service']['parameters']['UseStgIdentityCenterTrust']) is bool
            instances, _ = human_instances(template,human,bindings,t.parse_template(template)[0],environment,
                                           resolve_references=False)
            assert any(item['id']=='service' for item in instances['instances'])
    print('Declared instance inputs: PASS (dev/stg IAM service; legal IDs; empty optional/default; Value name; six invalid-input classes)')


def check_kms_alias(root):
    producer = root/'model/preview/team/kms.properties'
    producer.parent.mkdir(parents=True)
    original = '\n'.join([
        'desired.resource.011.resourceType=KMS.Key',
        'desired.resource.011.anchor=kms-material-key',
        'desired.row.011-001.property=KMS.Key.KeyId',
        'desired.row.011-001.value=[011](#kms-material-key)',
        'desired.resource.012.resourceType=KMS.Alias',
        'desired.resource.012.anchor=kms-alias-app-preview-material-one',
        'desired.resource.012.parentProperty=KMS.Alias.TargetKeyId',
        'desired.resource.012.parentReference=[011](#kms-material-key)',
        'desired.row.012-001.property=KMS.Alias.AliasName',
        'desired.row.012-001.value=`alias/app-preview-material-one`',
        'desired.row.012-002.property=KMS.Alias.TargetKeyId',
        'desired.row.012-002.value=[011](#kms-material-key)',
    ])+'\n'
    write_model(producer, original)
    template = root/'model/templates/team/codecommit.properties.tpl'
    template.parent.mkdir(parents=True,exist_ok=True)
    template.write_text('\n'.join([
        '# model-template: 1', '# definition: Repository',
        '# reference: KmsAlias '+t.json_text({'service':'kms','resource':'012','resourceType':'KMS.Alias'}),
        '# resource: repository', '# row: kms repository',
        'desired.resource.repository.resourceType=CodeCommit.Repository',
        'desired.resource.repository.anchor=codecommit-repository',
        'desired.row.kms.property=CodeCommit.Repository.KmsKeyId',
        'desired.row.kms.value=<<KmsAlias>>', '# end-definition',
    ])+'\n', encoding='utf-8')
    human = {'instances':{}}
    bindings = {'instances':{'repository':{'definition':'Repository','resources':{'repository':'021'},
        'rows':{'kms':'021-001'},'parameters':{},'labels':{}}}}
    observed = {'version':1,'values':{}}
    values,_,files = t.expand(template,human,observed,bindings,'preview')
    key = 'desired.row.021-001.value'
    assert values[key]=='[alias/app-preview-material-one](kms.md#kms-alias-app-preview-material-one)'
    assert set(load_model(producer).files) <= set(files)
    directory = root/'model/parameters/preview/team/codecommit'
    path = root/'model/preview/team/codecommit.properties'
    write_fixture_files({path:''.join(k+'='+v+'\n' for k,v in values.items()),

        directory/'parameters.yaml':'instances: {}\n',directory/'bindings.json':t.json_text(bindings),directory/'observed.json':t.json_text(observed)})
    old_digest = t.design_source_digest(path)
    assert set(load_model(producer).files) <= set(t.source_inputs(path))
    assert ('preview','team','codecommit') in t.affected(root,[producer.relative_to(root)])
    write_model(producer, original.replace('material-one','material-two'))
    assert load_model(path).values[key]=='[alias/app-preview-material-two](kms.md#kms-alias-app-preview-material-two)'
    assert t.design_source_digest(path)!=old_digest
    for bad,phrase in [
        (original.replace('KMS.Alias','KMS.Key'),'type-mismatched'),
        (original.replace('KMS.Alias.AliasName','KMS.Alias.TargetKeyId'),'exactly one name'),
        (original+'desired.row.012-003.property=KMS.Alias.AliasName\ndesired.row.012-003.value=`alias/duplicate`\n','exactly one name'),
    ]:
        write_model(producer, bad)
        rejected(lambda:load_model(path),phrase)
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda:load_model(path),'missing')
    print('KMS Alias: PASS (authoritative AliasName/anchor; producer inputs/hash/impact; missing/wrong-type/unnamed/duplicate rejection)')


def check_external_instances(root):
    # Shared logical instance resolves different environment resource IDs through the typed resolver.
    kind = 'SecretsManager.Secret'
    selector = {'service': 'secrets-manager', 'instance': 'snowflake-pat', 'resourceType': kind, 'format': 'name'}
    template = root/'model/templates/team/quicksight.properties.tpl'
    declaration = '# reference: SecretName '+t.json_text(selector)
    text = '\n'.join(['# model-template: 1', '# definition: DataSource', declaration,
        '# resource: source', '# row: name source', '# row: password source',
        'desired.resource.source.resourceType=QuickSight.DataSource',
        'desired.resource.source.anchor=quicksight-source',
        'desired.row.name.property=QuickSight.DataSource.Name', 'desired.row.name.value=`<<SecretName>>`',
        'desired.row.password.property=QuickSight.DataSource.Credentials.CredentialPair.Password',
        'desired.row.password.value=`{{resolve:secretsmanager:<<SecretName>>:SecretString:token}}`', '# end-definition'])+'\n'
    binding = {'instances': {'datasource': {'definition': 'DataSource', 'resources': {'source': '001'},
        'rows': {'name': '001-001', 'password': '001-002'}, 'parameters': {}}}}

    def producer(env, identity, name, resource_type=kind, duplicate=False):
        path = root/'model'/env/'team/secrets-manager.properties'
        values = {}
        for rid in ([identity, '099'] if duplicate else [identity]):
            values.update({f'desired.resource.{rid}.resourceType': resource_type,
                f'desired.resource.{rid}.anchor': 'secret-'+rid,
                f'desired.row.{rid}-001.property': resource_type+'.Name',
                f'desired.row.{rid}-001.value': '`'+name+'`'})
        write_model(path, values)
        fixed = t.source_paths(path)[2]/'bindings.json'
        bindings = t.json_read(fixed.read_text(encoding='utf-8'))
        bindings['instances']['snowflake-pat'] = bindings['instances'].pop('fixture')
        fixed.write_text(t.json_text(bindings), encoding='utf-8')
        return path

    consumers = {}
    for env, identity in [('dev', '017'), ('stg', '083')]:
        target = producer(env, identity, 'secret-'+env)
        path = root/'model'/env/'team/quicksight.properties'
        directory = t.source_paths(path)[2]
        save_files({template: text, directory/'parameters.yaml': 'instances: {}\n',
                    directory/'bindings.json': t.json_text(binding)})
        model = load_model(path)
        assert model.values['desired.row.001-001.value'] == '`secret-'+env+'`'
        assert model.values['desired.row.001-002.value'] == '`{{resolve:secretsmanager:secret-'+env+':SecretString:token}}`'
        assert set(load_model(target).files) <= set(model.files)
        assert model.files[t.source_paths(target)[2]/'bindings.json']
        assert t.load_expansion(path).provenance['desired.row.001-002.value']['references']['SecretName']['instance'] == 'snowflake-pat'
        consumers[env] = path
        # The previous service/resource declaration returns exactly the same values.
        old = '# reference: SecretName '+t.json_text({'service': 'secrets-manager', 'resource': identity, 'resourceType': kind, 'format': 'name'})
        template.write_text(text.replace(declaration, old), encoding='utf-8')
        assert load_model(path).values == model.values
        template.write_text(text, encoding='utf-8')

    path = consumers['dev']
    digest = t.design_source_digest(path)
    target = producer('dev', '017', 'secret-dev-updated')
    assert t.design_source_digest(path) != digest
    assert load_model(path).values['desired.row.001-001.value'] == '`secret-dev-updated`'
    changed = t.source_paths(target)[2]/'bindings.json'
    assert ('dev', 'team', 'quicksight') in t.affected(root, [changed.relative_to(root)])
    template.write_text(text.replace('"instance":"snowflake-pat"', '"instance":"missing"'), encoding='utf-8')
    rejected(lambda: load_model(path), 'unknown external instance reference')
    template.write_text(text, encoding='utf-8')
    producer('dev', '017', 'wrong-type', 'Glue.SecurityConfiguration')
    rejected(lambda: load_model(path), 'type-mismatched external instance reference')
    producer('dev', '017', 'duplicate', duplicate=True)
    rejected(lambda: load_model(path), 'expected exactly one SecretsManager.Secret, found 2')
    from model_parameter_inputs import reference_schema
    rejected(lambda: reference_schema({**selector, 'resource': '017'}), 'template reference requires')
    rejected(lambda: reference_schema({**selector, 'instance': '../escape'}), 'invalid template reference target')
    print('External instances: PASS (environment IDs; names/passwords; missing/type/ambiguity; hashes/impact/trace; resource-ID compatibility)')



import pytest
from support.pytest_cli import run


@pytest.fixture
def root(tmp_path):
    return tmp_path.resolve()


def check_service_contracts():
    from support.service_contracts import check
    check()


def main():
    return run(__file__, message="model_parameter_inputs: PASS")


if __name__ == '__main__':
    raise SystemExit(main())

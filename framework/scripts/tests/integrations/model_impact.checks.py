#!/usr/bin/env python3
"""Active resource/attribute impact, baseline safety and transitive boundaries."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import json
import subprocess
import tempfile
from unittest.mock import patch

from model_templates import affected, design_source_digest, json_text

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def git(root, *arguments):
    result = subprocess.run(['git', *arguments], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def inputs(root, service, bindings, parameters, env='dev'):
    directory = root/'model/parameters'/env/'team'/service
    write(directory/'bindings.json', json_text({'instances': bindings}))
    write(directory/'parameters.yaml', json_text({'instances': parameters}))
    return directory/'parameters.yaml'


def producer(root, service, kind, name_property, env='dev'):
    template = root/'model/templates/team'/(service+'.properties.tpl')
    write(template, f'''# model-template: 1
# definition: Resource
# parameter: Name {{"type":"string","description":"名前","required":true}}
# parameter: Setting {{"type":"object","description":"設定","required":true}}
# resource: resource
# row: name resource
# row: setting resource
desired.resource.resource.resourceType={kind}
desired.resource.resource.anchor={service}-<<Name>>
desired.row.name.property={kind}.{name_property}
desired.row.name.value=`<<Name>>`
desired.row.setting.property={kind}.Setting
desired.row.setting.document={{"setting":"<<Setting>>"}}
# end-definition
''')
    return inputs(root, service, {f'item{i}': {'definition':'Resource','resources':{'resource':f'{i:03}'},
                         'rows':{'name':f'{i:03}-001','setting':f'{i:03}-002'},'parameters':{}}
                         for i in (1,2)},
                  {f'item{i}': {'parameters':{'Name':f'{env}-name{i}','Setting':{'trust':['old']}}} for i in (1,2)}, env)


def consumer(root, service, producer_service, kind, target='001', *, mode='name', fixed=False,
             optional=False, instance=False, env='dev'):
    ref = {'service':producer_service,'resourceType':kind}
    if mode != 'anchor':
        ref['format'] = mode
    ref['instance' if instance else 'resource'] = target
    template = root/'model/templates/team'/(service+'.properties.tpl')
    write(template, f'''# model-template: 1
# definition: Consumer
# reference: Producer {json_text(ref)}
''' + ('# parameter: Enabled {"type":"boolean","description":"参照使用","required":true}\n# optional: desired.row.source.value Enabled\n' if optional else '') + f'''# resource: resource
# row: name resource
# row: source resource
desired.resource.resource.resourceType=CodeBuild.Project
desired.resource.resource.anchor={service}-anchor
desired.row.name.property=CodeBuild.Project.Name
desired.row.name.value={'fixed-name' if fixed or optional else '<<Producer>>'}
desired.row.source.property=CodeBuild.Project.Description
desired.row.source.value=<<Producer>>
# end-definition
''')
    # An unused definition must never create a dependency.
    with template.open('a', encoding='utf-8') as stream:
        stream.write('''# definition: Unused
# reference: UnusedProducer {"service":"unused","resource":"001","resourceType":"IAM.Role","format":"name"}
# resource: resource
# row: name resource
desired.resource.resource.resourceType=CodeBuild.Project
desired.resource.resource.anchor=unused
desired.row.name.property=CodeBuild.Project.Name
desired.row.name.value=<<UnusedProducer>>
# end-definition
''')
    return inputs(root, service, {'consumer':{'definition':'Consumer','resources':{'resource':'005'},
                  'rows':{'name':'005-001','source':'005-002'},'parameters':{},
                  **({'labels':{'Producer':'fixed-label'}} if mode == 'anchor' else {})}},
                  {'consumer':{'parameters':{'Enabled':False}}} if optional else {}, env)


def baseline(root):
    git(root,'init'); git(root,'config','user.name','Fixture'); git(root,'config','user.email','fixture@example.invalid')
    git(root,'add','model'); git(root,'commit','-m','Baseline')
    return git(root,'rev-parse','HEAD')


def change(path, instance, key, value):
    value_set = json.loads(path.read_text(encoding='utf-8'))
    value_set['instances'][instance]['parameters'][key] = value
    path.write_text(json_text(value_set), encoding='utf-8')


def entry(service, env='dev'):
    return env,'team',service


@it_case
def check_precision(root, service, kind, name_property):
    source = producer(root, service, kind, name_property)
    template = root/'model/templates/team'/(service+'.properties.tpl')
    consumer(root,'uses-first',service,kind)
    consumer(root,'uses-second',service,kind,'002')
    consumer(root,'fixed-export',service,kind,fixed=True)
    consumer(root,'stops-here','fixed-export','CodeBuild.Project','005')
    consumer(root,'continues','uses-first','CodeBuild.Project','005')
    consumer(root,'disabled',service,kind,optional=True)
    baseline(root)
    own = {entry(service)}
    relative = source.relative_to(root)
    change(source,'item1','Setting',{'trust':['new']})
    consumer_path = root/'model/dev/team/uses-first.properties'
    digest = design_source_digest(consumer_path)
    assert affected(root,{relative}) == own
    git(root,'add',str(relative))
    change(source,'item1','Setting',{'trust':['other']})
    assert affected(root,{relative}) == own
    assert design_source_digest(consumer_path) != digest  # Scope narrowing never weakens byte snapshots.
    template.write_text('\n'.join(line for line in template.read_text().replace('{"setting":"<<Setting>>"}','{"fixed":true}').splitlines() if not line.startswith('# parameter: Setting')), encoding='utf-8')
    # The removed parameter must be removed from inputs too.
    data = json.loads(source.read_text())
    for item in data['instances'].values():
        del item['parameters']['Setting']
    source.write_text(json_text(data))
    assert affected(root,{relative,template.relative_to(root)}) == own
    from support.validator import MODULE
    write(root/f'docs/designs/dev/team/{service}.md','fixture')
    validator=MODULE.Validator(root,own)
    validator.accounts={('dev','team'):{}}
    validator.changed_paths={relative.as_posix(),template.relative_to(root).as_posix()}
    validator.check_validation_scope()
    assert not validator.errors,validator.errors
    change(source,'item1','Name','renamed')
    expected = own | {entry(s) for s in ('uses-first','fixed-export','continues')}
    assert affected(root,{relative,template.relative_to(root)}) == expected
    validator=MODULE.Validator(root,own)
    validator.accounts={('dev','team'):{}}
    validator.changed_paths={relative.as_posix(),template.relative_to(root).as_posix()}
    validator.check_validation_scope()
    assert any('affected validation scope' in error for error in validator.errors),validator.errors
    git(root,'add','model'); git(root,'commit','-m','Committed change')
    assert affected(root,{relative}) == own | {entry(s) for s in ('uses-first','uses-second','fixed-export','continues','stops-here','disabled')}


@it_case
def check_identity_and_deletion(root):
    source = producer(root,'iam','IAM.Role','RoleName')
    consumer(root,'uses-instance','iam','IAM.Role','item1',instance=True)
    start = baseline(root)
    binding = source.with_name('bindings.json')
    data = json.loads(binding.read_text())
    data['instances']['item1']['resources']['resource']='003'
    data['instances']['item1']['rows']={'name':'003-001','setting':'003-002'}
    binding.write_text(json_text(data))
    assert affected(root,{binding.relative_to(root)}) == {entry('iam'),entry('uses-instance')}
    git(root,'add','model'); git(root,'commit','-m','Remap')
    with patch('import_guard.base_revision', return_value=start):
        assert affected(root,{binding.relative_to(root)}) == {entry('iam'),entry('uses-instance')}
    del data['instances']['item1']
    binding.write_text(json_text(data))
    human=json.loads(source.read_text()); del human['instances']['item1']; source.write_text(json_text(human))
    assert affected(root,{binding.relative_to(root),source.relative_to(root)}) == {entry('iam'),entry('uses-instance')}


@it_case
def check_shared_environments(root):
    dev = producer(root,'iam','IAM.Role','RoleName')
    stg = producer(root,'iam','IAM.Role','RoleName',env='stg')
    for env in ('dev','stg'):
        consumer(root,'build','iam','IAM.Role',env=env)
    baseline(root)
    change(stg,'item1','Setting',{'trust':['sso-a','sso-b']})
    template = root/'model/templates/team/iam.properties.tpl'
    template.write_text(template.read_text()+'# comment-only change\n')
    assert affected(root,{stg.relative_to(root),template.relative_to(root)}) == {entry('iam','dev'),entry('iam','stg')}
    change(stg,'item1','Name','stg-renamed')
    assert affected(root,{stg.relative_to(root),template.relative_to(root)}) == {entry('iam','dev'),entry('iam','stg'),entry('build','stg')}
    assert json.loads(dev.read_text())['instances']['item1']['parameters']['Name']=='dev-name1'


@it_case
def check_identifiers(root):
    catalog=Path(__file__).resolve().parents[4]/'framework/materials/aws/EC2_VPC.properties'
    write(root/'framework/materials/aws/EC2_VPC.properties',catalog.read_text(encoding='utf-8'))
    source = producer(root,'vpc','EC2.VPC','Name')
    template = root/'model/templates/team/vpc.properties.tpl'
    text = template.read_text().replace('# row: setting resource', '# row: setting resource\n# row: identifier resource').replace('# end-definition', 'desired.row.identifier.property=EC2.VPC.VpcId\ndesired.row.identifier.value=unobserved\n# end-definition')
    template.write_text(text)
    binding = json.loads(source.with_name('bindings.json').read_text())
    for index in (1,2):
        binding['instances'][f'item{index}']['rows']['identifier']=f'{index:03}-003'
    source.with_name('bindings.json').write_text(json_text(binding))
    observed = source.with_name('observed.json')
    write(observed,json_text({'version':1,'values':{'observed.row.001-003.value':'`vpc-first`','observed.row.002-003.value':'`vpc-second`'}}))
    consumer(root,'by-id','vpc','EC2.VPC',mode='identifier')
    ref_template = root/'model/templates/team/by-id.properties.tpl'
    ref_template.write_text(ref_template.read_text().replace('"format":"identifier"', '"format":"identifier","property":"EC2.VPC.VpcId"'))
    consumer(root,'by-name','vpc','EC2.VPC')
    consumer(root,'by-anchor','vpc','EC2.VPC',mode='anchor')
    baseline(root)
    own={entry('vpc')}
    data=json.loads(observed.read_text()); data['values']['observed.row.002-003.value']='`vpc-second-new`'; observed.write_text(json_text(data))
    assert affected(root,{observed.relative_to(root)}) == own, affected(root,{observed.relative_to(root)})
    data['values']['observed.row.001-003.value']='`vpc-first-new`'; observed.write_text(json_text(data))
    assert affected(root,{observed.relative_to(root)}) == own|{entry('by-id')}
    del data['values']['observed.row.001-003.value']; observed.write_text(json_text(data))
    assert affected(root,{observed.relative_to(root)}) == own|{entry('by-id')}


@it_case
def check_type_and_unknown(root):
    source=producer(root,'iam','IAM.Role','RoleName')
    consumer(root,'build','iam','IAM.Role')
    baseline(root)
    template=root/'model/templates/team/iam.properties.tpl'
    template.write_text(template.read_text().replace('resourceType=IAM.Role','resourceType=IAM.User'))
    assert affected(root,{template.relative_to(root)}) == {entry('iam'),entry('build')}
    template.unlink()
    try:
        affected(root,{template.relative_to(root)})
    except (OSError,ValueError):
        pass
    else:
        raise AssertionError('missing authoritative template must stop')


@it_case
def check_import_scope(root):
    from import_guard import changes
    source=producer(root,'iam','IAM.Role','RoleName')
    consumer(root,'build','iam','IAM.Role')
    baseline(root)
    change(source,'item1','Setting',{'trust':['new']})
    _, found=changes(root,{source.relative_to(root).as_posix()},include_create=True)
    assert set(found)=={'dev/team/iam/001'}, found
    change(source,'item1','Name','renamed')
    _, found=changes(root,{source.relative_to(root).as_posix()},include_create=True)
    assert set(found)=={'dev/team/iam/001','dev/team/build/005'},found


@it_case
def check_selection(root):
    source=producer(root,'iam','IAM.Role','RoleName')
    unused=producer(root,'unused','IAM.Role','RoleName')
    human=consumer(root,'build','iam','IAM.Role',fixed=True)
    template=root/'model/templates/team/build.properties.tpl'
    template.write_text(template.read_text().replace('# resource: resource', '# parameter: UseSecond {"type":"boolean","description":"参照選択","required":true}\n# reference: Second {"service":"iam","resource":"002","resourceType":"IAM.Role","format":"name"}\n# choice: desired.row.source.value {"parameter":"UseSecond","value":"<<Second>>"}\n# resource: resource',1))
    human.write_text(json_text({'instances':{'consumer':{'parameters':{'UseSecond':True}}}}))
    baseline(root)
    change(source,'item1','Name','unselected-name')
    assert affected(root,{source.relative_to(root)}) == {entry('iam')}
    change(unused,'item1','Name','unused-name')
    assert affected(root,{unused.relative_to(root)}) == {entry('unused')}
    change(source,'item2','Name','selected-name')
    assert affected(root,{source.relative_to(root)}) == {entry('iam'),entry('build')}


@it_case
def check_cycles(root):
    consumer(root,'alpha','beta','CodeBuild.Project','005')
    consumer(root,'beta','alpha','CodeBuild.Project','005')
    baseline(root)
    template=root/'model/templates/team/alpha.properties.tpl'
    template.write_text(template.read_text()+'# changed\n')
    assert affected(root,{template.relative_to(root)}) == {entry('alpha'),entry('beta')}


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    for service,kind,name_property in [('iam','IAM.Role','RoleName'),('s3','S3.Bucket','BucketName'),('lambda','Lambda.Function','FunctionName')]:
        path=root/service;path.mkdir();check_precision(path,service,kind,name_property)
    path=root/'identity';path.mkdir();check_identity_and_deletion(path)
    path=root/'shared';path.mkdir();check_shared_environments(path)
    for label,check in [('identifiers',check_identifiers),('type',check_type_and_unknown),('import',check_import_scope),('selection',check_selection),('cycles',check_cycles)]:
        path=root/label;path.mkdir();check(path)
print('PASS: precise Model reference impact across services, snapshots and environments')

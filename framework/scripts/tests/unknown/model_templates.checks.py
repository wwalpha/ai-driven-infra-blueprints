#!/usr/bin/env python3
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


def rejected(function, phrase=None):
    try:
        function()
    except (ValueError,OSError,KeyError,TypeError,IndexError,Blocked) as error:
        if phrase:
            assert phrase in str(error),(phrase,error)
        return str(error)
    raise AssertionError('invalid input accepted')


def fixture(root, environments=('dev','prod')):
    shutil.copytree(ROOT/'framework',root/'framework')
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


def check_transactions(root):
    original=root/'original.properties';original.write_text('a=old\n')
    new=root/'new.json';output={original:'a=new\n',new:'{}\n'}
    write=Path.write_text
    def fail(path,*args,**kwargs):
        if path==new:raise OSError('injected partial-write failure')
        return write(path,*args,**kwargs)
    with patch.object(Path,'write_text',fail):rejected(lambda:templates.publish(root,output),'injected')
    assert original.read_text()=='a=old\n' and not new.exists()
    rejected(lambda:templates.publish(root,output,inputs={original:b'a=other\n'}),'changed after validation')
    assert original.read_text()=='a=old\n'
    # Written inputs are checked against published bytes; untouched inputs retain their snapshot.
    dependency = root/'dependency.json'; dependency.write_text('{}\n', encoding='utf-8')
    obsolete = root/'obsolete.json'; obsolete.write_text('{"old":true}\n', encoding='utf-8')
    snapshots = {original: original.read_bytes(), dependency: dependency.read_bytes(), obsolete: obsolete.read_bytes()}
    def verify():
        assert original.read_text() == 'a=new\n' and new.is_file() and not obsolete.exists()
    templates.publish(root, output, [obsolete], inputs=snapshots, verify=verify)
    assert original.read_text() == 'a=new\n' and not obsolete.exists()
    original.write_text('a=old\n'); new.unlink()
    obsolete.write_bytes(snapshots[obsolete])
    def concurrent():
        dependency.write_text('{"changed":true}\n')
    rejected(lambda: templates.publish(root, output, [obsolete], inputs=snapshots, verify=concurrent), 'inputs changed during publication')
    assert original.read_text() == 'a=old\n' and obsolete.read_bytes() == snapshots[obsolete] and not new.exists()
    dependency.write_bytes(snapshots[dependency])
    # A terminated process leaves a durable journal; the next reader restores prior inputs.
    program='''import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import model_templates as t, sync_files
root=Path(sys.argv[2]); original=root/'original.properties'
def crash(output):
    original.write_text('a=crash\\n');os._exit(17)
sync_files.save_files=crash
t.publish(root,{original:'a=crash\\n',root/'new.json':'{}\\n'})
'''
    result=subprocess.run([sys.executable,'-c',program,str(ROOT/'framework/scripts'),str(root)])
    assert result.returncode==17 and original.read_text()=='a=crash\n'
    with templates.publication_lock(root):pass
    assert original.read_text()=='a=old\n' and not new.exists()


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


def check_expansion(root):
    from model_parameter_inputs import yaml_read
    fixture(root)
    models={'dev':role_model('dev',2),'prod':role_model('prod',5)}
    template=install_candidate(root,models)
    for env,expected in models.items():assert load_model(root/'model'/env/'team/iam.properties').values==expected
    path=root/'model/dev/team/iam.properties';directory=root/'model/parameters/dev/team/iam'
    content=template.read_text();template.write_text(content.replace('共通の処理権限','共通の新権限'))
    for env,expected in models.items():assert sum(v=='共通の新権限' for v in load_model(root/'model'/env/'team/iam.properties').values.values())==len(entries(expected,'desired.resource.'))
    template.write_text(content)
    source=directory/'parameters.yaml';params=yaml_read(source.read_text())
    binding=templates.json_read((directory/'bindings.json').read_text());observed={'version':1,'values':{}}
    first=templates.expand(template,params,observed,binding,'dev')[0]
    params['instances']=dict(reversed(list(params['instances'].items())))
    binding['instances']=dict(reversed(list(binding['instances'].items())))
    assert templates.expand(template,params,observed,binding,'dev')[0]==first
    params['instances']['renamed']=params['instances'].pop('role_011');binding['instances']['renamed']=binding['instances'].pop('role_011')
    assert templates.expand(template,params,observed,binding,'dev')[0]==first
    params['instances']['renamed']['parameters']['Name']='`changed`'
    from model_parameter_inputs import parameter_text
    source.write_text(parameter_text(params,templates.parse_template(template)[0],binding))
    (directory/'bindings.json').write_text(templates.json_text(binding))
    templates.save_parameters(path,params)
    assert load_model(path).values['desired.row.011-004.value']=='`changed`'
    assert load_model(root/'model/prod/team/iam.properties').values==models['prod']
    assert templates.affected(root,{template.relative_to(root)})=={(env,'team','iam') for env in models}
    assert templates.affected(root,{source.relative_to(root)})=={('dev','team','iam')}
    trace=templates.load_expansion(path).provenance['desired.row.011-004.value']
    assert trace['inputs']['Name']['description'] and trace['rows']=={'name':'011-004'} and trace['bindingFile'].endswith('bindings.json')


def check_layout(root):
    fixture(root, ('dev', 'stg'))
    template = install_candidate(root, {env: role_model(env, 2) for env in ('dev', 'stg')})
    logical = root/'model/dev/team/iam.properties'
    assert templates.source_paths(logical) == (root, template, root/'model/parameters/dev/team/iam')
    for relative in ('model/templates/team/iam.properties', 'model/parameters/team/iam.properties',
                     'model/parameters/dev/team/iam/parameters.yaml', 'model/dev/team/iam.json',
                     'model/dev/team/iam.properties/part-001.properties'):
        assert templates.source_paths(root/relative) is None, relative
    from model_files import service_model_path
    physical = root/'model/templates/team/iam.properties/part-001.properties'
    assert service_model_path(physical, root/'model') == physical
    expected = {('dev', 'team', 'iam'), ('stg', 'team', 'iam')}
    assert templates.affected(root, {template.relative_to(root)}) == expected
    part = template.parent/'iam.properties/part-001.properties'
    part.parent.mkdir()
    part.write_bytes(template.read_bytes())
    template.write_text('# model-index: 1\n# part: iam.properties/part-001.properties\n', encoding='utf-8')
    assert templates.affected(root, {part.relative_to(root)}) == expected
    for env in ('dev', 'stg'):
        assert load_model(root/'model'/env/'team/iam.properties').values == role_model(env, 2)
        for name in ('parameters.yaml', 'bindings.json', 'observed.json'):
            assert templates.affected(root, {f'model/parameters/{env}/team/iam/{name}'}) == {(env, 'team', 'iam')}
        assert templates.affected(root, {f'model/{env}/team/iam.properties'}) == {(env, 'team', 'iam')}
    for relative in ('model/templates/team/unrelated.properties.tpl', 'model/templates/team/iam.json',
                     'model/parameters/dev/team/iam.json', 'docs/unrelated.md'):
        assert templates.affected(root, {relative}) == set(), relative
    # The scope guard must distinguish physical sources from logical selectors.
    from support.validator import MODULE
    for env in ('dev', 'stg'):
        view = root/'docs/designs'/env/'team/iam.md'
        view.parent.mkdir(parents=True)
        view.write_text('fixture', encoding='utf-8')
    for changed, rejected_scope in (({part.relative_to(root).as_posix()}, True),
                                    ({'model/parameters/dev/team/iam/parameters.yaml'}, False),
                                    ({'model/parameters/stg/team/iam/parameters.yaml'}, True),
                                    ({'model/dev/team/iam.properties'}, False)):
        validator = MODULE.Validator(root, {('dev', 'team', 'iam')})
        validator.accounts = {('dev', 'team'): {}, ('stg', 'team'): {}}
        validator.changed_paths = changed
        validator.check_validation_scope()
        assert bool(validator.errors) == rejected_scope, validator.errors


def check_reference_impact(root):
    from model_parameter_inputs import yaml_read
    fixture(root)
    template = root/'model/templates/team/codebuild.properties.tpl'
    text = '''# model-template: 1
# input: Suffix {"type":"string","description":"名前の接尾辞","required":true}
# definition: Project
# parameter: Name {"type":"string","description":"Project名","required":true}
# parameter: ArtifactsType {"type":"string","description":"artifact方式","required":true}
# resource: project
# row: name project
# row: artifacts project
desired.resource.project.resourceType=CodeBuild.Project
desired.resource.project.anchor=codebuild-<<Name>><<Suffix>>
desired.row.name.property=CodeBuild.Project.Name
desired.row.name.value=`<<Name>><<Suffix>>`
desired.row.artifacts.property=CodeBuild.Project.Artifacts.Type
desired.row.artifacts.value=<<ArtifactsType>>
# end-definition
'''
    bindings = {'instances': {'build': {'definition':'Project', 'resources':{'project':'005'},
                'rows':{'name':'005-001', 'artifacts':'005-003'}, 'parameters':{}}}}
    human = {'parameters':{'Suffix':''}, 'instances':{'build':{'parameters':{
             'Name':'app-dev-build', 'ArtifactsType':'NO_ARTIFACTS'}}}}
    source = root/'model/parameters/dev/team/codebuild/parameters.yaml'
    save_files({template:text, source:templates.json_text(human),
                source.with_name('bindings.json'):templates.json_text(bindings)})
    for service, producer, kind, consumer_kind in [('codepipeline','codebuild','CodeBuild.Project','CodePipeline.Pipeline'),
                                                    ('lambda','codepipeline','CodePipeline.Pipeline','Lambda.Function')]:
        consumer = root/'model/templates/team'/(service+'.properties.tpl')
        name_property = 'FunctionName' if service == 'lambda' else 'Name'
        save_files({consumer:f'''# model-template: 1
# definition: Consumer
# reference: Producer {{"service":"{producer}","resource":"005","resourceType":"{kind}","format":"name"}}
# resource: resource
# row: name resource
desired.resource.resource.resourceType={consumer_kind}
desired.resource.resource.anchor={service}-fixture
desired.row.name.property={consumer_kind}.{name_property}
desired.row.name.value=<<Producer>>
# end-definition
''', root/'model/parameters/dev/team'/service/'parameters.yaml':'instances: {}\n',
            root/'model/parameters/dev/team'/service/'bindings.json':templates.json_text({
                'instances':{'consumer':{'definition':'Consumer','resources':{'resource':'005'},
                             'rows':{'name':'005-001'},'parameters':{}}}})})
    relative = source.relative_to(root)
    own = {('dev','team','codebuild')}
    chain = own | {('dev','team',service) for service in ('codepipeline','lambda')}
    # Unknown baselines stay conservative, including a repository without Git.
    assert templates.affected(root, {relative}) == chain
    def git(*args):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    git('init'); git('config','user.email','fixture@example.invalid'); git('config','user.name','Fixture')
    git('add','model'); git('commit','-m','Fixture baseline')
    baseline = git('rev-parse','HEAD')
    assert templates.affected(root, {relative}) == chain  # No known diff must not hide a committed rename.
    def change(name, value):
        params = yaml_read(source.read_text(encoding='utf-8'))
        (params['parameters'] if name == 'Suffix' else params['instances']['build']['parameters'])[name] = value
        source.write_text(templates.json_text(params), encoding='utf-8')
    change('ArtifactsType','CODEPIPELINE')
    assert templates.affected(root, {relative}) == own
    git('add',str(relative))
    assert templates.affected(root, {relative}) == own  # Staged inputs count too.
    change('Name','renamed')
    assert templates.affected(root, {relative}) == chain  # Combined staged/unstaged changes.
    change('Name','app-dev-build'); change('Suffix','-two')
    assert templates.affected(root, {relative}) == chain
    change('Suffix','')
    assert templates.affected(root, {relative, source.with_name('bindings.json').relative_to(root)}) == own
    assert templates.affected(root, {relative, template.relative_to(root)}) == own
    change('Name','committed-name'); git('add',str(relative)); git('commit','-m','Fixture change')
    assert templates.affected(root, {relative}) == chain
    with patch('worktree_task.committed_task_paths', return_value={relative.as_posix()}), \
         patch('worktree_task.load', return_value=(None,None,None,{'start':baseline})):
        assert templates.affected(root, {relative}) == chain  # Pinned task baseline survives commits.


    import model_impact as impact
    from validation_cache import input_scope, memo_table
    previous = root / 'previous'
    shutil.copytree(root / 'model', previous / 'model')
    shutil.copyfile(root / 'project.json', previous / 'project.json')

    @input_scope
    def reuse():
        with patch.object(impact, 'model_paths', wraps=impact.model_paths) as builds:
            graph = impact.dependencies(root, active=True)
            assert impact.dependencies(root / '.', active=True) == graph
            assert builds.call_count == 1
            # Public results and merged graphs must not mutate the cache's inner sets.
            next(iter(graph.values())).add(('dev', 'team', 'unrelated'))
            assert all(('dev', 'team', 'unrelated') not in items for items in impact.dependencies(root).values())
            impact.propagate(root, set(own), set(own), previous)
            assert builds.call_count == 2  # Separate comparison root.
            impact.dependencies(root, active=False)
            assert builds.call_count == 3
            assert ('dev','team','lambda') in impact.dependencies(root)
            shutil.rmtree(root / 'model/parameters/dev/team/lambda')
            # A nested input_scope inherits the outer snapshot; writes end it explicitly.
            memo_table().clear()
            assert ('dev','team','lambda') not in impact.dependencies(root)
            assert builds.call_count == 4
            shutil.copytree(previous / 'model/parameters/dev/team/lambda', root / 'model/parameters/dev/team/lambda')
            memo_table().clear()
            assert ('dev','team','lambda') in impact.dependencies(root)
            assert builds.call_count == 5
            from import_scope import restrict, read_consumers
            with restrict(('dev','team','codebuild')):
                with read_consumers(own):
                    assert set(impact.dependencies(root)) == own
                with read_consumers(chain):
                    assert set(impact.dependencies(root)) == chain
            reference = root / 'model/templates/team/codepipeline.properties.tpl'
            original = reference.read_text(encoding='utf-8')
            reference.write_text(''.join(line for line in original.splitlines(keepends=True)
                                       if not line.startswith('# reference: ')).replace('<<Producer>>','fixed'), encoding='utf-8')
            memo_table().clear()
            assert not impact.dependencies(root)[('dev','team','codepipeline')]
            reference.write_text('invalid', encoding='utf-8')
            memo_table().clear()
            rejected(lambda: impact.dependencies(root), 'header required')
            reference.write_text(original, encoding='utf-8')
            memo_table().clear()
            assert impact.dependencies(root)[('dev','team','codepipeline')] == own
    reuse()


def check_template_snapshot(root):
    from validation_cache import input_scope
    path = write_model(root / 'model/dev/team/config.properties', config_model())
    template = templates.service_source(path)[1]

    @input_scope
    def reuse():
        from validation_cache import memoized
        parsed = []
        original_parser = templates._parse_template.__wrapped__
        def parse(*args):
            parsed.append(args[0])
            return original_parser(*args)
        with patch.object(templates, '_parse_template', memoized(parse)):
            first = templates.load_expansion(path)
            second = templates.load_expansion(path)
            assert first.values == second.values
            # Count actual parser bodies, not the memoized lookup calls.
            assert len(parsed) == 1
            _, files = templates.parse_template(template)
            assert not any('parameters' in file.parts for file in files)
            first.files[root / 'foreign'] = 'unrelated'
            assert root / 'foreign' not in second.files
        original = template.read_text(encoding='utf-8')
        template.write_text('invalid', encoding='utf-8')
        rejected(lambda: templates.load_expansion(path), 'header required')
        template.write_text(original, encoding='utf-8')
        assert templates.load_expansion(path).values == first.values
    reuse()


def check_creation(root):
    fixture(root)
    path = write_model(root/'model/dev/team/config.properties', config_model())
    directory = root/'model/parameters/dev/team/config'
    expected = load_model(path).values
    for _ in range(2):
        templates.create_service(path)
        assert load_model(path).values == expected
        assert not path.exists() and not (directory/'source.json').exists()
    changed = templates.json_read((directory/'bindings.json').read_text())
    changed['instances']['fixture']['definition'] = 'Unknown'
    (directory/'bindings.json').write_text(templates.json_text(changed))
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    rejected(lambda: templates.create_service(path), 'unknown definition')
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


def check_invalid(root):
    from model_parameter_inputs import yaml_read
    fixture(root,('dev',));template=install_candidate(root,{'dev':role_model('dev',2)})
    path=root/'model/dev/team/iam.properties';directory=root/'model/parameters/dev/team/iam'
    params=yaml_read((directory/'parameters.yaml').read_text());binding=templates.json_read((directory/'bindings.json').read_text());observed={'version':1,'values':{}}
    for mutate in (lambda p:p.update(unknown=1),lambda p:p['instances']['role_011']['parameters'].pop('Name'),lambda p:p['instances']['role_011']['parameters'].update(Name=True),lambda p:p['instances']['role_011'].update(definition='Role')):
        invalid=copy.deepcopy(params);mutate(invalid);rejected(lambda:templates.expand(template,invalid,observed,binding,'dev'))
    for mutate in (lambda b:b['instances']['role_011'].update(definition='missing'),lambda b:b['instances']['role_018']['resources'].update(role='011'),lambda b:b['instances']['role_011']['rows'].update(name='099-004')):
        invalid=copy.deepcopy(binding);mutate(invalid);rejected(lambda:templates.expand(template,params,observed,invalid,'dev'))
    original=template.read_text()
    for syntax in ('<<Missing>>','<<#Name>>x<</Name>>','<<^Name>>x<</Name>>','<<>partial>>','<<&Name>>','<<{Name}>>','<<= x y =>>','{{#Name}}','{{>partial}}'):
        template.write_text(original.replace('<<Name>>',syntax));rejected(lambda:templates.expand(template,params,observed,binding,'dev'))
    template.write_text(original)
    for value in ('a"b\\日本語=終','', '<<not-reparsed>>','${AWS::Region} {{resolve:ssm:literal}}'):
        invalid=copy.deepcopy(params);invalid['instances']['role_011']['parameters']['Name']=value
        assert templates.expand(template,invalid,observed,binding,'dev')[0]['desired.row.011-004.value']==value
    invalid=copy.deepcopy(params);invalid['instances']['role_011']['parameters']['Name']='x\ninjected.key=bad'
    rejected(lambda:templates.expand(template,invalid,observed,binding,'dev'),'one line')
    (directory/'parameters.json').write_text('{}');rejected(lambda:read_model(path),'unsupported JSON');(directory/'parameters.json').unlink()
    for name in ('parameters.yaml','bindings.json'):
        file=directory/name;content=file.read_bytes();file.unlink();rejected(lambda:read_model(path));file.write_bytes(content)
    template.unlink();rejected(lambda:read_model(path));template.write_text(original)
    legacy=root/'model/dev/team/legacy.properties';legacy.parent.mkdir(parents=True,exist_ok=True);legacy.write_text('desired.service.legacy.serviceId=legacy\n');rejected(lambda:read_model(legacy),'YAML Model inputs missing')


def check_sync(root):
    with patch.object(sync_runtime, 'sync', wraps=sync_runtime.sync) as calls:
        fixture(root,('dev',));path=write_fixture(root,'dev','config',config_model())
        view=root/'docs/designs/dev/team/config.md'
        before={p:p.read_bytes() for p in root.rglob('*') if p.is_file() and p.suffix!='.pyc'}
        with redirect_stdout(io.StringIO()):
            sync_runtime.sync(root,True,'dev','team',services=['config'])
            sync_runtime.sync(root,False,'dev','team',services=['config'])
        assert all(p.read_bytes()==v for p,v in before.items())
        from cloudformation_observed import observed_destinations,publish_observed
        changes=observed_destinations(root,'dev','team',{path:load_model(path).values},{path:{'observed.row.007-009.value':'`new-id`'}},check_scope=False)[0]
        assert root/'model/parameters/dev/team/config/observed.json' in changes
        publish_observed(root,changes)
        assert load_model(path).values['observed.row.007-009.value']=='`new-id`'
        with redirect_stdout(io.StringIO()):sync_runtime.sync(root,True,'dev','team',services=['config'])
        # The four newline combinations remain in sync-model.checks.py::check_markdown_newlines.
        for newline,final in (('\r\n',False),):
            original=view.read_text();content=original.rstrip('\n').replace('\n',newline)+(newline if final else '')
            view.write_bytes(content.encode())
            with redirect_stdout(io.StringIO()):sync_runtime.sync(root,True,'dev','team',services=['config'])
            assert view.read_bytes()==content.encode()
        template=root/'model/templates/team/config.properties.tpl';saved=template.read_bytes();real=sync_runtime.validate_candidates
        def drift(*args,**kwargs):real(*args,**kwargs);template.write_bytes(saved+b'# changed\n')
        with patch.object(sync_runtime,'validate_candidates',drift),redirect_stdout(io.StringIO()):rejected(lambda:sync_runtime.sync(root,True,'dev','team',services=['config']),'inputs changed')
        template.write_bytes(saved)
    assert calls.call_count == 6, 'initial/write/match/observed/newline/drift coverage'


def check_common_shape(root):
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
    observed={'version':1,'values':{}}
    binding={'instances':{'fixed':{'definition':'Bucket','resources':{'bucket':'017'},
                                 'rows':{'name':'017-023','config':'017-025'},'parameters':{'HasLogicalId':False}},
                          'note':{'definition':'Note','resources':{},'rows':{},'parameters':{}}}}
    human={'instances':{'fixed':{'parameters':{'HasPolicy':False,'HasExtraStatement':False,'UsesReference':False,'AlternateAnchor':False}}}}
    minimal=templates.expand(template,human,observed,binding)[0]
    assert 'desired.resource.017.logicalId' not in minimal
    assert not any(key.startswith('desired.row.017-024.') for key in minimal)
    assert templates.json_read(minimal['desired.row.017-025.value'][1:-1])=={'Items':[1,3],'Value':'','Keep':None}
    assert minimal['display.service.note']=='[017](#s3-fixed)'
    full=copy.deepcopy(binding);full['instances']['fixed']['rows']['policy']='017-024'
    full['instances']['fixed']['parameters'].update(HasLogicalId=True,LogicalId='FixedBucket')
    inputs=copy.deepcopy(human);inputs['instances']['fixed']['parameters'].update(HasPolicy=True)
    values=templates.expand(template,inputs,observed,full)[0]
    assert templates.json_read(values['desired.row.017-024.document'])=={'Statement':[{'Resource':'*'}]}
    assert values['desired.resource.017.logicalId']=='FixedBucket'
    inputs['instances']['fixed']['parameters'].update(UsesReference=True,AlternateAnchor=True)
    inputs['instances']['fixed']['parameters'].update(HasExtraStatement=True,ExtraResource='explicit-target')
    values=templates.expand(template,inputs,observed,full)[0]
    assert values['desired.row.017-023.value']=='[017](#s3-alternate)'
    assert values['display.service.note']=='[017](#s3-alternate)'
    assert templates.json_read(values['desired.row.017-025.value'][1:-1])=={'Drop':None,'Items':[0,1,2,3],'Value':False,'Keep':None}
    assert templates.json_read(values['desired.row.017-024.document'])['Statement'][1]['Resource']=='explicit-target'
    assert 'desired.row.017-024.artifactSha256' in values
    bad=copy.deepcopy(binding);bad['instances']['fixed']['parameters']['HasLogicalId']='false'
    rejected(lambda:templates.expand(template,human,observed,bad),'explicit boolean')
    bad=copy.deepcopy(binding);del bad['instances']['fixed']['parameters']['HasLogicalId']
    rejected(lambda:templates.expand(template,human,observed,bad),'explicit boolean')
    bad=copy.deepcopy(binding);del bad['instances']['fixed']['rows']['name']
    rejected(lambda:templates.expand(template,human,observed,bad),'local ID map')
    rejected(lambda:templates.expand(template,human,observed,full),'local ID map')
    bad=copy.deepcopy(human);bad['instances']['fixed']['parameters']=[]
    rejected(lambda:templates.expand(template,bad,observed,binding),'parameters must be an object')
    original=template.read_text(encoding='utf-8')
    for malformed in (original.replace('/Statement/1','/Statement/-1'),
                      original.replace('/Statement/1','/Statement/01'),
                      original.replace('/Statement/1','/Statement/~2'),
                      original.replace('"pointer":"/Value"','"pointer":null'),
                      original.replace('# choice: desired.row.config.value', '# choice: desired.row.config.value {"parameter":"AlternateAnchor","value":"other"}\n# choice: desired.row.config.value'),
                      original.replace('desired.resource.bucket.logicalId HasLogicalId','desired.resource.bucket.unknown HasLogicalId'),
                      original.replace('HasLogicalId boolean','HasLogicalId string')):
        template.write_text(malformed,encoding='utf-8')
        rejected(lambda:templates.parse_template(template))
    template.write_text(original.replace('# choice: desired.row.name.value', '# choice: desired.row.name.value {"parameter":"AlternateAnchor","value":"other"}\n# choice: desired.row.name.value'),encoding='utf-8')
    rejected(lambda:templates.expand(template,inputs,observed,full),'ambiguous field choices')



import pytest
from support.pytest_cli import run


@pytest.fixture
def root(tmp_path):
    return tmp_path.resolve()


def main():
    return run(__file__, message="model_templates: PASS")


if __name__ == '__main__':
    raise SystemExit(main())

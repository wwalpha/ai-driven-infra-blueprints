#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_templates_fixtures import *

def check_transactions(root):
    original=root/'original.properties';original.write_text('a=old\n')
    new=root/'new.json';output={original:'a=new\n',new:'{}\n'}
    write=Path.write_text
    def fail(path,*args,**kwargs):
        if path==new:raise OSError('injected partial-write failure')
        return write(path,*args,**kwargs)
    with patch.object(Path,'write_text',fail):rejected(lambda:templates.publish(root,output),'injected')
    assert original.read_text()=='a=old\n'
    rejected(lambda:templates.publish(root,output,inputs={original:b'a=other\n'}),'changed after validation')
    assert original.read_text()=='a=old\n'
    # Written inputs are checked against published bytes; untouched inputs retain their snapshot.
    dependency = root/'dependency.json'; dependency.write_text('{}\n', encoding='utf-8')
    obsolete = root/'obsolete.json'; obsolete.write_text('{"old":true}\n', encoding='utf-8')
    snapshots = {original: original.read_bytes(), dependency: dependency.read_bytes(), obsolete: obsolete.read_bytes()}
    def verify():
        assert original.read_text() == 'a=new\n' and new.is_file()
    templates.publish(root, output, [obsolete], inputs=snapshots, verify=verify)
    assert original.read_text() == 'a=new\n'
    original.write_text('a=old\n'); new.unlink()
    obsolete.write_bytes(snapshots[obsolete])
    def concurrent():
        dependency.write_text('{"changed":true}\n')
    rejected(lambda: templates.publish(root, output, [obsolete], inputs=snapshots, verify=concurrent), 'inputs changed during publication')
    assert original.read_text() == 'a=old\n' and obsolete.read_bytes() == snapshots[obsolete]
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
    assert original.read_text()=='a=old\n'

    def callback():
        path = root/'view.md'
        path.write_bytes(b'original\r\n')
        called = []
        def finish_import():
            called.append(path.read_bytes())
            raise ValueError('injected completion callback failure')
        with pytest.raises(ValueError, match='completion callback'):
            templates.publish(root, {path: 'changed\n'}, inputs={}, verify=finish_import)
        assert called == [b'changed\r\n']
        assert path.read_bytes() == b'original\r\n'
        with templates.publication_lock(root) as journal:
            assert not journal.exists()

    callback()

    def recovery():
        first, created = root/'view.md', root/'artifact.json'
        first.write_bytes(b'original\r\n')
        originals = {first: first.read_bytes(), created: None}
        write = Path.write_text
        def interrupted(path, *args, **kwargs):
            result = write(path, *args, **kwargs)
            if path == created:
                raise KeyboardInterrupt()
            return result
        with templates.publication_lock(root) as journal:
            with patch.object(Path, 'write_text', interrupted), pytest.raises(KeyboardInterrupt):
                templates._publish_transaction(root, {first: 'changed\n', created: '{}\n'}, (), journal,
                                               originals=originals)
            assert journal.is_file()
        # Recovery precedes the next generation snapshot and its originals/output differences.
        with templates.publication_lock(root) as journal:
            assert first.read_bytes() == originals[first] and not created.exists()
            assert not journal.exists()
        with templates.publication_lock(root) as journal:
            with patch.object(Path, 'write_text', side_effect=OSError('injected I/O')), pytest.raises(OSError):
                templates._publish_transaction(root, {first: 'changed\n'}, (), journal,
                                               originals={first: originals[first]})
            assert first.read_bytes() == originals[first] and not journal.exists()

    recovery()

    def file_rollback():
        from support.model_sources import write_fixture_files as save_files
        first, created, last = [root / name for name in ('first.md', 'new.json', 'last.md')]
        originals = {first: b'first\r\n', last: b'last\r\n'}
        write_text, write_bytes = Path.write_text, Path.write_bytes
        for failed in (first, created, last):
            for path, content in originals.items():
                path.write_bytes(content)
            calls = []
            def fail_write(path, *args, **kwargs):
                calls.append(path)
                if path == failed:
                    write_text(path, 'partially written', encoding='utf-8')
                    raise OSError('injected publication failure')
                return write_text(path, *args, **kwargs)
            with patch.object(Path, 'write_text', fail_write):
                with pytest.raises(OSError) as error:
                    save_files({first: 'changed\n', created: '{}\n', last: 'changed\n'})
                assert str(error.value) == 'injected publication failure'
            assert failed in calls
            assert {path: path.read_bytes() for path in originals} == originals
        restores = []
        def fail_restore(path, content):
            restores.append(path)
            raise OSError('injected restoration failure')
        with patch.object(Path, 'write_text', fail_write), patch.object(Path, 'write_bytes', fail_restore):
            with pytest.raises(OSError) as error:
                save_files({first: 'changed\n', created: '{}\n', last: 'changed\n'})
            assert 'generated-file rollback failed:' in str(error.value)
            assert all(f'{path}: injected restoration failure' in str(error.value) for path in (last, first))
        assert last in calls and restores == [last, first]
        for path, content in originals.items():
            write_bytes(path, content)
        with patch.object(Path, 'write_text', side_effect=AssertionError('unchanged file rewritten')):
            save_files({path: content.decode('utf-8') for path, content in originals.items()})
        print('File rollback: PASS (first/middle/last partial write, restoration error, no-op)')

    file_rollback()

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
    # A substantive shared input must reach both consumers and remain stable on regeneration.
    template.write_text(content.replace('lambda.amazonaws.com', 'ec2.amazonaws.com'))
    for env in models:
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, 'team', services=['iam']) == 0
        outputs = {p: p.read_bytes() for p in (root/'docs/designs'/env/'team').rglob('*') if p.is_file()}
        policies = [p for p in outputs if p.suffix == '.json']
        assert len(policies) == len(entries(models[env], 'desired.resource.'))
        assert all(json.loads(outputs[p])['Statement'][0]['Principal']['Service'] == 'ec2.amazonaws.com' for p in policies)
        with redirect_stdout(io.StringIO()) as diagnostics:
            assert sync_runtime.sync(root, True, env, 'team', services=['iam']) == 0
        assert all(p.read_bytes() == data for p, data in outputs.items())
        assert 'FAIL' not in diagnostics.getvalue()
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
    with patch('worktree_task.task_start_commit', return_value=baseline):
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
    original = template.read_text(encoding='utf-8')

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
        template.write_text('invalid', encoding='utf-8')
        assert templates.load_expansion(path).values == second.values
        template.write_text(original, encoding='utf-8')
        assert templates.load_expansion(path).values == first.values
    reuse()
    template.write_text('invalid', encoding='utf-8')
    rejected(lambda: templates.load_expansion(path), 'header required')
    template.write_text(original, encoding='utf-8')


def check_creation(root):
    fixture(root)
    path = write_model(root/'model/dev/team/config.properties', config_model())
    directory = root/'model/parameters/dev/team/config'
    expected = load_model(path).values
    for _ in range(2):
        templates.create_service(path)
        assert load_model(path).values == expected
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
        for newline,final in (('\n',True), ('\n',False), ('\r\n',True), ('\r\n',False)):
            original=view.read_text();content=original.rstrip('\n').replace('\n',newline)+(newline if final else '')
            view.write_bytes(content.encode())
            with redirect_stdout(io.StringIO()):sync_runtime.sync(root,True,'dev','team',services=['config'])
            assert view.read_bytes()==content.encode()
        template=root/'model/templates/team/config.properties.tpl';saved=template.read_bytes();real=sync_runtime.validate_candidates
        def drift(*args,**kwargs):real(*args,**kwargs);template.write_bytes(saved+b'# changed\n')
        with patch.object(sync_runtime,'validate_candidates',drift),redirect_stdout(io.StringIO()):rejected(lambda:sync_runtime.sync(root,True,'dev','team',services=['config']),'inputs changed')
        template.write_bytes(saved)
    assert calls.call_count == 9, 'initial/write/match/observed/newline/drift coverage'


def check_common_shape(root):
    template = common_shape_template(root)
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
    original = template.read_text(encoding='utf-8')
    template.write_text(original.replace('# choice: desired.row.name.value', '# choice: desired.row.name.value {"parameter":"AlternateAnchor","value":"other"}\n# choice: desired.row.name.value'),encoding='utf-8')
    rejected(lambda:templates.expand(template,inputs,observed,full),'ambiguous field choices')


def main():
    return run(__file__, message="model_templates: PASS")


if __name__ == '__main__':
    raise SystemExit(main())


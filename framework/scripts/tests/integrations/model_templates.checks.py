#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_templates_fixtures import *

def check_transactions(root):
    from types import SimpleNamespace
    from generation_inputs import GenerationInputs
    from model.operations import _verify_published_inputs
    from sync_files import changed_files
    task = root / 'tasks/example.md'
    task.parent.mkdir()
    task.write_text('## Task contract\n- Task type: `migration`\n- Task status: `running`\n## Validation scope\n- `framework`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `**`\n')
    def transaction(root, output, obsolete=(), *, read_paths=(), verify=None):
        snapshot = GenerationInputs(root)
        for path in set(output) | set(obsolete) | set(read_paths):
            snapshot.read(path)
        changes = {**changed_files(output), **{path: None for path in obsolete}}
        def finish():
            if verify is not None:
                verify()
            _verify_published_inputs(SimpleNamespace(root=root, snapshot=snapshot), changes)
        try:
            with publication_lock(root) as journal:
                snapshot.verify()
                _publish_transaction(root, output, obsolete, journal, finish=finish)
        finally:
            snapshot.close()
    original=root/'original.properties';original.write_text('a=old\n')
    new=root/'new.json';output={original:'a=new\n',new:'{}\n'}
    write=Path.write_text
    def fail(path,*args,**kwargs):
        if path==new:raise OSError('injected partial-write failure')
        return write(path,*args,**kwargs)
    with patch.object(Path,'write_text',fail):rejected(lambda:transaction(root,output),'injected')
    assert original.read_text()=='a=old\n'
    stale = GenerationInputs(root); stale.read(original)
    original.write_text('a=other\n')
    rejected(stale.verify, 'inputs changed')
    assert original.read_text() == 'a=other\n'
    original.write_text('a=old\n')
    # Written inputs are checked against published bytes; untouched inputs retain their snapshot.
    dependency = root/'dependency.json'; dependency.write_text('{}\n', encoding='utf-8')
    obsolete = root/'obsolete.json'; obsolete.write_text('{"old":true}\n', encoding='utf-8')
    snapshots = {original: original.read_bytes(), dependency: dependency.read_bytes(), obsolete: obsolete.read_bytes()}
    def verify():
        assert original.read_text() == 'a=new\n' and new.is_file()
    transaction(root, output, [obsolete], read_paths=snapshots, verify=verify)
    assert original.read_text() == 'a=new\n'
    original.write_text('a=old\n'); new.unlink()
    obsolete.write_bytes(snapshots[obsolete])
    def concurrent():
        dependency.write_text('{"changed":true}\n')
    rejected(lambda: transaction(root, output, [obsolete], read_paths=snapshots, verify=concurrent), 'inputs changed during publication')
    assert original.read_text() == 'a=old\n' and obsolete.read_bytes() == snapshots[obsolete]
    dependency.write_bytes(snapshots[dependency])
    # A terminated process leaves a durable journal; the next reader restores prior inputs.
    program='''import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from model.sources import publication_lock, _publish_transaction
import sync_files
root=Path(sys.argv[2]); original=root/'original.properties'
def crash(output):
    original.write_text('a=crash\\n');os._exit(17)
sync_files.save_files=crash
with publication_lock(root) as journal:
    _publish_transaction(root,{original:'a=crash\\n',root/'new.json':'{}\\n'},(),journal)
'''
    result=subprocess.run([sys.executable,'-c',program,str(ROOT/'framework/scripts'),str(root)])
    assert result.returncode==17 and original.read_text()=='a=crash\n'
    with publication_lock(root):pass
    assert original.read_text()=='a=old\n'

    def callback():
        path = root/'view.md'
        path.write_bytes(b'original\r\n')
        called = []
        def finish_import():
            called.append(path.read_bytes())
            raise ValueError('injected completion callback failure')
        with pytest.raises(ValueError, match='completion callback'):
            transaction(root, {path: 'changed\n'}, verify=finish_import)
        assert called == [b'changed\r\n']
        assert path.read_bytes() == b'original\r\n'
        with publication_lock(root) as journal:
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
        with publication_lock(root) as journal:
            with patch.object(Path, 'write_text', interrupted), pytest.raises(KeyboardInterrupt):
                _publish_transaction(root, {first: 'changed\n', created: '{}\n'}, (), journal,
                                               originals=originals)
            assert journal.is_file()
        # Recovery precedes the next generation snapshot and its originals/output differences.
        with publication_lock(root) as journal:
            assert first.read_bytes() == originals[first] and not created.exists()
            assert not journal.exists()
        with publication_lock(root) as journal:
            with patch.object(Path, 'write_text', side_effect=OSError('injected I/O')), pytest.raises(OSError):
                _publish_transaction(root, {first: 'changed\n'}, (), journal,
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
    fixture(root)
    models = {'dev': role_model('dev', 2), 'prod': role_model('prod', 5)}
    install_candidate(root, models)
    original = {}
    for env, expected in models.items():
        path = root / 'model' / env / 'team/iam.properties'
        assert load_model(path).authoritative == expected
        original[env] = path.read_bytes()
    # Each explicit environment is edited deliberately; no shared source expands to the other.
    for env in models:
        path = root / 'model' / env / 'team/iam.properties'
        edited = {key: value.replace('lambda.amazonaws.com', 'ec2.amazonaws.com') if key.endswith('.document') else value
                  for key, value in models[env].items()}
        write_model(path, edited)
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, env, 'team', services=['iam']) == 0
        outputs = {p: p.read_bytes() for p in (root / 'docs/designs' / env / 'team').rglob('*') if p.is_file()}
        policies = [p for p in outputs if p.suffix == '.json']
        assert len(policies) == len(entries(models[env], 'desired.resource.'))
        assert all(json.loads(outputs[p])['Statement'][0]['Principal']['Service'] == 'ec2.amazonaws.com' for p in policies)
        with redirect_stdout(io.StringIO()) as diagnostics:
            assert sync_runtime.sync(root, True, env, 'team', services=['iam']) == 0
        assert all(p.read_bytes() == data for p, data in outputs.items()) and 'FAIL' not in diagnostics.getvalue()
        path.write_bytes(original[env])
    path = root / 'model/dev/team/iam.properties'
    current = dict(models['dev']); current['desired.row.011-004.value'] = '`changed`'
    write_model(path, current)
    assert load_model(path).authoritative['desired.row.011-004.value'] == '`changed`'
    assert load_model(root / 'model/prod/team/iam.properties').authoritative == models['prod']
    assert affected(root, {path.relative_to(root)}) == {('dev', 'team', 'iam')}
    trace = trace_model(path, 'desired.row.011-004.value')
    assert trace['file'] == str(path) and trace['value'] == '`changed`'



def check_layout(root):
    fixture(root, ('dev', 'stg'))
    install_candidate(root, {env: role_model(env, 2) for env in ('dev', 'stg')})
    logical = root / 'model/dev/team/iam.properties'
    from model.files import service_model_path
    scope = source_scope(root, logical)
    assert (scope.environment, scope.target, scope.service) == ('dev', 'team', 'iam')
    for relative in ('model/templates/team/iam.properties', 'model/parameters/team/iam.properties',
                     'model/parameters/dev/team/iam/parameters.yaml', 'model/dev/team/iam.json',
                     'model/dev/team/iam.properties/part-001.properties'):
        rejected(lambda: load_model(source_scope(root, root / relative)))
    values = dict(load_model(logical).authoritative)
    output = split(logical, values, limit=20)
    assert len(output) > 1
    for path, text in output.items():
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    part = next(path for path in output if path != logical)
    assert service_model_path(part, root / 'model') == logical
    assert affected(root, {part.relative_to(root)}) == {('dev', 'team', 'iam')}
    assert load_model(logical).authoritative == values
    assert load_model(root / 'model/stg/team/iam.properties').authoritative == role_model('stg', 2)
    from support.validator import MODULE
    for env in ('dev', 'stg'):
        view = root / 'docs/designs' / env / 'team/iam.md'
        view.parent.mkdir(parents=True, exist_ok=True)
        view.write_text('fixture\n', encoding='utf-8')
    for changed, rejected_scope in (({part.relative_to(root).as_posix()}, False),
                                    ({'model/stg/team/iam.properties'}, True), ({'model/dev/team/iam.properties'}, False)):
        validator = MODULE.Validator(root, {('dev', 'team', 'iam')})
        validator.accounts = {('dev', 'team'): {}, ('stg', 'team'): {}}
        validator.changed_paths = changed
        validator.check_validation_scope()
        assert bool(validator.errors) == rejected_scope, validator.errors
    assert affected(root, {'docs/unrelated.md'}) == set()



def check_reference_impact(root):
    fixture(root)
    from support.producer_identifier_reference_fixtures import reference, resource
    from model.sources import design_source_digest, FileReads
    from model.importing.scope import restrict, read_consumers
    paths = {}
    for service, kind, producer, producer_kind in [('codebuild', 'CodeBuild.Project', None, None),
            ('codepipeline', 'CodePipeline.Pipeline', 'codebuild', 'CodeBuild.Project'),
            ('lambda', 'Lambda.Function', 'codepipeline', 'CodePipeline.Pipeline')]:
        path = root / 'model/dev/team' / (service + '.properties')
        prop = 'FunctionName' if service == 'lambda' else 'Name'
        values = resource('005', kind, service + '-fixture', [(prop, '`app-dev-build`')])
        if producer:
            values.update(reference('producer', 'desired.row.005-001.value', 'app-dev-build', producer, '005', producer_kind,
                                    prop=producer_kind + '.Name', environment='dev'))
        write_model(path, values); paths[service] = path
    own = {('dev', 'team', 'codebuild')}
    chain = own | {('dev', 'team', service) for service in ('codepipeline', 'lambda')}
    source = paths['codebuild']; relative = source.relative_to(root)
    assert affected(root, {relative}) == chain
    previous = root / 'previous'; shutil.copytree(root / 'model', previous / 'model')
    shutil.copyfile(root / 'project.json', previous / 'project.json')
    original = source.read_bytes()
    for raw in (original + b'# annotation\n', original.replace(b'app-dev-build', b'renamed')):
        source.write_bytes(raw)
        assert affected(root, {relative}) == chain
        assert load_model(paths['codepipeline']).authoritative['desired.row.005-001.value'] == '`app-dev-build`'
    source.write_bytes(original)
    graph = dependencies(root)
    graph[('dev', 'team', 'codepipeline')].add(('dev', 'team', 'unrelated'))
    assert ('dev', 'team', 'unrelated') not in dependencies(root)[('dev', 'team', 'codepipeline')]
    with restrict(('dev', 'team', 'codebuild')):
        with read_consumers(own):
            assert set(dependencies(root)) == own
        with read_consumers(chain):
            assert set(dependencies(root)) == chain
    values = dict(load_model(paths['codepipeline']).authoritative)
    values = {key: value for key, value in values.items() if not key.startswith('desired.reference.')}
    write_model(paths['codepipeline'], values)
    assert not dependencies(root)[('dev', 'team', 'codepipeline')]
    assert affected(root, {relative}, before=previous) == chain
    raw = paths['codepipeline'].read_bytes()
    paths['codepipeline'].write_text('invalid')
    rejected(lambda: dependencies(root), 'unsupported Model format')
    paths['codepipeline'].write_bytes(raw)
    paths['lambda'].unlink()
    assert ('dev', 'team', 'lambda') not in dependencies(root)



def check_template_snapshot(root):
    from validation_cache import input_scope
    import model.sources
    fixture(root, ('dev',))
    path = write_model(root / 'model/dev/team/config.properties', config_model())
    original = path.read_bytes()
    @input_scope
    def reuse():
        with patch.object(model.sources, '_read_model', wraps=model.sources._read_model) as parsed:
            first, second = load_model(path), load_model(path)
            assert first is second and parsed.call_count == 1
            with pytest.raises(TypeError):
                first.files[root / 'foreign'] = 'unrelated'
            with pytest.raises(TypeError):
                first.authoritative['desired.row.007-001.value'] = 'changed'
        path.write_text('invalid')
        assert load_model(path) is first
        path.write_bytes(original)
        assert load_model(path) is first
    reuse()
    path.write_text('invalid')
    rejected(lambda: load_model(path), 'unsupported Model format')
    path.write_bytes(original)



def check_creation(root):
    fixture(root)
    from model.sources import list_models
    path = root / 'model/dev/team/config.properties'
    assert list_models(root) == [] and not path.exists()
    write_model(path, config_model())
    expected = load_model(path).authoritative
    original = path.read_bytes()
    for _ in range(2):
        assert load_model(path).authoritative == expected and path.read_bytes() == original
    path.write_text(serialize({**expected, 'desired.resource.007.unknown': 'Unknown'}))
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    rejected(lambda: load_model(path), 'unknown Model field')
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}



def check_invalid(root):
    fixture(root, ('dev',))
    path = install_candidate(root, {'dev': role_model('dev', 2)})
    values = dict(load_model(path).authoritative)
    original = path.read_bytes()
    for bad in ({**values, 'desired.row.011-004.unknown': '1'},
                {key: value for key, value in values.items() if key != 'desired.row.011-004.value'},
                {**values, 'desired.row.099-004.property': 'IAM.Role.RoleName', 'desired.row.099-004.value': 'x', 'desired.row.099-004.comment': 'orphan'},
                {**values, 'observed.row.999-001.value': 'x'}):
        path.write_text(serialize(bad)); rejected(lambda: load_model(path))
    path.write_bytes(original)
    for value in ('a"b\\日本語=終', '', '<<not-reparsed>>', '${AWS::Region} {{resolve:ssm:literal}}',
                  '<<Missing>>', '<<#Name>>x<</Name>>', '<<^Name>>x<</Name>>', '<<>partial>>',
                  '<<&Name>>', '<<{Name}>>', '<<= x y =>>', '{{#Name}}', '{{>partial}}'):
        write_model(path, {**values, 'desired.row.011-004.value': value})
        assert load_model(path).authoritative['desired.row.011-004.value'] == value
    rejected(lambda: serialize({**values, 'desired.row.011-004.value': 'x\ninjected.key=bad'}))
    path.write_bytes(original)
    path.unlink(); rejected(lambda: read_model(path)); path.write_bytes(original)
    path.write_text('desired.service.legacy.serviceId=legacy\n')
    rejected(lambda: read_model(path), 'unsupported Model format')



def check_sync(root):
    with patch.object(sync_runtime, 'sync', wraps=sync_runtime.sync) as calls:
        fixture(root, ('dev',)); path = write_fixture(root, 'dev', 'config', config_model())
        view = root / 'docs/designs/dev/team/config.md'
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and p.suffix != '.pyc'}
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, 'dev', 'team', services=['config']) == 0
            assert sync_runtime.sync(root, False, 'dev', 'team', services=['config']) == 0
        assert all(p.read_bytes() == value for p, value in before.items())
        # Observation publication rights/IMPORT protection are exercised by the managed observation IT.
        values = dict(load_model(path).authoritative)
        values['observed.row.007-009.value'] = '`new-id`'
        write_model(path, values)
        with redirect_stdout(io.StringIO()):
            assert sync_runtime.sync(root, True, 'dev', 'team', services=['config']) == 0
        assert load_model(path).authoritative['observed.row.007-009.value'] == '`new-id`'
        for newline, final in (('\n', True), ('\n', False), ('\r\n', True), ('\r\n', False)):
            original = view.read_text(); content = original.rstrip('\n').replace('\n', newline) + (newline if final else '')
            view.write_bytes(content.encode())
            with redirect_stdout(io.StringIO()):
                assert sync_runtime.sync(root, True, 'dev', 'team', services=['config']) == 0
            assert view.read_bytes() == content.encode()
        saved = path.read_bytes(); real = sync_runtime.validate_candidates
        def drift(*args, **kwargs):
            real(*args, **kwargs); path.write_bytes(saved + b'# changed\n')
        with patch.object(sync_runtime, 'validate_candidates', drift), redirect_stdout(io.StringIO()):
            rejected(lambda: sync_runtime.sync(root, True, 'dev', 'team', services=['config']), 'inputs changed')
        assert path.read_bytes() == saved + b'# changed\n'
        path.write_bytes(saved)
    assert calls.call_count == 9



def check_common_shape(root):
    fixture(root, ('dev',))
    path = root / 'model/dev/team/shared.properties'
    minimal = {'desired.resource.017.resourceType': 'S3.Bucket', 'desired.resource.017.logicalId': 'S3_Bucket_001', 'desired.resource.017.anchor': 'resource-S3_Bucket_001',
        'desired.service.identity.lastAllocated': '{"S3.Bucket":1}',
        'desired.row.017-023.property': 'S3.Bucket.BucketName', 'desired.row.017-023.value': '`fixed-name`', 'desired.row.017-023.comment': '名前',
        'desired.row.017-025.property': 'S3.Bucket.Tags', 'desired.row.017-025.value': '`{"Items":[1,3],"Value":"","Keep":null}`',
        'desired.row.017-025.comment': '明示した配列と型', 'desired.note.bucket.text': '[S3_Bucket_001](shared.md#resource-S3_Bucket_001)'}
    write_model(path, minimal)
    assert load_model(path).authoritative == minimal
    from model.sources import FileReads
    from model.operations import CandidateReads
    missing = {key: value for key, value in minimal.items() if key != 'desired.resource.017.logicalId'}
    with pytest.raises(ValueError):
        load_model(path, CandidateReads(FileReads(), {path: serialize(missing)}))
    assert not any(key.startswith('desired.row.017-024.') for key in minimal)
    full = {**minimal, 'desired.resource.017.logicalId': 'S3_Bucket_001',
        'desired.row.017-024.property': 'S3.BucketPolicy.PolicyDocument', 'desired.row.017-024.value': '[policy.json](shared/policy.json)',
        'desired.row.017-024.comment': '明示した権限', 'desired.row.017-024.document': '{"Statement":[{"Resource":"*"}]}' }
    write_model(path, full)
    assert json.loads(load_model(path).authoritative['desired.row.017-024.document']) == {'Statement': [{'Resource': '*'}]}
    assert load_model(path).authoritative['desired.resource.017.logicalId'] == 'S3_Bucket_001'
    full.update({'desired.row.017-023.value': '[S3_Bucket_001](shared.md#resource-S3_Bucket_001)',
        'desired.note.bucket.text': '[S3_Bucket_001](shared.md#resource-S3_Bucket_001)', 'desired.row.017-025.value': '`{"Drop":null,"Items":[0,1,2,3],"Value":false,"Keep":null}`',
        'desired.row.017-024.document': '{"Statement":[{"Resource":"*"},{"Resource":"explicit-target"}]}'})
    write_model(path, full)
    model = load_model(path)
    assert model.authoritative == full
    assert json.loads(model.authoritative['desired.row.017-025.value'][1:-1]) == {'Drop': None, 'Items': [0, 1, 2, 3], 'Value': False, 'Keep': None}
    assert json.loads(model.authoritative['desired.row.017-024.document'])['Statement'][1]['Resource'] == 'explicit-target'
    assert 'desired.row.017-024.artifactSha256' in model.values and 'desired.row.017-024.artifactSha256' not in model.authoritative
    for bad in ({**full, 'desired.row.017-025.value': '`{"a":1,"a":2}`'},
                {key: value for key, value in full.items() if key != 'desired.row.017-024.property'},
                {**full, 'desired.row.017-024.artifactSha256': 'stale'}):
        try:
            raw = serialize(bad); path.write_text(raw); load_model(path)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid explicit shape accepted')



def main():
    return run(__file__, message="model_templates: PASS")


if __name__ == '__main__':
    raise SystemExit(main())

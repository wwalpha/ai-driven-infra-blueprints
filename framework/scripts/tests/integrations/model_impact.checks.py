#!/usr/bin/env python3
"""Saved reference graph, explicit environment isolation and resource change boundaries."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
import json
import shutil
import subprocess
import tempfile
from model.impact import affected, dependencies
from model.sources import FileReads, load_model, design_source_digest
from model.format import serialize
from support.model_sources import write_model
from support.producer_identifier_reference_fixtures import setup, resource, reference, dependency_hashes
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def git(root, *arguments):
    result = subprocess.run(['git', *arguments], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def producer(root, service, kind, name_property, env='dev'):
    values = {}
    for number in (1, 2):
        rid = f'{number:03}'
        values.update(resource(rid, kind, service + '-' + rid, [
            (name_property, '`' + env + '-name' + str(number) + '`'),
            ('Setting', '`{"trust":["old"]}`')]))
        values[f'desired.resource.{rid}.resourceMode'] = 'CREATE'
    return write_model(root / 'model' / env / 'team' / (service + '.properties'), values)


def consumer(root, service, producer_service, kind, target='001', *, mode='name', fixed=False,
             optional=False, env='dev'):
    name_property = {'IAM.Role': 'RoleName', 'S3.Bucket': 'BucketName',
                     'Lambda.Function': 'FunctionName', 'EC2.VPC': 'Name', 'CodeBuild.Project': 'Name'}[kind]
    prop = 'VpcId' if mode == 'identifier' else name_property
    value = ('[fixed-label](' + producer_service + '.md#' + producer_service + '-' + target + ')' if mode == 'link'
             else '`vpc-first`' if mode == 'identifier' else '`' + env + '-name' + str(int(target)) + '`')
    values = resource('005', 'CodeBuild.Project', service + '-005', [('Name', 'fixed-name')])
    values['desired.resource.005.resourceMode'] = 'CREATE'
    if not optional:
        values.update({'desired.row.005-002.property': 'CodeBuild.Project.Description',
                       'desired.row.005-002.comment': '保存済み参照', 'desired.row.005-002.value': value})
        values.update(reference('producer', 'desired.row.005-002.value', value, producer_service, target,
                                kind, mode=mode, prop=kind + '.' + prop if mode != 'link' else None,
                                environment=env, label='fixed' if mode == 'link' else 'none'))
        if not fixed:
            values['desired.row.005-001.value'] = value
            values.update(reference('name', 'desired.row.005-001.value', value, producer_service, target,
                                    kind, mode=mode, prop=kind + '.' + prop if mode != 'link' else None,
                                    environment=env, label='fixed' if mode == 'link' else 'none'))
    return write_model(root / 'model' / env / 'team' / (service + '.properties'), values)


def baseline(root):
    git(root, 'init'); git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'add', 'project.json', 'model'); git(root, 'commit', '-m', 'Baseline')
    return git(root, 'rev-parse', 'HEAD')


def change(path, rid, key, value):
    values = dict(load_model(path, FileReads()).authoritative)
    field = '001' if key == 'Name' else '002'
    values[f'desired.row.{rid}-{field}.value'] = ('`' + json.dumps(value, separators=(',', ':')) + '`'
                                               if not isinstance(value, str) else '`' + value + '`')
    write_model(path, values)


def entry(service, env='dev'):
    return env, 'team', service


@it_case
def check_precision(root, service, kind, name_property):
    source = producer(root, service, kind, name_property)
    for name, target, fixed in [('uses-first', '001', False), ('uses-second', '002', False),
                                 ('fixed-export', '001', True)]:
        consumer(root, name, service, kind, target, fixed=fixed)
    consumer(root, 'stops-here', 'fixed-export', 'CodeBuild.Project', '005')
    consumer(root, 'continues', 'uses-first', 'CodeBuild.Project', '005')
    consumer(root, 'disabled', service, kind, optional=True)
    baseline(root)
    relative = source.relative_to(root)
    path = root / 'model/dev/team/uses-first.properties'
    digest, hashes, saved = design_source_digest(path), dependency_hashes(path), path.read_bytes()
    change(source, '001', 'Setting', {'trust': ['new']})
    expected = {entry(s) for s in (service, 'uses-first', 'uses-second', 'fixed-export', 'stops-here', 'continues')}
    assert affected(root, {relative}) == expected
    assert design_source_digest(path) == digest and dependency_hashes(path) != hashes
    assert path.read_bytes() == saved
    git(root, 'add', str(relative))
    change(source, '001', 'Setting', {'trust': ['other']})
    assert affected(root, {relative}) == expected
    from support.validator import MODULE
    validator = MODULE.Validator(root, {entry(service)})
    validator.accounts = {('dev', 'team'): {}}
    validator.changed_paths = {relative.as_posix()}
    validator.check_validation_scope()
    assert any('affected validation scope' in error for error in validator.errors), validator.errors
    change(source, '001', 'Name', 'renamed')
    assert affected(root, {relative}) == expected
    assert path.read_bytes() == saved and load_model(path).warnings
    git(root, 'add', 'model'); git(root, 'commit', '-m', 'Committed change')
    assert affected(root, {relative}) == expected


@it_case
def check_identity_and_deletion(root):
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    target = consumer(root, 'uses-identity', 'iam', 'IAM.Role')
    baseline(root)
    with tempfile.TemporaryDirectory() as directory:
        before = Path(directory)
        shutil.copytree(root / 'model', before / 'model')
        shutil.copyfile(root / 'project.json', before / 'project.json')
        values = dict(load_model(source).authoritative)
        values = {key.replace('.001.', '.003.').replace('.001-', '.003-'): value for key, value in values.items()}
        write_model(source, values)
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam'), entry('uses-identity')}
        assert not load_model(target).warnings  # Renumbering entries preserves logical identity.
        values = {key: value for key, value in values.items() if not key.startswith(('desired.resource.003.', 'desired.row.003-'))}
        write_model(source, values)
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam'), entry('uses-identity')}
        source.unlink()
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam'), entry('uses-identity')}
        # Removing the last current usage still retains its old incoming scope for final validation.
        values = dict(load_model(target).authoritative)
        write_model(target, {key: value for key, value in values.items() if not key.startswith('desired.reference.')})
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam'), entry('uses-identity')}


@it_case
def check_shared_environments(root):
    dev = producer(root, 'iam', 'IAM.Role', 'RoleName')
    stg = producer(root, 'iam', 'IAM.Role', 'RoleName', env='stg')
    for env in ('dev', 'stg'):
        consumer(root, 'build', 'iam', 'IAM.Role', env=env)
    baseline(root)
    saved = dev.read_bytes()
    change(stg, '001', 'Setting', {'trust': ['sso-a', 'sso-b']})
    assert affected(root, {stg.relative_to(root)}) == {entry('iam', 'stg'), entry('build', 'stg')}
    change(stg, '001', 'Name', 'stg-renamed')
    assert affected(root, {stg.relative_to(root)}) == {entry('iam', 'stg'), entry('build', 'stg')}
    assert dev.read_bytes() == saved


@it_case
def check_identifiers(root):
    source = producer(root, 'vpc', 'EC2.VPC', 'Name')
    values = dict(load_model(source).authoritative)
    for rid, identifier in [('001', 'first'), ('002', 'second')]:
        values.update({f'desired.row.{rid}-003.property': 'EC2.VPC.VpcId',
                       f'desired.row.{rid}-003.comment': '識別子', f'desired.row.{rid}-003.value': 'PENDING_DEPLOY',
                       f'observed.row.{rid}-003.value': '`vpc-' + identifier + '`'})
    write_model(source, values)
    paths = [consumer(root, 'by-id', 'vpc', 'EC2.VPC', mode='identifier'),
             consumer(root, 'by-name', 'vpc', 'EC2.VPC'), consumer(root, 'by-anchor', 'vpc', 'EC2.VPC', mode='link')]
    baseline(root)
    saved = [path.read_bytes() for path in paths]
    digest, hashes = design_source_digest(source), dependency_hashes(paths[0])
    values['observed.row.002-003.value'] = '`vpc-second-new`'
    write_model(source, values)
    expected = {entry(s) for s in ('vpc', 'by-id', 'by-name', 'by-anchor')}
    assert affected(root, {source.relative_to(root)}) == expected
    values['observed.row.001-003.value'] = '`vpc-first-new`'
    write_model(source, values)
    assert affected(root, {source.relative_to(root)}) == expected
    assert design_source_digest(source) == digest and dependency_hashes(paths[0]) != hashes
    del values['observed.row.001-003.value']; write_model(source, values)
    assert any('unobserved' in warning['message'] for warning in load_model(paths[0]).warnings)
    assert [path.read_bytes() for path in paths] == saved


@it_case
def check_type_and_unknown(root):
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    target = consumer(root, 'build', 'iam', 'IAM.Role')
    baseline(root)
    text = source.read_text(); source.write_text(text.replace('IAM.Role', 'IAM.User').replace('IAM_Role', 'IAM_User'))
    assert affected(root, {source.relative_to(root)}) == {entry('iam'), entry('build')}
    assert any('absent' in warning['message'] for warning in load_model(target).warnings)
    source.write_text(text + 'desired.resource.001.resourceType=IAM.Role\n')
    try:
        affected(root, {source.relative_to(root)})
    except ValueError as error:
        assert 'duplicate' in str(error), str(error)
    else:
        raise AssertionError('malformed authority must stop incoming analysis')
    source.unlink()
    assert affected(root, {source.relative_to(root)}) == {entry('iam'), entry('build')}
    assert load_model(target).warnings


@it_case
def check_import_scope(root):
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    consumer(root, 'build', 'iam', 'IAM.Role')
    baseline(root)
    for key, value in [('Setting', {'trust': ['new']}), ('Name', 'renamed')]:
        change(source, '001', key, value)
        assert affected(root, {source.relative_to(root)}) == {entry('iam'), entry('build')}


@it_case
def check_selection(root):
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    unused = producer(root, 'unused', 'IAM.Role', 'RoleName')
    target = consumer(root, 'build', 'iam', 'IAM.Role', '002', fixed=True)
    baseline(root)
    change(source, '001', 'Name', 'unselected-name')
    assert affected(root, {source.relative_to(root)}) == {entry('iam'), entry('build')}
    change(unused, '001', 'Name', 'unused-name')
    assert affected(root, {unused.relative_to(root)}) == {entry('unused')}
    change(source, '002', 'Name', 'selected-name')
    assert affected(root, {source.relative_to(root)}) == {entry('iam'), entry('build')}
    from model.importing.scope import restrict, read_consumers
    with restrict(entry('iam')), read_consumers({entry('iam'), entry('build')}):
        assert set(dependencies(root)) == {entry('iam'), entry('build')}
    assert target.read_bytes() and len([key for key in load_model(target).authoritative if key.startswith('desired.resource.') and key.endswith('.resourceType')]) == 1


@it_case
def check_cycles(root):
    left = consumer(root, 'alpha', 'beta', 'CodeBuild.Project', '005')
    right = consumer(root, 'beta', 'alpha', 'CodeBuild.Project', '005')
    baseline(root)
    saved = right.read_bytes()
    left.write_text(left.read_text() + '# changed\n')
    assert affected(root, {left.relative_to(root)}) == {entry('alpha'), entry('beta')}
    assert right.read_bytes() == saved


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    checks = [(service, check_precision, (service, kind, prop)) for service, kind, prop in [
        ('iam', 'IAM.Role', 'RoleName'), ('s3', 'S3.Bucket', 'BucketName'), ('lambda', 'Lambda.Function', 'FunctionName')]]
    checks += [(label, check, ()) for label, check in [('identity', check_identity_and_deletion),
        ('shared', check_shared_environments), ('identifiers', check_identifiers), ('type', check_type_and_unknown),
        ('import', check_import_scope), ('selection', check_selection), ('cycles', check_cycles)]]
    for label, check, args in checks:
        path = root / label
        setup(path, ('iam', 's3', 'lambda', 'vpc', 'codebuild'), ('IAM.Role', 'S3.Bucket', 'Lambda.Function', 'EC2.VPC', 'CodeBuild.Project'), environments=('dev', 'stg'))
        check(path, *args)
print('PASS: saved Model reference impact, resource changes, snapshots and environments')

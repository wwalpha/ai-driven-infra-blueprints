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
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam')}
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
    revision = baseline(root)
    saved = right.read_bytes()
    left.write_text(left.read_text() + '# changed\n')
    assert affected(root, {left.relative_to(root)}) == {entry('alpha'), entry('beta')}
    assert right.read_bytes() == saved

    from import_guard import snapshots
    with snapshots(root, revision, {}) as (before, _):
        assert affected(root, {left.relative_to(root)}, before=before) == {entry('alpha')}
        values = dict(load_model(left).authoritative)
        values.update({'desired.row.005-003.property': 'CodeBuild.Project.Setting',
                       'desired.row.005-003.value': '`changed`', 'desired.row.005-003.comment': 'setting'})
        write_model(left, values)
        assert affected(root, {left.relative_to(root)}, before=before) == {entry('alpha'), entry('beta')}


@it_case
def check_resource_addition(root):
    from import_guard import snapshots
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    consumer(root, 'secretsmanager', 'iam', 'IAM.Role', '001')
    consumer(root, 's3', 'iam', 'IAM.Role', '002')
    revision = baseline(root)
    values = dict(load_model(source).authoritative)
    values.update(resource('003', 'IAM.Role', 'iam-003', [('RoleName', '`dev-name3`')]))
    values['desired.resource.003.resourceMode'] = 'CREATE'
    values['desired.service.identity.lastAllocated'] = '{"IAM.Role":3}'
    write_model(source, values)
    with snapshots(root, revision, {}) as (before, _):
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam')}
    consumer(root, 's3', 'iam', 'IAM.Role', '003')
    with snapshots(root, revision, {}) as (before, _):
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam'), entry('s3')}
        from model.format import split
        from sync_files import save_files
        parts = split(source, values, limit=12)
        save_files(parts)
        part = next(path for path in parts if path != source)
        assert affected(root, {part.relative_to(root)}, before=before) == {entry('iam'), entry('s3')}
        new_source = producer(root, 'new-service', 'IAM.Role', 'RoleName')
        assert affected(root, {new_source.relative_to(root)}, before=before) == {entry('new-service')}


@it_case
def check_resource_changes(root):
    from import_guard import snapshots
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    consumer(root, 'secretsmanager', 'iam', 'IAM.Role', '001')
    consumer(root, 's3', 'iam', 'IAM.Role', '002')
    consumer(root, 'macie', 's3', 'CodeBuild.Project', '005')
    revision = baseline(root)
    original = dict(load_model(source).authoritative)
    paths = {source.relative_to(root)}
    with snapshots(root, revision, {}) as (before, _):
        change(source, '001', 'Setting', {'trust': ['first']})
        assert affected(root, paths, before=before) == {entry('iam'), entry('secretsmanager')}
        write_model(source, original)
        change(source, '002', 'Setting', {'trust': ['second']})
        assert affected(root, paths, before=before) == {entry(s) for s in ('iam', 's3', 'macie')}
        change(source, '001', 'Setting', {'trust': ['first']})
        assert affected(root, paths, before=before) == {entry(s) for s in ('iam', 'secretsmanager', 's3', 'macie')}
        write_model(source, {key: value for key, value in original.items()
            if not key.startswith(('desired.resource.001.', 'desired.row.001-', 'display.resource.001.'))})
        assert affected(root, paths, before=before) == {entry('iam'), entry('secretsmanager')}
        write_model(source, original)
        target = consumer(root, 'secretsmanager', 'iam', 'IAM.Role', '002')
        assert affected(root, {target.relative_to(root)}, before=before) == {entry('secretsmanager')}
        change(source, '001', 'Setting', {'trust': ['old reference']})
        change(source, '002', 'Setting', {'trust': ['new reference']})
        assert affected(root, paths | {target.relative_to(root)}, before=before) == {entry(s) for s in ('iam', 'secretsmanager', 's3', 'macie')}
        source.unlink()
        assert affected(root, paths, before=before) == {entry(s) for s in ('iam', 'secretsmanager', 's3', 'macie')}


@it_case
def check_semantic_boundaries(root):
    from import_guard import snapshots
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    target = consumer(root, 'build', 'iam', 'IAM.Role', '001')
    values = dict(load_model(source).authoritative)
    values['observed.row.001-001.value'] = '`first`'
    values['observed.row.002-001.value'] = '`second`'
    write_model(source, values)
    revision = baseline(root)
    with snapshots(root, revision, {}) as (before, _):
        source.write_text(source.read_text() + '# comment\n\n')
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam')}
        changed = dict(values)
        changed['desired.row.001-001.comment'] = '説明だけ'
        changed['display.resource.001.label'] = '表示だけ'
        write_model(source, changed)
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam')}
        changed = {key.replace('.001.', '.007.').replace('.001-', '.007-'): value for key, value in values.items()}
        write_model(source, changed)
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam')}
        write_model(source, values)
        changed = dict(values); changed['observed.row.002-001.value'] = '`second-new`'
        write_model(source, changed)
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam')}
        changed['observed.row.001-001.value'] = '`first-new`'
        write_model(source, changed)
        assert affected(root, {source.relative_to(root)}, before=before) == {entry('iam'), entry('build')}
        write_model(source, values)
        assert affected(root, {'project.json'}, before=before) == {entry('iam'), entry('build')}
        # A changed Consumer referencing a different service is a separate seed in the union.
        target_values = dict(load_model(target).authoritative)
        target_values.update({'desired.row.005-003.property': 'CodeBuild.Project.Setting',
            'desired.row.005-003.value': '`{"new":true}`', 'desired.row.005-003.comment': 'new setting'})
        write_model(target, target_values)
        assert affected(root, {source.relative_to(root), target.relative_to(root)}, before=before) == {entry('iam'), entry('build')}


@it_case
def check_stack_context_and_fallback(root):
    from import_guard import snapshots
    from model.impact import analyze
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    target = consumer(root, 'build', 'iam', 'IAM.Role')
    values = dict(load_model(source).authoritative)
    stack_values = {'desired.stack.primary.deployOrder': '1', 'desired.stack.other.deployOrder': '2',
                   'desired.stack.primary.name': 'primary', 'desired.stack.primary.placementName': 'primary',
                   'desired.stack.primary.template': 'main.yaml', 'desired.stack.primary.parameters': 'params.json',
                   'desired.stack.other.name': 'other', 'desired.stack.other.placementName': 'other',
                   'desired.stack.other.template': 'other.yaml', 'desired.stack.other.parameters': 'other.json'}
    stack_source = write_model(root / 'model/dev/team/stacks.properties', stack_values)
    consumer_values = dict(load_model(target).authoritative)
    consumer_values.update({'desired.row.005-003.property': 'CodeBuild.Project.Description',
        'desired.row.005-003.comment': 'Stack', 'desired.row.005-003.value': 'primary',
        **{'desired.reference.stack.' + field: value for field, value in {
            'consumerKey': 'desired.row.005-003.value', 'text': 'primary', 'occurrence': '1',
            'producerKind': 'stack', 'producerScope': 'dev/team/stacks', 'producerId': 'primary',
            'property': 'name', 'format': 'name', 'labelPolicy': 'none'}.items()},
        'desired.row.005-004.property': 'CodeBuild.Project.Description',
        'desired.row.005-004.comment': 'Context', 'desired.row.005-004.value': '111111111111',
        **{'desired.reference.context.' + field: value for field, value in {
            'consumerKey': 'desired.row.005-004.value', 'text': '111111111111', 'occurrence': '1',
            'producerKind': 'context', 'producerScope': 'dev/team', 'contextProperty': 'executionAccountId',
            'format': 'literal', 'labelPolicy': 'none'}.items()}})
    write_model(target, consumer_values)
    revision = baseline(root)
    with snapshots(root, revision, {}) as (before, _):
        stack_values['desired.stack.other.name'] = 'other-new'; write_model(stack_source, stack_values)
        assert affected(root, {stack_source.relative_to(root)}, before=before, raw=True) == {entry('stacks')}
        stack_values['desired.stack.primary.name'] = 'primary-new'; write_model(stack_source, stack_values)
        assert affected(root, {stack_source.relative_to(root)}, before=before, raw=True) == {entry('stacks'), entry('build')}
        from model.references import usages
        from model.sources import raw_model
        assert any(u.producer_kind == 'context' for u in usages(raw_model(target)))
        assert affected(root, {'project.json'}, before=before, raw=True) == {entry('iam'), entry('build'), entry('stacks')}
        stack_values['desired.stack.primary.name'] = 'primary'; stack_values['desired.stack.other.name'] = 'other'
        write_model(stack_source, {key: value for key, value in stack_values.items() if not key.startswith('desired.stack.primary.')})
        assert affected(root, {stack_source.relative_to(root)}, before=before, raw=True) == {entry('stacks'), entry('build')}
        write_model(stack_source, stack_values)
        values['desired.deployment.maxConcurrentStacks'] = '2'
        write_model(source, values)
        assert affected(root, {source.relative_to(root)}, before=before, raw=True) == {entry('iam'), entry('build')}
        del values['desired.deployment.maxConcurrentStacks']
        write_model(source, values)
        consumer_values['desired.reference.producer.producerLogicalId'] = 'IAM_Role_999'
        consumer_values['desired.reference.name.producerLogicalId'] = 'IAM_Role_999'
        write_model(target, consumer_values)
        change(source, '002', 'Setting', {'new': True})
        impact = analyze(root, {source.relative_to(root)}, before=before, raw=True)
        assert impact.services == {entry('iam'), entry('build')}
        assert any(reason['reason'] == 'unresolved producer' for reason in impact.reasons)
    # The old authority may be syntactically broken; its correction is never rejected.
    source.write_text('broken old Model')
    revision = baseline(root)
    source.write_text(serialize(values), encoding='utf-8')
    with snapshots(root, revision, {}) as (before, _):
        impact = analyze(root, {source.relative_to(root)}, before=before, raw=True)
        assert impact.services == {entry('iam'), entry('build')}
        assert any('uncomparable' in reason['reason'] for reason in impact.reasons)


@it_case
def check_task_snapshot_routes(root):
    from unittest.mock import patch
    from import_guard import require_import_changes
    from model.impact import task_impact
    from model.operations import validate_candidates
    from model.format import split
    from validation_cache import input_context
    from task_contract import selected_task
    from support.worktree_task_fixtures import cli
    from support.validator import MODULE
    source = producer(root, 'iam', 'IAM.Role', 'RoleName')
    consumer(root, 'secretsmanager', 'iam', 'IAM.Role', '001')
    consumer(root, 's3', 'iam', 'IAM.Role', '002')
    write(root / '.gitignore', '/.worktrees/\ntasks/**\nissues/**\n')
    baseline(root)
    git(root, 'add', '.gitignore'); git(root, 'commit', '-m', 'Fixture lifecycle ignores')
    state = cli(root, 'create', 'precision-routes')
    target = Path(state['worktree'])
    source = target / source.relative_to(root)
    values = dict(load_model(source).authoritative)
    values.update(resource('003', 'IAM.Role', 'iam-003', [('RoleName', '`dev-name3`')]))
    values['desired.resource.003.resourceMode'] = 'CREATE'
    values['desired.service.identity.lastAllocated'] = '{"IAM.Role":3}'
    output = split(source, values)
    paths = {p.relative_to(target).as_posix() for p in output}
    name = state['task_file']
    listed = '\n'.join('- `' + path + '`' for path in sorted(paths | {name}))
    text = ('## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `update`\n'
            '## Validation scope\n- `dev/team/iam`\n## Modified files\n' + listed + '\n## Allowed paths\n' + listed + '\n')
    write(target / name, text)
    write(target / 'issues/dev/team/issues.md', '### secretsmanager\n1. Unrelated secret issue\n')
    with selected_task(target, name):
        with input_context():
            candidate = task_impact(target, paths, output=output)
            assert candidate.services == {entry('iam')}
            assert not validate_candidates(target, paths, output, {entry('iam')})
            require_import_changes(target, output=output)
        # Real ordinary save uses a one-use managed capability and its publication transaction.
        from model.adapters.task import edit_write_context
        from model.operations import prepare_edit, publish_edit
        with edit_write_context(target, {entry('iam')}, name) as context:
            from model.sources import edit_base
            snapshot = edit_base(source, context.snapshot)
            publish_edit(prepare_edit(snapshot, output, context), context)
        saved_bytes = source.read_bytes()
        write(target / name, text.replace('- `dev/team/iam`\n', '- `dev/team/iam`\n- `dev/team/secretsmanager`\n'))
        try:
            with edit_write_context(target, {entry('iam')}, name) as context:
                snapshot = edit_base(source, context.snapshot)
                publish_edit(prepare_edit(snapshot, {source: source.read_text() + '# extra declared scope\n'}, context), context)
        except ValueError as error:
            assert 'issue' in str(error).lower()
        else:
            raise AssertionError('save must gate the full declared scope')
        assert source.read_bytes() == saved_bytes
        write(target / name, text)
        for stage in ('unstaged', 'staged', 'committed'):
            if stage == 'staged':
                git(target, 'add', 'model')
            elif stage == 'committed':
                git(target, 'commit', '-m', 'Task addition')
            with input_context():
                from model.impact_graph import Graph
                from import_guard import archive_sources
                with patch.object(Graph, 'include', autospec=True, side_effect=Graph.include) as include, patch(
                        'import_guard.archive_sources', wraps=archive_sources) as archive:
                    saved = task_impact(target)
                    require_import_changes(target)
                    validator = MODULE.Validator(target, {entry('iam')}, write=True)
                    validator.accounts = {('dev', 'team'): {}}
                    validator.task.permission_paths = paths
                    validator.check_validation_scope()
                    assert saved.services == candidate.services == validator.task.impact == validator.task.design_impact
                    assert not validator.errors, validator.errors
                    from support.validator import load
                    sync_main = load('sync-model')
                    with patch.object(sync_main, 'run_generation', return_value=0) as generation:
                        assert sync_main.main(['--repository-root', str(target), '--write',
                            '--scope', 'dev/team/iam', '--jobs', '1']) == 0
                    assert generation.call_args.args[:2] == (target, {entry('iam')})
                    assert include.call_count == 2 and archive.call_count == 1
            from issue_gate import require_no_issues
            require_no_issues(target, {entry('iam')})
            try:
                require_no_issues(target, {entry('iam'), entry('secretsmanager')})
            except ValueError as error:
                assert 'issue' in str(error).lower()
            else:
                raise AssertionError('declared extra scope must retain its Issue Gate')
        write(target / 'issues/dev/team/issues.md', '### iam\n1. Related role issue\n')
        try:
            with edit_write_context(target, {entry('iam')}, name):
                raise AssertionError('related Issue must stop save authority')
        except ValueError as error:
            assert 'issue' in str(error).lower()
        write(target / 'issues/dev/team/issues.md', '未解決issueなし\n')
        # Final-candidate base is explicit and agrees with the registered Task baseline.
        from types import SimpleNamespace
        final = SimpleNamespace(base_commit=state['start'], changed_paths=frozenset(paths), scope=frozenset({entry('iam')}))
        with input_context():
            require_import_changes(target, final_candidate=final)
            assert task_impact(target, paths, base=final.base_commit).services == candidate.services


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    checks = [(service, check_precision, (service, kind, prop)) for service, kind, prop in [
        ('iam', 'IAM.Role', 'RoleName'), ('s3', 'S3.Bucket', 'BucketName'), ('lambda', 'Lambda.Function', 'FunctionName')]]
    checks += [(label, check, ()) for label, check in [('identity', check_identity_and_deletion),
        ('shared', check_shared_environments), ('identifiers', check_identifiers), ('type', check_type_and_unknown),
        ('import', check_import_scope), ('selection', check_selection), ('cycles', check_cycles), ('addition', check_resource_addition), ('changes', check_resource_changes),
        ('semantics', check_semantic_boundaries), ('stacks', check_stack_context_and_fallback),
        ('routes', check_task_snapshot_routes)]]
    for label, check, args in checks:
        path = root / label
        setup(path, ('iam', 's3', 'lambda', 'vpc', 'codebuild'), ('IAM.Role', 'S3.Bucket', 'Lambda.Function', 'EC2.VPC', 'CodeBuild.Project'), environments=('dev', 'stg'))
        check(path, *args)
print('PASS: saved Model reference impact, resource changes, snapshots and environments')

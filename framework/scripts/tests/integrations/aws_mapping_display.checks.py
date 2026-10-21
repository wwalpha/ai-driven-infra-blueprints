#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.aws_mapping_display_fixtures import *

from support.it_workspace import copy_framework

@it_case
def check(root):
    seed = root / 'seed'
    copy_framework(seed / 'framework')
    (seed / 'project.json').write_text(json.dumps({'projectName': 'fixture', 'targets': [
        {'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')

    def variant(name, changes):
        target = root / name
        shutil.copytree(seed, target)
        for service, kind, prop, display in changes:
            change(target, service, kind, prop, **display)
        return target

    values = fixture('cloudwatch-logs', 'Logs.LogGroup', 'cwlogs-app-dev-flow', [
        ('LogGroupName', '`cwlogs-app-dev-flow`'), ('RetentionInDays', '`30`'), ('DeletionProtectionEnabled', '`false`')])
    for name in ('baseline', 'rename', 'hidden', 'hidden-name', 'hidden-kms'):
        changes = []
        if name != 'baseline':
            changes.append(('cloudwatch-logs', 'Logs.LogGroup', 'RetentionInDays', {'name': 'KeepDays'}))
        if name.startswith('hidden'):
            changes.append(('cloudwatch-logs', 'Logs.LogGroup', 'RetentionInDays', {'show': False}))
        if name == 'hidden-name':
            changes.append(('cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName', {'show': False}))
        if name == 'hidden-kms':
            changes.append(('cloudwatch-logs', 'Logs.LogGroup', 'KmsKeyId', {'show': False}))
        current = variant(name, changes)
        path = current / 'docs/designs/dev/123456789012/cloudwatch-logs.md'
        source = current / 'model/dev/123456789012/cloudwatch-logs.properties'
        write_model(source, values)
        saved = snapshot_model(source)
        path.parent.mkdir(parents=True, exist_ok=True)

        def verify(value=values):
            path.write_text(markdown_for(path, value, current), encoding='utf-8')
            assert path.read_text() == markdown_for(path, value, current)
            validate_views(current, current, [path], {path: value})
            return path.read_text(encoding='utf-8')

        document = verify()
        if name == 'rename':
            assert '| KeepDays | `30` |' in document
        if name.startswith('hidden'):
            assert 'KeepDays' not in document and 'RetentionInDays' not in document
            assert values['desired.row.007-012.value'] == '`30`'
        if name == 'hidden':
            path.write_text(document.replace('| 2 | DeletionProtectionEnabled', '| 2 | KeepDays | `30` | 不正な表示 |\n| 3 | DeletionProtectionEnabled'), encoding='utf-8')
            try:
                validate_views(current, current, [path], {path: values})
            except ValueError as error:
                assert 'must not be displayed' in str(error)
            else:
                raise AssertionError('hidden row accepted')
            invalid = {**values, 'desired.row.007-012.value': '`invalid-days`'}
            try:
                verify(invalid)
            except ValueError as error:
                assert 'schema violation' in str(error), str(error)
            else:
                raise AssertionError('hidden literal escaped schema validation')
        if name == 'hidden-name':
            assert '| LogGroupName |' not in document
            missing = {key: value for key, value in values.items() if not key.startswith('desired.row.007-011.')}
            try:
                markdown_for(path, missing, current)
            except ValueError as error:
                assert 'nameless independent resource' in str(error)
            else:
                raise AssertionError('hidden required property was not required')
        if name == 'hidden-kms':
            bad_reference = {**values, 'desired.row.007-014.property': 'Logs.LogGroup.KmsKeyId',
                             'desired.row.007-014.value': '[missing](kms.md#kms-missing)',
                             'desired.row.007-014.comment': '非表示でも参照を検証する'}
            path.write_text(markdown_for(path, bad_reference, current), encoding='utf-8')
            findings = validate_views(current, current, [path], {path: bad_reference})
            assert not findings.errors
            assert any('broken design link' in warning['message'] for warning in findings.warnings)
        assert snapshot_model(source) == saved

    config = fixture('config', 'Config.ConfigurationRecorder', 'default', [
        ('Name', '`default`'), ('RoleARN', 'Pending'), ('RecordingGroup.ResourceTypes', '`["AWS::S3::Bucket","AWS::EC2::VPC"]`')])
    for name in ('RoleName', 'RecorderRole', 'hidden-role'):
        current = variant(name, [('config', 'Config.ConfigurationRecorder', 'RoleARN',
                                 {'show': False} if name == 'hidden-role' else {'name': name}),
                                ('config', 'Config.ConfigurationRecorder', 'RecordingGroup.ResourceTypes', {'name': 'SelectedTypes'})])
        config_path = current / 'docs/designs/dev/123456789012/config.md'
        config_path.parent.mkdir(parents=True)
        if name == 'hidden-role':
            missing = {key: value for key, value in config.items() if not key.startswith('desired.row.007-012.')}
            try:
                markdown_for(config_path, missing, current)
            except ValueError as error:
                assert 'required provider schema property missing' in str(error)
            else:
                raise AssertionError('hidden required RoleARN was not validated')
        else:
            document = markdown_for(config_path, config, current)
            assert f'| {name} | Pending |' in document and 'SelectedTypes[1]' in document
            config_path.write_text(document, encoding='utf-8')
            from design_layout import expanded_display_rows
            assert any("Config.ConfigurationRecorder.RoleARN | Pending" in line for line in expanded_display_rows(document.splitlines(), current))
            assert document == markdown_for(config_path, config, current)
    from security_group_tables import GROUP_COMMENTS
    sg = fixture('security-group', 'EC2.SecurityGroup', 'sg-app-dev-flow', [
        ('Id', '[Fixture](#security-group-sg-app-dev-flow)'), ('GroupDescription', '`flow`'),
        ('GroupName', '`sg-app-dev-flow`'), ('VpcId', '`vpc-00000000000000001`')])
    for identity, row in entries(sg, 'desired.row.'):
        sg['desired.row.' + identity + '.comment'] = GROUP_COMMENTS[row['property'].removeprefix('EC2.SecurityGroup.')]
    for key in ('property', 'comment'):
        sg['observed.row.007-011.' + key] = sg['desired.row.007-011.' + key]
    sg['observed.row.007-011.value'] = 'sg-00000000000000001'
    for visible in (True, False):
        current = variant('sg-' + str(visible), [('security-group', 'EC2.SecurityGroup', 'GroupDescription', {'name': 'Purpose', 'show': visible})])
        sg_path = current / 'docs/designs/dev/123456789012/security-group.md'
        sg_path.parent.mkdir(parents=True)
        document = markdown_for(sg_path, sg, current)
        assert ('| Purpose |' in document) == visible
        sg_path.write_text(document, encoding='utf-8')
        from design_layout import expanded_design
        assert expanded_design(document.splitlines(), root=current)[0]
        assert document == markdown_for(sg_path, sg, current)
    # A grouped identity can suppress its display unit without deleting the Model child.
    current = variant('repository', [])
    repository = fixture('codecommit', 'CodeCommit.Repository', 'fixture-repo', [
        ('RepositoryName', '`fixture-repo`'), ('RepositoryId', '`kept-hidden-id`')])
    repository_path = current / 'docs/designs/dev/123456789012/codecommit.md'
    repository_path.parent.mkdir(parents=True)
    repository_path.write_text(markdown_for(repository_path, repository, current), encoding='utf-8')
    assert 'kept-hidden-id' not in repository_path.read_text(encoding='utf-8')
    write_model(current / 'model/dev/123456789012/codecommit.properties', repository)
    validate_views(current, current, [repository_path], {repository_path: repository})
    assert 'RepositoryId' not in repository_path.read_text()
    assert repository['desired.row.007-012.value'] == '`kept-hidden-id`'
    print('P5 grouped displays: PASS (SG basic rename/hide, grouped identity projection; formal source retained)')
    print('P5 display: PASS (independent static definitions; rename/reverse, hidden/required/typed/link validation, Config RoleARN, ordered arrays, no source writes)')


if __name__ == '__main__':
    with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
        with TemporaryDirectory(prefix='mapping-display-') as directory:
            check(Path(directory))


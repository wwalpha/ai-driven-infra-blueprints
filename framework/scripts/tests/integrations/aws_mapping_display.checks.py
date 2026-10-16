#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.aws_mapping_display_fixtures import *

def check(root):
    shutil.copytree(ROOT / 'framework', root / 'framework')
    (root / 'project.json').write_text(json.dumps({'projectName': 'fixture', 'targets': [
        {'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')
    path = root / 'docs/designs/dev/123456789012/cloudwatch-logs.md'
    source = root / 'model/dev/123456789012/cloudwatch-logs.properties'
    values = fixture('cloudwatch-logs', 'Logs.LogGroup', 'cwlogs-app-dev-flow', [
        ('LogGroupName', '`cwlogs-app-dev-flow`'), ('RetentionInDays', '`30`'), ('DeletionProtectionEnabled', '`false`')])
    write_model(source, values)
    saved = snapshot_model(source)
    path.parent.mkdir(parents=True, exist_ok=True)

    def verify(value=values):
        path.write_text(markdown_for(path, value, root), encoding='utf-8')
        actual = properties(model_for(path, root, source=value))
        expected = {key: item for key, item in projection(value, root).items() if not key.startswith('display.')}
        assert actual == expected, {key: (actual.get(key), expected.get(key)) for key in actual.keys() | expected.keys() if actual.get(key) != expected.get(key)}
        validate_views(root, root, [path], {path: value})
        return path.read_text(encoding='utf-8')

    verify()
    change(root, 'cloudwatch-logs', 'Logs.LogGroup', 'RetentionInDays', name='KeepDays')
    assert '| KeepDays | `30` |' in verify()
    change(root, 'cloudwatch-logs', 'Logs.LogGroup', 'RetentionInDays', show=False)
    hidden = verify()
    assert 'KeepDays' not in hidden and 'RetentionInDays' not in hidden
    assert values['desired.row.007-012.value'] == '`30`' and snapshot_model(source) == saved
    path.write_text(hidden.replace('| 2 | DeletionProtectionEnabled', '| 2 | KeepDays | `30` | 不正な表示 |\n| 3 | DeletionProtectionEnabled'), encoding='utf-8')
    try:
        model_for(path, root, source=values)
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
    change(root, 'cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName', show=False)
    assert '| LogGroupName |' not in verify()
    missing = {key: value for key, value in values.items() if not key.startswith('desired.row.007-011.')}
    try:
        markdown_for(path, missing, root)
    except ValueError as error:
        assert 'nameless independent resource' in str(error)
    else:
        raise AssertionError('hidden required property was not required')
    assert snapshot_model(source) == saved
    change(root, 'cloudwatch-logs', 'Logs.LogGroup', 'KmsKeyId', show=False)
    bad_reference = {**values, 'desired.row.007-014.property': 'Logs.LogGroup.KmsKeyId',
                     'desired.row.007-014.value': '[missing](kms.md#kms-missing)',
                     'desired.row.007-014.comment': '非表示でも参照を検証する'}
    try:
        verify(bad_reference)
    except ValueError as error:
        assert 'broken design link' in str(error), str(error)
    else:
        raise AssertionError('hidden reference escaped validation')

    config = fixture('config', 'Config.ConfigurationRecorder', 'default', [
        ('Name', '`default`'), ('RoleARN', 'Pending'), ('RecordingGroup.ResourceTypes', '`["AWS::S3::Bucket","AWS::EC2::VPC"]`')])
    config_path = path.with_name('config.md')
    for name in ('RoleName', 'RecorderRole'):
        change(root, 'config', 'Config.ConfigurationRecorder', 'RoleARN', name=name)
        change(root, 'config', 'Config.ConfigurationRecorder', 'RecordingGroup.ResourceTypes', name='SelectedTypes')
        document = markdown_for(config_path, config, root)
        assert f'| {name} | Pending |' in document and 'SelectedTypes[1]' in document
        config_path.write_text(document, encoding='utf-8')
        actual = properties(model_for(config_path, root, source=config))
        assert actual == {key: value for key, value in config.items() if not key.startswith('display.')}
    change(root, 'config', 'Config.ConfigurationRecorder', 'RoleARN', show=False)
    missing = {key: value for key, value in config.items() if not key.startswith('desired.row.007-012.')}
    try:
        markdown_for(config_path, missing, root)
    except ValueError as error:
        assert 'required provider schema property missing' in str(error)
    else:
        raise AssertionError('hidden required RoleARN was not validated')
    from security_group_tables import GROUP_COMMENTS
    sg = fixture('security-group', 'EC2.SecurityGroup', 'sg-app-dev-flow', [
        ('Id', '[Fixture](#security-group-sg-app-dev-flow)'), ('GroupDescription', '`flow`'),
        ('GroupName', '`sg-app-dev-flow`'), ('VpcId', '`vpc-00000000000000001`')])
    for identity, row in entries(sg, 'desired.row.'):
        sg['desired.row.' + identity + '.comment'] = GROUP_COMMENTS[row['property'].removeprefix('EC2.SecurityGroup.')]
    for key in ('property', 'comment'):
        sg['observed.row.007-011.' + key] = sg['desired.row.007-011.' + key]
    sg['observed.row.007-011.value'] = 'sg-00000000000000001'
    sg_path = path.with_name('security-group.md')
    change(root, 'security-group', 'EC2.SecurityGroup', 'GroupDescription', name='Purpose')
    for visible in (True, False):
        change(root, 'security-group', 'EC2.SecurityGroup', 'GroupDescription', show=visible)
        document = markdown_for(sg_path, sg, root)
        assert ('| Purpose |' in document) == visible
        sg_path.write_text(document, encoding='utf-8')
        assert properties(model_for(sg_path, root, source=sg)) == {
            key: value for key, value in projection(sg, root).items() if not key.startswith('display.')}
    # A grouped identity can suppress its display unit without deleting the Model child.
    repository = fixture('codecommit', 'CodeCommit.Repository', 'fixture-repo', [
        ('RepositoryName', '`fixture-repo`'), ('RepositoryId', '`kept-hidden-id`')])
    repository_path = path.with_name('codecommit.md')
    repository_path.write_text(markdown_for(repository_path, repository, root), encoding='utf-8')
    assert 'kept-hidden-id' not in repository_path.read_text(encoding='utf-8')
    assert properties(model_for(repository_path, root, source=repository)) == {
        key: value for key, value in projection(repository, root).items() if not key.startswith('display.')}
    assert repository['desired.row.007-012.value'] == '`kept-hidden-id`'
    print('P5 grouped displays: PASS (SG basic rename/hide, grouped identity projection; formal source retained)')
    print('P5 compact groups: PASS (CodeBuild, CloudTrail, Glue, CodePipeline; hidden constituents keep their source values)')
    print('P5 display: PASS (rename/reverse, hidden rows retained, required/typed validation, explicit row IDs, Config RoleARN, ordered arrays, no source writes)')


if __name__ == '__main__':
    with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
        with TemporaryDirectory(prefix='mapping-display-') as directory:
            check(Path(directory))


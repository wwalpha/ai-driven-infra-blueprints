#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.aws_mapping_display_fixtures import *


@it_case
def check(root):
    seed = root / 'seed'
    seed.mkdir()
    (seed / 'project.json').write_text(json.dumps({'projectName': 'fixture', 'targets': [
        {'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}) + '\n', encoding='utf-8')

    values = fixture('cloudwatch-logs', 'Logs.LogGroup', 'cwlogs-app-dev-flow', [
        ('LogGroupName', '`cwlogs-app-dev-flow`'), ('RetentionInDays', '`30`'), ('DeletionProtectionEnabled', '`false`')])
    current = root / 'baseline'
    shutil.copytree(seed, current)
    path = current / 'docs/designs/dev/123456789012/cloudwatch-logs.md'
    source = current / 'model/dev/123456789012/cloudwatch-logs.properties'
    write_model(source, values)
    saved = snapshot_model(source)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(markdown_for(path, values, current), encoding='utf-8')
    assert path.read_text() == markdown_for(path, values, current)
    validate_views(current, current, [path], {path: values})
    assert snapshot_model(source) == saved

    # A grouped identity can suppress its display unit without deleting the Model child.
    current = root / 'repository'
    shutil.copytree(seed, current)
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
    print('P5 grouped displays: PASS (current CodeCommit projection; formal source retained)')
    print('P5 display: PASS (current Logs display, roundtrip, validation, unchanged Model)')


if __name__ == '__main__':
    with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
        with TemporaryDirectory(prefix='mapping-display-') as directory:
            check(Path(directory))


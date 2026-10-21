#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.aws_mapping_display_fixtures import *

def check_mapping_display_rows(tmp_path):
    root = tmp_path
    shutil.copytree(ROOT / 'framework', root / 'framework')
    from model.display import display_rows
    from design_layout import formal_property
    nested = 'DataSourceParameters.SnowflakeParameters.Database'
    change(root, 'quicksight', 'QuickSight.DataSource', nested, name='WarehouseDatabase')
    row = ['1', 'QuickSight.DataSource.' + nested, '`finance`', 'ネストした正式属性']
    shown = display_rows('QuickSight.DataSource', [row], root)
    assert shown == [['1', 'WarehouseDatabase', *row[2:]]]
    assert formal_property('WarehouseDatabase', 'QuickSight.DataSource', root) == row[1]
    for service, kind, rows, hidden in [
        ('codebuild', 'CodeBuild.Project', [('Environment.EnvironmentVariables[].Name', '`FLAG`'),
            ('Environment.EnvironmentVariables[].Value', '`false`'), ('Environment.EnvironmentVariables[].Type', '`PLAINTEXT`')], 'Environment.EnvironmentVariables[].Type'),
        ('cloudtrail', 'CloudTrail.Trail', [('EventSelectors[].DataResources[].Type', '`AWS::S3::Object`'),
            ('EventSelectors[].DataResources[].Values', '`["arn:aws:s3"]`')], 'EventSelectors[].DataResources[].Type'),
        ('glue', 'Glue.Job', [('DefaultArguments', '`{"--flag":"false"}`')], 'DefaultArguments'),
        ('codepipeline', 'CodePipeline.Pipeline', [('Stages[].Name', '`Source`'),
            ('Stages[].Actions[].Name', '`Fetch`')], 'Stages[].Actions[].Name'),
    ]:
        full = [[str(i), kind + '.' + prop, value, '集約表示の入力'] for i, (prop, value) in enumerate(rows, 1)]
        original = copy.deepcopy(full)
        change(root, service, kind, hidden, show=False)
        assert display_rows(kind, full, root) == []
        assert full == original



def check_group_projection(tmp_path):
    root = tmp_path
    shutil.copytree(ROOT / 'framework', root / 'framework')
    alias = fixture('kms', 'KMS.Alias', 'alias/fixture', [('AliasName', '`alias/fixture`')])
    change(root, 'kms', 'KMS.Alias', 'AliasName', show=False)
    assert selected_rows([['007-011', 'KMS.Alias.AliasName', '`alias/fixture`', '識別名']], root) == []
    assert 'desired.resource.007.resourceType' not in projection(alias, root)
    assert alias['desired.resource.007.resourceType'] == 'KMS.Alias'



def check_validation_projection_scope(tmp_path):
    import aws_mapping_display as display
    import sync_views
    source = {'first': 'one', 'second': 'two'}
    provider = object()
    calls = []

    def projected(values, root):
        calls.append((tuple(values.items()), root))
        if 'invalid' in values:
            raise ValueError('projection failure')
        return dict(values)

    with patch.object(display, 'projection', side_effect=projected), patch.object(
            display, 'mappings_for', return_value=provider) as providers:
        with display._validation_projection_scope():
            first = display._validation_projection(source, tmp_path)
            first['first'] = 'caller mutation'
            assert display._validation_projection(source, tmp_path) == source
            assert len(calls) == 1
            for operation in ('change', 'add', 'delete', 'order'):
                if operation == 'change':
                    source['first'] = 'changed'
                elif operation == 'add':
                    source['third'] = 'three'
                elif operation == 'delete':
                    del source['third']
                else:
                    source['first'] = source.pop('first')
                before = len(calls)
                assert list(display._validation_projection(source, tmp_path).items()) == list(source.items())
                assert len(calls) == before + 1
            display._validation_projection(dict(source), tmp_path)
            assert len(calls) == 6
            display._validation_projection(source, tmp_path / 'other-root')
            assert len(calls) == 7
            providers.return_value = object()
            display._validation_projection(source, tmp_path)
            assert len(calls) == 8
            source['invalid'] = 'yes'
            for _ in range(2):
                try:
                    display._validation_projection(source, tmp_path)
                except ValueError as error:
                    assert str(error) == 'projection failure'
                else:
                    raise AssertionError('exception must propagate')
            assert len(calls) == 10
            del source['invalid']
            # Direct callers always compute, even inside validation.
            display.projection(source, tmp_path)
            display.projection(source, tmp_path)
            assert len(calls) == 12
        assert display._validation_projections.get() is None
        with display._validation_projection_scope():
            display._validation_projection(source, tmp_path)
            assert len(calls) == 13
        display._validation_projection(source, tmp_path)
        display._validation_projection(source, tmp_path)
        assert len(calls) == 15

    def fail(*args):
        assert display._validation_projections.get() == {}
        raise ValueError('validator failure')

    with patch.object(sync_views, 'view_validator', side_effect=fail):
        for _ in range(2):
            try:
                sync_views.validate_views(tmp_path, tmp_path, [], {})
            except ValueError as error:
                assert str(error) == 'validator failure'
            else:
                raise AssertionError('validator must fail')
            assert display._validation_projections.get() is None


def check_validation_projection_semantics(tmp_path):
    import aws_mapping_display as display
    root = tmp_path
    shutil.copytree(ROOT / 'framework', root / 'framework')
    cases = [
        ('kms', 'KMS.Alias', [('AliasName', '`alias/fixture`')], 'AliasName'),
        ('codebuild', 'CodeBuild.Project', [('Name', '`fixture`'),
            ('Environment.EnvironmentVariables[].Name', '`FLAG`'),
            ('Environment.EnvironmentVariables[].Value', '`false`'),
            ('Environment.EnvironmentVariables[].Type', '`PLAINTEXT`')],
            'Environment.EnvironmentVariables[].Type'),
        ('lambda', 'Lambda.Permission', [('Id', '`permission`'),
            ('FunctionName', '`function`'), ('Action', '`lambda:InvokeFunction`')], 'FunctionName'),
    ]
    for service, kind, rows, hidden in cases:
        change(root, service, kind, hidden, show=False)
        source = fixture(service, kind, 'fixture', rows)
        original = dict(source)
        expected = display.projection(source, root)
        with patch.object(display, 'projection', wraps=display.projection) as compute:
            with display._validation_projection_scope():
                assert display._validation_projection(source, root) == expected
                assert display._validation_projection(source, root) == expected
                assert compute.call_count == 1
        assert source == original
    # A later validation observes a new definitions root/provider.
    other = root / 'updated'
    shutil.copytree(ROOT / 'framework', other / 'framework')
    change(other, 'kms', 'KMS.Alias', 'AliasName', show=True)
    source = fixture('kms', 'KMS.Alias', 'alias/fixture', [('AliasName', '`alias/fixture`')])
    with display._validation_projection_scope():
        assert display._validation_projection(source, root) != source
    with display._validation_projection_scope():
        assert display._validation_projection(source, other) == source


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

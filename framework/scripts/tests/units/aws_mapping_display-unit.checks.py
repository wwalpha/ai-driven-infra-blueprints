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
    from model_display import display_rows
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



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

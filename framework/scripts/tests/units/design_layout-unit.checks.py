#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import design_layout as _imports_design_layout
import pytest as _imports_pytest
import support.design_layout_fixtures as _exports_support_design_layout_fixtures
from design_layout import resource_display_selection, resource_has_name_property
from support.design_layout_fixtures import (
    REPOSITORY,
    Path,
    expanded_display_rows,
    model_projection,
    pipeline_rows,
    pytest,
    resource_anchor,
    resource_display_name,
    run,
    sys,
)
from support.design_layout_fixtures import pytestmark as pytestmark

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

# Preserve shared fixtures and compatibility exports under their historical names.
catalog = _exports_support_design_layout_fixtures.catalog
resource_logical_ids = _exports_support_design_layout_fixtures.resource_logical_ids



def check_resource_display_names():
    kind = 'Config.ConfigurationRecorder'
    assert resource_has_name_property(REPOSITORY, kind, 'IMPORT')
    assert resource_display_selection(REPOSITORY, kind, [], 'Config recorder', 'IMPORT', 1) == ('Config recorder', None)
    assert resource_display_selection(REPOSITORY, 'SNS.Topic', [], 'Notifications', 'IMPORT', 1) == ('Notifications', None)
    assert resource_display_selection(REPOSITORY, kind, [['1', 'Name', '`default`', '名称']], 'label', 'IMPORT', 1) == ('default', 'default')
    for mode, rows, label, message in (
        ('CREATE', [], 'Config recorder', 'required Name is not selected'),
        ('IMPORT', [], None, 'confirmed resource display label is missing'),
        ('IMPORT', [['1', 'Name', '``', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '`   `', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '`UNSET`', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '`Pending`', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '[name](#other)', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '`PENDING_DEPLOY`', '名称']], 'label', 'confirmed and non-empty'),
        ('IMPORT', [['1', 'Name', '`{{application}}`', '名称']], 'label', 'confirmed and non-empty'),
    ):
        with pytest.raises(ValueError, match=message):
            resource_display_selection(REPOSITORY, kind, rows, label, mode, 1)
    for kind in ('CodeCommit.Repository', 'KMS.Alias', 'CloudFront.CachePolicy'):
        with pytest.raises(ValueError, match='required provider schema property missing'):
            resource_display_selection(REPOSITORY, kind, [], 'label', 'IMPORT', 1)
    for kind in ('IAM.Role', 'CodeBuild.Project'):
        with pytest.raises(ValueError, match='must appear exactly once'):
            resource_display_selection(REPOSITORY, kind, [], 'label', 'IMPORT', 1)
    for label in ('', 'UNSET', 'PENDING_DEPLOY'):
        with pytest.raises(ValueError, match='confirmed resource display label is missing'):
            resource_display_selection(REPOSITORY, 'GuardDuty.Detector', [], label, 'IMPORT', 1)
    assert resource_display_name("IAM.Role", [["1", "RoleName", "`role-app-dev`", "名前"]]) == "role-app-dev"
    assert resource_display_name("KMS.Key", [["1", "KMS.Alias.AliasName", "`alias/app`", "名前"]]) == "app"
    assert resource_display_name("Scheduler.Schedule", [["1", "GroupName", "`default`", "group"]]) is None
    assert resource_display_name("EC2.SecurityGroup", [["1", "EC2.SecurityGroup.Tags[].Key", '"Name"', "タグ"], ["2", "EC2.SecurityGroup.Tags[].Value", '"sg-app-dev"', "タグ"]]) == "sg-app-dev"
    assert resource_anchor("secretsmanager", "app/dev/key") == "secretsmanager-app-dev-key"
    kind = 'Glue.Connection'
    configured = ['1', 'ConnectionInput.Name', '`configured-connection`', '接続の設定名']
    for field in ('Name', kind + '.Name'):
        for value in ('[Glue_Connection_001](#resource-Glue_Connection_001)', '`PENDING_DEPLOY`', '`generated-connection`'):
            output = ['2', field, value, '生成識別子']
            rows = [configured, output]
            assert resource_display_selection(REPOSITORY, kind, rows, None, 'CREATE', 1) == ('configured-connection', 'configured-connection')
            assert resource_display_selection(REPOSITORY, kind, rows, 'label', 'IMPORT', 1) == ('configured-connection', 'configured-connection')
            assert resource_display_name(kind, rows) == 'configured-connection'
            assert resource_display_name(kind, [output]) is None
            with pytest.raises(ValueError, match='required Name is not selected'):
                resource_display_selection(REPOSITORY, kind, [output], 'label', 'CREATE', 1)
            assert resource_display_selection(REPOSITORY, kind, [output], 'label', 'IMPORT', 1) == ('label', None)
            with pytest.raises(ValueError, match='confirmed resource display label is missing'):
                resource_display_selection(REPOSITORY, kind, [output], None, 'IMPORT', 1)
            with pytest.raises(ValueError, match='confirmed and non-empty'):
                resource_display_selection(REPOSITORY, kind, [[*configured[:2], '`UNSET`', configured[3]], output], None, 'CREATE', 1)


    kind = 'GuardDuty.Detector'
    assert not resource_has_name_property(REPOSITORY, kind)
    for count in (1, 2):
        assert resource_display_selection(REPOSITORY, kind, [], 'primary-detector', 'CREATE', count) == ('primary-detector', None)
    assert resource_display_selection(REPOSITORY, kind, [], None, 'CREATE', 1) == (kind, None)
    assert resource_display_selection(REPOSITORY, kind, [], None, 'CREATE', 2) == (None, None)
    assert resource_display_name(kind, [['1', 'Tags[].Key', '`Name`', 'キー'], ['2', 'Tags[].Value', '`selected-name`', '名前']]) == 'selected-name'
    assert resource_has_name_property(REPOSITORY, 'CodeCommit.Repository')
    assert resource_has_name_property(REPOSITORY, 'SNS.Topic')
    aliases = [['1', 'KMS.Alias.AliasName', '`alias/one`', 'alias'], ['2', 'KMS.Alias.AliasName', '`alias/two`', 'alias']]
    for label in (None, 'other'):
        with pytest.raises(ValueError, match='multiple aliases'):
            resource_display_name('KMS.Key', aliases, label)
    assert resource_display_name('KMS.Key', aliases, 'one') == 'one'
    assert resource_display_name('KMS.Key', []) is None
    for invalid in ('alias/', 'one'):
        with pytest.raises(ValueError, match='AliasName'):
            resource_display_name('KMS.Key', [['1', 'KMS.Alias.AliasName', invalid, 'alias']])



def check_cloudtrail_expansion():
    trail = '# AWS CloudTrail 詳細設計\n\n- Design service ID: `cloudtrail`\n- Owned catalog resource types: `CloudTrail.Trail`\n\n## リソース詳細\n\n<a id="cloudtrail-trail"></a>\n\n### CloudTrail.Trail: Trail\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 1 | TrailName | `trail` | 証跡の名前 |\n| 2 | EventSelectors.DataResources[1].S3 | [data-bucket](s3.md#s3-data-bucket) | S3 objectの記録対象 |\n| 3 | EventSelectors.DataResources[2].Lambda | [function-one](lambda.md#lambda-function-one) | Lambda functionの記録対象 |\n| 4 | IsLogging | `true` | event記録の有効化 |\n| 5 | S3BucketName | [data-bucket](s3.md#s3-data-bucket) | ログの配信先bucket |\n'
    expanded = "\n".join(expanded_display_rows(trail.splitlines()))
    assert expanded.count("CloudTrail.Trail.EventSelectors[].DataResources[].Type") == 2
    assert "`AWS::S3::Object`" in expanded and "`AWS::Lambda::Function`" in expanded
    assert expanded.count("CloudTrail.Trail.EventSelectors[].DataResources[].Values") == 2



def _callback_check_pipeline_expansion_design(service: str, resource_type: str, logical_id: str, rows: list[tuple[str, str]]):
    return "\n".join([
        f"# {service} 詳細設計", f"- Design service ID: `{service}`",
        f"- Owned catalog resource types: `{resource_type}`", "## リソース詳細",
        f'<a id="{service}-{logical_id.lower()}"></a>', f"### {resource_type}: {logical_id}",
        "| No. | Property | Value | Source / Comment |", "| ---: | --- | --- | --- |",
        *(f"| {n} | {prop} | {value} | 設定する属性 |" for n, (prop, value) in enumerate(rows, 1)),
    ]) + "\n"


def check_pipeline_expansion(catalog):
    design = _callback_check_pipeline_expansion_design

    rows = [
        ("Name", "`pipeline`"),
        ("RoleArn", "[role](iam.md#iam-role)"),
        ("Stages[1].Actions.ActionTypeId.Provider", "`CodeCommit`"),
        ("Stages[1].Actions.Configuration.BranchName", "`dev`"),
        ("Stages[1].Actions.Configuration.PollForSourceChanges", "`false`"),
        ("Stages[1].Actions.Configuration.RepositoryName", "[repo](codecommit.md#codecommit-repo)"),
        ("Stages[1].Actions.Name", "`Source`"),
        ("Stages[1].Name", "`Source`"),
        ("Stages[2].Actions[1].ActionTypeId.Provider", "`CodeBuild`"),
        ("Stages[2].Actions[1].Configuration.ProjectName", "[build](codebuild.md#codebuild-build)"),
        ("Stages[2].Actions[1].Name", "`Build`"),
        ("Stages[2].Actions[2].ActionTypeId.Provider", "`CodeBuild`"),
        ("Stages[2].Actions[2].Configuration.ProjectName", "[build](codebuild.md#codebuild-build)"),
        ("Stages[2].Actions[2].Name", "`Test`"),
        ("Stages[2].Name", "`BuildAndTest`"),
    ]
    pipeline = design("codepipeline", "CodePipeline.Pipeline", "Pipeline", rows)
    _ = design("codecommit", "CodeCommit.Repository", "Repo", [("RepositoryName", "`repo`")])

    assert not catalog[2].get("CodeCommit.Repository")
    assert not model_projection.identifier_outputs(REPOSITORY).get("CodeCommit.Repository")
    expanded = "\n".join(expanded_display_rows(pipeline.splitlines()))
    assert expanded.count("CodePipeline.Pipeline.Stages[].Actions[].Configuration |") == 3
    assert '`{"BranchName":"dev","PollForSourceChanges":"false","RepositoryName":"[repo](codecommit.md#codecommit-repo)"}`' in expanded
    assert "Stages[1]" not in expanded and "Actions[2]" not in expanded
    formal_rows = [
        [cells[0], cells[1].removeprefix("CodePipeline.Pipeline."), *cells[2:]]
        for line in expanded.splitlines()
        if len(cells := [cell.strip() for cell in line.strip("|").split("|")]) == 4 and cells[0].isdigit()
    ]
    assert [(row[1], row[2]) for row in pipeline_rows(formal_rows)] == rows



def check_fixed_identity_anchors():
    assert resource_anchor('config', 'default', 'Config.ConfigurationRecorder') == 'config-configuration-recorder-default'
    assert resource_anchor('config', 'DEFAULT', 'Config.ConfigurationRecorder') == 'config-configuration-recorder-default'
    assert resource_anchor('config', 'default', 'Config.DeliveryChannel') == 'config-delivery-channel-default'
    assert resource_anchor('s3', 'app/data', 'S3.Bucket') == 's3-app-data'
    pytest = _imports_pytest
    resource_logical_ids = _imports_design_layout.resource_logical_ids
    lines = []
    for logical in ('EC2_Subnet_001', 'EC2_Subnet_002'):
        lines += ['<!-- resource-logical-id: ' + logical + ' -->', '<a id="resource-' + logical + '"></a>', '### EC2.Subnet: same-name']
    assert resource_logical_ids(lines) == {'resource-EC2_Subnet_001': 'EC2_Subnet_001', 'resource-EC2_Subnet_002': 'EC2_Subnet_002'}
    with pytest.raises(ValueError, match='duplicate'):
        resource_logical_ids(lines + lines[:3])


if __name__ == '__main__':
    raise SystemExit(run(__file__))

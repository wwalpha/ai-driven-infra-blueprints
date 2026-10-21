#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.design_layout_fixtures import *

def check_resource_display_names():
    assert resource_display_name("IAM.Role", [["1", "RoleName", "`role-app-dev`", "名前"]]) == "role-app-dev"
    assert resource_display_name("KMS.Key", [["1", "KMS.Alias.AliasName", "`alias/app`", "名前"]]) == "app"
    assert resource_display_name("Scheduler.Schedule", [["1", "GroupName", "`default`", "group"]]) is None
    assert resource_display_name("EC2.SecurityGroup", [["1", "EC2.SecurityGroup.Tags[].Key", '"Name"', "タグ"], ["2", "EC2.SecurityGroup.Tags[].Value", '"sg-app-dev"', "タグ"]]) == "sg-app-dev"
    assert resource_anchor("secretsmanager", "app/dev/key") == "secretsmanager-app-dev-key"



def check_cloudtrail_expansion():
    trail = '# AWS CloudTrail 詳細設計\n\n- Design service ID: `cloudtrail`\n- Owned catalog resource types: `CloudTrail.Trail`\n\n## リソース詳細\n\n<a id="cloudtrail-trail"></a>\n\n### CloudTrail.Trail: Trail\n\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 1 | TrailName | `trail` | 証跡の名前 |\n| 2 | EventSelectors.DataResources[1].S3 | [data-bucket](s3.md#s3-data-bucket) | S3 objectの記録対象 |\n| 3 | EventSelectors.DataResources[2].Lambda | [function-one](lambda.md#lambda-function-one) | Lambda functionの記録対象 |\n| 4 | IsLogging | `true` | event記録の有効化 |\n| 5 | S3BucketName | [data-bucket](s3.md#s3-data-bucket) | ログの配信先bucket |\n'
    expanded = "\n".join(expanded_display_rows(trail.splitlines()))
    assert expanded.count("CloudTrail.Trail.EventSelectors[].DataResources[].Type") == 2
    assert "`AWS::S3::Object`" in expanded and "`AWS::Lambda::Function`" in expanded
    assert expanded.count("CloudTrail.Trail.EventSelectors[].DataResources[].Values") == 2



def check_pipeline_expansion(catalog):
    def design(service: str, resource_type: str, logical_id: str, rows: list[tuple[str, str]]) -> str:
        return "\n".join([
            f"# {service} 詳細設計", f"- Design service ID: `{service}`",
            f"- Owned catalog resource types: `{resource_type}`", "## リソース詳細",
            f'<a id="{service}-{logical_id.lower()}"></a>', f"### {resource_type}: {logical_id}",
            "| No. | Property | Value | Source / Comment |", "| ---: | --- | --- | --- |",
            *(f"| {n} | {prop} | {value} | 設定する属性 |" for n, (prop, value) in enumerate(rows, 1)),
        ]) + "\n"

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
    repository = design("codecommit", "CodeCommit.Repository", "Repo", [("RepositoryName", "`repo`")])

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
    from design_layout import resource_logical_ids
    import pytest
    lines = []
    for logical in ('EC2_Subnet_001', 'EC2_Subnet_002'):
        lines += ['<!-- resource-logical-id: ' + logical + ' -->', '<a id="resource-' + logical + '"></a>', '### EC2.Subnet: same-name']
    assert resource_logical_ids(lines) == {'resource-EC2_Subnet_001': 'EC2_Subnet_001', 'resource-EC2_Subnet_002': 'EC2_Subnet_002'}
    with pytest.raises(ValueError, match='duplicate'):
        resource_logical_ids(lines + lines[:3])


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

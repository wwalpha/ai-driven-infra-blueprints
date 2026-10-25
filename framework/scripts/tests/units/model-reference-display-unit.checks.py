"""Model-bound display expectations, using authored synthetic Resources only."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.sources as sources
import pytest
from design.document import DesignIndex, model_reference_tables
from design.layout import expanded_display_rows
from model.display import reference_rows, row_table
from model.render import generate_markdown
from support.lambda_permission_fixtures import fixture as permission_fixture
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from support.model_sources import write_model
from support.pytest_cli import run
from sync_runtime import _compare_generation
from utils.aws_mappings import mapping_alias
from utils.input_cache import input_context
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def pipeline(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        resource(
            tmp_path,
            "codebuild",
            "CodeBuild.Project",
            attribute="Name",
            observed="build-project",
        )
        scope, values = resource(
            tmp_path, "codepipeline", "CodePipeline.Pipeline", attribute="Name"
        )
        values["desired.row.001-001.value"] = "`synthetic-pipeline`"
        rows = []
        golden = [["1", "Name", "`synthetic-pipeline`", "合成"]]
        for stage, count in ((1, 1), (2, 4)):
            rows.append(("Stages[].Name", f"`stage-{stage}`", "ステージ"))
            golden.append(["", f"Stages[{stage}].Name", f"`stage-{stage}`", "ステージ"])
            for action in range(1, count + 1):
                prefix = f"Stages[{stage}]." + (
                    "Actions." if count == 1 else f"Actions[{action}]."
                )
                for field, value, comment in (
                    ("Name", f"`build-{action}`", "アクション"),
                    ("ActionTypeId.Category", "`Build`", "分類"),
                    ("ActionTypeId.Owner", "`AWS`", "所有者"),
                    ("ActionTypeId.Provider", "`CodeBuild`", "プロバイダ"),
                    ("ActionTypeId.Version", "`1`", "版"),
                ):
                    rows.append(("Stages[].Actions[]." + field, value, comment))
                    golden.append(["", prefix + field, value, comment])
                rows.append(
                    (
                        "Stages[].Actions[].Configuration",
                        "`"
                        + json.dumps(
                            {
                                "ProjectName": reference(
                                    "CodeBuild_Project_001", "Name"
                                ),
                                "BatchEnabled": "false",
                            }
                        )
                        + "`",
                        "ProjectName: ビルド対象 / BatchEnabled: 通常設定",
                    )
                )
                golden.extend(
                    [
                        [
                            "",
                            prefix + "Configuration.ProjectName",
                            "`build-project`",
                            "ビルド対象",
                        ],
                        [
                            "",
                            prefix + "Configuration.BatchEnabled",
                            "`false`",
                            "通常設定",
                        ],
                    ]
                )
        for number, (prop, value, comment) in enumerate(rows, 2):
            values.update(
                {
                    f"desired.row.001-{number:03d}.property": "CodePipeline.Pipeline."
                    + prop,
                    f"desired.row.001-{number:03d}.value": value,
                    f"desired.row.001-{number:03d}.comment": comment,
                }
            )
        for number, row in enumerate(golden, 1):
            row[0] = str(number)
            if row[1].startswith("Stages[1].Actions."):
                source = json.dumps([row[1], row[2], 1], ensure_ascii=True)
                row[1] = row[1].replace("Actions.", "Actions[1].")
                row[3] = "<!-- array-source: " + source + " --> " + row[3]
        save(scope, values)
        path = tmp_path / "docs/designs/qa/team/codepipeline.md"
        yield tmp_path, scope, path, values, row_table(golden)


def check_pipeline_visible_baseline(pipeline):
    root, _, path, values, golden = pipeline
    markdown = generate_markdown(path, values, FRAMEWORK)
    assert "\n".join(golden) in markdown
    assert "reference-rows" not in markdown and "reference-value" not in markdown
    assert "$modelRef" not in markdown
    snapshot = reference_rows(values)["CodePipeline_Pipeline_001"]
    assert len(snapshot.references) == 5
    assert all(
        nodes[0].logical_id == "CodeBuild_Project_001" and nodes[0].attribute == "Name"
        for _, nodes in snapshot.references
    )
    document = DesignIndex(FRAMEWORK).get(path, text=markdown, values=values)
    semantic = "\n".join(document.raw.expanded[0])
    assert semantic.count("$modelRef") == 5 and semantic.count("ビルド対象") == 5
    assert generate_markdown(path, values, FRAMEWORK) == markdown
    # Identical fixture with ordinary values retains precisely the same visible table.
    ordinary = {
        key: value.replace(
            json.dumps(reference("CodeBuild_Project_001", "Name")), '"build-project"'
        )
        for key, value in values.items()
    }
    assert generate_markdown(path, ordinary, FRAMEWORK) == markdown
    assert (
        model_reference_tables(path, markdown, tuple(ordinary.items()), FRAMEWORK) == ()
    )


@pytest.mark.parametrize(
    "change",
    [
        "property",
        "value",
        "comment",
        "key",
        "order",
        "missing",
        "added",
        "stage",
        "action",
        "logical",
        "anchor",
    ],
)
def check_actual_markdown_must_match(pipeline, change):
    _, _, path, values, golden = pipeline
    markdown = generate_markdown(path, values, FRAMEWORK)
    row = next(line for line in golden if "Configuration.ProjectName" in line)
    changes = {
        "property": markdown.replace("ActionTypeId.Version", "ActionTypeId.Other", 1),
        "value": markdown.replace("`build-project`", "`edited-project`", 1),
        "comment": markdown.replace("ビルド対象", "改変", 1),
        "key": markdown.replace("Configuration.ProjectName", "Configuration.Other", 1),
        "order": markdown.replace(
            golden[3] + "\n" + golden[4], golden[4] + "\n" + golden[3], 1
        ),
        "missing": markdown.replace(row + "\n", "", 1),
        "added": markdown.replace(row, row + "\n" + row, 1),
        "stage": markdown.replace("Stages[1]", "Stages[3]", 1),
        "action": markdown.replace("Actions[1]", "Actions[7]", 1),
        "logical": markdown.replace(
            "resource-logical-id: CodePipeline_Pipeline_001",
            "resource-logical-id: CodePipeline_Pipeline_099",
        ),
        "anchor": markdown.replace('<a id="saved-001">', '<a id="changed-anchor">'),
    }
    assert changes[change] != markdown
    document = DesignIndex(FRAMEWORK).get(path, text=changes[change], values=values)
    with pytest.raises(ValueError, match="Model expected display"):
        _ = document.raw.expanded


@pytest.mark.parametrize("marker", ["reference-rows", "reference-value"])
def check_obsolete_metadata_requires_regeneration(pipeline, marker):
    root, _, path, values, _ = pipeline
    current = generate_markdown(path, values, FRAMEWORK)
    path.parent.mkdir(parents=True)
    legacy = current.replace(
        "ビルド対象", "<!-- " + marker + ": e30= --> ビルド対象", 1
    )
    path.write_text(legacy, encoding="utf-8")
    plan = SimpleNamespace(
        root=root,
        read_inputs={},
        expected_outputs={path: {path: current}},
        failures=[],
        saved={},
    )
    _compare_generation(plan)
    assert plan.failures and not plan.saved
    with pytest.raises(ValueError, match="obsolete Model reference metadata"):
        expanded_display_rows(legacy.splitlines(), FRAMEWORK)
    path.write_text(current, encoding="utf-8")
    plan.failures.clear()
    _compare_generation(plan)
    assert not plan.failures and path in plan.saved


def check_snapshot_candidate_and_definition_roots(pipeline):
    root, scope, path, values, _ = pipeline
    candidate = dict(values)
    candidate["desired.row.001-001.comment"] = "候補だけのcomment"
    expected = generate_markdown(path, candidate, FRAMEWORK)
    index = DesignIndex(FRAMEWORK)
    document = index.get(path, text=expected, values=candidate)
    candidate["desired.row.001-001.comment"] = "外部変更"
    with (
        input_context(),
        patch.object(sources, "_read_model", wraps=sources._read_model) as reads,
    ):
        assert "候補だけのcomment" in "\n".join(document.raw.display_lines)
        assert document.headings.expanded is document.headings.expanded
        # Only the producer is read; the selected candidate is never reloaded from disk.
        assert all(call.args[0].path != scope.path for call in reads.call_args_list)
        assert len(reads.call_args_list) == len(
            {call.args[0].path for call in reads.call_args_list}
        )
    with pytest.raises(ValueError, match="Model expected display"):
        _ = DesignIndex(FRAMEWORK).get(path, text=expected).raw.expanded
    with pytest.raises(ValueError, match="cannot mix Model snapshots"):
        index.get(path, values=candidate)
    assert root != FRAMEWORK


def check_matching_display_still_requires_valid_structure(pipeline):
    _, _, path, values, _ = pipeline
    invalid = {
        key: value.replace('"BatchEnabled":', '"Bad.Key":').replace(
            "BatchEnabled: ", "Bad.Key: "
        )
        for key, value in values.items()
    }
    markdown = generate_markdown(path, invalid, FRAMEWORK)
    with pytest.raises(ValueError, match="Configuration.<Key>"):
        _ = (
            DesignIndex(FRAMEWORK)
            .get(path, text=markdown, values=invalid)
            .raw.display_lines
        )


def check_expectation_is_shared_within_validation(pipeline):
    _, _, path, values, _ = pipeline
    expected = generate_markdown(path, values, FRAMEWORK)
    with (
        input_context(),
        patch("model.render.generate_markdown", wraps=generate_markdown) as render,
    ):
        first = model_reference_tables(path, expected, tuple(values.items()), FRAMEWORK)
        second = model_reference_tables(
            path, expected, tuple(values.items()), FRAMEWORK
        )
        assert first is second and render.call_count == 1


def check_no_model_does_not_recover_typed_references(pipeline):
    root, _, path, values, _ = pipeline
    markdown = generate_markdown(path, values, FRAMEWORK)
    unrelated = root / "standalone.md"
    document = DesignIndex(FRAMEWORK).get(unrelated, text=markdown)
    assert not document.reference_tables and document.model_values is None
    assert "$modelRef" not in "\n".join(document.raw.display_lines)
    build = [
        "### CodeBuild.Project: build",
        "",
        "| No. | Property | Value | Source / Comment |",
        "| ---: | --- | --- | --- |",
        "| 1 | Environment.Variables.SECRET | `unresolved` | <!-- codebuild-variable-type: SECRETS_MANAGER --> 参照 |",
    ]
    findings = Findings(root)
    result = findings.evaluate(
        "standalone", None, lambda: expanded_display_rows(build, FRAMEWORK)
    )
    assert result.status == "NOT_RUN" and result.warnings and not result.errors


@pytest.mark.parametrize(
    "prop,producer,attribute",
    [
        ("VpcConfig.VpcId", "EC2.VPC", "VpcId"),
        ("VpcConfig.Subnets", "EC2.Subnet", "SubnetId"),
        ("VpcConfig.SecurityGroupIds", "EC2.SecurityGroup", "GroupId"),
    ],
)
def check_codebuild_vpc_typed_rows(tmp_path, prop, producer, attribute):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        resource(
            tmp_path,
            "producer",
            producer,
            attribute=attribute,
            observed="PENDING_DEPLOY",
        )
        scope, values = resource(
            tmp_path, "codebuild", "CodeBuild.Project", attribute="Name"
        )
        values["desired.row.001-001.value"] = "`build`"
        node = reference(producer.replace(".", "_") + "_001", attribute)
        values.update(
            {
                "desired.row.001-002.property": "CodeBuild.Project." + prop,
                "desired.row.001-002.value": "`"
                + json.dumps([node] if prop != "VpcConfig.VpcId" else node)
                + "`",
                "desired.row.001-002.comment": "ネットワーク",
            }
        )
        save(scope, values)
        path = tmp_path / "docs/designs/qa/team/codebuild.md"
        markdown = generate_markdown(path, values, FRAMEWORK)
        assert "pending_deploy" in markdown and "reference-rows" not in markdown
        assert "$modelRef" in "\n".join(
            DesignIndex(FRAMEWORK).get(path, text=markdown).raw.display_lines
        )
        with pytest.raises(ValueError, match="Markdown differs from Model expected display"):
            _ = (
                DesignIndex(FRAMEWORK)
                .get(path, text=markdown.replace("pending_deploy", "tampered"))
                .raw.display_lines
            )


def check_grouped_rows_keep_identity_and_references(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        resource(
            tmp_path,
            "s3",
            "S3.Bucket",
            attribute="Arn",
            observed="arn:aws:s3:::synthetic-bucket",
        )
        values = permission_fixture()
        values.update(
            {
                "desired.row.002-007.property": "Lambda.Permission.SourceArn",
                "desired.row.002-007.value": "`"
                + json.dumps(reference("S3_Bucket_001", "Arn"))
                + "`",
                "desired.row.002-007.comment": "呼出元",
            }
        )
        scope = sources.Scope(tmp_path, "qa", "team", "lambda")
        write_model(scope.path, values)
        current = sources.load_model(scope).values
        path = tmp_path / "docs/designs/qa/team/lambda.md"
        markdown = generate_markdown(path, current, FRAMEWORK)
        expanded, children = (
            DesignIndex(FRAMEWORK).get(path, text=markdown, values=current).raw.expanded
        )
        assert len(children) == 1
        assert next(iter(children.values()))["logicalId"] == "Lambda_Permission_001"
        assert "$modelRef" in "\n".join(expanded)
        assert "Permission.SourceArn" in markdown and "lambda-permission:" in markdown
        assert "reference-rows" not in markdown and "reference-value" not in markdown


if __name__ == "__main__":
    raise SystemExit(run(__file__))

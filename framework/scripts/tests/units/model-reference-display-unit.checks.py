"""Model-bound display expectations, using authored synthetic Resources only."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from generation_inputs import GenerationInputs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.projection as projection
import model.sources as sources
import pytest
from design.catalog import DesignSchemaCatalog
from design.document import (
    DesignIndex,
    DisplayMismatchError,
    model_reference_tables,
    model_resource_reference_tables,
)
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
from validation.runner import Validator

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def pipeline(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        producer, producer_values = resource(
            tmp_path,
            "codebuild",
            "CodeBuild.Project",
            attribute="Name",
            observed="build-project",
        )
        producer_values["desired.row.001-001.value"] = "`build-project`"
        producer_values.pop("observed.row.001-001.value")
        save(producer, producer_values)
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
                row[1] = row[1].replace("Actions.", "Actions[1].")
        save(scope, values)
        path = tmp_path / "docs/designs/qa/team/codepipeline.md"
        yield tmp_path, scope, path, values, row_table(golden)


@pytest.mark.parametrize(
    "service,kind,field,value",
    [
        ("guardduty", "GuardDuty.Detector", "Enable", "`true`"),
        ("kms", "KMS.Key", "KeySpec", "`SYMMETRIC_DEFAULT`"),
        (
            "securityhub",
            "SecurityHub.Hub",
            "ControlFindingGenerator",
            "`SECURITY_CONTROL`",
        ),
        ("macie", "Macie.Session", "Status", "`ENABLED`"),
        ("ec2", "EC2.EIP", "Domain", "`vpc`"),
        (
            "sqs",
            "SQS.QueuePolicy",
            "Queues[]",
            "`https://sqs.ap-northeast-1.amazonaws.com/123456789012/queue`",
        ),
    ],
)
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def check_nameless_projection_display(tmp_path, service, kind, field, value, mode):
    with mapping_alias(FRAMEWORK, tmp_path):
        _, values = resource(tmp_path, service, kind, attribute=field)
        values["desired.row.001-001.value"] = value
        values["desired.resource.001.resourceMode"] = mode
        before = dict(values)
        path = tmp_path / "docs/designs/qa/team" / (service + ".md")
        markdown = generate_markdown(path, values, FRAMEWORK)
        assert f"| 1 | [{kind}](#saved-001) | 合成 |" in markdown
        assert f'<a id="saved-001"></a>\n\n### {kind}\n' in markdown
        assert f"<!-- resource-logical-id: {kind.replace('.', '_')}_001 -->" in markdown
        assert values == before
        assert DesignIndex(FRAMEWORK).get(
            path, text=markdown, values=values
        ).raw.logical_ids == {"saved-001": kind.replace(".", "_") + "_001"}

        values["display.resource.001.label"] = "primary"
        labeled = generate_markdown(path, values, FRAMEWORK)
        assert "[primary](#saved-001)" in labeled
        assert f"### {kind}: primary\n" in labeled

        values.pop("display.resource.001.label")
        _, second = resource(tmp_path, service, kind, attribute=field, number="002")
        second["desired.row.002-001.value"] = value
        second["desired.resource.002.resourceMode"] = mode
        values.update(second)
        multiple = generate_markdown(path, values, FRAMEWORK)
        for number in ("001", "002"):
            logical = kind.replace(".", "_") + "_" + number
            assert f"[{logical}](#saved-{number})" in multiple
            assert f"### {kind}: {logical}\n" in multiple


@pytest.mark.parametrize(
    "name,label,expected",
    [
        ("confirmed-queue", "selected-label", "confirmed-queue"),
        ("PENDING_DEPLOY", "selected-label", "selected-label"),
        ("UNSET", "PENDING_DEPLOY", "SQS_Queue_001"),
    ],
)
def check_named_projection_fallback(tmp_path, name, label, expected):
    with mapping_alias(FRAMEWORK, tmp_path):
        _, values = resource(tmp_path, "sqs", "SQS.Queue", attribute="QueueName")
        values["desired.row.001-001.value"] = "`" + name + "`"
        values["display.resource.001.label"] = label
        before = dict(values)
        markdown = generate_markdown(
            tmp_path / "docs/designs/qa/team/sqs.md", values, FRAMEWORK
        )
        assert f"[{expected}](#saved-001)" in markdown
        assert f"### SQS.Queue: {expected}\n" in markdown
        assert values == before


@pytest.mark.parametrize("label", [None, "primary-key"])
@pytest.mark.parametrize(
    "observed", ["PENDING_DEPLOY", "12345678-1234-1234-1234-123456789012"]
)
def check_nameless_projection_reference(tmp_path, label, observed):
    with mapping_alias(FRAMEWORK, tmp_path):
        producer, key, consumer, policy = project(tmp_path)
        key["desired.row.001-001.property"] = "KMS.Key.KeyId"
        key["observed.row.001-001.value"] = "`" + observed + "`"
        if label is not None:
            key["display.resource.001.label"] = label
        save(producer, key)
        before = dict(policy)
        path = tmp_path / "docs/designs/qa/team/iam.md"
        producer_path = path.with_name("kms.md")
        producer_markdown = generate_markdown(producer_path, key, FRAMEWORK)
        name = label or "KMS.Key"
        assert f"[{name}](#saved-001)" in producer_markdown
        heading = "### KMS.Key" + (": " + label if label else "")
        assert f'<a id="saved-001"></a>\n\n{heading}\n' in producer_markdown
        markdown = generate_markdown(path, policy, FRAMEWORK)
        if observed == "PENDING_DEPLOY":
            assert "$modelRef" in markdown
        else:
            link = f"[{name}](kms.md#saved-001)"
            assert link in markdown
            resolved = projection.reference_resolver(
                policy, consumer, tmp_path
            ).resolve(link, consumer)
            assert resolved[2]["logicalId"] == "KMS_Key_001"
            assert model_reference_tables(
                path, markdown, tuple(policy.items()), FRAMEWORK
            )
        assert "$modelRef" in policy["desired.row.001-002.document"]
        assert policy == before


def check_pipeline_visible_baseline(pipeline):
    root, _, path, values, golden = pipeline
    markdown = generate_markdown(path, values, FRAMEWORK)
    linked_golden = [
        line.replace("`build-project`", "[build-project](codebuild.md#saved-001)")
        for line in golden
    ]
    assert "\n".join(linked_golden) in markdown
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
    # Equal ordinary values remain plain text; only actual nodes produce links.
    ordinary = {
        key: value.replace(
            json.dumps(reference("CodeBuild_Project_001", "Name")), '"build-project"'
        )
        for key, value in values.items()
    }
    ordinary_markdown = generate_markdown(path, ordinary, FRAMEWORK)
    assert "\n".join(golden) in ordinary_markdown
    assert "[build-project]" not in ordinary_markdown
    assert model_reference_tables(
        path, ordinary_markdown, tuple(ordinary.items()), FRAMEWORK
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
    row = next(
        line for line in markdown.splitlines() if "Configuration.ProjectName" in line
    )
    changes = {
        "property": markdown.replace("ActionTypeId.Version", "ActionTypeId.Other", 1),
        "value": markdown.replace(
            "[build-project](codebuild.md#saved-001)",
            "[edited-project](codebuild.md#saved-001)",
            1,
        ),
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
    message = (
        "logicalId/anchor/ownership"
        if change in {"logical", "anchor"}
        else "Model expected display"
    )
    with pytest.raises(ValueError, match=message):
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
        snapshot=GenerationInputs(root, read_only=True),
        expected_outputs={path: {path: current}},
        failure_records=[],
        saved={},
    )
    _compare_generation(plan)
    assert plan.failure_records and not plan.saved
    with pytest.raises(ValueError, match="obsolete Model reference metadata"):
        expanded_display_rows(legacy.splitlines(), FRAMEWORK)
    path.write_text(current, encoding="utf-8")
    plan.failure_records.clear()
    plan.snapshot = GenerationInputs(root, read_only=True)
    _compare_generation(plan)
    assert not plan.failure_records and path in plan.saved


def check_snapshot_candidate_and_definition_roots(pipeline):
    root, scope, path, values, _ = pipeline
    candidate = dict(values)
    candidate["desired.row.001-001.comment"] = "候補だけのcomment"
    expected = generate_markdown(path, candidate, FRAMEWORK)
    index = DesignIndex(FRAMEWORK)
    document = index.get(path, text=expected, values=candidate)
    candidate["desired.row.001-001.comment"] = "外部変更"
    with (
        input_context(read_only=True),
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
    with pytest.raises(ValueError):
        _ = document.raw.display_lines
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
        assert "$modelRef" in markdown and "PENDING_DEPLOY" not in markdown
        assert "reference-rows" not in markdown
        assert "$modelRef" in "\n".join(
            DesignIndex(FRAMEWORK).get(path, text=markdown).raw.display_lines
        )
        with pytest.raises(
            ValueError, match="Markdown differs from Model expected display"
        ):
            _ = (
                DesignIndex(FRAMEWORK)
                .get(
                    path,
                    text=markdown.replace(
                        producer.replace(".", "_") + "_001", "tampered"
                    ),
                )
                .raw.display_lines
            )


@pytest.fixture
def noted_policies(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        producer, key, scope, values = project(tmp_path)
        key["observed.row.001-001.value"] = (
            "`arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012`"
        )
        save(producer, key)
        for key, value in list(values.items()):
            if ".001" in key:
                values[key.replace(".001", ".002")] = (
                    value.replace("saved-001", "saved-002")
                    .replace("IAM_ManagedPolicy_001", "IAM_ManagedPolicy_002")
                    .replace("synthetic-policy", "second-policy")
                    .replace("policy.json", "second.json")
                )
        values["desired.service.identity.lastAllocated"] = '{"IAM.ManagedPolicy":2}'
        save(scope, values)
        values["desired.note.001.text"] = "サービス全体の注記\n複数行の説明"
        values["desired.note.002.text"] = "もう一つの注記"
        path = tmp_path / "docs/designs/qa/team/iam.md"
        yield path, scope, values


@pytest.mark.parametrize("notes", ["none", "single", "multiple"])
@pytest.mark.parametrize("single_resource", [False, True])
def check_service_notes_are_outside_resource_display(
    noted_policies, notes, single_resource
):
    path, scope, values = noted_policies
    if single_resource:
        values = {key: value for key, value in values.items() if ".002" not in key}
    if notes != "multiple":
        values = {
            key: value
            for key, value in values.items()
            if not key.startswith("desired.note.")
        }
    if notes == "single":
        values["desired.note.001.text"] = "サービス全体の注記"
    save(
        scope,
        {
            key: value
            for key, value in values.items()
            if not key.startswith("desired.note.")
        },
    )
    markdown = generate_markdown(path, values, FRAMEWORK)
    without_notes = {
        key: value
        for key, value in values.items()
        if not key.startswith("desired.note.")
    }
    suffix = "".join(
        "\n\n" + value
        for key, value in values.items()
        if key.startswith("desired.note.")
    )
    assert (
        markdown
        == generate_markdown(path, without_notes, FRAMEWORK)[:-1] + suffix + "\n"
    )
    recovered = model_resource_reference_tables(path, markdown, values, FRAMEWORK)
    assert len(recovered) == (1 if single_resource else 2)
    assert all(error is None for _, _, error in recovered)
    assert model_reference_tables(path, markdown, tuple(values.items()), FRAMEWORK)


@pytest.mark.parametrize("change", ["attribute", "policy", "row"])
@pytest.mark.parametrize("last", [False, True])
@pytest.mark.parametrize(
    "notes,note_changed", [(False, False), (True, False), (True, True)]
)
def check_resource_differences_survive_service_notes(
    noted_policies, change, last, notes, note_changed
):
    path, _, values = noted_policies
    if not notes:
        values = {
            key: value
            for key, value in values.items()
            if not key.startswith("desired.note.")
        }
    markdown = generate_markdown(path, values, FRAMEWORK)
    before, after = markdown.split(
        "<!-- resource-logical-id: IAM_ManagedPolicy_002 -->"
    )
    target = after if last else before
    changed = {
        "attribute": target.replace(
            "`second-policy`" if last else "`synthetic-policy`", "`edited-policy`"
        ),
        "policy": target.replace("kms:Decrypt", "kms:Encrypt", 1),
        "row": target.replace("合成JSON", "改変された行", 1),
    }[change]
    changed = "<!-- resource-logical-id: IAM_ManagedPolicy_002 -->".join(
        (before, changed) if last else (changed, after)
    )
    if note_changed:
        changed = changed.replace("もう一つの注記", "変更した注記")
    assert changed != markdown
    recovered = model_resource_reference_tables(path, changed, values, FRAMEWORK)
    assert [error is not None for _, _, error in recovered] == [
        not last,
        last or note_changed,
    ]
    assert isinstance(recovered[int(last)][2], DisplayMismatchError)
    if note_changed and not last:
        assert "boundary unavailable" in str(recovered[-1][2])
    with pytest.raises(ValueError, match="Model expected display") as caught:
        model_reference_tables(path, changed, tuple(values.items()), FRAMEWORK)
    if note_changed:
        assert any(
            item["savedDisplay"] == "変更した注記"
            and item["expectedDisplay"] == "もう一つの注記"
            for item in caught.value.positions
        )


@pytest.mark.parametrize(
    "change",
    ["changed", "deleted", "multiline", "unknown_heading", "trailing"],
)
@pytest.mark.parametrize("model_changed", [False, True])
def check_service_note_differences_remain_document_failures(
    noted_policies, change, model_changed
):
    path, scope, values = noted_policies
    markdown = generate_markdown(path, values, FRAMEWORK)
    changed = {
        "changed": markdown.replace("もう一つの注記", "改変した注記"),
        "deleted": markdown.replace("\nもう一つの注記", ""),
        "multiline": markdown.replace("複数行の説明", "変更した説明\n追加の説明"),
        "unknown_heading": markdown + "\n## 未知の末尾テキスト\n",
        "trailing": markdown + "未知の末尾テキスト\n",
    }[change]
    if model_changed:
        if change in {"deleted", "trailing"}:
            values = {
                k: v for k, v in values.items() if not k.startswith("desired.note.")
            }
        elif change == "multiline":
            values = {**values, "desired.note.001.text": "変更した注記\n追加の説明"}
        else:
            values = {**values, "desired.note.002.text": "変更した注記"}
        changed = markdown
        if change == "unknown_heading":
            changed += "\n## 未知の末尾テキスト\n"
        elif change == "trailing":
            changed += "未知の末尾テキスト\n"
    recovered = model_resource_reference_tables(path, changed, values, FRAMEWORK)
    assert len(recovered) == 2
    assert recovered[0][2] is None
    if model_changed and change in {"deleted", "trailing"}:
        assert isinstance(recovered[1][2], DisplayMismatchError)
    else:
        assert "boundary unavailable" in str(recovered[1][2])
        assert not isinstance(recovered[1][2], DisplayMismatchError)
    with pytest.raises(ValueError, match="Model expected display"):
        model_reference_tables(path, changed, tuple(values.items()), FRAMEWORK)
    path.parent.mkdir(parents=True)
    path.write_text(changed, encoding="utf-8")
    expected = generate_markdown(path, values, FRAMEWORK)
    plan = SimpleNamespace(
        root=scope.root,
        snapshot=GenerationInputs(scope.root, read_only=True),
        expected_outputs={path: {path: expected}},
        failure_records=[],
        saved={},
    )
    _compare_generation(plan)
    assert "generation.mismatch" in {item.code for item in plan.failure_records}
    assert not plan.saved
    validator = Validator(
        scope.root, {("qa", "team", "iam")}, definitions_root=FRAMEWORK
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    with patch("validation.design_tables.design_model_values", return_value=values):
        validator.check_design_tables(
            *validator.check_design_service_ownership([path]), paths=[path]
        )
    assert validator.findings.status == "FAIL"
    assert {item["resource"] for item in validator.findings.unverified} == {
        "document",
        "IAM_ManagedPolicy_002",
    }


def check_ambiguous_service_note_resource_identity_is_not_accepted(noted_policies):
    path, _, values = noted_policies
    markdown = generate_markdown(path, values, FRAMEWORK)
    ambiguous = (
        markdown
        + '\n<!-- resource-logical-id: IAM_ManagedPolicy_002 -->\n<a id="saved-002"></a>\n\n### IAM.ManagedPolicy: second-policy\n'
    )
    with pytest.raises(ValueError, match="duplicate saved Resource anchor"):
        model_resource_reference_tables(path, ambiguous, values, FRAMEWORK)
    with pytest.raises(ValueError):
        model_reference_tables(path, ambiguous, tuple(values.items()), FRAMEWORK)


@pytest.mark.parametrize(
    "note",
    [
        "### IAM.ManagedPolicy: note-example",
        "# 説明\n## 注意\n### IAM.ManagedPolicy: note-example\n#### 詳細",
        '<!-- resource-logical-id: Note_001 -->\n<a id="note"></a>\n\n'
        "### IAM.ManagedPolicy: note-example\n\n"
        "| No. | Property | Value | Source / Comment |\n"
        "| ---: | --- | --- | --- |\n| 1 | Name | `note` | 注記 |",
    ],
)
def check_resource_like_service_notes_are_not_resources(noted_policies, note):
    path, scope, values = noted_policies
    values["desired.note.002.text"] = note
    markdown = generate_markdown(path, values, FRAMEWORK)
    recovered = model_resource_reference_tables(path, markdown, values, FRAMEWORK)
    assert len(recovered) == 2
    assert all(error is None for _, _, error in recovered)
    assert model_reference_tables(path, markdown, tuple(values.items()), FRAMEWORK)
    document = DesignIndex(FRAMEWORK).get(path, text=markdown, values=values)
    assert document.lines == tuple(markdown.splitlines())
    assert "note-example" not in "\n".join(document.headings.lines)
    assert "note-example" not in "\n".join(document.raw.expanded[0])
    path.parent.mkdir(parents=True)
    path.write_text(markdown, encoding="utf-8")
    validator = Validator(
        scope.root, {("qa", "team", "iam")}, definitions_root=FRAMEWORK
    )
    validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
    with patch("validation.design_tables.design_model_values", return_value=values):
        metadata = validator.check_design_service_ownership([path])
        validator.check_design_tables(*metadata, paths=[path])
    with patch("validation.design.design_model_values", return_value=values):
        validator.check_resource_names(metadata[0], paths=[path])
    assert validator.findings.status == "PASS", validator.findings.errors


@pytest.mark.parametrize("notes", [False, True])
@pytest.mark.parametrize(
    "addition",
    [
        "| No. | Property | Value | Source / Comment |\n"
        "| ---: | --- | --- | --- |\n| 1 | Unknown | `bad` | 不正な属性 |",
        "| 99 | Unknown | `bad` | 不正なRow |",
        "任意の不正な追記",
        "## 不正な追記\n不正な本文",
    ],
)
def check_last_resource_additions_are_not_ignored(noted_policies, notes, addition):
    path, _, values = noted_policies
    without_notes = {
        key: value
        for key, value in values.items()
        if not key.startswith("desired.note.")
    }
    markdown = generate_markdown(path, values if notes else without_notes, FRAMEWORK)
    if notes:
        markdown = markdown.replace(
            "\n\nサービス全体の注記", "\n\n" + addition + "\n\nサービス全体の注記", 1
        )
    else:
        markdown += "\n" + addition + "\n"
    recovered = model_resource_reference_tables(
        path, markdown, values if notes else without_notes, FRAMEWORK
    )
    assert recovered[0][2] is None
    assert isinstance(recovered[1][2], DisplayMismatchError), recovered[1][2]
    with pytest.raises(ValueError):
        model_reference_tables(
            path,
            markdown,
            tuple((values if notes else without_notes).items()),
            FRAMEWORK,
        )


def check_deleted_service_suffix_keeps_resources_available(noted_policies):
    path, _, values = noted_policies
    without_notes = {
        key: value
        for key, value in values.items()
        if not key.startswith("desired.note.")
    }
    markdown = generate_markdown(path, without_notes, FRAMEWORK)
    recovered = model_resource_reference_tables(path, markdown, values, FRAMEWORK)
    assert len(recovered) == 2
    assert all(error is None for _, _, error in recovered)
    with pytest.raises(ValueError, match="Model expected display"):
        model_reference_tables(path, markdown, tuple(values.items()), FRAMEWORK)


def check_changed_note_heading_keeps_independent_recovery(noted_policies):
    path, _, values = noted_policies
    markdown = generate_markdown(path, values, FRAMEWORK).replace(
        "もう一つの注記", "### IAM.ManagedPolicy: changed-note"
    )
    recovered = model_resource_reference_tables(path, markdown, values, FRAMEWORK)
    assert recovered[0][2] is None
    assert "boundary unavailable" in str(recovered[1][2])
    with pytest.raises(ValueError):
        model_reference_tables(path, markdown, tuple(values.items()), FRAMEWORK)


def check_unknown_resource_identity_is_rejected(noted_policies):
    path, _, values = noted_policies
    markdown = generate_markdown(path, values, FRAMEWORK)
    foreign = (
        '<!-- resource-logical-id: IAM_ManagedPolicy_999 -->\n<a id="foreign"></a>\n\n'
        "### IAM.ManagedPolicy: foreign\n"
    )
    markdown = markdown.replace(
        "\n\nサービス全体の注記", "\n\n" + foreign + "\nサービス全体の注記"
    )
    with pytest.raises(ValueError, match="Resource groups differ from Model"):
        model_resource_reference_tables(path, markdown, values, FRAMEWORK)


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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        validator = Validator(
            tmp_path, {("qa", "team", "lambda")}, definitions_root=FRAMEWORK
        )
        validator.schema_catalog = DesignSchemaCatalog(FRAMEWORK)
        with patch(
            "design.document.model_resource_reference_tables",
            wraps=model_resource_reference_tables,
        ) as fallback:
            validator.check_design_tables(
                *validator.check_design_service_ownership([path]), paths=[path]
            )
        assert (
            not validator.findings.unverified
            and not validator.findings.processing_errors
        )
        fallback.assert_not_called()
        recovered = model_resource_reference_tables(path, markdown, current, FRAMEWORK)
        assert len(recovered) == 1 and recovered[0][2] is None
        assert recovered[0][1] == model_reference_tables(
            path, markdown, tuple(current.items()), FRAMEWORK
        )


@pytest.mark.parametrize("tamper", ["none", "parent", "child"])
@pytest.mark.parametrize("note_changed", [False, True])
def check_grouped_resource_recovery_keeps_parent_and_children_together(
    tmp_path, tamper, note_changed
):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        resource(
            tmp_path,
            "s3",
            "S3.Bucket",
            attribute="Arn",
            observed="arn:aws:s3:::synthetic-bucket",
        )
        values = permission_fixture(parents=2)
        for identity in ("002", "004"):
            values.update(
                {
                    f"desired.row.{identity}-007.property": "Lambda.Permission.SourceArn",
                    f"desired.row.{identity}-007.value": "`"
                    + json.dumps(reference("S3_Bucket_001", "Arn"))
                    + "`",
                    f"desired.row.{identity}-007.comment": "呼出元",
                }
            )
        values["desired.note.001.text"] = "サービス全体の注記"
        values["desired.note.002.text"] = "もう一つの注記"
        scope = sources.Scope(tmp_path, "qa", "team", "lambda")
        write_model(scope.path, values)
        path = tmp_path / "docs/designs/qa/team/lambda.md"
        markdown = generate_markdown(path, values, FRAMEWORK)
        if note_changed:
            values["desired.note.002.text"] = "変更した注記"
        del values["desired.resource.002.parentProperty"]
        write_model(scope.path, values)
        if tamper == "parent":
            markdown = markdown.replace(
                "### Lambda.Function: app-dev-worker-2",
                "### Lambda.Function: tampered-worker",
            )
        elif tamper == "child":
            markdown = markdown.replace(
                "`events.amazonaws.com`", "`lambda.amazonaws.com`"
            )
        with pytest.raises(ValueError, match="parentProperty"):
            model_reference_tables(path, markdown, tuple(values.items()), FRAMEWORK)
        recovered = model_resource_reference_tables(path, markdown, values, FRAMEWORK)
        assert len(recovered) == 2
        assert "parentProperty" in str(recovered[0][2])
        if tamper != "none":
            assert "differs from Model" in str(recovered[1][2])
        elif note_changed:
            assert "boundary unavailable" in str(recovered[1][2])
        else:
            assert recovered[1][2] is None
            assert {
                resource.logical_id
                for table in recovered[1][1]
                for resource in table.resources
            } == {"Lambda_Function_002", "Lambda_Permission_002"}


if __name__ == "__main__":
    raise SystemExit(run(__file__))

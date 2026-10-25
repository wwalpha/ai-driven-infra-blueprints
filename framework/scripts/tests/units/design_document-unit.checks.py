#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import design.layout as _imports_design_layout
import model.projection as _imports_model_projection
import pytest
import support.model_reference_fixtures as reference_models
import support.model_sources as _imports_support_model_sources
import sync_runtime as _imports_sync_runtime
import validation.design_links as _imports_validation_design_links
from support.design_document_fixtures import (
    DesignIndex,
    Path,
    ThreadPoolExecutor,
    aws_mapping_display,
    documents,
    hashlib,
    model_design,
    model_projection,
    patch,
    reference_fixture,
    sys,
    tempfile,
)
from support.validator import diagnostics, load
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_snapshots_request(first, index, path, /, _):
    document = index.get(path.parent / ".." / path.parent.name / path.name)
    assert document is first
    return document.view(frozenset({"kms-aliastwo"})).expanded


def check_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        _, path, _, _ = reference_fixture(root)
        read_text = Path.read_text
        with (
            patch.object(
                Path, "read_text", autospec=True, side_effect=read_text
            ) as reads,
            patch.object(
                documents, "expanded_design", wraps=documents.expanded_design
            ) as expands,
            patch.object(
                documents, "resource_logical_ids", wraps=documents.resource_logical_ids
            ) as identities,
        ):
            index = DesignIndex()
            first = index.get(path)
            request = _bind_framework_callback(
                _callback_check_snapshots_request, first, index, path
            )
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(request, range(12)))
            assert all(result is results[0] for result in results)
            assert (
                sum(call.args[0].suffix == ".md" for call in reads.call_args_list)
                == expands.call_count
                == identities.call_count
                == 1
            )
            # A sibling alias selects the same grouped parent and shares its parse.
            assert first.view(frozenset({"kms-aliasone"})).expanded is results[0]
            assert expands.call_count == identities.call_count == 1
            original = first.text
            path.write_text(
                original.replace("alias/two", "alias/changed"), encoding="utf-8"
            )
            assert index.get(path) is first and first.text == original
            index.invalidate(path)
            refreshed = index.get(path)
            assert refreshed is not first and "alias/changed" in refreshed.text
            assert (
                sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2
            )
            assert first.text == original
            path.unlink()
            index.invalidate(path)
            try:
                index.get(path)
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("invalidated missing target was reused")
        try:
            _ = first.headings.expanded
        except ValueError as error:
            assert (
                str(error)
                == "resource logical ID metadata must precede its anchor and heading"
            )
        else:
            raise AssertionError(
                "unrelated invalid metadata was not retained in the full snapshot"
            )


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


@patch.object(
    aws_mapping_display,
    "MODEL_ONLY",
    aws_mapping_display.MODEL_ONLY | {"S3.Bucket.SourceKeyId"},
)
def check_snapshot():
    with tempfile.TemporaryDirectory() as directory:
        source, target, text, _ = reference_fixture(Path(directory).resolve())
        index = DesignIndex()
        read_text = Path.read_text
        with (
            patch.object(
                Path, "read_text", autospec=True, side_effect=read_text
            ) as reads,
            patch.object(
                documents, "expanded_design", wraps=documents.expanded_design
            ) as expands,
        ):
            projection = index.get(source).headings.expanded
            assert (
                sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 1
            )
            assert expands.call_count == 1  # The source table is normalized once.
            assert model_projection.linked_resource(
                source, "[alias/two](kms.md#resource-AliasTwo)", design_index=index
            ) == ("KMS.Alias", "AliasTwo")
            assert model_projection.linked_resource(
                source, "[key](kms.md#kms-keyone)", design_index=index
            ) == ("KMS.Key", "KeyHidden")
            assert (
                model_projection.linked_resource(
                    source, "[missing](kms.md#absent)", design_index=index
                )
                is None
            )
            assert (
                model_projection.linked_resource(
                    source, "[missing](absent.md#absent)", design_index=index
                )
                is None
            )
            assert (
                model_projection.linked_resource(source, "literal", design_index=index)
                is None
            )
            assert model_projection.linked_resource(
                source, "[alias/three](kms.md#resource-AliasThree)", design_index=index
            ) == ("KMS.Alias", "AliasThree")
            assert expands.call_count == 4
            assert (
                sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2
            )
        assert projection is index.get(source).headings.expanded
        assert index.get(source).headings.expanded is index.get(source).raw.expanded
        repository = Path(__file__).resolve().parents[4]
        values = {
            "desired.service.s3.serviceId": "s3",
            "desired.service.s3.ownedCatalogResourceTypes": "S3.Bucket",
            "desired.resource.001.resourceType": "S3.Bucket",
            "desired.service.identity.lastAllocated": '{"S3.Bucket":1}',
            "desired.resource.001.logicalId": "S3_Bucket_001",
            "desired.note.001.text": "<!-- [hidden](hidden.md#hidden) -->",
        }
        rows = [
            ("S3.Bucket.BucketName", "`app-data`", "bucketの名前"),
            ("S3.Bucket.Region", "`us-east-1`", "bucketを配置するregion"),
        ]
        rows += [
            (
                "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID",
                f"[alias/{'two' if n % 2 == 0 else 'three'}](kms.md#resource-Alias{'Two' if n % 2 == 0 else 'Three'})",
                "暗号化に使用するKMS alias",
            )
            for n in range(80)
        ]
        rows += [
            ("S3.Bucket.SourceKeyId", "[KeyHidden](kms.md#kms-keyone)", "参照ID"),
            ("S3.Bucket.SourceKeyId", "[unresolved](absent.md#absent)", "未解決参照"),
            ("S3.Bucket.SourceKeyId", "[unresolved](kms.md#absent)", "未解決anchor"),
        ]
        for number, row in enumerate(rows, 1):
            values.update(
                {
                    f"desired.row.001-{number:03d}." + field: value
                    for field, value in zip(
                        ("property", "value", "comment"), row, strict=False
                    )
                }
            )
        values.update(
            {
                "observed.row.001-083.property": "S3.Bucket.SourceKeyId",
                "observed.row.001-083.value": "1234abcd-12ab-34cd-56ef-1234567890ab",
                "observed.row.001-083.comment": "参照ID",
            }
        )
        values.update(
            {
                "display.service.title": "# S3 詳細設計",
                "display.resource.001.comment": "アプリケーションのデータを保管するbucket",
            }
        )
        values["desired.resource.001.resourceMode"] = "IMPORT"

        write_model = _imports_support_model_sources.write_model
        project_root = source.parents[4]
        (project_root / "project.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "environment": "dev",
                            "alias": "account",
                            "awsAccountId": "123456789012",
                            "awsRegion": "us-east-1",
                            "iacEngine": "cloudformation",
                        }
                    ]
                }
            )
        )
        values["desired.resource.001.anchor"] = "s3-app-data"
        write_model(project_root / "model/dev/account/s3.properties", values)
        rendered = model_design.markdown_for(
            source, values, project_root, definitions_root=repository
        )
        assert (
            hashlib.sha256(rendered.encode()).hexdigest()
            == "28a9c8d82fc0b72d82245953c5ccc5d13303d707f7907c6128769844c629a1ea"
        ), hashlib.sha256(rendered.encode()).hexdigest()
        # Alias links also retain an explicit consumer observation, without inventing Alias identifiers.
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        alias_source = dict(values)
        alias_source.update(
            {
                "observed.row.001-003.property": values["desired.row.001-003.property"],
                "observed.row.001-003.comment": values["desired.row.001-003.comment"],
                "observed.row.001-003.value": observed,
            }
        )
        alias_text = text.replace(
            "[alias/two](kms.md#resource-AliasTwo)",
            f"[{observed}](kms.md#resource-AliasTwo)",
            1,
        )
        source.write_text(alias_text, encoding="utf-8")
        resource_rows = _imports_model_projection.resource_rows
        shown = resource_rows(alias_source, "001", "S3.Bucket", repository)
        assert shown[2][2] == f"[{observed}](kms.md#resource-AliasTwo)", shown
        assert (
            values["desired.row.001-003.value"]
            == "[alias/two](kms.md#resource-AliasTwo)"
        )

        _compare_generation = _imports_sync_runtime._compare_generation
        for changed in (
            alias_text.replace(observed, "different", 1),
            alias_text.replace("resource-AliasTwo", "resource-AliasThree", 1),
        ):
            source.write_text(changed, encoding="utf-8")
            plan = SimpleNamespace(
                root=source.parent,
                read_inputs={},
                expected_outputs={source: {source: alias_text}},
                failures=[],
                saved={},
            )
            _compare_generation(plan)
            assert plan.failures == ["generated Markdown is stale or missing: s3.md"]
        resource_modes = _imports_design_layout.resource_modes
        for mode in ("CREATE", "IMPORT"):
            source.write_text(
                f"<!-- resource-mode: s3-app-data {mode} -->\n" + text, encoding="utf-8"
            )
            assert (
                resource_modes(
                    source.read_text().splitlines(),
                    values | {"desired.resource.001.resourceMode": mode},
                )["s3-app-data"]
                == mode
            )


@patch.object(
    aws_mapping_display,
    "MODEL_ONLY",
    aws_mapping_display.MODEL_ONLY | {"S3.Bucket.SourceKeyId"},
)
def check_links():
    module = load("validate-blueprint")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        source, target, text, ref = reference_fixture(root)
        location = "docs/designs/dev/account/s3.md: "
        missing = [
            "broken design link: " + location + "absent.md#absent",
            "missing design anchor: " + location + "kms.md#absent",
        ]
        alias_error = (
            "S3 KMSMasterKeyID must display the referenced KMS alias name: " + location
        )
        internal = (
            [
                "design link must not display internal logical ID: "
                + location
                + "AliasTwo"
            ]
            * 40
            + missing
            + [alias_error + "AliasTwo"] * 40
        )
        valid = text.replace(
            "| 84 | SourceKeyId | [unresolved](absent.md#absent) | 未解決参照 |\n", ""
        ).replace(
            "| 85 | SourceKeyId | [unresolved](kms.md#absent) | 未解決anchor |\n", ""
        )
        # Exact diagnostic messages and check counts; repeated warnings are deduplicated.
        cases = [
            (text, ref, missing, 416),
            (valid, ref, [], 409),
            (text.replace("[alias/two]", "[AliasTwo]"), ref, internal, 416),
            (
                text,
                ref.replace(
                    "resource-logical-id: KeyHidden", "resource-logical-id: Bad!"
                ),
                [
                    "invalid grouped design: docs/designs/dev/account/kms.md: resource logical ID metadata must precede its anchor and heading",
                    *missing,
                ],
                254,
            ),
            (
                text,
                ref.replace("kms-keytwo", "kms-keyone"),
                ["duplicate resource anchor", *missing],
                253,
            ),
            (
                text,
                ref.replace("logical-id: AliasTwo", "logical-id: AliasOne"),
                [
                    "invalid grouped design: docs/designs/dev/account/kms.md: invalid or duplicate grouped logical ID/anchor: AliasOne",
                    *missing,
                ],
                254,
            ),
            (text, "<!-- resource-mode: kms-keyone CREATE -->\n" + ref, missing, 416),
            (text, "<!-- resource-mode: kms-keyone IMPORT -->\n" + ref, missing, 416),
            (
                text.replace(
                    '<a id="s3-app-data"></a>',
                    '<!-- resource-logical-id: Bad! -->\n<a id="s3-app-data"></a>',
                ),
                ref,
                [
                    "invalid grouped design: "
                    + location
                    + "resource logical ID metadata must precede its anchor and heading",
                    *missing,
                ],
                252,
            ),
            (
                text.replace("| 1 | BucketName", "| 1 | KMS.Alias.AliasName"),
                ref,
                [
                    "invalid grouped design: "
                    + location
                    + "grouped resource has wrong parent: KMS.Alias: S3.Bucket",
                    *missing,
                ],
                252,
            ),
        ]
        validator = module.Validator(root)
        for content, referenced, expected, checks in cases:
            source.write_text(content, encoding="utf-8")
            target.write_text(referenced, encoding="utf-8")
            # Reusing the Validator object must not retain snapshots between calls.
            validator.errors.clear()
            validator.findings.warnings.clear()
            validator.checks = 0
            validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert sorted(set(diagnostics(validator))) == sorted(set(expected)), (
                diagnostics(validator)
            )
            assert all(
                error.startswith("invalid grouped design:")
                for error in validator.errors
            )
            assert validator.checks == checks
        design_links = _imports_validation_design_links
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        model = {
            "desired.resource.001.resourceType": "S3.Bucket",
            "desired.resource.001.logicalId": "S3_Bucket_001",
            "desired.resource.001.anchor": "resource-S3_Bucket_001",
            "desired.service.identity.lastAllocated": '{"S3.Bucket":1}',
            "desired.row.001-001.property": "S3.Bucket.SourceKeyId",
            "desired.row.001-001.value": "[alias/two](kms.md#resource-AliasTwo)",
            "observed.row.001-001.value": observed,
        }
        alias_text = valid.replace("s3-app-data", "resource-S3_Bucket_001").replace(
            f"[{observed}](kms.md#kms-keyone)",
            f"[{observed}](kms.md#resource-AliasTwo)",
        )
        for content, expected in [
            (alias_text, []),
            (alias_text.replace(observed, "different"), ["different"]),
            (
                alias_text.replace(
                    f"[{observed}](kms.md#resource-AliasTwo)",
                    f"[{observed}](kms.md#resource-AliasThree)",
                ),
                [observed],
            ),
        ]:
            source.write_text(content, encoding="utf-8")
            target.write_text(ref, encoding="utf-8")
            validator.errors.clear()
            validator.findings.warnings.clear()
            with patch.object(design_links, "design_model_values", return_value=model):
                validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert not validator.errors
            assert len(validator.findings.warnings) == len(expected), (
                validator.findings.warnings
            )
            assert all(
                label in error
                for label, error in zip(expected, diagnostics(validator), strict=False)
            )
        source.write_text(text, encoding="utf-8")
        target.write_text(ref, encoding="utf-8")
        read_text = Path.read_text
        with patch.object(
            Path, "read_text", autospec=True, side_effect=read_text
        ) as reads:
            validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert (
                sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2
            )


@pytest.mark.parametrize(
    "metadata",
    ["", "<!-- reference-rows: obsolete -->\n", "<!-- reference-value: obsolete -->\n"],
)
def check_candidate_saved_reference_boundary(tmp_path, metadata):
    source, target, _, target_text = reference_fixture(tmp_path, count=1)
    # Limit the candidate to a real link with no pre-existing missing references.
    source.write_text(
        '<a id="bucket"></a>\n### S3.Bucket: bucket\n'
        "| No. | Property | Value | Comment |\n| ---: | --- | --- | --- |\n"
        "| 1 | BucketName | `bucket` | 合成バケット |\n"
        "| 2 | BucketEncryption[].KMSMasterKeyID | [wrong](kms.md#resource-AliasTwo) | 合成参照 |\n",
        encoding="utf-8",
    )
    target.write_text(
        target_text.replace(
            "### KMS.Key: KeyOne\n", "### KMS.Key: KeyOne\n" + metadata
        ),
        encoding="utf-8",
    )
    before = target.read_bytes()
    findings = Findings(tmp_path)
    with patch.object(
        documents, "model_reference_tables", wraps=documents.model_reference_tables
    ) as strict:
        _imports_validation_design_links.check_design_links(
            {},
            [source],
            design_sources={source: {}},
            findings=findings,
            root=tmp_path,
            scope=None,
            candidate_paths={source},
        )
        assert all(call.args[0] == source for call in strict.call_args_list)
    assert not findings.errors, findings.errors
    if metadata:
        assert any(
            warning["code"] == "design.links_unverified"
            for warning in findings.warnings
        ), findings.warnings
    else:
        assert not any(
            warning["code"] == "design.links_unverified"
            for warning in findings.warnings
        )
        assert any(
            "must display the referenced KMS alias name" in warning["message"]
            for warning in findings.warnings
        )
    assert target.read_bytes() == before
    if metadata:
        with pytest.raises(ValueError, match="obsolete Model reference metadata"):
            _ = (
                DesignIndex()
                .get(target)
                .view(frozenset({"resource-AliasTwo"}))
                .expanded
            )
        strict = Findings(tmp_path)
        _imports_validation_design_links.check_design_links(
            {},
            [source, target],
            design_sources={source: {}, target: {}},
            findings=strict,
            root=tmp_path,
            scope=None,
            candidate_paths={source, target},
        )
        assert any(
            "obsolete Model reference metadata" in error for error in strict.errors
        ), strict.errors


def check_saved_typed_reference_display_difference(project_workspace):
    root = project_workspace
    reference_models.project(root)
    reference_models.resource(
        root, "iam", "IAM.Role", observed="arn:aws:iam::123456789012:role/fixture-role"
    )
    scope, values = reference_models.resource(
        root, "codepipeline", "CodePipeline.Pipeline", attribute="Name"
    )
    values.update(
        {
            "desired.row.001-001.value": "`synthetic-pipeline`",
            "desired.row.001-002.property": "CodePipeline.Pipeline.RoleArn",
            "desired.row.001-002.value": "`"
            + json.dumps(reference_models.reference("IAM_Role_001", "Arn"))
            + "`",
            "desired.row.001-002.comment": "合成参照",
        }
    )
    reference_models.save(scope, values)
    target = root / "docs/designs/qa/team/codepipeline.md"
    target.parent.mkdir(parents=True)
    markdown = model_design.generate_markdown(
        target, values, reference_models.FRAMEWORK
    )
    target.write_text(markdown + "\n<!-- stale display -->\n", encoding="utf-8")
    source = target.with_name("consumer.md")
    source.write_text("[pipeline](codepipeline.md#saved-001)\n", encoding="utf-8")
    before = target.read_bytes()
    findings = Findings(root)
    _imports_validation_design_links.check_design_links(
        {},
        [source],
        design_sources={source: {}},
        findings=findings,
        root=root,
        scope=None,
        definitions_root=reference_models.FRAMEWORK,
        candidate_paths={source},
    )
    assert not findings.errors, findings.errors
    assert target.read_bytes() == before
    # The same saved typed reference still requires exact display in read-only validation.
    strict = Findings(root)
    with patch.object(
        documents, "model_reference_tables", wraps=documents.model_reference_tables
    ) as render:
        document = DesignIndex(reference_models.FRAMEWORK).get(target)
        assert document.headings.lines
        render.assert_not_called()
        with pytest.raises(
            ValueError, match="Markdown differs from Model expected display"
        ):
            _ = document.headings.expanded
    _imports_validation_design_links.check_design_links(
        {},
        [source],
        design_sources={source: {}},
        findings=strict,
        root=root,
        scope=None,
        definitions_root=reference_models.FRAMEWORK,
    )
    assert any(
        "Markdown differs from Model expected display" in error
        for error in strict.errors
    )
    assert strict.unverified and target.read_bytes() == before


@pytest.mark.parametrize("phase", ["view-build", "view-expand", "view-display"])
def check_view_failure_isolation(tmp_path, phase):
    source = tmp_path / "docs/designs/dev/team/codebuild.md"
    source.parent.mkdir(parents=True)
    source.write_text("# 合成\n[missing](missing.json)\n", encoding="utf-8")
    findings = Findings(tmp_path)
    owner, method = {
        "view-build": (documents.DesignDocument, "view"),
        "view-expand": (documents, "expanded_design"),
        "view-display": (documents, "model_reference_tables"),
    }[phase]
    with patch.object(owner, method, side_effect=ValueError("synthetic invalid View")):
        _imports_validation_design_links.check_design_links(
            {},
            [source],
            findings=findings,
            root=tmp_path,
            scope=None,
            design_sources={source: {}},
        )
    assert sum("synthetic invalid View" in error for error in findings.errors) == 1
    assert any("broken design link" in error for error in findings.errors)
    assert findings.unverified == [
        dict(
            code="design.links_unverified",
            reason="dependency",
            path="docs/designs/dev/team/codebuild.md",
            service="codebuild",
            phase=phase,
            exception="ValueError",
            message="synthetic invalid View",
            complete=False,
        )
    ]
    assert (
        findings.result("design.links", {("dev", "team", "codebuild")}).status
        == "NOT_RUN"
    )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

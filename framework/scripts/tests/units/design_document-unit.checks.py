#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import design.layout as _imports_design_layout
import pytest
import support.model_reference_fixtures as reference_models
import support.model_sources as _imports_support_model_sources
import sync_runtime as _imports_sync_runtime
import validation.design_links as _imports_validation_design_links
import yaml
from model.core import properties
from support.design_document_fixtures import (
    DesignIndex,
    Path,
    ThreadPoolExecutor,
    aws_mapping_display,
    documents,
    model_design,
    patch,
    reference_fixture,
    sys,
    tempfile,
)
from support.rotation_schedule_fixtures import fixture as rotation_fixture
from support.security_group_tables_fixtures import GENERATED_MODEL
from support.validator import diagnostics
from utils.aws_mappings import mapping_alias
from validation import runner as validation_runner
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
        assert projection is index.get(source).headings.expanded
        assert index.get(source).headings.expanded is index.get(source).raw.expanded
        project_root = source.parents[4]
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        alias_text = text.replace(
            "[alias/two](kms.md#resource-AliasTwo)",
            f"[{observed}](kms.md#resource-AliasTwo)",
            1,
        )
        values = {
            "desired.resource.001.resourceType": "S3.Bucket",
            "desired.resource.001.logicalId": "S3_Bucket_001",
            "desired.resource.001.anchor": "s3-app-data",
        }
        _compare_generation = _imports_sync_runtime._compare_generation
        for changed in (
            alias_text.replace(observed, "different", 1),
            alias_text.replace("resource-AliasTwo", "resource-AliasThree", 1),
        ):
            source.write_text(changed, encoding="utf-8")
            plan = SimpleNamespace(
                root=project_root,
                snapshot=_imports_sync_runtime.GenerationInputs(
                    project_root, read_only=True
                ),
                expected_outputs={source: {source: alias_text}},
                failure_records=[],
                saved={},
            )
            _compare_generation(plan)
            assert len(plan.failure_records) == 1
            diagnostic = plan.failure_records[0]
            assert diagnostic.code == "design.display.mismatch"
            assert diagnostic.source_path == "docs/designs/dev/account/s3.md"
            assert diagnostic.details["savedDisplay"] in changed
            assert diagnostic.details["expectedDisplay"] in alias_text
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
    module = validation_runner
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
    assert strict.status == "FAIL"
    assert {d.code for d in strict.diagnostics} == {"design.display.mismatch"}
    assert all(d.source_path.endswith("codepipeline.md") for d in strict.diagnostics)
    assert strict.unverified and target.read_bytes() == before


@pytest.mark.parametrize("phase", ["view-build", "view-expand", "view-display"])
def check_view_failure_isolation(tmp_path, phase):
    source = tmp_path / "docs/designs/dev/team/codebuild.md"
    source.parent.mkdir(parents=True)
    source.write_text("# 合成\n[missing](codebuild/missing.json)\n", encoding="utf-8")
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
    assert any(d.code == "design.artifact.missing" for d in findings.diagnostics)
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
            status="FAIL",
        )
    ]
    assert (
        findings.result("design.links", {("dev", "team", "codebuild")}).status == "FAIL"
    )


@pytest.mark.parametrize(
    "service,kind,field",
    [
        ("glue", "Glue.SecurityConfiguration", "EncryptionConfiguration.S3Encryptions"),
        (
            "secretsmanager",
            "SecretsManager.RotationSchedule",
            "ExternalSecretRotationMetadata",
        ),
    ],
)
@pytest.mark.parametrize("fault", [None, "unrelated", "table", "model"])
def check_candidate_indexed_saved_reference(tmp_path, service, kind, field, fault):
    reference_models.project(tmp_path)
    project_file = tmp_path / "project.json"
    project = json.loads(project_file.read_text(encoding="utf-8"))
    project["projectName"] = "synthetic"
    project["targets"].reverse()
    project_file.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    scope, values = reference_models.resource(tmp_path, service, kind, attribute="Name")
    if service == "secretsmanager":
        values = rotation_fixture(2)
        owner, first_row = "002", 4
        anchor = values["desired.resource.002.anchor"]
        parent_anchor = values["desired.resource.001.anchor"]
        unrelated = "app-dev-secret-2"
    else:
        values["desired.row.001-001.value"] = "`synthetic`"
        _, other = reference_models.resource(
            tmp_path, service, kind, attribute="Name", number="002"
        )
        values.update({key: value for key, value in other.items() if ".002" in key})
        values["desired.row.002-001.value"] = "`other`"
        values["desired.service.identity.lastAllocated"] = json.dumps({kind: 2})
        owner, first_row = "001", 2
        anchor = parent_anchor = "saved-001"
        unrelated = "other"
    for number in (1, 2):
        row = f"desired.row.{owner}-{first_row + number - 1:03}"
        prop = "KmsKeyArn" if service == "glue" else "Key"
        values.update(
            {
                row + ".property": f"{kind}.{field}[].{prop}",
                row + ".value": f"`value-{number}`",
                row + ".comment": "合成配列",
            }
        )
    reference_models.save(scope, values)
    target = tmp_path / f"docs/designs/qa/team/{service}.md"
    target.parent.mkdir(parents=True)
    with mapping_alias(reference_models.FRAMEWORK, tmp_path):
        text = model_design.generate_markdown(
            target, values, reference_models.FRAMEWORK
        )
    if fault == "unrelated":
        text = (
            text.replace(f"`{unrelated}`", "`stale`").replace(
                "### " + kind + ": " + unrelated, "### " + kind + ": stale-heading"
            )
            + "\n### IAM.Role: unrelated-note-heading\n注記の差分\n"
        )
    elif fault == "table":
        text = text.replace("`value-2`", "`tampered`")
    elif fault == "model":
        scope.path.unlink()
    target.write_text(text, encoding="utf-8")
    source = target.with_name("iam.md")
    iam_scope, iam = reference_models.resource(
        tmp_path, "iam", "IAM.Role", attribute="RoleName"
    )
    iam["desired.row.001-001.value"] = "`synthetic-role`"
    iam.update(
        {
            "desired.row.001-002.property": "IAM.Role.Description",
            "desired.row.001-002.value": "`"
            + json.dumps(
                reference_models.reference(
                    values[f"desired.resource.{owner}.logicalId"],
                    "Id" if service == "secretsmanager" else "Name",
                )
            )
            + "`",
            "desired.row.001-002.comment": "合成の配列参照先",
            "desired.row.001-003.property": "IAM.Role.AssumeRolePolicyDocument",
            "desired.row.001-003.value": "[trust](iam/trust.json)",
            "desired.row.001-003.comment": "合成信頼ポリシー",
            "desired.row.001-003.document": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        }
    )
    reference_models.save(iam_scope, iam)
    with mapping_alias(reference_models.FRAMEWORK, tmp_path):
        files = model_design.generate_files(source, iam, tmp_path)
    for file, content in files.items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    findings = Findings(tmp_path)
    result = findings.evaluate(
        "design.links",
        {("qa", "team", "iam")},
        _bind_framework_callback(
            _imports_validation_design_links.check_design_links,
            {},
            [source],
            design_sources={source: iam},
            findings=findings,
            root=tmp_path,
            scope=None,
            definitions_root=reference_models.FRAMEWORK,
            candidate_paths={source},
        ),
    )
    assert result.status == (
        "FAIL" if fault == "table" else "FAIL" if fault == "model" else "PASS"
    ), (findings.errors, findings.unverified)
    assert (result.status == "PASS") == (fault in (None, "unrelated"))
    if fault == "table":
        assert any(
            item.code == "design.display.mismatch" for item in findings.diagnostics
        )
        assert findings.unverified[0]["cause_keys"]
    if fault is None:
        document = DesignIndex(reference_models.FRAMEWORK).get(target)
        with patch.object(
            documents,
            "_model_reference_display",
            wraps=documents._model_reference_display,
        ) as render:
            view = document.reference_view(frozenset({anchor}))
            assert document.reference_view(frozenset({anchor})) is view
            render.assert_called_once()
            selected = render.call_args.args[1]
            assert {
                rid
                for rid, _ in documents._model_display.entries(
                    selected, "desired.resource."
                )
            } == ({"001", "002"} if service == "secretsmanager" else {"001"})
        assert view.document is None
        assert {table.anchor for table in view.reference_tables} == {parent_anchor}
        expanded = "\n".join(view.expanded[0])
        assert "value-1" in expanded and "value-2" in expanded
        assert (
            f"{field.split('.')[-1]}[1]" in text
            and f"{field.split('.')[-1]}[2]" in text
        )
    stage = tmp_path / "stage"
    for directory in ("model", "docs"):
        shutil.copytree(tmp_path / directory, stage / directory)
    shutil.copyfile(tmp_path / "project.json", stage / "project.json")
    plan = SimpleNamespace(
        root=tmp_path,
        stage=stage,
        generated={source: [stage / file.relative_to(tmp_path) for file in files]},
        destinations={source: iam},
        failure_records=[],
        failures=[],
        markdown_paths=[source],
        model_paths=[iam_scope.path],
        unavailable={},
        validation={},
        accounts=None,
        generated_scope={("qa", "team", "iam")},
        definitions_root=reference_models.FRAMEWORK,
        reference_warnings=[],
        expected_outputs={},
        snapshot=None,
        saved_paths=[],
    )
    _imports_sync_runtime.validate_generation(plan, jobs=1)
    assert source in plan.expected_outputs
    assert not plan.failure_records
    assert target.read_text(encoding="utf-8") == text


def check_scoped_import_security_group_reference(tmp_path):
    reference_models.project(tmp_path)
    scope, values = reference_models.resource(
        tmp_path,
        "security-group",
        "EC2.SecurityGroup",
        attribute="Id",
        observed="sg-11111111",
    )
    values["desired.resource.001.resourceMode"] = "IMPORT"
    values["display.resource.001.label"] = "imported-group"
    for number, (prop, value) in enumerate(
        (
            ("GroupDescription", "synthetic group"),
            ("GroupName", "imported-group"),
            ("VpcId", "vpc-11111111"),
        ),
        2,
    ):
        values.update(
            {
                f"desired.row.001-{number:03}.property": "EC2.SecurityGroup." + prop,
                f"desired.row.001-{number:03}.value": f"`{value}`",
                f"desired.row.001-{number:03}.comment": "合成設定",
            }
        )
    reference_models.save(scope, values)
    path = tmp_path / "docs/designs/qa/team/security-group.md"
    text = model_design.generate_markdown(path, values, reference_models.FRAMEWORK)
    # Parent-only references omit horizontal rules before parsing or comparison.
    text += "\n| Direction | invalid unrelated rule |\n| bad | bad |\n"
    document = DesignIndex(reference_models.FRAMEWORK).get(
        path, text=text, values=values
    )
    view = document.reference_view(frozenset({"saved-001"}))
    assert view.modes == {"saved-001": "IMPORT"}
    assert view.bound_anchors == {
        ("EC2.SecurityGroup", "EC2_SecurityGroup_001"): "saved-001"
    }
    assert "invalid unrelated rule" not in "\n".join(view.lines)
    assert "$modelRef" in "\n".join(view.expanded[0])
    assert document.reference_view(frozenset({"saved-001"})) is view


@pytest.mark.parametrize(
    "anchor,fault",
    [
        ("EC2_SecurityGroup_001", None),
        ("EC2_SecurityGroup_002", None),
        ("EC2_SecurityGroup_001", "basic"),
        ("EC2_SecurityGroup_001", "omitted"),
        ("EC2_SecurityGroup_002", "omitted"),
        ("EC2_SecurityGroup_001", "unrelated"),
        ("EC2_SecurityGroupIngress_001", None),
        ("EC2_SecurityGroupEgress_001", None),
        ("EC2_SecurityGroupIngress_001", "rule"),
        ("EC2_SecurityGroupEgress_001", "rule"),
    ],
)
def check_scoped_security_group_model_reference(
    tmp_path: Path, anchor: str, fault: str | None
) -> None:
    reference_models.project(tmp_path)
    model = tmp_path / "model/qa/team/security-group.properties"
    values = properties(GENERATED_MODEL)
    values["display.service.title"] = "# 合成Security Group"
    for identity, _ in documents._model_display.entries(values, "desired.resource."):
        values[f"display.resource.{identity}.comment"] = "合成SG"
    for row in ("001-004", "006-008"):
        values[f"desired.row.{row}.value"] = "`vpc-00000001`"
        values.pop(f"observed.row.{row}.value", None)
    _imports_support_model_sources.write_model(model, values)
    reference_models.dependency_index.rebuild(tmp_path)
    values = _imports_support_model_sources.load_model(model).values
    path = tmp_path / "docs/designs/qa/team/security-group.md"
    path.parent.mkdir(parents=True)
    markdown = model_design.generate_markdown(path, values, reference_models.FRAMEWORK)
    text = markdown
    assert "| Direction |" in text and "<!-- security-group-tags:" in text
    if fault == "basic":
        text = text.replace("`group-one`", "`tampered`")
    elif fault == "omitted":
        tags = next(
            line
            for line in text.splitlines()
            if line.startswith("<!-- security-group-tags:")
        )
        text = text.replace("`tcp`", "`tampered`").replace(
            tags, "<!-- security-group-tags: invalid -->"
        )
    elif fault == "unrelated":
        text = text.replace("`No selected rules`", "`tampered`")
    elif fault == "rule":
        rule = next(
            line for line in text.splitlines() if f'id="resource-{anchor}"' in line
        )
        text = text.replace(
            rule,
            rule.replace("`tcp`", "`udp`")
            if "Ingress" in anchor
            else rule.replace("`-1`", "`tcp`"),
        )
    if fault is not None:
        assert text != markdown
    path.write_text(text, encoding="utf-8")
    document = DesignIndex(reference_models.FRAMEWORK).get(path)
    fragments = frozenset({"resource-" + anchor})
    if fault in {"basic", "rule"}:
        with pytest.raises(documents.DisplayMismatchError):
            document.reference_view(fragments)
    else:
        view = document.reference_view(fragments)
        lines, children = view.expanded
        expanded = "\n".join(lines)
        if "SecurityGroup_" in anchor:
            assert not children
            assert "SecurityGroupIngress" not in expanded
            assert "SecurityGroupEgress" not in expanded
            assert "Tags[]" not in expanded
        else:
            assert "resource-" + anchor in children
            assert "IpProtocol" in expanded
        assert document.reference_view(fragments) is view

    source = path.with_name("iam.md")
    iam_scope, iam = reference_models.resource(
        tmp_path, "iam", "IAM.Role", attribute="RoleName"
    )
    iam["desired.row.001-001.value"] = "`consumer`"
    iam.update(
        {
            "desired.row.001-002.property": "IAM.Role.Description",
            "desired.row.001-002.value": "`"
            + json.dumps(
                reference_models.reference(
                    anchor,
                    "GroupId" if anchor.startswith("EC2_SecurityGroup_") else "Id",
                )
            )
            + "`",
            "desired.row.001-002.comment": "合成SG参照",
        }
    )
    reference_models.save(iam_scope, iam)
    source.write_text(
        model_design.generate_markdown(source, iam, reference_models.FRAMEWORK),
        encoding="utf-8",
    )
    findings = Findings(tmp_path)
    result = findings.evaluate(
        "design.links",
        {("qa", "team", "iam")},
        _bind_framework_callback(
            _imports_validation_design_links.check_design_links,
            {},
            [source],
            design_sources={source: iam},
            findings=findings,
            root=tmp_path,
            scope=None,
            definitions_root=reference_models.FRAMEWORK,
            candidate_paths={source},
        ),
    )
    assert result.status == ("FAIL" if fault in {"basic", "rule"} else "PASS"), (
        findings.errors,
        findings.unverified,
    )


def check_s3_replication_rules_markdown(tmp_path: Path) -> None:
    reference_models.project(tmp_path)
    scope, values = reference_models.resource(
        tmp_path, "s3", "S3.Bucket", attribute="BucketName"
    )
    mapping = yaml.safe_load(
        (reference_models.FRAMEWORK / "framework/mappings/aws/s3.yaml").read_text(
            encoding="utf-8"
        )
    )["resourceTypes"]["S3.Bucket"]["properties"]
    fields = [
        name for name in mapping if name.startswith("ReplicationConfiguration.Rules[]")
    ]
    assert len(fields) == 20
    rows = [("ReplicationConfiguration.Role", "replication-role")]
    for number in (1, 2):
        rows.extend(
            (field, f"value-{number}-{index}") for index, field in enumerate(fields)
        )
    for number, (field, value) in enumerate(rows, 2):
        values.update(
            {
                f"desired.row.001-{number:03}.property": "S3.Bucket." + field,
                f"desired.row.001-{number:03}.value": f"`{value}`",
                f"desired.row.001-{number:03}.comment": "設定",
            }
        )
    reference_models.save(scope, values)
    path = tmp_path / "docs/designs/qa/team/s3.md"
    text = model_design.generate_markdown(path, values, reference_models.FRAMEWORK)
    assert "replication-role" in text
    for number in (1, 2):
        for index, field in enumerate(fields):
            displayed = field.replace("Rules[]", f"Rules[{number}]").replace(
                "[]", "[1]"
            )
            assert f"{displayed} | `value-{number}-{index}`" in text


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

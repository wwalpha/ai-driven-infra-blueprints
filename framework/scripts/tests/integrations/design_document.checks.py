#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import design_layout as _imports_design_layout
import model.projection as _imports_model_projection
import support.model_sources as _imports_support_model_sources
import sync_runtime as _imports_sync_runtime
import validation.design_links as _imports_validation_design_links
from support.design_document_fixtures import (
    DesignIndex,
    Path,
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
from support.it_case_receipt import it_case
from support.validator import diagnostics

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@it_case
@patch.object(aws_mapping_display, 'MODEL_ONLY', aws_mapping_display.MODEL_ONLY | {'S3.Bucket.SourceKeyId'})
def check_snapshot(sync):
    with tempfile.TemporaryDirectory() as directory:
        source, target, text, _ = reference_fixture(Path(directory).resolve())
        index = DesignIndex()
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads, \
             patch.object(documents, "expanded_design", wraps=documents.expanded_design) as expands:
            projection = index.get(source).headings.expanded
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 1
            assert expands.call_count == 1  # The source table is normalized once.
            assert model_projection.linked_resource(source, "[alias/two](kms.md#resource-AliasTwo)", design_index=index) == ("KMS.Alias", "AliasTwo")
            assert model_projection.linked_resource(source, "[key](kms.md#kms-keyone)", design_index=index) == ("KMS.Key", "KeyHidden")
            assert model_projection.linked_resource(source, "[missing](kms.md#absent)", design_index=index) is None
            assert model_projection.linked_resource(source, "[missing](absent.md#absent)", design_index=index) is None
            assert model_projection.linked_resource(source, "literal", design_index=index) is None
            assert model_projection.linked_resource(source, "[alias/three](kms.md#resource-AliasThree)", design_index=index) == ("KMS.Alias", "AliasThree")
            assert expands.call_count == 4
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2
        assert projection is index.get(source).headings.expanded
        assert index.get(source).headings.expanded is index.get(source).raw.expanded
        repository = Path(__file__).resolve().parents[4]
        values = {'desired.service.s3.serviceId': 's3',
                  'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket',
                  'desired.resource.001.resourceType': 'S3.Bucket',
                  'desired.service.identity.lastAllocated': '{"S3.Bucket":1}',
                  'desired.resource.001.logicalId': 'S3_Bucket_001',
                  'desired.note.001.text': '<!-- [hidden](hidden.md#hidden) -->'}
        rows = [('S3.Bucket.BucketName', '`app-data`', 'bucketの名前'),
                ('S3.Bucket.Region', '`us-east-1`', 'bucketを配置するregion')]
        rows += [('S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID',
                  f'[alias/{"two" if n % 2 == 0 else "three"}](kms.md#resource-Alias{"Two" if n % 2 == 0 else "Three"})',
                  '暗号化に使用するKMS alias') for n in range(80)]
        rows += [('S3.Bucket.SourceKeyId', '[KeyHidden](kms.md#kms-keyone)', '参照ID'),
                 ('S3.Bucket.SourceKeyId', '[unresolved](absent.md#absent)', '未解決参照'),
                 ('S3.Bucket.SourceKeyId', '[unresolved](kms.md#absent)', '未解決anchor')]
        for number, row in enumerate(rows, 1):
            values.update({f'desired.row.001-{number:03d}.' + field: value for field, value in zip(('property', 'value', 'comment'), row, strict=False)})
        values.update({'observed.row.001-083.property': 'S3.Bucket.SourceKeyId',
                       'observed.row.001-083.value': '1234abcd-12ab-34cd-56ef-1234567890ab',
                       'observed.row.001-083.comment': '参照ID'})
        values.update({'display.service.title': '# S3 詳細設計',
                       'display.resource.001.comment': 'アプリケーションのデータを保管するbucket'})
        values["desired.resource.001.resourceMode"] = "IMPORT"

        write_model = _imports_support_model_sources.write_model
        project_root = source.parents[4]
        (project_root / "project.json").write_text(json.dumps({"targets": [{"environment": "dev", "alias": "account", "awsAccountId": "123456789012", "awsRegion": "us-east-1", "iacEngine": "cloudformation"}]}))
        values["desired.resource.001.anchor"] = "s3-app-data"
        write_model(project_root / "model/dev/account/s3.properties", values)
        rendered = model_design.markdown_for(source, values, project_root, definitions_root=repository)
        assert hashlib.sha256(rendered.encode()).hexdigest() == "28a9c8d82fc0b72d82245953c5ccc5d13303d707f7907c6128769844c629a1ea", hashlib.sha256(rendered.encode()).hexdigest()
        # Alias links also retain an explicit consumer observation, without inventing Alias identifiers.
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        alias_source = dict(values)
        alias_source.update({"observed.row.001-003.property": values["desired.row.001-003.property"],
                             "observed.row.001-003.comment": values["desired.row.001-003.comment"],
                             "observed.row.001-003.value": observed})
        alias_text = text.replace("[alias/two](kms.md#resource-AliasTwo)", f"[{observed}](kms.md#resource-AliasTwo)", 1)
        source.write_text(alias_text, encoding="utf-8")
        resource_rows = _imports_model_projection.resource_rows
        shown = resource_rows(alias_source, '001', 'S3.Bucket', repository)
        assert shown[2][2] == f'[{observed}](kms.md#resource-AliasTwo)', shown
        assert values['desired.row.001-003.value'] == '[alias/two](kms.md#resource-AliasTwo)'

        _compare_generation = _imports_sync_runtime._compare_generation
        for changed in (alias_text.replace(observed, 'different', 1),
                        alias_text.replace('resource-AliasTwo', 'resource-AliasThree', 1)):
            source.write_text(changed, encoding='utf-8')
            plan = SimpleNamespace(root=source.parent, read_inputs={}, expected_outputs={source: {source: alias_text}}, failures=[], saved={})
            _compare_generation(plan)
            assert plan.failures == ['generated Markdown is stale or missing: s3.md']
        resource_modes = _imports_design_layout.resource_modes
        for mode in ('CREATE', 'IMPORT'):
            source.write_text(f'<!-- resource-mode: s3-app-data {mode} -->\n' + text, encoding='utf-8')
            assert resource_modes(source.read_text().splitlines(), values | {'desired.resource.001.resourceMode': mode})['s3-app-data'] == mode



@it_case
@patch.object(aws_mapping_display, 'MODEL_ONLY', aws_mapping_display.MODEL_ONLY | {'S3.Bucket.SourceKeyId'})
def check_links(module):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        source, target, text, ref = reference_fixture(root)
        location = "docs/designs/dev/account/s3.md: "
        missing = ["broken design link: " + location + "absent.md#absent",
                   "missing design anchor: " + location + "kms.md#absent"]
        alias_error = "S3 KMSMasterKeyID must display the referenced KMS alias name: " + location
        invalid = missing + [alias_error + ("alias/two" if n % 2 == 0 else "alias/three") for n in range(80)] + [
            "identifier reference does not match observed target: " + location + "S3.Bucket.SourceKeyId: 1234abcd-12ab-34cd-56ef-1234567890ab"]
        internal = ["design link must not display internal logical ID: " + location + "AliasTwo"] * 40 + missing + [alias_error + "AliasTwo"] * 40
        valid = text.replace("| 84 | SourceKeyId | [unresolved](absent.md#absent) | 未解決参照 |\n", "").replace(
            "| 85 | SourceKeyId | [unresolved](kms.md#absent) | 未解決anchor |\n", "")
        # Exact diagnostic messages and check counts; repeated warnings are deduplicated.
        cases = [
            (text, ref, missing, 416),
            (valid, ref, [], 409),
            (text.replace("[alias/two]", "[AliasTwo]"), ref, internal, 416),
            (text, ref.replace("resource-logical-id: KeyHidden", "resource-logical-id: Bad!"), invalid, 416),
            (text, ref.replace("kms-keytwo", "kms-keyone"), ["duplicate resource anchor", *invalid[:-1]], 415),
            (text, ref.replace("logical-id: AliasTwo", "logical-id: AliasOne"), invalid, 416),
            (text, "<!-- resource-mode: kms-keyone CREATE -->\n" + ref, missing, 416),
            (text, "<!-- resource-mode: kms-keyone IMPORT -->\n" + ref, missing, 416),
            (text.replace('<a id="s3-app-data"></a>', '<!-- resource-logical-id: Bad! -->\n<a id="s3-app-data"></a>'),
             ref, ["invalid grouped design: " + location + "resource logical ID metadata must precede its anchor and heading", *missing], 417),
            (text.replace("| 1 | BucketName", "| 1 | KMS.Alias.AliasName"), ref,
             ["invalid grouped design: " + location + "grouped resource has wrong parent: KMS.Alias: S3.Bucket", *missing], 417),
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
            assert sorted(set(diagnostics(validator))) == sorted(set(expected)), diagnostics(validator)
            assert all(error.startswith("invalid grouped design:") for error in validator.errors)
            assert validator.checks == checks
        design_links = _imports_validation_design_links
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        model = {"desired.resource.001.resourceType": "S3.Bucket",
                 "desired.resource.001.logicalId": "S3_Bucket_001",
                 "desired.resource.001.anchor": "resource-S3_Bucket_001",
                 "desired.service.identity.lastAllocated": '{"S3.Bucket":1}',
                 "desired.row.001-001.property": "S3.Bucket.SourceKeyId",
                 "desired.row.001-001.value": "[alias/two](kms.md#resource-AliasTwo)",
                 "observed.row.001-001.value": observed}
        alias_text = valid.replace("s3-app-data", "resource-S3_Bucket_001").replace(f"[{observed}](kms.md#kms-keyone)", f"[{observed}](kms.md#resource-AliasTwo)")
        for content, expected in [(alias_text, []),
                                  (alias_text.replace(observed, "different"), ["different"]),
                                  (alias_text.replace(f"[{observed}](kms.md#resource-AliasTwo)",
                                                      f"[{observed}](kms.md#resource-AliasThree)"), [observed])]:
            source.write_text(content, encoding="utf-8")
            target.write_text(ref, encoding="utf-8")
            validator.errors.clear()
            validator.findings.warnings.clear()
            with patch.object(design_links, "design_model_values", return_value=model):
                validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert not validator.errors
            assert len(validator.findings.warnings) == len(expected), validator.findings.warnings
            assert all(label in error for label, error in zip(expected, diagnostics(validator), strict=False))
        source.write_text(text, encoding="utf-8")
        target.write_text(ref, encoding="utf-8")
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads:
            validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2


if __name__ == "__main__":
    from support.model_sources import catalog_display
    from support.validator import load
    with catalog_display():
        check_snapshot(load("sync-model"))
        check_links(load("validate-blueprint"))
        print("design-document: PASS (single read/parse, concurrent reuse, selective groups, immutable snapshot, invalidation)")

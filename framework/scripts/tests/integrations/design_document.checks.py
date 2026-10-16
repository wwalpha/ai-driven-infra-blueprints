#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.design_document_fixtures import *

@patch.object(aws_mapping_display, 'MODEL_ONLY', aws_mapping_display.MODEL_ONLY | {'S3.Bucket.SourceKeyId'})
def check_projection(sync):
    with tempfile.TemporaryDirectory() as directory:
        source, target, text, _ = reference_fixture(Path(directory).resolve())
        index = DesignIndex()
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads, \
             patch.object(documents, "expanded_design", wraps=documents.expanded_design) as expands:
            projection = model_projection.model_for(source, Path(__file__).resolve().parents[4], design_index=index)
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2
            assert expands.call_count == 4  # Source, two parents, and empty unresolved view.
            assert model_projection.linked_resource(source, "[alias/two](kms.md#kms-aliastwo)", design_index=index) == ("KMS.Alias", "AliasTwo")
            assert model_projection.linked_resource(source, "[key](kms.md#kms-keyone)", design_index=index) == ("KMS.Key", "KeyHidden")
            assert model_projection.linked_resource(source, "[missing](kms.md#absent)", design_index=index) is None
            assert model_projection.linked_resource(source, "[missing](absent.md#absent)", design_index=index) is None
            assert model_projection.linked_resource(source, "literal", design_index=index) is None
            assert expands.call_count == 4
        # Captured from the pre-index implementation, including unresolved-link fallbacks.
        assert hashlib.sha256(projection.encode()).hexdigest() == "4e56a48f9624ff229f0d6821d294924422d8c94cd6dc88d477e2c81c8fb7f1e9"
        assert index.get(source).headings.expanded is index.get(source).view(projection=True).expanded
        repository = Path(__file__).resolve().parents[4]
        values = model_core.properties(projection)
        values.update({'display.service.title': '# S3 詳細設計',
                       'display.resource.001.comment': 'アプリケーションのデータを保管するbucket'})
        values["desired.resource.001.resourceMode"] = "IMPORT"
        rendered = model_design.markdown_for(source, values, repository)
        assert hashlib.sha256(rendered.encode()).hexdigest() == "f68a22524d5bbad245d31afe6f8c263035d80a223480574d9187a6db75f23bdd"
        # Alias links also retain an explicit consumer observation, without inventing Alias identifiers.
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        alias_source = dict(values)
        alias_source.update({"observed.row.001-003.property": values["desired.row.001-003.property"],
                             "observed.row.001-003.comment": values["desired.row.001-003.comment"],
                             "observed.row.001-003.value": observed})
        alias_text = text.replace("[alias/two](kms.md#kms-aliastwo)", f"[{observed}](kms.md#kms-aliastwo)", 1)
        source.write_text(alias_text, encoding="utf-8")
        roundtrip = model_core.properties(model_projection.model_for(source, repository, source=alias_source))
        assert roundtrip["desired.row.001-003.value"] == values["desired.row.001-003.value"]
        assert roundtrip["observed.row.001-003.value"] == observed
        source.write_text(alias_text.replace(observed, "different", 1), encoding="utf-8")
        tampered = model_core.properties(model_projection.model_for(source, repository, source=alias_source))
        assert tampered["observed.row.001-003.value"] != observed
        source.write_text(alias_text.replace("kms-aliastwo", "kms-aliasthree", 1), encoding="utf-8")
        tampered = model_core.properties(model_projection.model_for(source, repository, source=alias_source))
        assert tampered["desired.row.001-003.value"] != values["desired.row.001-003.value"]
        for mode in ("CREATE", "IMPORT"):
            source.write_text(f"<!-- resource-mode: s3-app-data {mode} -->\n" + text, encoding="utf-8")
            assert f"desired.resource.001.resourceMode={mode}\n" in model_projection.model_for(source)


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
        # Exact ordered diagnostics and check counts captured before implementation.
        cases = [
            (text, ref, missing, 416),
            (valid, ref, [], 409),
            (text.replace("[alias/two]", "[AliasTwo]"), ref, internal, 416),
            (text, ref.replace("resource-logical-id: KeyHidden", "resource-logical-id: Bad!"), invalid, 416),
            (text, ref.replace("kms-keytwo", "kms-keyone"), invalid, 416),
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
            validator.checks = 0
            validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert validator.errors == expected, validator.errors
            assert validator.checks == checks
        from validation import design_links
        observed = "1234abcd-12ab-34cd-56ef-1234567890ab"
        model = {"desired.resource.001.resourceType": "S3.Bucket",
                 "desired.resource.001.anchor": "s3-app-data",
                 "desired.row.001-001.property": "S3.Bucket.SourceKeyId",
                 "desired.row.001-001.value": "[alias/two](kms.md#kms-aliastwo)",
                 "observed.row.001-001.value": observed}
        alias_text = valid.replace(f"[{observed}](kms.md#kms-keyone)", f"[{observed}](kms.md#kms-aliastwo)")
        for content, expected in [(alias_text, []),
                                  (alias_text.replace(observed, "different"), ["different"]),
                                  (alias_text.replace(f"[{observed}](kms.md#kms-aliastwo)",
                                                      f"[{observed}](kms.md#kms-aliasthree)"), [observed])]:
            source.write_text(content, encoding="utf-8")
            target.write_text(ref, encoding="utf-8")
            validator.errors.clear()
            with patch.object(design_links, "design_model_values", return_value=model):
                validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert len(validator.errors) == len(expected), validator.errors
            assert all(label in error for label, error in zip(expected, validator.errors))
        source.write_text(text, encoding="utf-8")
        target.write_text(ref, encoding="utf-8")
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads:
            validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        print("design-document: PASS (single read/parse, concurrent reuse, selective groups, immutable snapshot, invalidation)")


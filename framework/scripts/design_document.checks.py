#!/usr/bin/env python3
"""Plain Python snapshot checks and shared reference-heavy regression fixture."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import model_design
import model_core
import model_projection
import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import design_document as documents
from design_document import DesignIndex

import importlib.util
from pathlib import Path

def reference_fixture(root, count=80):
    scripts = Path(__file__).parent
    spec = importlib.util.spec_from_file_location('layout_fixtures', scripts / 'design_layout.checks.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    source = root / 'docs/designs/dev/account/s3.md'
    source.parent.mkdir(parents=True, exist_ok=True)
    target = source.with_name('kms.md')
    target_text = fixtures.KMS.replace('<a id="kms-keyone"></a>', '<!-- resource-logical-id: KeyHidden -->\n<a id="kms-keyone"></a>')
    # Invalid unrelated metadata must remain outside reference-target parsing scope.
    target_text += '\n<!-- resource-logical-id: Bad! -->\n<a id="kms-unrelated"></a>\n### KMS.Key: unrelated\n'
    source_text = fixtures.S3.split('| 3 | BucketEncryption', 1)[0]
    for number in range(count):
        label, anchor = ('alias/two', 'kms-aliastwo') if number % 2 == 0 else ('alias/three', 'kms-aliasthree')
        source_text += f'| {number+3} | BucketEncryption[].KMSMasterKeyID | [{label}](kms.md#{anchor}) | 暗号化に使用するKMS alias |\n'
    source_text += f'| {count+3} | SourceKeyId | [1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone) | 参照ID |\n'
    source_text += f'| {count+4} | SourceKeyId | [unresolved](absent.md#absent) | 未解決参照 |\n'
    source_text += f'| {count+5} | SourceKeyId | [unresolved](kms.md#absent) | 未解決anchor |\n'
    source_text += '<!-- [hidden](hidden.md#hidden) -->\n'
    source.write_text(source_text, encoding='utf-8')
    target.write_text(target_text, encoding='utf-8')
    return source, target, source_text, target_text


def check_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        _, path, _, _ = reference_fixture(root)
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads, \
             patch.object(documents, "expanded_design", wraps=documents.expanded_design) as expands, \
             patch.object(documents, "resource_logical_ids", wraps=documents.resource_logical_ids) as identities:
            index = DesignIndex()
            first = index.get(path)
            def request(_):
                document = index.get(path.parent / ".." / path.parent.name / path.name)
                assert document is first
                return document.view(frozenset({"kms-aliastwo"})).expanded
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(request, range(12)))
            assert all(result is results[0] for result in results)
            assert reads.call_count == expands.call_count == identities.call_count == 1
            # A sibling alias selects the same grouped parent and shares its parse.
            assert first.view(frozenset({"kms-aliasone"})).expanded is results[0]
            assert expands.call_count == identities.call_count == 1
            original = first.text
            path.write_text(original.replace("alias/two", "alias/changed"), encoding="utf-8")
            assert index.get(path) is first and first.text == original
            index.invalidate(path)
            refreshed = index.get(path)
            assert refreshed is not first and "alias/changed" in refreshed.text
            assert reads.call_count == 2
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
            first.headings.expanded
        except ValueError as error:
            assert str(error) == "resource logical ID metadata must precede its anchor and heading"
        else:
            raise AssertionError("unrelated invalid metadata was not retained in the full snapshot")


def check_projection(sync):
    with tempfile.TemporaryDirectory() as directory:
        source, target, text, _ = reference_fixture(Path(directory).resolve())
        index = DesignIndex()
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads, \
             patch.object(documents, "expanded_design", wraps=documents.expanded_design) as expands:
            projection = model_projection.model_for(source, Path(__file__).resolve().parents[2], design_index=index)
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
        repository = Path(__file__).resolve().parents[2]
        imported = model_projection.imported_model(source, repository)
        assert hashlib.sha256(imported.encode()).hexdigest() == "bc1677174d702a4c7bb2780fda2979be471ee9974a6e43e11e63c02dad1ef3bd"
        values = model_core.properties(imported)
        values["desired.resource.001.resourceMode"] = "IMPORT"
        rendered = model_design.markdown_for(source, values, repository)
        assert hashlib.sha256(rendered.encode()).hexdigest() == "f68a22524d5bbad245d31afe6f8c263035d80a223480574d9187a6db75f23bdd"
        for mode in ("CREATE", "IMPORT"):
            source.write_text(f"<!-- resource-mode: s3-app-data {mode} -->\n" + text, encoding="utf-8")
            assert f"desired.resource.001.resourceMode={mode}\n" in model_projection.model_for(source)


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
        source.write_text(text, encoding="utf-8")
        target.write_text(ref, encoding="utf-8")
        read_text = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=read_text) as reads:
            validator.check_design_links({"KMS.Key": {"KMS.Key.KeyId"}}, [source])
            assert sum(call.args[0].suffix == ".md" for call in reads.call_args_list) == 2


if __name__ == "__main__":
    check_snapshots()
    print("design-document: PASS (single read/parse, concurrent reuse, selective groups, immutable snapshot, invalidation)")

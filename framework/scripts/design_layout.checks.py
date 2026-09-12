#!/usr/bin/env python3
"""Check grouped identities, references and catalog display coverage end to end."""

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

from design_layout import LAYOUTS, expanded_design, layout_errors


REPOSITORY = Path(__file__).resolve().parents[2]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_script("validate-blueprint")
MODEL = load_script("sync-model")
KMS = """# KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース一覧

### KMS.Key

| Key | AliasNames |
| --- | --- |
| [KeyOne](#kms-keyone) | alias/one, alias/two |
| [KeyTwo](#kms-keytwo) | alias/three |

## リソース詳細

<a id="kms-keyone"></a>

### KMS.Key: KeyOne

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KMS.Key.KeyId | `1234abcd-12ab-34cd-56ef-1234567890ab` | KMS keyを識別するID |
| 2 | KMS.Key.EnableKeyRotation | `true` | key materialの自動rotationを有効にする設定 |
| 3 | KMS.Alias.AliasName | `alias/one` | <a id="kms-aliasone"></a><!-- logical-id: AliasOne --> KMS keyを識別するalias |
| 4 | KMS.Alias.AliasName | `alias/two` | <a id="kms-aliastwo"></a><!-- logical-id: AliasTwo --> KMS keyを識別するalias |

<a id="kms-keytwo"></a>

### KMS.Key: KeyTwo

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KMS.Key.KeyId | `PENDING_DEPLOY` | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | `alias/three` | <a id="kms-aliasthree"></a><!-- logical-id: AliasThree --> KMS keyを識別するalias |
"""
S3 = """# S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`

## リソース一覧

### S3.Bucket

| BucketName | Region | KMSAlias |
| --- | --- | --- |
| [app-data](#s3-app-data) | us-east-1 | alias/two |

## リソース詳細

<a id="s3-app-data"></a>

### S3.Bucket: app-data

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | S3.Bucket.BucketName | `app-data` | bucketの名前 |
| 2 | S3.Bucket.Region | `us-east-1` | bucketを配置するregion |
| 3 | S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID | [alias/two](kms.md#kms-aliastwo) | 暗号化に使用するKMS alias |
"""


def main() -> None:
    assert not layout_errors(REPOSITORY)
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        kms = root / "docs/designs/dev/123456789012/kms.md"
        kms.parent.mkdir(parents=True)
        s3 = kms.with_name("s3.md")
        metadata = {kms: ("kms", ("KMS.Key", "KMS.Alias")), s3: ("s3", ("S3.Bucket",))}

        def errors(kms_text=KMS, s3_text=S3):
            kms.write_text(kms_text, encoding="utf-8")
            s3.write_text(s3_text, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables(metadata, *catalog)
            validator.check_design_overviews()
            validator.check_design_links(catalog[2])
            return validator.errors

        assert not errors(), errors()
        original = kms.read_bytes()
        model = MODEL.model_for(kms, REPOSITORY)
        assert kms.read_bytes() == original
        assert "desired.resource.002.resourceType=KMS.Alias" in model
        assert "desired.resource.002.logicalId=AliasOne" in model
        assert "desired.resource.003.logicalId=AliasTwo" in model
        assert "desired.resource.003.anchor=kms-aliastwo" in model
        assert "desired.resource.003.parentProperty=KMS.Alias.TargetKeyId" in model
        assert "desired.resource.003.parentReference=[KeyOne](#kms-keyone)" in model
        assert "desired.resource.005.parentReference=[KeyTwo](#kms-keytwo)" in model
        assert "desired.row.003-001.value=`alias/two`" in model
        assert "observed.row.001-001.value=`1234abcd-12ab-34cd-56ef-1234567890ab`" in model
        assert "observed.row.004-001.value=`PENDING_DEPLOY`" in model
        assert "<!--" not in model and "<a " not in model
        assert "observed.row.003" not in model
        assert MODEL.linked_resource(s3, "[alias/two](kms.md#kms-aliastwo)") == ("KMS.Alias", "AliasTwo")
        s3_model = MODEL.model_for(s3, REPOSITORY)
        assert "desired.row.001-003.value=[alias/two](kms.md#kms-aliastwo)" in s3_model
        assert "observed.row.001-003" not in s3_model

        marker = '<a id="kms-aliastwo"></a><!-- logical-id: AliasTwo --> '
        bad_designs = [
            (KMS.replace(marker, ""), "requires anchor and logical ID"),
            (KMS.replace('KMS.Alias.AliasName', 'AliasName').replace(marker, ""), "full catalog name"),
            (KMS.replace('<!-- logical-id: AliasTwo -->', '<!-- logical-id: AliasOne -->'), "duplicate grouped logical ID"),
            (KMS.replace('id="kms-aliastwo"', 'id="kms-aliasone"'), "duplicate resource anchor"),
            (KMS.replace('id="kms-aliastwo"', 'id="kms-wrong"'), "logical ID/anchor"),
            (KMS.replace('`alias/three`', '`alias/two`'), "duplicate grouped identity value"),
            (KMS.replace('`alias/three`', '`bad-alias`'), "provider schema violation"),
            (KMS.replace('### KMS.Key: KeyOne', '### S3.Bucket: KeyOne'), "wrong parent"),
            (KMS.replace('| 4 | KMS.Alias.AliasName', '| 4 | KMS.Alias.TargetKeyId'), "must be omitted"),
            (KMS.replace('| 4 | KMS.Alias.AliasName', '| 4 | KMS.Key.Description'), "child identity marker"),
            (KMS.replace('### KMS.Key: KeyOne', '### KMS.Alias: KeyOne'), "independent heading"),
            (KMS.replace('| 4 | KMS.Alias.AliasName', '\n| No. | Property | Value | Source / Comment |\n| ---: | --- | --- | --- |\n| 4 | KMS.Alias.AliasName'), "exactly one detail table"),
        ]
        for markdown, message in bad_designs:
            failures = errors(markdown)
            assert any(message in error for error in failures), (message, failures)
        for reference in ("[alias/one](kms.md#kms-aliastwo)", "[alias/two](kms.md#kms-keyone)", "[alias/two](kms.md#kms-missing)"):
            assert errors(KMS, S3.replace("[alias/two](kms.md#kms-aliastwo)", reference))

        # Moving an identified child updates only its parent relationship, not its identity.
        alias_line = next(line for line in KMS.splitlines() if marker in line)
        moved = KMS.replace(alias_line + "\n", "").rstrip() + "\n" + alias_line.replace("| 4 |", "| 3 |") + "\n"
        assert not errors(moved), errors(moved)
        _, children = expanded_design(moved.splitlines())
        assert children["kms-aliastwo"]["parentLogicalId"] == "KeyTwo"
        assert children["kms-aliastwo"]["logicalId"] == "AliasTwo"
        moved_model = MODEL.model_for(kms, REPOSITORY)
        assert "desired.resource.005.logicalId=AliasTwo" in moved_model
        assert "desired.resource.005.parentReference=[KeyTwo](#kms-keytwo)" in moved_model

        # A new catalog type cannot silently inherit an independent display decision.
        shutil.copytree(REPOSITORY / "framework/materials/aws", root / "framework/materials/aws")
        shutil.copytree(REPOSITORY / "framework/materials/api", root / "framework/materials/api")
        layout_path = root / "framework/rules/resource-layout.json"
        layout_path.parent.mkdir(parents=True)
        layout_path.write_text(json.dumps(LAYOUTS), encoding="utf-8")
        shutil.copyfile(REPOSITORY / "framework/rules/resource-name-properties.json", layout_path.with_name("resource-name-properties.json"))
        assert not layout_errors(root)
        name_path = layout_path.with_name("resource-name-properties.json")
        names = json.loads(name_path.read_text())
        missing_name = dict(names)
        del missing_name["IAM.Role"]
        name_path.write_text(json.dumps(missing_name))
        assert any("name coverage" in error for error in layout_errors(root))
        name_path.write_text(json.dumps({**names, "IAM.Role": ["MissingName"]}))
        assert any("name property is absent" in error for error in layout_errors(root))
        name_path.write_text(json.dumps(names))
        (root / "framework/materials/aws/Example_Child.properties").write_text("Example.Child.Name=\n", encoding="utf-8")
        assert any("unclassified=['Example.Child']" in error for error in layout_errors(root))
        broken = {**LAYOUTS, "Example.Child": "independent", "KMS.Alias": {**LAYOUTS["KMS.Alias"], "parentProperty": "Missing"}}
        layout_path.write_text(json.dumps(broken), encoding="utf-8")
        assert any("parent property is absent" in error for error in layout_errors(root))
    print("design-layout: PASS (grouped identities, parent changes, S3 references, invalid designs, catalog coverage)")


if __name__ == "__main__":
    main()

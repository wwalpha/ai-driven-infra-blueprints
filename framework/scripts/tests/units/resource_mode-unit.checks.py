#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

import pytest
from model.sources import model_parts
from support.resource_mode_fixtures import (
    ROOT,
    Path,
    json,
    markdown_for,
    model,
    naming_errors,
    read_model,
    resource_mode,
    snapshot_model,
    sync_views,
    sys,
    tempfile,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_default_mode():
    assert resource_mode({}) == "CREATE"



def check_import_naming_exemption():
    root = ROOT
    rows = [["1", "CachePolicyConfig.Name", "LEGACY", "名前"]]
    assert naming_errors(root, "CloudFront.CachePolicy", rows)
    assert not naming_errors(root, "CloudFront.CachePolicy", rows, "IMPORT")
    assert naming_errors(root, "IAM.Role", [], "IMPORT")
    assert naming_errors(root, "CodeBuild.Project", [], "IMPORT")



def check_required_name_modes():
    root = ROOT
    path = root / 'docs/designs/dev/123456789012/ec2.md'
    validator_module = sync_views.view_validator(root, root).__class__
    for kind in ("EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"):
        for mode in ("CREATE", "IMPORT"):
            for rows in ([], [["1", kind + ".Name", "PRIVATE_SUBNET_01", "Nameタグ"]]):
                validator = validator_module(root)
                validator.check_required_name_tag(path, kind, "PRIVATE_SUBNET_01", rows, mode)
                assert bool(validator.errors) == (mode == "CREATE"), (kind, mode, validator.errors)




pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

def _callback_main_check(path, root, source, /, values):
    values = {key: value for key, value in values.items() if not (key.startswith("observed.row.") and key.endswith((".property", ".comment")))}
    original = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(source, original)
    original = {file: file.read_bytes() for file in (source, *model_parts(source))}
    try:
        read_model(source)
        path.write_text(markdown_for(path, values, root), encoding="utf-8")
        sync_views.validate_views(root, root, [path], {path: values})
    except (ValueError, KeyError) as error:
        return str(error)
    assert snapshot_model(source) == original
    assert path.read_text(encoding="utf-8") == markdown_for(path, values, root)
    assert "resource-mode:" not in path.read_text(encoding="utf-8")
    assert "resource-entry:" not in path.read_text(encoding="utf-8")
    return ""

def check_resource_mode_conditions():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation",
        }]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/ec2.md"
        source = root / "model/dev/123456789012/ec2.properties"
        path.parent.mkdir(parents=True)
        source.parent.mkdir(parents=True)

        write_model(source.with_name('cloudformation-stacks.properties'), {
            'desired.stack.001.name': 'fixture', 'desired.stack.001.placementName': 'fixture',
            'desired.stack.001.template': 'fixture.yaml', 'desired.stack.001.parameters': 'fixture.json',
            'desired.stack.001.deployOrder': '1', 'display.stack.001.comment': '合成Stack'})
        check = _bind_framework_callback(_callback_main_check, path, root, source)

        # Required cases exercise the generator, schema/catalog validator and projection.
        assert not (error := check(model())), error
        assert "lower-kebab-case" in check(model(name="PRIVATE_SUBNET_01"))
        imported = model(name="PRIVATE_SUBNET_01", mode="IMPORT")
        assert not (error := check(imported)), error
        assert "PRIVATE_SUBNET_01" in path.read_text(encoding="utf-8")
        assert not (error := check(model(name=None, mode="IMPORT"))), error
        output = path.read_text(encoding="utf-8")
        assert "| Name |" not in output and "Tags[]" not in output
        assert "### EC2.VPC\n" in output and "| resourceMode |" not in output
        assert "lower-kebab-case" in check(model(name="PRIVATE_SUBNET_01", mode=None))
        assert not (error := check(model(mode=None))), error
        assert "resource-mode:" not in path.read_text(encoding="utf-8")
        print("resourceMode: PASS (required cases 1–5, omitted-mode CREATE compatibility)")

        # All six mandatory-Name types retain CREATE checks; IMPORT can omit tags.
        for kind in ("EC2.VPC", "EC2.VPCEndpoint", "EC2.Instance"):
            for label in (None, "取得済みresource", "InternalId"):
                assert not (error := check(model(kind, None, "IMPORT", label))), error
            assert check(model(kind, None, "CREATE", "表示名"))
            assert not (error := check(model(kind, "LEGACY_NAME_01", "IMPORT"))), error
        # A case-different key is retained as an ordinary tag, without synthesizing Name.
        tagged = model("EC2.VPCEndpoint", "LEGACY_NAME_01", "IMPORT", "取得済みresource")
        tagged["desired.row.001-003.value"] = "name"
        tagged["desired.row.001-001.value"] = "[Endpoint](#ec2-service-endpoint)"
        assert not (error := check(tagged)), error
        assert "| Tags[1].Key | name |" in path.read_text(encoding="utf-8")

        # A mixed service must not exempt its CREATE neighbour.
        mixed = model(name="LEGACY_NAME_01", mode="IMPORT")
        neighbour = model(name="INVALID_CREATE_NAME", mode="CREATE")
        mixed.update({key.replace(".001", ".002", 1): value.replace("EC2_VPC_001", "EC2_VPC_002").replace("fixture-InternalId", "fixture-OtherId")
                      for key, value in neighbour.items() if ".001" in key})
        mixed["desired.service.identity.lastAllocated"] = json.dumps({"EC2.VPC": 2})
        assert "lower-kebab-case" in check(mixed)
        # Provider constraints, catalog selection and row structure still fail for IMPORT.
        bad = {**imported, "desired.row.001-004.property": "EC2.VPC.EnableDnsSupport",
               "desired.row.001-004.value": "broken", "desired.row.001-004.comment": "DNS解決の有効化"}
        assert "provider schema violation" in check(bad)
        assert "display Mapping property missing: EC2.VPC.Unknown" in check({**bad, "desired.row.001-004.property": "EC2.VPC.Unknown"})
        assert "Row requires property, value and comment" in check({key: value for key, value in imported.items() if key != "desired.row.001-001.comment"})
        # The EC2 tag schema specifies string only; use its actual boolean constraint above.
        assert "requires the corresponding Tags[].Value" in check({
            key: value for key, value in model("EC2.Instance", "LEGACY", "IMPORT").items()
            if not key.startswith("desired.row.001-005.")
        })
        assert "requires the corresponding Tags[].Key" in check({
            key: value for key, value in model("EC2.Instance", "LEGACY", "IMPORT").items()
            if not key.startswith("desired.row.001-004.")
        })
        for invalid in ("", "REFERENCE", "create", "IMPORT "):
            assert "resourceMode must be CREATE or IMPORT" in check({**imported, "desired.resource.001.resourceMode": invalid})
        assert not (error := check(imported)), error
        # Identified grouped children carry their own mode without a new property row.
        kms_path = path.with_name("kms.md")
        kms = {
            "desired.service.kms.serviceId": "kms",
            "desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
            "display.service.title": "# KMS 詳細設計",
            "display.resource.001.comment": "データを暗号化する鍵",
            "desired.resource.001.resourceType": "KMS.Key",
            "desired.resource.001.logicalId": "KMS_Key_001", 'desired.resource.001.anchor': 'resource-KMS_Key_001',
            "desired.resource.001.cfn-logicalId": "fixture-Key",
            "desired.service.identity.lastAllocated": json.dumps({"KMS.Key": 1, "KMS.Alias": 1}),
            "desired.resource.001.resourceMode": "CREATE",
            "desired.row.001-001.property": "KMS.Key.KeyId",
            "desired.row.001-001.value": "[KMS_Key_001](kms.md#resource-KMS_Key_001)",
            "desired.row.001-001.comment": "一意に識別するID",
            "observed.row.001-001.property": "KMS.Key.KeyId",
            "observed.row.001-001.value": "PENDING_DEPLOY",
            "observed.row.001-001.comment": "一意に識別するID",
            "desired.resource.002.resourceType": "KMS.Alias",
            "desired.resource.002.logicalId": "KMS_Alias_001", 'desired.resource.002.anchor': 'resource-KMS_Alias_001',
            "desired.resource.002.resourceMode": "IMPORT",
            "desired.resource.002.parentProperty": "KMS.Alias.TargetKeyId",
            "desired.resource.002.parentReference": "[KMS_Key_001](kms.md#resource-KMS_Key_001)",
            "desired.row.002-001.property": "KMS.Alias.AliasName",
            "desired.row.002-001.value": "alias/LEGACY_KEY",
            "desired.row.002-001.comment": "鍵を識別するalias",
        }
        kms_path.write_text(markdown_for(kms_path, kms, root), encoding="utf-8")
        assert kms_path.read_text(encoding="utf-8") == markdown_for(kms_path, kms, root)
        assert "### KMS.Alias" not in kms_path.read_text(encoding="utf-8")
    print("resourceMode: PASS (Name policies, mixed modes, schema/structure, metadata, lossless sync)")


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

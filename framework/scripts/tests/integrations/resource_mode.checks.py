#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.resource_mode_fixtures import *

def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation",
        }]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/ec2.md"
        source = root / "model/dev/123456789012/ec2.properties"
        path.parent.mkdir(parents=True)
        source.parent.mkdir(parents=True)

        def check(values):
            original = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
            write_model(source, original)
            original = read_model(source)
            try:
                path.write_text(markdown_for(path, values, root), encoding="utf-8")
                sync_views.validate_views(root, root, [path], {path: values})
            except (ValueError, KeyError) as error:
                return str(error)
            assert read_model(source) == original
            projected = properties(model_projection.model_for(path, root))
            assert projected == {key: value for key, value in values.items() if not key.startswith("display.")}
            assert "resource-mode:" not in path.read_text(encoding="utf-8")
            assert "resource-entry:" not in path.read_text(encoding="utf-8")
            return ""

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
        tagged["desired.resource.001.anchor"] = "ec2-resource"
        tagged["desired.row.001-001.value"] = "[InternalId](#ec2-resource)"
        assert not (error := check(tagged)), error
        assert "| Tags[1].Key | name |" in path.read_text(encoding="utf-8")

        # A mixed service must not exempt its CREATE neighbour.
        mixed = model(name="LEGACY_NAME_01", mode="IMPORT")
        neighbour = model(name="INVALID_CREATE_NAME", mode="CREATE")
        mixed.update({key.replace(".001", ".002", 1): value.replace("InternalId", "OtherId")
                      for key, value in neighbour.items() if ".001" in key})
        assert "lower-kebab-case" in check(mixed)
        # Provider constraints, catalog selection and row structure still fail for IMPORT.
        bad = {**imported, "desired.row.001-004.property": "EC2.VPC.EnableDnsSupport",
               "desired.row.001-004.value": "broken", "desired.row.001-004.comment": "DNS解決の有効化"}
        assert "provider schema violation" in check(bad)
        assert "display Mapping property missing: EC2.VPC.Unknown" in check({**bad, "desired.row.001-004.property": "EC2.VPC.Unknown"})
        assert "invalid resource row" in check({key: value for key, value in imported.items() if key != "desired.row.001-001.comment"})
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
        original = path.read_text(encoding="utf-8")
        marker = "<!-- resource-mode: ec2-private_subnet_01 IMPORT -->"
        for replacement in (marker + "\n" + marker, marker.replace("IMPORT", "REFERENCE"), marker.replace("private_subnet_01", "missing")):
            try:
                resource_modes((original + replacement + "\n").splitlines())
            except ValueError:
                pass
            else:
                raise AssertionError("invalid resourceMode metadata accepted")
        # Legacy comments cannot override the authoritative mode during verification.
        stale = original + marker.replace("IMPORT", "CREATE") + "\n"
        assert resource_modes(stale.splitlines(), imported)["ec2-private_subnet_01"] == "IMPORT"
        path.write_text(stale, encoding="utf-8")
        sync_views.validate_views(root, root, [path], {path: imported})
        try:
            SYNC.sync(root, False, "dev", "123456789012", services=["ec2"])
        except ValueError as error:
            assert "stale or missing" in str(error), error
        else:
            raise AssertionError("stale generated view accepted")
        # Coverage-only exemption does not waive confirmed actual name checks.
        assert not (error := check(imported)), error
        before = snapshot_model(source)
        assert SYNC.sync(root, True, "dev", "123456789012", services=["ec2"]) == 0
        assert SYNC.sync(root, False, "dev", "123456789012", services=["ec2"]) == 0
        assert snapshot_model(source) == before
        assert "PRIVATE_SUBNET_01" in path.read_text(encoding="utf-8")
        # Identified grouped children carry their own mode without a new property row.
        kms_path = path.with_name("kms.md")
        kms = {
            "desired.service.kms.serviceId": "kms",
            "desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
            "display.service.title": "# KMS 詳細設計",
            "display.resource.001.comment": "データを暗号化する鍵",
            "desired.resource.001.resourceType": "KMS.Key",
            "desired.resource.001.logicalId": "Key",
            "desired.resource.001.anchor": "kms-legacy_key",
            "desired.resource.001.resourceMode": "CREATE",
            "desired.row.001-001.property": "KMS.Key.KeyId",
            "desired.row.001-001.value": "[Key](#kms-legacy_key)",
            "desired.row.001-001.comment": "一意に識別するID",
            "observed.row.001-001.property": "KMS.Key.KeyId",
            "observed.row.001-001.value": "PENDING_DEPLOY",
            "observed.row.001-001.comment": "一意に識別するID",
            "desired.resource.002.resourceType": "KMS.Alias",
            "desired.resource.002.logicalId": "Alias",
            "desired.resource.002.anchor": "kms-alias-legacy_key",
            "desired.resource.002.resourceMode": "IMPORT",
            "desired.resource.002.parentProperty": "KMS.Alias.TargetKeyId",
            "desired.resource.002.parentReference": "[Key](#kms-legacy_key)",
            "desired.row.002-001.property": "KMS.Alias.AliasName",
            "desired.row.002-001.value": "alias/LEGACY_KEY",
            "desired.row.002-001.comment": "鍵を識別するalias",
        }
        kms_path.write_text(markdown_for(kms_path, kms, root), encoding="utf-8")
        assert properties(model_projection.model_for(kms_path, root, source=kms)) == {
            key: value for key, value in kms.items() if not key.startswith("display.")
        }
        assert "### KMS.Alias" not in kms_path.read_text(encoding="utf-8")
    print("resourceMode: PASS (Name policies, mixed modes, schema/structure, metadata, lossless sync)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()


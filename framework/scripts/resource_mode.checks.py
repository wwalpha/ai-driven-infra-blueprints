#!/usr/bin/env python3
"""CREATE compatibility and IMPORT's naming-only exemption through generated views."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

from design_layout import resource_anchor, resource_mode, resource_modes
from model_design import markdown_for, naming_errors, properties

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mode_sync", Path(__file__).with_name("sync-model.py"))
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def model(kind="EC2.VPC", name="vpc-app-dev", mode="CREATE", label=None):
    service = "ec2"
    display = name or label or kind
    anchor = resource_anchor(service, display, kind)
    identifier = {"EC2.VPC": "VpcId", "EC2.VPCEndpoint": "Id", "EC2.Instance": "InstanceId"}[kind]
    physical = {"EC2.VPC": "vpc-0123456789abcdef0", "EC2.VPCEndpoint": "vpce-0123456789abcdef0", "EC2.Instance": "i-0123456789abcdef0"}[kind]
    rows = []
    if name and kind == "EC2.VPC":
        rows.append(("Name", name))
    rows.append((identifier, f"[InternalId](#{anchor})"))
    if kind == "EC2.VPC":
        rows.append(("CidrBlock", "10.1.0.0/16"))
    elif kind == "EC2.VPCEndpoint":
        rows.append(("ServiceName", "com.amazonaws.ap-northeast-1.s3"))
    else:
        rows += [("ImageId", "ami-0123456789abcdef0"), ("InstanceType", "t3.micro")]
    if name and kind != "EC2.VPC":
        rows += [("Tags[].Key", "Name"), ("Tags[].Value", name)]
    if kind == "EC2.VPCEndpoint":
        rows += [("VpcEndpointType", "Gateway"), ("VpcId", "vpc-0123456789abcdef0")]
    result = {
        "desired.service.ec2.serviceId": service,
        "desired.service.ec2.ownedCatalogResourceTypes": kind,
        "display.service.title": "# EC2 詳細設計",
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.logicalId": "InternalId",
        "desired.resource.001.anchor": anchor,
        "display.resource.001.comment": "業務用ネットワークを構成するresource",
    }
    if mode is not None:
        result["desired.resource.001.resourceMode"] = mode
    if label:
        result["display.resource.001.label"] = label
    for number, (field, value) in enumerate(rows, 1):
        key = f"001-{number:03d}"
        for suffix, item in (("property", kind + "." + field), ("value", value), ("comment", "設定値を指定する属性")):
            result[f"desired.row.{key}.{suffix}"] = item
            if field == identifier:
                result[f"observed.row.{key}.{suffix}"] = physical if suffix == "value" else item
    return result


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
            source.write_text(original, encoding="utf-8")
            try:
                path.write_text(markdown_for(path, values, root), encoding="utf-8")
                SYNC.validate_views(root, root, [path], {path: values})
            except (ValueError, KeyError) as error:
                return str(error)
            assert source.read_text(encoding="utf-8") == original
            projected = properties(SYNC.model_for(path, root))
            assert projected == {key: value for key, value in values.items() if not key.startswith("display.")}
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
        validator_module = SYNC.view_validator(root, root).__class__
        for kind in ("EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"):
            for mode in ("CREATE", "IMPORT"):
                for rows in ([], [["1", kind + ".Name", "PRIVATE_SUBNET_01", "Nameタグ"]]):
                    validator = validator_module(root)
                    validator.check_required_name_tag(path, kind, "PRIVATE_SUBNET_01", rows, mode)
                    assert bool(validator.errors) == (mode == "CREATE"), (kind, mode, validator.errors)
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
        assert "not selected by design catalog" in check({**bad, "desired.row.001-004.property": "EC2.VPC.Unknown"})
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
        assert resource_mode({}) == "CREATE"
        assert not (error := check(imported)), error
        original = path.read_text(encoding="utf-8")
        marker = "<!-- resource-mode: ec2-private_subnet_01 IMPORT -->"
        for replacement in (marker + "\n" + marker, marker.replace("IMPORT", "REFERENCE"), marker.replace("private_subnet_01", "missing")):
            try:
                resource_modes(original.replace(marker, replacement).splitlines())
            except ValueError:
                pass
            else:
                raise AssertionError("invalid resourceMode metadata accepted")
        path.write_text(original.replace(marker, marker.replace("IMPORT", "CREATE")), encoding="utf-8")
        try:
            SYNC.validate_views(root, root, [path], {path: imported})
        except ValueError as error:
            assert "projection mismatch" in str(error)
        else:
            raise AssertionError("model/display mode mismatch accepted")
        # Coverage-only exemption does not waive confirmed actual name checks.
        rows = [["1", "CachePolicyConfig.Name", "LEGACY", "名前"]]
        assert naming_errors(root, "CloudFront.CachePolicy", rows)
        assert not naming_errors(root, "CloudFront.CachePolicy", rows, "IMPORT")
        assert naming_errors(root, "IAM.Role", [], "IMPORT")
        assert naming_errors(root, "CodeBuild.Project", [], "IMPORT")
        assert not (error := check(imported)), error
        before = source.read_bytes()
        assert SYNC.sync(root, True, "dev", "123456789012", services=["ec2"]) == 0
        assert SYNC.sync(root, False, "dev", "123456789012", services=["ec2"]) == 0
        assert source.read_bytes() == before
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
        assert properties(SYNC.model_for(kms_path, root)) == {
            key: value for key, value in kms.items() if not key.startswith("display.")
        }
        assert "### KMS.Alias" not in kms_path.read_text(encoding="utf-8")
    print("resourceMode: PASS (Name policies, mixed modes, schema/structure, metadata, lossless sync)")


if __name__ == "__main__":
    main()

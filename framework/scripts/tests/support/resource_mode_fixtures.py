"""CREATE compatibility and IMPORT's naming-only exemption through generated views."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import shutil
import tempfile

import model.projection as model_projection
import sync_runtime as SYNC
import sync_views
from design.layout import resource_mode, resource_modes
from design.layout_schema import resource_anchor
from model.core import properties
from model.files import read_model
from model.render import markdown_for
from model.validation import naming_errors
from support.model_sources import snapshot_model, write_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]



def model(kind="EC2.VPC", name="vpc-app-dev", mode="CREATE", label=None):
    service = "ec2"
    display = name or label or kind
    anchor = resource_anchor(service, display, kind)
    identifier = {"EC2.VPC": "VpcId", "EC2.VPCEndpoint": "Id", "EC2.Instance": "InstanceId"}[kind]
    physical = {"EC2.VPC": "vpc-0123456789abcdef0", "EC2.VPCEndpoint": "vpce-0123456789abcdef0", "EC2.Instance": "i-0123456789abcdef0"}[kind]
    rows = []
    if name and kind == "EC2.VPC":
        rows.append(("Name", name))
    logical = kind.replace(".", "_") + "_001"
    rows.append((identifier, f"[{logical}](#{anchor})"))
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
        "desired.resource.001.logicalId": logical, 'desired.resource.001.anchor': anchor,
        "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
        "desired.resource.001.cfn-logicalId": "fixture-InternalId",
        "display.resource.001.comment": "業務用ネットワークを構成するresource",
    }
    if mode == 'IMPORT':
        result.pop('desired.resource.001.cfn-logicalId')
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


__all__ = ['Path', 'ROOT', 'SYNC', 'json', 'markdown_for', 'model', 'model_projection', 'naming_errors', 'properties', 'read_model', 'resource_anchor', 'resource_mode', 'resource_modes', 'shutil', 'snapshot_model', 'sync_views', 'sys', 'tempfile', 'write_model']

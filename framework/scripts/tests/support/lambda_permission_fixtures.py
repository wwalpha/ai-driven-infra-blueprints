"""Lambda Permission grouping, hidden identity and lossless view checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import re
import shutil
import tempfile

import model.projection as model_projection
import sync_views
from design.layout import expanded_design, formal_property, layout_errors
from design.layout_schema import resource_anchor
from model.core import properties
from model.files import read_model
from model.render import markdown_for
from support.import_model_fixtures import resource_values, service_values
from support.model_sources import write_model
from support.validator import load

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]

HELPERS = __import__("support.model_design_fixtures", fromlist=["model"])

SYNC = HELPERS.SYNC

FUNCTION, PERMISSION = "Lambda.Function", "Lambda.Permission"


def fixture(parents=1, children=1, deployed=False):
    values = {
        "desired.service.lambda.serviceId": "lambda",
        "desired.service.lambda.ownedCatalogResourceTypes": FUNCTION + "," + PERMISSION,
        "display.service.title": "# Lambda 詳細設計",
    }
    values["desired.service.identity.lastAllocated"] = json.dumps(
        {FUNCTION: parents, PERMISSION: parents * children}
    )
    number = 0
    for parent in range(parents):
        number += 1
        identity = f"{number:03d}"
        name, logical = (
            f"app-dev-worker-{parent + 1}",
            f"Lambda_Function_{parent + 1:03d}",
        )
        anchor = resource_anchor("lambda", name)
        values.update(
            {
                f"desired.resource.{identity}.resourceType": FUNCTION,
                f"desired.resource.{identity}.logicalId": logical,
                f"desired.resource.{identity}.anchor": anchor,
                f"desired.resource.{identity}.cfn-logicalId": f"fixture-Worker{parent + 1}",
                f"display.resource.{identity}.comment": "業務データを処理する関数",
            }
        )
        rows = [
            ("FunctionName", f"`{name}`"),
            (
                "Code.ImageUri",
                "`123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/worker:latest`",
            ),
            ("PackageType", "`Image`"),
            (
                "Role",
                "`"
                + json.dumps(
                    {"$modelRef": {"logicalId": "IAM_Role_001", "attribute": "Arn"}}
                )
                + "`",
            ),
        ]
        for index, (field, value) in enumerate(rows, 1):
            key = f"desired.row.{identity}-{index:03d}"
            values.update(
                {
                    key + ".property": FUNCTION + "." + field,
                    key + ".value": value,
                    key + ".comment": "属性の設定値",
                }
            )
        for child in range(children):
            number += 1
            child_id = f"{number:03d}"
            child_name, child_logical = (
                f"app-dev-invoke-{parent + 1}-{child + 1}",
                f"Lambda_Permission_{parent * children + child + 1:03d}",
            )
            child_anchor = resource_anchor("lambda", child_name)
            reference = (
                "`"
                + json.dumps(
                    {"$modelRef": {"logicalId": logical, "attribute": "FunctionName"}}
                )
                + "`"
            )
            values.update(
                {
                    f"desired.resource.{child_id}.resourceType": PERMISSION,
                    f"desired.resource.{child_id}.logicalId": child_logical,
                    f"desired.resource.{child_id}.anchor": child_anchor,
                    f"desired.resource.{child_id}.cfn-logicalId": f"fixture-Invoke{parent + 1}Child{child + 1}",
                    f"desired.resource.{child_id}.parentProperty": PERMISSION
                    + ".FunctionName",
                    f"desired.resource.{child_id}.parentReference": reference,
                    f"display.resource.{child_id}.label": child_name,
                }
            )
            rows = [
                (
                    "Id",
                    "`"
                    + json.dumps(
                        {"$modelRef": {"logicalId": child_logical, "attribute": "Id"}}
                    )
                    + "`",
                ),
                ("Action", "`lambda:InvokeFunction`"),
                ("EventSourceToken", "`source-token`"),
                ("FunctionName", reference),
                ("Principal", "`events.amazonaws.com`"),
                ("SourceAccount", "`123456789012`"),
            ]
            for index, (field, value) in enumerate(rows, 1):
                key = f"{child_id}-{index:03d}"
                values.update(
                    {
                        f"desired.row.{key}.property": PERMISSION + "." + field,
                        f"desired.row.{key}.value": value,
                        f"desired.row.{key}.comment": f"許可属性{index}の設定値",
                    }
                )
                if field == "Id":
                    values.update(
                        {
                            f"observed.row.{key}.property": PERMISSION + ".Id",
                            f"observed.row.{key}.value": f"`permission-{parent + 1}-{child + 1}`"
                            if deployed
                            else "`PENDING_DEPLOY`",
                            f"observed.row.{key}.comment": f"許可属性{index}の設定値",
                        }
                    )
    return values


def role_fixture(root):
    values = service_values("iam", ["IAM.Role"])
    values.update(
        resource_values(
            "001",
            "IAM.Role",
            "iam-app-dev-worker-role",
            "CREATE",
            [("RoleName", "`app-dev-worker-role`")],
        )
    )
    write_model(root / "model/dev/123456789012/iam.properties", values)


def rejects(action, message):
    try:
        action()
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError(f"invalid input accepted: {message}")


__all__ = [
    "FUNCTION",
    "HELPERS",
    "PERMISSION",
    "Path",
    "ROOT",
    "SYNC",
    "expanded_design",
    "fixture",
    "formal_property",
    "json",
    "layout_errors",
    "load",
    "markdown_for",
    "model_projection",
    "properties",
    "re",
    "read_model",
    "rejects",
    "resource_anchor",
    "shutil",
    "sync_views",
    "sys",
    "tempfile",
    "write_model",
]

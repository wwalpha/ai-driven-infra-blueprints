"""Checks for authoritative properties, service displays and service failure protection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import io
import json
import os
import shutil
import subprocess
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

import model.projection as model_projection
import model.render as model_design
import pytest
import sync_files
import sync_runtime
import sync_views
from design.catalog import DesignSchemaCatalog
from design.layout import (
    SUBNET_LIST_PROPERTIES,
    catalog_order_errors,
    expanded_display_rows,
    resource_display_name,
    resource_has_name_property,
    stack_deployment_policy,
    stack_design,
)
from design.layout_schema import ALIGNMENT, HEADER, resource_anchor
from design.services.definitions.codebuild import CODEBUILD_VPC_PROPERTIES
from design.services.ec2.security_groups import COMMENTS, GROUP_COMMENTS
from model.core import properties, stack_model
from model.display import catalog_display_rows, display_rows, row_table
from model.files import load_model, read_model
from model.projection import resource_rows
from model.render import markdown_for
from model.validation import (
    design_naming_errors,
    naming_errors,
    naming_rule_files,
    naming_target_matches,
    naming_targets,
    validate_kms_policy_accounts,
)
from support.model_sources import snapshot_model, write_fixture_files, write_model
from support.pytest_cli import Diagnostics, run
from support.validator import load

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


ROOT = Path(__file__).resolve().parents[4]

SYNC = load("sync-model")


def model(service, kind, name, rows, logical_id=None, label=None):
    anchor = resource_anchor(service, name, kind)
    result = {
        f"desired.service.{service}.serviceId": service,
        f"desired.service.{service}.ownedCatalogResourceTypes": kind,
        "display.service.title": f"# {service} 詳細設計",
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.anchor": anchor,
        "desired.resource.001.logicalId": kind.replace(".", "_") + "_001",
        "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
        "desired.resource.001.cfn-logicalId": "fixture-"
        + (logical_id or "Resource").replace("_", ""),
        "display.resource.001.comment": "対象環境のデータ処理を提供するresource",
    }
    if kind in DesignSchemaCatalog(ROOT).api_schemas:
        result.pop("desired.resource.001.cfn-logicalId")
    if label:
        result["display.resource.001.label"] = label
    for number, (field, value, comment) in enumerate(rows, 1):
        key = f"001-{number:03d}"
        result[f"desired.row.{key}.property"] = kind + "." + field
        result[f"desired.row.{key}.value"] = value
        result[f"desired.row.{key}.comment"] = comment
    return result


def text(values):
    values = dict(values)
    for key, value in list(values.items()):
        if key.endswith(".document"):
            document = json.loads(value)
            values[key] = json.dumps(
                document, ensure_ascii=False, separators=(",", ":")
            )
            values[key.removesuffix(".document") + ".artifactSha256"] = (
                model_projection.document_sha256(document)
            )
    return (
        "# model-format: 2\n# Runtime projection for fixture comparison; write_model strips derived fields.\n"
        + "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
    )


STACK_VALUES = {
    "desired.stack.001.name": "fixture",
    "desired.stack.001.placementName": "fixture",
    "desired.stack.001.template": "fixture.yaml",
    "desired.stack.001.parameters": "fixture.json",
    "desired.stack.001.deployOrder": "1",
    "display.stack.001.comment": "合成Stack",
}


def roundtrip(path, values, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    project_root = path.parents[4]
    project = project_root / "project.json"
    if not project.exists():
        target = {
            "environment": path.parents[1].name,
            "awsAccountId": "123456789012",
            "awsRegion": "ap-northeast-1",
            "iacEngine": "cloudformation",
        }
        if path.parent.name != target["awsAccountId"]:
            target["alias"] = path.parent.name
        project.write_text(json.dumps({"targets": [target]}))
    stacks = (
        project_root
        / "model"
        / path.relative_to(project_root / "docs/designs").parent
        / "cloudformation-stacks.properties"
    )
    if not stacks.exists() and any(
        key.endswith(".cfn-logicalId") and value.startswith("fixture-")
        for key, value in values.items()
    ):
        write_model(
            stacks,
            {
                "desired.stack.001.name": "fixture",
                "desired.stack.001.placementName": "fixture",
                "desired.stack.001.template": "fixture.yaml",
                "desired.stack.001.parameters": "fixture.json",
                "desired.stack.001.deployOrder": "1",
                "display.stack.001.comment": "合成Stack",
            },
        )
    if stacks.exists():
        stack_values = dict(load_model(stacks).values)
        stack_view = path.with_name("cloudformation-stacks.md")
        expected_stack = markdown_for(
            stack_view, stack_values, project_root, definitions_root=root
        )
        if not stack_view.exists() or stack_view.read_bytes() != expected_stack.encode(
            "utf-8"
        ):
            stack_view.write_text(expected_stack, encoding="utf-8")
    write_model(
        project_root
        / "model"
        / path.relative_to(project_root / "docs/designs").with_suffix(".properties"),
        values,
    )
    expected = markdown_for(path, values, project_root, definitions_root=root)
    path.write_text(expected, encoding="utf-8")
    plan = SimpleNamespace(
        root=project_root,
        read_inputs={},
        expected_outputs={path: {path: expected}},
        failure_records=[],
        saved={},
    )
    sync_runtime._compare_generation(plan)
    assert not plan.failure_records, plan.failure_records
    return expected


@pytest.fixture
def root(project_workspace):
    return project_workspace


@pytest.fixture
def project(root):
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    stacks = root / "model/dev/123456789012/cloudformation-stacks.properties"
    values = {
        "desired.stack.001.name": "fixture",
        "desired.stack.001.placementName": "fixture",
        "desired.stack.001.template": "fixture.yaml",
        "desired.stack.001.parameters": "fixture.json",
        "desired.stack.001.deployOrder": "1",
        "display.stack.001.comment": "合成Stack",
    }
    write_model(stacks, values)
    view = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text(markdown_for(view, values, root), encoding="utf-8")


__all__ = [
    "ALIGNMENT",
    "CODEBUILD_VPC_PROPERTIES",
    "COMMENTS",
    "Diagnostics",
    "GROUP_COMMENTS",
    "HEADER",
    "Path",
    "ROOT",
    "SUBNET_LIST_PROPERTIES",
    "SYNC",
    "SimpleNamespace",
    "catalog_display_rows",
    "catalog_order_errors",
    "design_naming_errors",
    "display_rows",
    "expanded_display_rows",
    "io",
    "json",
    "load",
    "load_model",
    "markdown_for",
    "model",
    "model_design",
    "model_projection",
    "naming_errors",
    "naming_rule_files",
    "naming_target_matches",
    "naming_targets",
    "os",
    "patch",
    "project",
    "properties",
    "pytest",
    "pytestmark",
    "read_model",
    "redirect_stderr",
    "resource_anchor",
    "resource_display_name",
    "resource_has_name_property",
    "resource_rows",
    "root",
    "roundtrip",
    "row_table",
    "run",
    "shutil",
    "snapshot_model",
    "stack_deployment_policy",
    "stack_design",
    "stack_model",
    "subprocess",
    "sync_files",
    "sync_runtime",
    "sync_views",
    "sys",
    "text",
    "validate_kms_policy_accounts",
    "write_fixture_files",
    "write_model",
]


def main():
    return run(
        Path(__file__).resolve().parents[1] / "integrations/model_design.checks.py",
        message="model_design: PASS (7 integration checks: generated references, imports, accounts, stacks and service failure protection)",
    )


__all__.append("main")

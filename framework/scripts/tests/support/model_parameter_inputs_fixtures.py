"""Explicit environment Models and generic YAML rejection fixtures."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from unittest.mock import patch as patch

import pytest
from model.format import parse as parse
from model.sources import load_model as load_model
from support.import_model_fixtures import (
    resource_values,
    service_values,
)
from support.model_sources import declare_outputs, write_model
from utils.yaml_format import yaml_read as yaml_read

ROOT = Path(__file__).resolve().parents[4]


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError, KeyError, TypeError) as error:
        assert phrase in str(error), (phrase, str(error))
    else:
        raise AssertionError("invalid input accepted: " + phrase)


def fixture(root):
    environments = ("preview", "prod")
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "app",
                "targets": [
                    {
                        "environment": env,
                        "alias": alias,
                        "awsAccountId": account,
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for env in environments
                    for alias, account in [
                        ("other", "210987654321"),
                        ("team", "123456789012"),
                    ]
                ],
            }
        )
        + "\n"
    )
    paths = {}
    for env in environments:
        values = service_values("vpc", ["EC2.VPC", "EC2.Subnet"])
        suffix = "-one" if env == "preview" else ""
        for rid, kind, identity in [
            ("017", "EC2.VPC", "main-vpc"),
            ("042", "EC2.Subnet", "private-a"),
            ("083", "EC2.Subnet", "private-c"),
        ]:
            name = (
                ("vpc" if kind == "EC2.VPC" else "sbnt")
                + "-app-"
                + env
                + suffix
                + ("" if kind == "EC2.VPC" else "-" + identity[-1])
            )
            anchor = "vpc-" + name
            fields = [
                ("Name", "`" + name + "`"),
                (
                    "CidrBlock",
                    "`10.10.0.0/23`" if kind == "EC2.VPC" else "`10.10.0.0/25`",
                ),
                (
                    "VpcId" if kind == "EC2.VPC" else "SubnetId",
                    f"[resource](#{anchor})",
                ),
                ("EnableDnsSupport", "`true`")
                if kind == "EC2.VPC"
                else ("VpcId", f"[vpc](#vpc-vpc-app-{env}{suffix})"),
            ]
            values.update(resource_values(rid, kind, anchor, "IMPORT", fields))
            values[f"desired.row.{rid}-002.comment"] = "環境注記 " + env
            values[f"observed.row.{rid}-003.value"] = (
                "`"
                + ("vpc-" if kind == "EC2.VPC" else "subnet-")
                + rid
                + "0" * 14
                + "`"
            )
            if kind == "EC2.Subnet":
                values[f"observed.row.{rid}-004.value"] = "vpc-017" + "0" * 14
        values["desired.service.identity.lastAllocated"] = (
            '{"EC2.VPC":17,"EC2.Subnet":83}'
        )
        path = root / "model" / env / "team/vpc.properties"
        write_model(path, values)
        paths[env] = path
    for env in environments:
        write_model(
            root / "model" / env / "team/cloudformation-stacks.properties",
            {
                "desired.stack.001.name": "fixture",
                "desired.stack.001.placementName": "fixture",
                "desired.stack.001.template": "fixture.yaml",
                "desired.stack.001.parameters": "fixture.json",
                "desired.stack.001.deployOrder": "1",
                "display.stack.001.comment": "合成Stack",
            },
        )
    task = root / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n"
        + "## Validation scope\n"
        + "".join(
            "- `" + env + "/team/" + service + "`\n"
            for env in environments
            for service in ("vpc", "iam")
        )
        + "## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n- `model/**`\n- `docs/designs/**`\n"
    )
    declare_outputs(
        root, [root / "docs/designs" / env / "team/vpc.md" for env in environments]
    )
    return environments, paths


@pytest.fixture
def root(project_workspace):
    return project_workspace

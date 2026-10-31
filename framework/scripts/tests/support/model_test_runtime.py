#!/usr/bin/env python3
"""Standalone audit generation and execution checks; no AWS/network access."""

import json
import tempfile
from pathlib import Path

from model.core import entries
from model.sources import Scope, load_model
from support.model_sources import write_model
from utils.aws_mappings import mapping_alias
from utils.script_loader import module

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]
generator = module("model/audit.py", "model.audit")


def runtime(data):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = data["target"]
        (root / "project.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            **target,
                            "environment": environment,
                            "alias": alias,
                            "iacEngine": target.get("iacEngine", "cloudformation"),
                        }
                        for environment, alias in sorted(
                            {
                                tuple(address.split("/")[:2])
                                for address in data["models"]
                            }
                        )
                    ]
                }
            )
        )
        for address, values in data["models"].items():
            resources = dict(entries(values, "desired.resource."))
            authority = {
                **values,
                "desired.service.identity.lastAllocated": json.dumps(
                    {
                        kind: max(
                            int(resource["logicalId"].rsplit("_", 1)[1])
                            for resource in resources.values()
                            if resource["resourceType"] == kind
                        )
                        for kind in {
                            resource["resourceType"] for resource in resources.values()
                        }
                    }
                ),
            }
            write_model(root / "model" / (address + ".properties"), authority)
        with mapping_alias(ROOT, root):
            data["referenceRows"] = generator.reference_rows(
                root,
                {
                    address: load_model(Scope(root, *address.split("/")))
                    for address in data["models"]
                },
            )
    namespace = {
        "__name__": "audit_fixture",
        "__file__": "/offline/tests/dev/cde/vpc.py",
        "SNAPSHOT": data,
    }
    exec(
        compile(
            (ROOT / "framework/scripts/model/audit_runtime.py").read_text(
                encoding="utf-8"
            ),
            "<runtime>",
            "exec",
        ),
        namespace,
    )
    return namespace

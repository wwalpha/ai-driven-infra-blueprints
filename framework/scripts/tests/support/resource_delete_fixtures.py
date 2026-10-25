#!/usr/bin/env python3
"""Parent deletion transactions use synthetic sources; no consumer checkout or AWS."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

from model.format import owner, serialize
from model.operations import prepare_edit, publish_edit
from model.sources import load_model, scope_for
from support.import_model_fixtures import (
    operation_contract,
    resource_values,
    service_values,
)
from support.model_sources import write_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def contract(sources, references=(), detaches=()):
    text = (
        operation_contract("import-delete")
        .split("## Model merge pairs")[0]
        .split("## Model delete sources")[0]
    )
    if detaches:
        text += "- Model refactor: `value-preserving`\n"
    text += "## Model delete sources\n" + "".join(
        "- `" + source + "`\n" for source in sources
    )
    for heading, records in [
        ("Model reference changes", references),
        ("Model dependency detach", detaches),
    ]:
        if records:
            text += (
                "## "
                + heading
                + "\n"
                + "".join("- " + json.dumps(record) + "\n" for record in records)
            )
    return text


def fixture(root, multiple=False):
    root.mkdir(parents=True, exist_ok=True)
    services = ["service-a", "service-b"] if multiple else ["service-a"]
    count = 5 if multiple else 10
    sources = []
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": env,
                        "alias": "cde",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for env in ("dev", "stg")
                ]
            }
        )
    )
    for service in services:
        for env in ("dev", "stg"):
            values = service_values(service, ["Example.Resource"])
            for index in range(1, count + 2):
                rid = f"{index:03d}"
                values.update(
                    resource_values(
                        rid,
                        "Example.Resource",
                        "resource-" + rid,
                        "IMPORT",
                        [("Name", env + "-" + rid)],
                    )
                )
                values[f"observed.row.{rid}-001.value"] = "observed-" + rid
                if env == "stg" and index <= count:
                    sources.append("stg/cde/" + service + "/" + rid)
            write_model(
                root / "model" / env / "cde" / (service + ".properties"), values
            )
    return sources


def deletion(root, address):
    env, target, service, rid = address.split("/")
    file = root / "model" / env / target / (service + ".properties")
    values = dict(load_model(file).authoritative)
    return {
        file: serialize(
            {
                key: value
                for key, value in values.items()
                if owner(key, values) != ("resource", rid)
            }
        )
    }


def write_candidate(context, changes):
    scope = scope_for(next(iter(changes)))
    return publish_edit(
        prepare_edit(load_model(scope, context.snapshot), changes, context), context
    )


def save(changes):
    for path, text in changes.items():
        path.write_text(text, encoding="utf-8")


def changed(before, after):
    return {
        path.relative_to(after).as_posix()
        for path in after.rglob("*")
        if path.is_file()
        and (
            not (before / path.relative_to(after)).exists()
            or path.read_bytes() != (before / path.relative_to(after)).read_bytes()
        )
    }

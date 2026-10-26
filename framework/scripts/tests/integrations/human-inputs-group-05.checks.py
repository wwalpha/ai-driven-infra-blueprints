#!/usr/bin/env python3
"""Explicit group-05 properties, native JSON, identity and managed save boundaries."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json

from model.adapters.task import edit_write_context
from model.format import serialize
from model.sources import design_source_digest, load_model
from support.it_case_receipt import it_case
from support.model_sources import write_model
from support.producer_identifier_reference_fixtures import resource, setup
from support.publication_fixtures import publication_repository
from support.repository_fixtures import fixture, git, start

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SERVICES = {
    "cloudtrail": (
        "CloudTrail.Trail",
        [("TrailName", "`ctrail-fixture-preview`"), ("IsMultiRegionTrail", "`false`")],
    ),
    "secrets-manager": (
        "SecretsManager.Secret",
        [("Name", "`fixture/secret`"), ("Description", ' 001 \\ " ')],
    ),
    "vpc-endpoint": (
        "EC2.VPCEndpoint",
        [
            ("ServiceName", "`com.amazonaws.vpce.ap-northeast-1.vpce-svc-fixture`"),
            ("PrivateDnsEnabled", "`true`"),
        ],
    ),
}


@it_case
def check_declared_inputs(service="cloudtrail"):
    kind, rows = SERVICES[service]
    with fixture() as primary:
        setup(primary, [service], [kind], ("preview", "future"))
        values = resource("017", kind, service + "-fixed", rows)
        values["desired.resource.017.resourceMode"] = "CREATE"
        values.update(resource("083", kind, service + "-other", rows))
        values["desired.resource.083.resourceMode"] = "CREATE"
        document = {
            "Statement": [],
            "local": 3,
            "flag": False,
            "text": "001",
            "empty": "",
            "object": {"日本語": True},
            "array": ["b", "a", 1, False, None],
            "null": None,
            "number": 2.5,
        }
        if service == "vpc-endpoint":
            document = {
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "*",
                        "Resource": "*",
                        "Condition": {"Fixture": document},
                    }
                ]
            }
            updated_document = json.loads(json.dumps(document))
            updated_document["Statement"][0]["Condition"]["Fixture"]["number"] = 4.5
        prefix = "desired.row.017-003."
        if service == "vpc-endpoint":
            values.update(
                {
                    prefix + "property": kind + ".PolicyDocument",
                    prefix + "value": "[" + service + "](" + service + "/fixture.json)",
                    prefix + "comment": "合成 native JSON",
                    prefix + "document": json.dumps(document, ensure_ascii=False),
                }
            )
        paths = {}
        for environment in ("preview", "future"):
            path = primary / "model" / environment / "team" / (service + ".properties")
            write_model(path, values)
            paths[environment] = path.relative_to(primary).as_posix()
        git(primary, "add", "project.json", "model")
        git(primary, "commit", "-qm", "explicit group05 fixture")
        target, state = start(primary, files=tuple(paths.values()))
        name = state["task_file"]
        listed = "".join("- `" + path + "`\n" for path in (name, *paths.values()))
        text = (
            "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
            "## Required changes\n- [R1] Explicit group05 values\n## Acceptance checks\n- [R1] `exists:project.json`\n"
            "## Validation scope\n"
            + "".join("- `" + env + "/team/" + service + "`\n" for env in paths)
        )
        for heading in ("Modified files", "Allowed paths"):
            text += "## " + heading + "\n" + listed
        (target / name).write_text(text)
        path, other = target / paths["preview"], target / paths["future"]
        saved = other.read_bytes()
        initial = load_model(path)
        assert dict(initial.authoritative) == values
        if service == "vpc-endpoint":
            assert json.loads(initial.authoritative[prefix + "document"]) == document
        changed = {
            **values,
            "desired.row.017-002.value": "`changed`"
            if service == "secrets-manager"
            else "`true`"
            if service == "cloudtrail"
            else "`false`",
        }
        if service == "vpc-endpoint":
            changed[prefix + "document"] = json.dumps(updated_document)
        before = design_source_digest(path)
        with edit_write_context(
            target, {("preview", "team", service)}, name
        ) as context:
            assert publish_edit(
                prepare_edit(
                    load_model(path, context.snapshot),
                    {path: serialize(changed)},
                    context,
                ),
                context,
            ) == (path,)
        assert dict(load_model(path).authoritative) == changed
        assert other.read_bytes() == saved and design_source_digest(path) != before
        assert (
            load_model(path).authoritative["desired.row.083-002.value"]
            == values["desired.row.083-002.value"]
        )
        raw = path.read_bytes()
        with edit_write_context(
            target, {("preview", "team", service)}, name
        ) as context:
            assert (
                publish_edit(
                    prepare_edit(
                        load_model(path, context.snapshot),
                        {path: serialize(changed)},
                        context,
                    ),
                    context,
                )
                == ()
            )
        assert path.read_bytes() == raw
    print(
        service
        + ": PASS (explicit fields/types, identity, derived hash, managed edit/no-op and environment isolation)"
    )


if __name__ == "__main__":
    with publication_repository():
        for service in sorted(SERVICES):
            check_declared_inputs(service)

#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from model.adapters.task import edit_write_context
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import (
    Path,
    affected,
    design_source_digest,
    json,
    load_model,
    resource,
    serialize,
    setup,
    tempfile,
    trace_model,
    write_model,
)
from support.publication_fixtures import publication_repository
from support.repository_fixtures import fixture, git, start
from utils.json_format import json_text, policy_json, validate_aws_document

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check(root):
    with fixture() as primary:
        setup(primary, ["vpc-endpoint"], ["EC2.VPCEndpoint"], ("preview", "release"))
        key = "desired.row.017-004."
        document = {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Resource": "*",
                    "Condition": {
                        "IpAddress": {"aws:VpcSourceIp": "198.51.100.0/24"},
                        "Fixture": {"Enabled": False, "Count": 2, "Text": "日本語"},
                    },
                    "Action": ["s3:GetObject", "s3:ListBucket"],
                }
            ]
        }
        values = {
            name.replace(".017-001.", ".017-004."): value
            for name, value in resource(
                "017",
                "EC2.VPCEndpoint",
                "gateway",
                [("PolicyDocument", "[policy](vpc-endpoint/policy.json)")],
            ).items()
        }
        values["desired.resource.017.resourceMode"] = "CREATE"
        values[key + "document"] = json.dumps(document, ensure_ascii=False)
        paths = {}
        for environment in ("preview", "release"):
            path = primary / "model" / environment / "team/vpc-endpoint.properties"
            write_model(path, values)
            paths[environment] = path.relative_to(primary).as_posix()
        git(primary, "add", "model", "project.json")
        git(primary, "commit", "-qm", "explicit document sources")
        target, state = start(primary, files=tuple(paths.values()))
        name = state["task_file"]
        listed = "".join("- `" + item + "`\n" for item in [name, *paths.values()])
        contract = (
            "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
            "## Required changes\n- [R1] Explicit native documents\n## Acceptance checks\n- [R1] `exists:project.json`\n"
            "## Validation scope\n- `preview/team/vpc-endpoint`\n- `release/team/vpc-endpoint`\n"
        )
        for heading in ("Modified files", "Allowed paths"):
            contract += "## " + heading + "\n" + listed
        (target / name).write_text(contract)
        first = load_model(target / paths["preview"])
        assert (
            load_model(target / paths["preview"]).authoritative == first.authoritative
        )
        actual = json.loads(first.authoritative[key + "document"])
        assert actual["Statement"][0]["Action"] == ["s3:GetObject", "s3:ListBucket"]
        assert (
            actual["Statement"][0]["Condition"]["Fixture"]["Enabled"] is False
            and type(actual["Statement"][0]["Condition"]["Fixture"]["Count"]) is int
        )
        assert json.loads(first.values[key + "document"]) == actual
        artifact = root / "policy.json"
        artifact.write_text(json_text(actual) + "\n", encoding="utf-8")
        saved_document = policy_json(artifact.read_text(encoding="utf-8"))
        validate_aws_document(saved_document)
        assert saved_document == actual
        updated = []
        for environment, relative in paths.items():
            path = target / relative
            before = design_source_digest(path)
            changed = {
                **values,
                key + "document": values[key + "document"].replace(
                    "198.51.100.0/24", "203.0.113.0/24"
                ),
            }
            with edit_write_context(
                target, {(environment, "team", "vpc-endpoint")}, name
            ) as context:
                assert publish_edit(
                    prepare_edit(
                        load_model(path, context.snapshot),
                        {path: serialize(changed)},
                        context,
                    ),
                    context,
                ) == (path,)
            current = load_model(path)
            updated.append(current.values)
            assert current.values[key + "document"] != first.values[key + "document"]
            assert design_source_digest(path) != before
            assert json.loads(current.values[key + "document"]) == json.loads(
                changed[key + "document"]
            )
            assert (
                trace_model(path, key + "document")["value"]
                == changed[key + "document"]
            )
            raw = path.read_bytes()
            with edit_write_context(
                target, {(environment, "team", "vpc-endpoint")}, name
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
            assert affected(target, [relative]) == {
                (environment, "team", "vpc-endpoint")
            }
        assert updated[0] == updated[1]
    print(
        "JSON document sources: PASS (native types/order; content equality; real managed edit/no-op; independent environments)"
    )


if __name__ == "__main__":
    with publication_repository(), tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

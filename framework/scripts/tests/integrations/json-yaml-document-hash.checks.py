#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from model.adapters.task import edit_write_context
from support.it_case_receipt import it_case
from support.json_yaml_document_hash_fixtures import (
    Path,
    affected,
    design_source_digest,
    document_sha256,
    json,
    json_sha256,
    json_text,
    load_model,
    rejected,
    resource,
    serialize,
    setup,
    tempfile,
    trace_model,
    write_model,
)
from support.publication_fixtures import publication_repository
from support.repository_fixtures import fixture, git, start

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
                    "Condition": {"IpAddress": {"aws:VpcSourceIp": "198.51.100.0/24"}},
                    "Action": ["s3:GetObject", "s3:ListBucket"],
                    "Enabled": False,
                    "Count": 2,
                    "Text": "日本語",
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
            actual["Statement"][0]["Enabled"] is False
            and type(actual["Statement"][0]["Count"]) is int
        )
        assert first.values[key + "artifactSha256"] == document_sha256(actual)
        assert key + "artifactSha256" not in first.authoritative
        artifact = root / "policy.json"
        artifact.write_text(json_text(actual) + "\n", encoding="utf-8")
        assert json_sha256(artifact) == first.values[key + "artifactSha256"]
        updated = []
        for environment, relative in paths.items():
            path = target / relative
            before = design_source_digest(path)
            raw = path.read_bytes()
            with edit_write_context(
                target, {(environment, "team", "vpc-endpoint")}, name
            ) as context:
                snapshot = load_model(path, context.snapshot)
                bad = {**snapshot.authoritative, key + "artifactSha256": "stale"}
                rejected(
                    lambda *, bad=bad, path=path, snapshot=snapshot: prepare_edit(
                        snapshot, {path: serialize(bad)}, context
                    ),
                    "unknown Model field",
                )
            assert path.read_bytes() == raw
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
            assert (
                current.values[key + "artifactSha256"]
                != first.values[key + "artifactSha256"]
            )
            assert design_source_digest(path) != before
            assert current.values[key + "artifactSha256"] == document_sha256(
                json.loads(current.authoritative[key + "document"])
            )
            assert (
                trace_model(path, key + "artifactSha256")["derivedFrom"]
                == key + "document"
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
        "JSON document hashes: PASS (canonical types/order; derived-only hash; stale authority rejection; real managed edit/no-op; independent environments)"
    )


if __name__ == "__main__":
    with publication_repository(), tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

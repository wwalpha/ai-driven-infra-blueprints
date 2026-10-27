#!/usr/bin/env python3
"""Fixed S3 anchors retain strict IDs, names and links in canonical Models."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
from contextlib import redirect_stdout

import support.producer_identifier_reference_fixtures as _exports_support_producer_identifier_reference_fixtures
import sync_runtime
from model.projection import bound_resource_anchors
from model.render import markdown_for as markdown_for
from support.it_case_receipt import it_case
from support.model_sources import declare_outputs
from support.producer_identifier_reference_fixtures import (
    Path,
    json,
    load_model,
    reference,
    resource,
    tempfile,
    write_model,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

# Preserve shared fixtures and compatibility exports under their historical names.
usages = _exports_support_producer_identifier_reference_fixtures.usages


@it_case
def check(root):
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "anchor-fixture",
                "targets": [
                    {
                        "environment": "preview",
                        "alias": alias,
                        "awsAccountId": account,
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for alias, account in [
                        ("other", "210987654321"),
                        ("team", "123456789012"),
                    ]
                ],
            }
        )
        + "\n"
    )
    task = root / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Validation scope\n- `preview/team/s3`\n"
        "## Allowed paths\n- `tasks/example.md`\n- `model/**`\n- `docs/designs/**`\n"
    )
    declare_outputs(root, [root / "docs/designs/preview/team/s3.md"])
    values = resource(
        "003",
        "S3.Bucket",
        "s3-archive-original",
        [("BucketName", "`archive-original`"), ("Region", "`ap-northeast-1`")],
    )
    values.update(
        {
            "desired.service.s3.serviceId": "s3",
            "desired.service.s3.ownedCatalogResourceTypes": "S3.Bucket",
            "display.service.title": "# Amazon S3 詳細設計",
        }
    )
    path = root / "model/preview/team/s3.properties"
    write_model(path, values)
    view = root / "docs/designs/preview/team/s3.md"
    assert sync_runtime.sync(root, True, "preview", "team", services=["s3"]) == 0
    assert bound_resource_anchors(path) == {
        ("S3.Bucket", "S3_Bucket_003"): "s3-archive-original"
    }
    consumer = path.with_name("cloudtrail.properties")
    linked = "[S3_Bucket_003](s3.md#s3-archive-original)"
    candidate = resource(
        "087", "CloudTrail.Trail", "cloudtrail-job", [("S3BucketName", linked)]
    )
    candidate.update(
        reference(
            "bucket",
            "desired.row.087-001.value",
            linked,
            "s3",
            "003",
            "S3.Bucket",
            mode="link",
            label="display-name",
        )
    )
    write_model(consumer, candidate)
    before = consumer.read_bytes()
    updated = {**values, "desired.row.003-001.value": "`archive-renamed`"}
    write_model(path, updated)
    assert (
        load_model(path).authoritative["desired.resource.003.anchor"]
        == "s3-archive-original"
    )
    assert (
        load_model(path).authoritative["desired.resource.003.logicalId"]
        == "S3_Bucket_003"
    )
    assert {key for key in updated if key.startswith("desired.row.")} == {
        key for key in values if key.startswith("desired.row.")
    }
    assert not load_model(consumer).warnings
    assert load_model(consumer).authoritative == candidate
    assert consumer.read_bytes() == before
    new_link = linked
    explicit = {
        **candidate,
        "desired.row.087-001.value": new_link,
        "desired.reference.bucket.text": new_link,
    }
    write_model(consumer, explicit)
    current = load_model(consumer)
    assert not current.warnings and len(usages(current)) == 1
    assert sync_runtime.sync(root, True, "preview", "team", services=["s3"]) == 0
    assert sync_runtime.sync(root, False, "preview", "team", services=["s3"]) == 0
    assert "### S3.Bucket: archive-renamed" in view.read_text()
    assert '<a id="s3-archive-original"></a>' in view.read_text()
    print(
        "Fixed S3 anchors: PASS (explicit rename/consumer update; fixed names/links/IDs; generation; syntax/identity rejection; unrelated directory isolation)"
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        with redirect_stdout(io.StringIO()) as output:
            check(Path(directory).resolve())
        print(output.getvalue().strip().splitlines()[-1])

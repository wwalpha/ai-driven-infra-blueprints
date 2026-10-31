#!/usr/bin/env python3
"""Explicit saved references: fixed identity, dependencies and semantic warnings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import (
    Path,
    affected,
    dependency_hashes,
    design_source_digest,
    load_model,
    reference,
    resource,
    setup,
    source_inputs,
    tempfile,
    warning,
    write_model,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check(root):
    setup(
        root,
        ["security-group", "quicksight", "vpc"],
        ["EC2.SecurityGroup", "QuickSight.VPCConnection", "EC2.VPC"],
    )
    producer = root / "model/preview/team/security-group.properties"
    original = resource(
        "052",
        "EC2.SecurityGroup",
        "security-group-app-preview-one",
        [
            ("GroupName", "`app-preview-one`"),
            ("GroupDescription", "`QuickSight VPC connection`"),
            (
                "VpcId",
                '`{"$modelRef":{"logicalId":"EC2_VPC_017","attribute":"VpcId"}}`',
            ),
        ],
    )
    write_model(producer, original)
    write_model(
        producer.with_name("vpc.properties"),
        resource("017", "EC2.VPC", "vpc-app-preview", [("Name", "`vpc-app-preview`")]),
    )
    path = producer.with_name("quicksight.properties")
    values = {}
    for rid, label, _policy in [
        ("021", "app-preview-one", "display-name"),
        ("083", "PENDING_DEPLOY", "fixed"),
    ]:
        link = '`{"$modelRef":{"logicalId":"EC2_SecurityGroup_052","attribute":"GroupId"}}`'
        values.update(
            resource(
                rid,
                "QuickSight.VPCConnection",
                "quicksight-" + rid,
                [("SecurityGroupIds", link)],
            )
        )

        values[f"display.resource.{rid}.label"] = label
    values["desired.note.producerName.text"] = "app-preview-one"
    values.update(
        reference(
            "producer-name",
            "desired.note.producerName.text",
            "app-preview-one",
            "security-group",
            "052",
            "EC2.SecurityGroup",
            prop="EC2.SecurityGroup.GroupName",
        )
    )
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert (
        snapshot.authoritative["desired.row.021-001.value"]
        == '`{"$modelRef":{"logicalId":"EC2_SecurityGroup_052","attribute":"GroupId"}}`'
    )
    assert (
        snapshot.authoritative["desired.row.083-001.value"]
        == '`{"$modelRef":{"logicalId":"EC2_SecurityGroup_052","attribute":"GroupId"}}`'
    )
    assert producer in source_inputs(path)
    assert affected(root, [producer.relative_to(root)]) == {
        ("preview", "team", "security-group"),
        ("preview", "team", "quicksight"),
    }
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    producer.write_text(producer.read_text() + "# producer annotation\n")
    assert (
        design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    )
    assert load_model(path).authoritative == snapshot.authoritative
    renamed = {
        key: value.replace("preview-one", "preview-two")
        for key, value in original.items()
    }
    write_model(producer, renamed)
    assert (
        warning(path, "differs from saved text").authoritative == snapshot.authoritative
    )
    write_model(
        producer,
        {key.replace(".052", ".053", 1): value for key, value in original.items()},
    )
    assert not load_model(path).warnings
    write_model(producer, original)
    write_model(producer, original)
    print(
        "Security Group references: PASS (GroupName; fixed labels; type/identity warnings; dependency snapshots)"
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())

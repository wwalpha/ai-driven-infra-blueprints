#!/usr/bin/env python3
"""Explicit saved references: fixed identity, dependencies and semantic warnings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.it_case_receipt import module_complete
from support.producer_identifier_reference_fixtures import (
    Path,
    affected,
    dependency_hashes,
    design_source_digest,
    json,
    load_model,
    resource,
    setup,
    source_inputs,
    tempfile,
    write_model,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check(root, service, kind, name_property):
    setup(root, [service, "ec2"], [kind, "EC2.Instance", "IAM.Role"])
    producer = root / "model/preview/team" / (service + ".properties")
    original = resource(
        "052",
        kind,
        service + "-app-preview-one",
        [
            (
                (name_property or "KMS.Key.Description").removeprefix(kind + "."),
                "`app-preview-one`",
            )
        ],
    )
    if name_property:
        original.update(
            resource("075", "IAM.Role", "iam-app-role", [("RoleName", "`app-role`")])
        )
        original.update(
            {
                "desired.row.052-002.property": "IAM.InstanceProfile.Roles",
                "desired.row.052-002.value": '`{"$modelRef":{"logicalId":"IAM_Role_075","attribute":"RoleName"}}`',
                "desired.row.052-002.comment": "ロール",
            }
        )
    original["desired.service.identity.lastAllocated"] = json.dumps(
        {kind: 52, **({"IAM.Role": 75} if name_property else {})}
    )
    write_model(producer, original)
    path = producer.with_name("ec2.properties")
    values = {}
    for rid, label, _policy in [
        (
            "021",
            "app-preview-one" if name_property else "052",
            "display-name" if name_property else "resource-id",
        ),
        ("083", "original-label", "fixed"),
    ]:
        link = (
            "`"
            + json.dumps(
                {
                    "$modelRef": {
                        "logicalId": kind.replace(".", "_") + "_052",
                        "attribute": "InstanceProfileName" if name_property else "Arn",
                    }
                }
            )
            + "`"
        )
        values.update(
            resource(
                rid,
                "EC2.Instance",
                "ec2-" + rid,
                [
                    (
                        "IamInstanceProfile"
                        if name_property
                        else "BlockDeviceMappings[].Ebs.KmsKeyId",
                        link,
                    )
                ],
            )
        )

        values[f"display.resource.{rid}.label"] = label
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert producer in source_inputs(path)
    assert affected(root, [producer.relative_to(root)]) == {
        ("preview", "team", service),
        ("preview", "team", "ec2"),
    }
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    producer.write_text(producer.read_text() + "# producer annotation\n")
    assert (
        design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    )
    assert load_model(path).authoritative == snapshot.authoritative
    write_model(
        producer,
        {
            key: value
            if key.endswith(".anchor")
            else value.replace("preview-one", "preview-two")
            for key, value in original.items()
        },
    )
    assert not load_model(path).warnings
    assert load_model(path).authoritative == snapshot.authoritative
    changed_label = dict(values)
    changed_label["display.resource.083.label"] = "changed-label"
    write_model(producer, original)
    write_model(path, changed_label)
    assert not load_model(path).warnings and design_source_digest(path) != digest
    write_model(path, values)


if __name__ == "__main__":
    for service, kind, name in [
        ("iam", "IAM.InstanceProfile", "IAM.InstanceProfile.InstanceProfileName"),
        ("kms", "KMS.Key", None),
    ]:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), service, kind, name)
    print(
        "Group 03 references: PASS (InstanceProfileName; unnamed Key; labels; explicit candidates; dependency snapshots; warnings)"
    )

module_complete(__file__)

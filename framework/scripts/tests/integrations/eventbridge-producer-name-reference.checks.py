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
    reference,
    resource,
    setup,
    source_inputs,
    tempfile,
    trace_model,
    warning,
    write_model,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check(root, service, kind, property_name):
    setup(root, [service, "eventbridge"], [kind, "Events.Rule", "Lambda.Permission"])
    producer = root / "model/preview/team" / (service + ".properties")
    original = resource(
        "052",
        kind,
        service + "-original",
        [
            (property_name, "`Original-Case_01`"),
            ("Nested.Name", "`unrelated-nested-name`"),
        ],
    )
    if service == "lambda":
        original.update(
            resource(
                "053",
                "Lambda.Permission",
                "lambda-invoke-permission",
                [
                    (
                        "FunctionName",
                        '`{"$modelRef":{"logicalId":"Lambda_Function_052","attribute":"Arn"}}`',
                    ),
                    ("Principal", "`events.amazonaws.com`"),
                    (
                        "SourceArn",
                        '`{"$modelRef":{"logicalId":"Events_Rule_021","attribute":"Arn"}}`',
                    ),
                ],
            )
        )
        original.update(
            {
                "desired.resource.053.parentProperty": "Lambda.Permission.FunctionName",
                "desired.resource.053.parentReference": '`{"$modelRef":{"logicalId":"Lambda_Function_052","attribute":"Arn"}}`',
            }
        )
    original["desired.service.identity.lastAllocated"] = json.dumps(
        {kind: 52, **({"Lambda.Permission": 53} if service == "lambda" else {})}
    )
    write_model(producer, original)
    path = producer.with_name("eventbridge.properties")
    values = resource(
        "021",
        "Events.Rule",
        "eventbridge-rule",
        [("Name", "`rule`"), ("EventPattern", "[config](eventbridge/raw.json)")],
    )
    key = "desired.row.021-002.document"
    values[key] = json.dumps({"name": "Original-Case_01", "count": 2, "enabled": True})
    link = f"[Original-Case_01]({service}.md#{service}-original)"
    values["desired.note.link.text"] = link
    values.update(
        reference(
            "link",
            "desired.note.link.text",
            "Original-Case_01",
            service,
            "052",
            kind,
            prop=kind + "." + property_name,
            label="none",
        )
    )
    values.update(
        reference(
            "raw",
            key,
            "Original-Case_01",
            service,
            "052",
            kind,
            prop=kind + "." + property_name,
            pointer="/name",
        )
    )
    write_model(path, values)
    snapshot = load_model(path)
    assert not snapshot.warnings, snapshot.warnings
    assert json.loads(snapshot.authoritative[key]) == {
        "name": "Original-Case_01",
        "count": 2,
        "enabled": True,
    }
    assert trace_model(path, key)["references"]["raw"]["format"] == "name"
    assert producer in source_inputs(path)
    digest, dependencies = design_source_digest(path), dependency_hashes(path)
    write_model(producer, {**original, "desired.row.052-001.value": "`Renamed`"})
    assert (
        warning(path, "differs from saved text").authoritative == snapshot.authoritative
    )
    assert (
        design_source_digest(path) == digest and dependency_hashes(path) != dependencies
    )
    assert affected(root, [producer.relative_to(root)]) == {
        ("preview", "team", service),
        ("preview", "team", "eventbridge"),
    }
    write_model(producer, original)


if __name__ == "__main__":
    for service, kind, name in [
        ("lambda", "Lambda.Function", "FunctionName"),
        ("sqs", "SQS.Queue", "QueueName"),
        ("iam", "IAM.User", "UserName"),
    ]:
        with tempfile.TemporaryDirectory() as directory:
            check(Path(directory).resolve(), service, kind, name)
    print(
        "EventBridge producer names: PASS (FunctionName/QueueName/UserName; typed JSON; labels; trace; dependency snapshots; warnings)"
    )

module_complete(__file__)

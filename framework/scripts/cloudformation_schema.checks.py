#!/usr/bin/env python3
"""Focused checks for the pinned CloudFormation provider schemas."""

from __future__ import annotations

from pathlib import Path

from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    assert snapshot_errors(root) == []
    catalog = CloudFormationSchemaCatalog(root)

    logs = catalog.schema("Logs.LogGroup")
    assert "BearerTokenAuthenticationEnabled" in logs["properties"]  # full schema, not the curated list
    assert catalog.literal_errors(
        "Logs.LogGroup",
        "KmsKeyId",
        "arn:aws:kms:ap-northeast-1:123456789012:key/11111111-2222-3333-4444-555555555555",
    ) == []
    assert catalog.literal_errors("Logs.LogGroup", "KmsKeyId", "not-used")
    assert catalog.literal_errors("Logs.LogGroup", "RetentionInDays", "30") == []
    assert catalog.literal_errors("Logs.LogGroup", "RetentionInDays", "31")
    try:
        catalog.property_schema("Logs.LogGroup", "Encryption")
    except KeyError:
        pass
    else:
        raise AssertionError("non-schema Logs.LogGroup.Encryption was accepted")

    assert catalog.required_properties("Athena.WorkGroup") == {"Name"}
    assert catalog.literal_errors("Athena.WorkGroup", "State", "ENABLED") == []
    assert catalog.literal_errors("Athena.WorkGroup", "State", "unexpected")
    assert catalog.property_schema("DynamoDB.Table", "KeySchema[].AttributeName")["type"] == "string"
    print("cloudformation-schema: PASS")


if __name__ == "__main__":
    main()

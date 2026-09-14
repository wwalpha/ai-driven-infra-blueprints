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
    materials = root / "framework" / "materials" / "aws"
    # These fields are intentionally supported by the curated catalog.
    for resource_type, properties in {
        "IAM.User": (
            "UserName",
            "Groups",
            "LoginProfile.Password",
            "LoginProfile.PasswordResetRequired",
            "ManagedPolicyArns",
            "Path",
            "PermissionsBoundary",
            "Policies[].PolicyName",
            "Policies[].PolicyDocument",
            "Tags[].Key",
            "Tags[].Value",
        ),
        "SecretsManager.Secret": ("Type",),
        "SecretsManager.RotationSchedule": (
            "ExternalSecretRotationMetadata[].Key",
            "ExternalSecretRotationMetadata[].Value",
            "ExternalSecretRotationRoleArn",
        ),
    }.items():
        lines = (materials / (resource_type.replace(".", "_") + ".properties")).read_text().splitlines()
        for property_path in properties:
            assert f"{resource_type}.{property_path}=" in lines, property_path
            node = catalog.property_schema(resource_type, property_path)
            assert "type" in node
            if resource_type.startswith("SecretsManager."):
                assert node["type"] == "string"
    assert catalog.property_schema("IAM.User", "UserName")["type"] == "string"
    assert catalog.property_schema("IAM.User", "LoginProfile.PasswordResetRequired")["type"] == "boolean"
    assert "object" in catalog.property_schema("IAM.User", "Policies[].PolicyDocument")["type"]
    assert sum(
        line.endswith("=IDENTIFIER_OUTPUT")
        for path in materials.glob("*.properties")
        for line in path.read_text(encoding="utf-8").splitlines()
    ) == 69
    eip = (materials / "EC2_EIP.properties").read_text(encoding="utf-8")
    assert "EC2.EIP.AllocationId=IDENTIFIER_OUTPUT" in eip
    assert "EC2.EIP.PublicIp=IDENTIFIER_OUTPUT" in eip
    assert "Glue.Database.DatabaseName=" in (
        materials / "Glue_Database.properties"
    ).read_text(encoding="utf-8")
    assert "SNS.Topic.TopicArn" not in (
        materials / "SNS_Topic.properties"
    ).read_text(encoding="utf-8")
    print("cloudformation-schema: PASS")


if __name__ == "__main__":
    main()

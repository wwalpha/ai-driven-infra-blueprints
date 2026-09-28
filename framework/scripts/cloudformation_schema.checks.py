#!/usr/bin/env python3
"""Focused checks for the pinned CloudFormation provider schemas."""

from __future__ import annotations

from pathlib import Path

from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors
from design_catalog import DesignSchemaCatalog


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
        "GuardDuty.MalwareProtectionPlan": (
            "Actions.Tagging.Status",
            "ProtectedResource.S3Bucket.BucketName",
            "ProtectedResource.S3Bucket.ObjectPrefixes[]",
            "Role",
            "Tags[].Key",
            "Tags[].Value",
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
    assert catalog.required_properties("GuardDuty.MalwareProtectionPlan") == {"ProtectedResource", "Role"}
    assert "GuardDuty.MalwareProtectionPlan.MalwareProtectionPlanId=IDENTIFIER_OUTPUT" in (
        materials / "GuardDuty_MalwareProtectionPlan.properties"
    ).read_text().splitlines()
    assert catalog.property_schema("GuardDuty.MalwareProtectionPlan", "MalwareProtectionPlanId")["type"] == "string"
    assert catalog.schema("GuardDuty.MalwareProtectionPlan")["primaryIdentifier"] == [
        "/properties/MalwareProtectionPlanId"
    ]
    assert catalog.literal_errors("GuardDuty.MalwareProtectionPlan", "Actions.Tagging.Status", "ENABLED") == []
    eip = (materials / "EC2_EIP.properties").read_text(encoding="utf-8")
    assert "EC2.EIP.AllocationId=IDENTIFIER_OUTPUT" in eip
    assert "EC2.EIP.PublicIp=IDENTIFIER_OUTPUT" in eip
    assert "Glue.Database.DatabaseName=" in (
        materials / "Glue_Database.properties"
    ).read_text(encoding="utf-8")
    assert "SNS.Topic.TopicArn" not in (
        materials / "SNS_Topic.properties"
    ).read_text(encoding="utf-8")
    for resource_type, paths in {
        "Glue.Connection": "ConnectionInput ConnectionInput.AuthenticationConfiguration ConnectionInput.PhysicalConnectionRequirements ConnectionInput.AthenaProperties",
        "Glue.Catalog": "FederatedCatalog",
        "Athena.WorkGroup": "WorkGroupConfiguration WorkGroupConfiguration.EngineVersion WorkGroupConfiguration.ResultConfiguration WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration",
        "LakeFormation.PrincipalPermissions": "Catalog Permissions PermissionsWithGrantOption Principal Resource Principal.DataLakePrincipalIdentifier Resource.Catalog Resource.Database Resource.Table Resource.TableWithColumns Resource.Database.CatalogId Resource.Database.Name Resource.Table.CatalogId Resource.Table.DatabaseName Resource.Table.Name Resource.Table.TableWildcard Resource.TableWithColumns.CatalogId Resource.TableWithColumns.DatabaseName Resource.TableWithColumns.Name Resource.TableWithColumns.ColumnNames Resource.TableWithColumns.ColumnWildcard Resource.TableWithColumns.ColumnWildcard.ExcludedColumnNames",
        "QuickSight.DataSource": "Credentials.KeyPairCredentials Credentials.KeyPairCredentials.KeyPairUsername Credentials.KeyPairCredentials.PrivateKey Credentials.KeyPairCredentials.PrivateKeyPassphrase",
    }.items():
        lines = (materials / (resource_type.replace(".", "_") + ".properties")).read_text().splitlines()
        for path in paths.split():
            assert f"{resource_type}.{path}=" in lines, path
            assert catalog.property_schema(resource_type, path)
    lake = (materials / "LakeFormation_PrincipalPermissions.properties").read_text()
    assert "LakeFormation.PrincipalPermissions.PrincipalIdentifier=IDENTIFIER_OUTPUT" in lake
    assert "LakeFormation.PrincipalPermissions.ResourceIdentifier=IDENTIFIER_OUTPUT" in lake
    for path in ("DataCatalog.DatabaseName", "DataCatalog.TableName"):
        try:
            catalog.property_schema("Athena.WorkGroup", path)
        except KeyError:
            pass
        else:
            raise AssertionError(f"unsupported Athena.WorkGroup path: {path}")
    scheduler = (materials / "Scheduler_Schedule.properties").read_text(encoding="utf-8").splitlines()
    assert len(scheduler) == 43
    assert "Scheduler.Schedule.Arn=" not in scheduler
    assert DesignSchemaCatalog(root).cloudformation_type("Scheduler.Schedule") == "AWS::Scheduler::Schedule"
    assert catalog.required_properties("Scheduler.Schedule") == {
        "FlexibleTimeWindow", "ScheduleExpression", "Target"
    }
    for path in (
        "Name", "FlexibleTimeWindow.Mode", "ScheduleExpression", "ScheduleExpressionTimezone",
        "Target.Arn", "Target.RoleArn", "Target.Input", "Target.RetryPolicy.MaximumRetryAttempts",
    ):
        assert f"Scheduler.Schedule.{path}=" in scheduler
        assert catalog.property_schema("Scheduler.Schedule", path)
    assert catalog.literal_errors("Scheduler.Schedule", "FlexibleTimeWindow.Mode", "OFF") == []
    assert catalog.literal_errors("Scheduler.Schedule", "FlexibleTimeWindow.Mode", "WRONG")
    print("cloudformation-schema: PASS")


if __name__ == "__main__":
    main()

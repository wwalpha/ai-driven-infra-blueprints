#!/usr/bin/env python3
"""Offline executable adapter contracts and coverage evidence."""

import json
import socket
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from aws_mapping import runtime_registry
from aws_mapping_catalog import project
from aws_mapping_compare import value as mapping_value
from model.importing import (
    adapter_contracts,
    cli,
    contract_fixtures,
    coverage,
    inventory,
    limitations,
)
from model.importing.discovery import ADAPTER_INVENTORIES
from support.check_model_aws_fixtures import SchemaOffline
from support.pytest_cli import run
from utils.aws_mappings import owners

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    connect = Mock(side_effect=AssertionError("network forbidden"))
    external_cli = Mock(side_effect=AssertionError("external CLI forbidden"))
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(cli.comparator().Context, "cli", external_cli)
    yield
    connect.assert_not_called()
    external_cli.assert_not_called()


@pytest.mark.parametrize("kind", sorted(ADAPTER_INVENTORIES))
def test_existing_sdk_fixture_through_import_inventory_and_selectors(kind):
    service = owners(ROOT)[kind]
    ctx = SchemaOffline(ROOT)
    ctx.verified = True
    ctx.import_mode = True
    record = inventory.adapter_inventory(ctx, service, (kind,))[0]
    mapping, mapped = inventory.import_comparison(ROOT, service)
    model = SimpleNamespace(
        ctx=ctx,
        path=ROOT / "model/dev" / ctx.target["directory"] / (service + ".properties"),
        service=service,
        values={},
        resources=[],
    )
    resource = cli.selector_resource(model, "fixture", record, mapped)
    compared = 0
    for key, prop in mapped.items():
        if not (
            key.startswith(kind + ".")
            and prop.include
            and prop.source == "aws"
            and mapping.getters.get(prop.field.getter, {}).get("kind") == "adapter"
        ):
            continue
        _, raw = mapping_value(ctx, resource, mapping, prop, key)
        expected = project(prop, record.get("getters", {}).get(prop.field.getter, {}))
        if expected == cli.comparator().MISSING:
            continue
        assert cli.comparator().normalize(
            ctx, raw, prop.field.norm
        ) == cli.comparator().normalize(ctx, expected, prop.field.norm), key
        compared += 1
    assert compared > 0


def test_real_adapter_and_sdk_fixture_results():
    mapping = runtime_registry(ROOT, "quicksight")
    vpc = adapter_contracts.run(ROOT, mapping, "QuickSight.VPCConnection")
    dns = vpc["vpc"]["properties"]["QuickSight.VPCConnection.DnsResolvers"]
    assert dns["status"] == "verified"
    assert {
        "normal",
        "empty",
        "missing-value",
        "access-denied",
        "missing-selector",
        "invalid-account",
    } <= set(dns["branches"])
    assert vpc["vpc"]["status"] == "verified"
    group = adapter_contracts.run(ROOT, mapping, "QuickSight.Group")
    namespace = group["group-namespace"]["properties"]["QuickSight.Group.Namespace"]
    assert namespace["status"] == "verified"
    assert "missing-arn" in namespace["branches"]
    assert (
        group["sdk-quicksight-group"]["properties"]["QuickSight.Group.GroupName"][
            "status"
        ]
        == "verified"
    )
    assert group["sdk-quicksight-group"]["status"] == "verified"
    assert all(
        item["status"] == "verified"
        for item in group["sdk-quicksight-group"]["properties"].values()
    )


def test_new_mapping_property_stays_unverified():
    mapping = runtime_registry(ROOT, "quicksight")
    original = mapping.properties["QuickSight.VPCConnection.DnsResolvers"]
    added = replace(original, field=replace(original.field, path="NewField"))
    copy = SimpleNamespace(
        service="quicksight",
        properties={**mapping.properties, "QuickSight.VPCConnection.NewField": added},
        getters=mapping.getters,
        identities=mapping.identities,
    )
    result = adapter_contracts.run(ROOT, copy, "QuickSight.VPCConnection")
    assert (
        result["vpc"]["properties"]["QuickSight.VPCConnection.NewField"]["status"]
        == "unverified"
    )
    missing = replace(original, field=replace(original.field, getter="not-registered"))
    copy.properties["QuickSight.VPCConnection.NewField"] = missing
    result = adapter_contracts.run(ROOT, copy, "QuickSight.VPCConnection")
    assert result["not-registered"]["status"] == "broken"


def test_shared_getter_fixture_rechecks_each_mapping_path(monkeypatch):
    mapping = runtime_registry(ROOT, "quicksight")
    fixture = Mock(wraps=adapter_contracts.group_fixture)
    monkeypatch.setattr(adapter_contracts, "group_fixture", fixture)
    result = adapter_contracts.run(ROOT, mapping, "QuickSight.Group")
    assert fixture.call_count == 1
    assert result["sdk-quicksight-group"]["status"] == "verified"
    key = "QuickSight.Group.Description"
    prop = mapping.properties[key]
    changed = SimpleNamespace(
        service=mapping.service,
        properties={
            **mapping.properties,
            key: replace(prop, field=replace(prop.field, path="Changed")),
        },
        getters=mapping.getters,
    )
    result = adapter_contracts.run(ROOT, changed, "QuickSight.Group")
    assert result["sdk-quicksight-group"]["properties"][key]["status"] == "unverified"
    assert result["sdk-quicksight-group"]["status"] == "unverified"
    changed.properties[key] = replace(prop, transform="present")
    result = adapter_contracts.run(ROOT, changed, "QuickSight.Group")
    assert result["sdk-quicksight-group"]["properties"][key]["status"] == "unverified"


def test_route53_getter_uses_real_inventory_and_distinct_branches():
    mapping = runtime_registry(ROOT, "route53")
    result = adapter_contracts.run(ROOT, mapping, "Route53.RecordSet")["record"]
    assert result["status"] == "verified"
    assert all(item["status"] == "verified" for item in result["properties"].values())
    assert (
        "ambiguous-routing"
        in result["properties"]["Route53.RecordSet.SetIdentifier"]["branches"]
    )
    key = "Route53.RecordSet.AliasTarget.DNSName"
    prop = mapping.properties[key]
    changed = SimpleNamespace(
        service=mapping.service,
        properties={
            **mapping.properties,
            key: replace(prop, field=replace(prop.field, path="Changed")),
        },
        getters=mapping.getters,
    )
    result = adapter_contracts.run(ROOT, changed, "Route53.RecordSet")["record"]
    assert result["properties"][key]["status"] == "unverified"
    assert result["status"] == "unverified"


def test_datazone_getter_uses_scoped_inventory():
    mapping = runtime_registry(ROOT, "datazone")
    domain = adapter_contracts.run(ROOT, mapping, "DataZone.Domain")[
        "sdk-datazone-domain"
    ]
    assert domain["status"] == "verified"
    assert {"normal", "missing-selector", "access-denied"} <= set(
        domain["properties"]["DataZone.Domain.DomainVersion"]["branches"]
    )
    result = adapter_contracts.run(ROOT, mapping, "DataZone.Project")[
        "sdk-datazone-project"
    ]
    assert result["status"] == "verified"
    assert {"normal", "missing-selector", "access-denied", "account-mismatch"} <= set(
        result["properties"]["DataZone.Project.DomainIdentifier"]["branches"]
    )


def test_lakeformation_getter_checks_all_mapped_paths():
    mapping = runtime_registry(ROOT, "lake-formation")
    result = adapter_contracts.run(ROOT, mapping, "LakeFormation.Resource")[
        "sdk-lakeformation-resource"
    ]
    assert result["status"] == "verified"
    assert all(item["status"] == "verified" for item in result["properties"].values())
    assert (
        "missing-value"
        in result["properties"]["LakeFormation.Resource.WithFederation"]["branches"]
    )


def test_logs_import_normalization_does_not_require_kms_api():
    mapping = runtime_registry(ROOT, "cloudwatch-logs")
    result = adapter_contracts.run(ROOT, mapping, "Logs.LogGroup")["base"]
    assert result["status"] == "verified"
    assert result["properties"]["Logs.LogGroup.LogGroupName"]["status"] == "verified"
    assert result["properties"]["Logs.LogGroup.KmsKeyId"]["status"] == "verified"
    ctx = cli.import_context(
        ROOT, adapter_contracts.TARGET, service="cloudwatch-logs", no_profile=True
    )
    assert ("kms", "describe_key") not in ctx.allowed
    ctx.call = Mock(side_effect=AssertionError("Import normalization must be offline"))
    adapter_contracts.import_normalize(
        ctx,
        "Logs.LogGroup",
        "Logs.LogGroup.KmsKeyId",
        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
    )
    ctx.call.assert_not_called()


def test_subnet_contract_checks_id_and_name_selector_branches():
    mapping = runtime_registry(ROOT, "vpc")
    result = adapter_contracts.run(ROOT, mapping, "EC2.Subnet")["base"]
    assert result["status"] == "verified"
    evidence = result["properties"]["EC2.Subnet.CidrBlock"]
    assert {
        "id-selector",
        "name-selector",
        "vpc-filter",
        "ambiguous",
        "access-denied",
    } <= set(evidence["branches"])


@pytest.mark.parametrize(
    "kind,getter",
    [
        ("Config.ConfigurationRecorder", "recorder"),
        ("Config.DeliveryChannel", "channel"),
    ],
)
def test_config_inventory_and_adapter_contract(kind, getter):
    mapping = runtime_registry(ROOT, "config")
    result = adapter_contracts.run(ROOT, mapping, kind)[getter]
    assert result["status"] == "verified", result
    if getter == "recorder":
        assert (
            "INCLUSION_BY_RESOURCE_TYPES"
            in result["properties"][kind + ".RecordingGroup.ResourceTypes"]["branches"]
        )
        assert (
            "EXCLUSION_BY_RESOURCE_TYPES"
            in result["properties"][
                kind + ".RecordingGroup.ExclusionByResourceTypes.ResourceTypes"
            ]["branches"]
        )


def test_failed_fixture_is_broken_and_coverage_keeps_levels(monkeypatch, capsys):
    monkeypatch.setattr(
        adapter_contracts,
        "vpc_fixture",
        Mock(side_effect=ValueError("fixture failure")),
    )
    result = coverage.report(ROOT, "quicksight")
    vpc = next(
        item
        for item in result["resources"]
        if item["resourceType"] == "QuickSight.VPCConnection"
    )
    dns = next(
        item
        for item in vpc["propertyDiagnostics"]
        if item["property"].endswith(".DnsResolvers")
    )
    assert dns["adapterContract"]["status"] == "broken"
    assert dns["status"] == "capturable"
    assert result["runtimeVerified"] is False
    assert result["summary"]["adapterContractGetters"]["broken"] >= 1
    assert coverage.main(["--service", "quicksight", "--strict"]) == 1
    assert "adapter contract broken" in capsys.readouterr().out


def test_fake_context_rejects_invalid_and_unknown_requests():
    fake = adapter_contracts.FakeCalls(
        SimpleNamespace(allowed={("quicksight", "describe_vpc_connection")}), {}
    )
    with pytest.raises(ValueError):
        fake.request(
            "quicksight",
            "describe_vpc_connection",
            {"AwsAccountId": 123, "VPCConnectionId": "x"},
        )
    with pytest.raises(ValueError, match="allowlist"):
        fake.request("quicksight", "delete_vpc_connection", {})
    with pytest.raises(ValueError, match="Invalid fixture response"):
        fake.response(
            "quicksight",
            "describe_vpc_connection",
            {"VPCConnection": {"DnsResolvers": 7}},
        )
    with pytest.raises(adapter_contracts.InvalidFixture, match="no SDK output shape"):
        fake.response("s3", "create_bucket_metadata_configuration", {"unexpected": 1})


def test_invalid_response_fixture_is_validation_error(monkeypatch, capsys):
    monkeypatch.setattr(
        adapter_contracts,
        "vpc_fixture",
        Mock(side_effect=adapter_contracts.InvalidFixture("invalid SDK output")),
    )
    mapping = runtime_registry(ROOT, "quicksight")
    with pytest.raises(adapter_contracts.InvalidFixture, match="invalid SDK output"):
        adapter_contracts.run(ROOT, mapping, "QuickSight.VPCConnection")
    for fmt in ("text", "json"):
        assert coverage.main(["--service", "quicksight", "--format", fmt]) == 2
        assert "Fixture Validation Error" in capsys.readouterr().err


def test_model_invalid_fixture_is_validation_error(monkeypatch):
    monkeypatch.setattr(
        adapter_contracts.cli,
        "validation_errors",
        Mock(return_value=["invalid fixture value"]),
    )
    mapping = runtime_registry(ROOT, "config")
    with pytest.raises(adapter_contracts.InvalidFixture, match="invalid fixture value"):
        adapter_contracts.run(ROOT, mapping, "Config.DeliveryChannel")


def test_shared_sdk_fixture_records_partial_evidence_without_verification():
    mapping = runtime_registry(ROOT, "vpc")
    result = adapter_contracts.shared_fixture_evidence(
        ROOT,
        mapping,
        "EC2.FlowLog",
        "base",
        adapter_contracts.contracts(mapping, "EC2.FlowLog")["base"],
    )
    evidence = result["EC2.FlowLog.ResourceId"]
    assert evidence["status"] == "unverified"
    assert set(evidence["branches"]) == {
        "normal",
        "access-denied",
        "all-selectors-missing",
    }
    assert "SDK-shaped synthetic" in evidence["reason"]


@pytest.mark.parametrize(
    ("service", "kind", "counts"),
    [
        ("cloudtrail", "CloudTrail.Trail", {"base": 8, "status": 1, "selectors": 4}),
        ("glue", "Glue.Job", {"base": 18}),
        ("glue", "Glue.SecurityConfiguration", {"base": 5}),
    ],
)
def test_direct_service_contracts(service, kind, counts):
    mapping = runtime_registry(ROOT, service)
    results = adapter_contracts.run(ROOT, mapping, kind)
    for getter, count in counts.items():
        result = results[getter]
        assert result["status"] == "verified"
        assert len(result["properties"]) == count
        assert result["fixtureOperation"]
        assert all(
            {"normal", "missing-selector", "access-denied"} <= set(item["branches"])
            for item in result["properties"].values()
        )


def test_pipeline_preserves_sensitive_contracts():
    mapping = runtime_registry(ROOT, "codepipeline")
    result = adapter_contracts.run(ROOT, mapping, "CodePipeline.Pipeline")
    assert result["base"]["status"] == "unverified"
    properties = {
        key: value
        for getter in result.values()
        for key, value in getter["properties"].items()
    }
    assert sum(item["status"] == "verified" for item in properties.values()) == 20
    assert (
        sum(
            item["reason"] == "Sensitive or explicitly unobservable Property"
            for item in properties.values()
        )
        == 2
    )


def test_kms_key_identity_branches():
    results = adapter_contracts.run(ROOT, runtime_registry(ROOT, "kms"), "KMS.Key")
    for getter in ("base", "rotation", "policy"):
        result = results[getter]
        assert result["status"] == "verified"
        assert all(
            {
                "alias-selector",
                "missing-selector",
                "conflicting-aliases",
                "multiple-aliases-one-key",
            }
            <= set(item["branches"])
            for item in result["properties"].values()
        )


def test_kms_alias_membership_branches():
    result = adapter_contracts.run(ROOT, runtime_registry(ROOT, "kms"), "KMS.Alias")[
        "alias"
    ]
    assert result["status"] == "verified"
    assert "parent-mismatch" in result["properties"]["KMS.Alias.AliasName"]["branches"]


def test_route_table_reuses_network_selector_fixture():
    mapping = runtime_registry(ROOT, "vpc")
    result = adapter_contracts.run(ROOT, mapping, "EC2.RouteTable")["base"]
    assert result["status"] == "verified"
    assert result["fixtureOperation"] == "ec2.describe_route_tables"
    assert all(item["status"] == "verified" for item in result["properties"].values())


def test_security_hub_contract_requires_no_selector():
    mapping = runtime_registry(ROOT, "security-hub")
    result = adapter_contracts.run(ROOT, mapping, "SecurityHub.Hub")["base"]
    assert result["status"] == "verified"
    assert result["selectors"] == []
    assert {"normal", "missing-value", "access-denied"} <= set(
        result["properties"]["SecurityHub.Hub.AutoEnableControls"]["branches"]
    )


@pytest.mark.parametrize(
    "service,kind,key",
    [
        ("athena", "Athena.WorkGroup", "Description"),
        ("codecommit", "CodeCommit.Repository", "RepositoryDescription"),
        ("mwaa", "MWAA.Environment", "DagS3Path"),
    ],
)
def test_cloud_control_inventory_and_direct_adapter_contract(service, kind, key):
    mapping = runtime_registry(ROOT, service)
    result = adapter_contracts.run(ROOT, mapping, kind)["base"]
    assert result["status"] == "verified", result
    assert {"normal", "missing-value", "missing-selector", "access-denied"} <= set(
        result["properties"][kind + "." + key]["branches"]
    )


def test_lambda_function_and_recursion_contracts_use_distinct_operations():
    mapping = runtime_registry(ROOT, "lambda")
    result = adapter_contracts.run(ROOT, mapping, "Lambda.Function")
    assert result["base"]["status"] == "verified"
    assert result["recursion"]["status"] == "verified"
    assert result["base"]["fixtureOperation"] == "lambda.get_function"
    for key in (
        "MemorySize",
        "ReservedConcurrentExecutions",
        "Code.S3Bucket",
        "Code.S3Key",
    ):
        assert (
            result["base"]["properties"]["Lambda.Function." + key]["status"]
            == "verified"
        )
    assert (
        result["recursion"]["fixtureOperation"]
        == "lambda.get_function_recursion_config"
    )


def test_lambda_get_function_response_shape():
    fake = adapter_contracts.FakeCalls(SimpleNamespace(allowed=set()), {})
    payload = {
        "Code": {
            "ResolvedS3Object": {
                "S3Bucket": "fixture",
                "S3Key": "file.zip",
                "S3ObjectVersion": "v1",
            }
        }
    }
    assert fake.response("lambda", "get_function", payload) == payload
    with pytest.raises(
        adapter_contracts.InvalidFixture, match="Invalid fixture response"
    ):
        fake.response(
            "lambda",
            "get_function",
            {"Code": {"ResolvedS3Object": {"WrongField": "x"}}},
        )


def test_eventbridge_rule_and_scheduler_contracts_cover_bus_scope():
    mapping = runtime_registry(ROOT, "eventbridge")
    rule = adapter_contracts.run(ROOT, mapping, "Events.Rule")
    assert rule["base"]["status"] == "verified"
    assert rule["targets"]["status"] == "verified"
    assert (
        "explicit-event-bus"
        in rule["base"]["properties"]["Events.Rule.Name"]["branches"]
    )
    schedule = adapter_contracts.run(ROOT, mapping, "Scheduler.Schedule")["schedule"]
    assert schedule["status"] == "verified"
    assert schedule["fixtureOperation"] == "scheduler.get_schedule"


def test_scheduler_import_uses_group_and_cloud_inventory():
    kind = "Scheduler.Schedule"
    ctx, _ = adapter_contracts.fixture_context(
        ROOT, "eventbridge", adapter_contracts.DirectCalls, {}
    )
    ctx.pages = Mock(
        return_value={
            "ResourceDescriptions": [
                {
                    "Identifier": "job",
                    "Properties": json.dumps({"Name": "job", "GroupName": "custom"}),
                }
            ]
        }
    )
    ctx.call = Mock(
        return_value={
            "Name": "job",
            "GroupName": "custom",
            "State": "ENABLED",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ScheduleExpression": "rate(1 hour)",
            "ScheduleExpressionTimezone": "UTC",
            "Target": {
                "Arn": "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture",
                "RoleArn": "arn:aws:iam::123456789012:role/fixture",
                "RetryPolicy": {
                    "MaximumEventAgeInSeconds": 3600,
                    "MaximumRetryAttempts": 3,
                },
            },
        }
    )
    records = inventory.inventory_for(ctx).inventory("eventbridge", kind)
    assert records[0]["identity"] == "job"
    assert records[0]["seedProperties"][kind + ".GroupName"] == "custom"
    normalized = cli.normalize_records(ctx, "eventbridge", records)
    ctx.call.assert_called_once_with(
        "scheduler", "get_schedule", Name="job", GroupName="custom"
    )
    assert (
        normalized[0]["properties"][kind + ".Target.RetryPolicy.MaximumRetryAttempts"][
            "value"
        ]
        == 3
    )


def test_scheduler_import_rejects_unconfirmed_group():
    kind = "Scheduler.Schedule"
    ctx, _ = adapter_contracts.fixture_context(
        ROOT, "eventbridge", adapter_contracts.DirectCalls, {}
    )
    ctx.pages = Mock(
        return_value={
            "ResourceDescriptions": [
                {"Identifier": "job", "Properties": json.dumps({"Name": "job"})}
            ]
        }
    )
    ctx.call = Mock()
    records = inventory.inventory_for(ctx).inventory("eventbridge", kind)
    assert records == []
    ctx.call.assert_not_called()


def test_secret_metadata_includes_external_secret_type():
    result = adapter_contracts.run(
        ROOT, runtime_registry(ROOT, "secrets-manager"), "SecretsManager.Secret"
    )["base"]
    assert result["status"] == "verified"
    assert (
        result["properties"]["SecretsManager.Secret.KmsKeyId"]["status"] == "verified"
    )
    assert result["properties"]["SecretsManager.Secret.Type"]["status"] == "verified"


def test_all_mapped_contracts_have_execution_or_sensitive_evidence():
    mappings = {}
    for kind, service in sorted(owners(ROOT).items()):
        if service not in mappings:
            mappings[service] = runtime_registry(ROOT, service)
        mapping = mappings[service]
        for getter, result in adapter_contracts.run(ROOT, mapping, kind).items():
            assert result["fixtureOperation"], (kind, getter)
            assert result["status"] != "broken", (kind, getter, result)
            for key, evidence in result["properties"].items():
                if evidence["status"] == "unverified":
                    assert (
                        evidence["reason"]
                        == "Sensitive or explicitly unobservable Property"
                    ), (key, evidence)
                else:
                    assert evidence["status"] == "verified", (key, evidence)
                    assert evidence["branches"], key
                    assert (
                        result["paths"][key]["path"]
                        == mapping.properties[key].field.path
                    )


def test_iam_direct_contracts_preserve_sensitive_classification():
    mapping = runtime_registry(ROOT, "iam")
    assert (
        adapter_contracts.run(ROOT, mapping, "IAM.Role")["base"]["status"] == "verified"
    )
    assert (
        adapter_contracts.run(ROOT, mapping, "IAM.InstanceProfile")["base"]["status"]
        == "verified"
    )
    user = adapter_contracts.run(ROOT, mapping, "IAM.User")["base"]
    assert user["status"] == "unverified"
    assert "Sensitive" in user["properties"]["IAM.User.UserName"]["reason"]


@pytest.mark.parametrize("kind", ["IAM.Role", "IAM.User"])
def test_iam_policy_getters_cover_list_detail_and_empty(kind):
    result = adapter_contracts.run(ROOT, runtime_registry(ROOT, "iam"), kind)
    assert result["attached"]["status"] == "verified"
    assert result["inline"]["status"] == "verified"
    assert (
        "empty"
        in result["attached"]["properties"][kind + ".ManagedPolicyArns"]["branches"]
    )
    assert (
        "detail-access-denied"
        in result["inline"]["properties"][kind + ".Policies[].PolicyDocument"][
            "branches"
        ]
    )
    assert result["inline"]["fixtureAdditionalOperations"] == [
        "iam.get_" + kind.split(".")[1].lower() + "_policy"
    ]


def test_iam_managed_policy_getters_cover_ambiguity_and_detail():
    result = adapter_contracts.run(
        ROOT, runtime_registry(ROOT, "iam"), "IAM.ManagedPolicy"
    )
    assert all(
        result[getter]["status"] == "verified"
        for getter in ("base", "document", "entities")
    )
    assert (
        "ambiguous-policy"
        in result["base"]["properties"]["IAM.ManagedPolicy.ManagedPolicyName"][
            "branches"
        ]
    )
    assert (
        "detail-access-denied"
        in result["document"]["properties"]["IAM.ManagedPolicy.PolicyDocument"][
            "branches"
        ]
    )
    assert (
        "empty-roles"
        in result["entities"]["properties"]["IAM.ManagedPolicy.Roles"]["branches"]
    )


def test_s3_configuration_getters_respect_absence_and_failures():
    results = adapter_contracts.run(ROOT, runtime_registry(ROOT, "s3"), "S3.Bucket")
    for getter in (
        "encryption",
        "lifecycle",
        "replication",
        "ownership",
        "public",
        "versioning",
    ):
        result = results[getter]
        assert result["status"] == "verified", result
        for evidence in result["properties"].values():
            assert {"normal", "missing-selector", "access-denied"} <= set(
                evidence["branches"]
            )
            if getter != "versioning":
                assert "optional-configuration-absent" in evidence["branches"]


def test_s3_bucket_policy_uses_acquired_bucket_selector():
    result = adapter_contracts.run(
        ROOT, runtime_registry(ROOT, "s3"), "S3.BucketPolicy"
    )["policy"]
    assert result["status"] == "verified"
    assert result["selectors"] == ["Bucket"]
    assert (
        "optional-configuration-absent"
        in result["properties"]["S3.BucketPolicy.PolicyDocument"]["branches"]
    )
    lock = adapter_contracts.run(ROOT, runtime_registry(ROOT, "s3"), "S3.Bucket")[
        "lock"
    ]
    evidence = lock["properties"]["S3.Bucket.ObjectLockEnabled"]
    assert evidence["status"] == "verified"
    assert {"object-lock-not-enabled", "optional-configuration-absent"} <= set(
        evidence["branches"]
    )


def test_s3_bucket_base_checks_region_and_arn_fallbacks():
    result = adapter_contracts.run(ROOT, runtime_registry(ROOT, "s3"), "S3.Bucket")[
        "base"
    ]
    assert result["status"] == "verified"
    assert {"region-default", "region-legacy", "arn-fallback", "ambiguous"} <= set(
        result["properties"]["S3.Bucket.BucketName"]["branches"]
    )
    assert result["fixtureAdditionalOperations"] == [
        "s3.get_bucket_location",
        "sts.get_caller_identity",
    ]


def test_sqs_queue_contract_checks_both_operations():
    result = adapter_contracts.run(ROOT, runtime_registry(ROOT, "sqs"), "SQS.Queue")[
        "queue"
    ]
    assert result["status"] == "verified"
    assert result["fixtureAdditionalOperations"] == ["sqs.get_queue_attributes"]
    assert result["properties"]["SQS.Queue.FifoQueue"]["status"] == "verified"
    assert (
        result["properties"]["SQS.Queue.MessageRetentionPeriod"]["status"] == "verified"
    )
    assert (
        "detail-access-denied" in result["properties"]["SQS.Queue.QueueUrl"]["branches"]
    )


def test_sqs_policy_contract_checks_scope_and_grouping():
    result = adapter_contracts.run(
        ROOT, runtime_registry(ROOT, "sqs"), "SQS.QueuePolicy"
    )["policy"]
    assert result["status"] == "verified"
    assert {
        "different-policies",
        "missing-policy",
        "account-mismatch",
        "missing-selector",
        "access-denied",
    } <= set(result["properties"]["SQS.QueuePolicy.PolicyDocument"]["branches"])


@pytest.mark.parametrize("service", ["s3", "sqs"])
def test_repaired_contract_preserves_static_diagnostics(service, capsys):
    assert coverage.main(["--service", service, "--strict"]) == 0
    assert "adapter contract broken" not in capsys.readouterr().out
    if service == "sqs":
        report = coverage.report(ROOT, service)
        queue = next(
            item for item in report["resources"] if item["resourceType"] == "SQS.Queue"
        )
        fifo = next(
            item
            for item in queue["propertyDiagnostics"]
            if item["property"] == "SQS.Queue.FifoQueue"
        )
        assert fifo["status"] == "uncertain"
        assert fifo["reasonCode"] == "ADAPTER_SELECTOR_UNCONFIRMED"
        assert fifo["adapterContract"]["status"] == "verified"


@pytest.mark.parametrize(
    "fifo,retention,expected_status",
    [
        ("false", "604800", "captured"),
        ("not-a-boolean", "not-a-number", "unavailable"),
    ],
)
def test_sqs_import_normalizes_sdk_string_values(fifo, retention, expected_status):
    ctx, fake = adapter_contracts.fixture_context(
        ROOT,
        "sqs",
        adapter_contracts.SQSCalls,
        {"FifoQueue": fifo, "MessageRetentionPeriod": retention},
    )
    source = inventory.inventory_for(ctx)
    mapping, mapped = source.mapping("sqs")
    cloud = {"QueueName": "fixture", "QueueUrl": fake.url}
    record = source.cloud_record(
        "sqs",
        "SQS.Queue",
        {"Identifier": fake.url, "Properties": json.dumps(cloud)},
        source.schema("SQS.Queue"),
        mapping,
        mapped,
    )
    captured = cli.normalize_records(ctx, "sqs", [record])[0]["properties"]
    assert captured["SQS.Queue.FifoQueue"]["status"] == expected_status
    assert captured["SQS.Queue.MessageRetentionPeriod"]["status"] == expected_status
    if expected_status == "captured":
        assert captured["SQS.Queue.FifoQueue"]["value"] is False
        assert captured["SQS.Queue.MessageRetentionPeriod"]["value"] == 604800


def test_quicksight_source_contract_separates_types_and_secrets():
    mapping = runtime_registry(ROOT, "quicksight")
    result = adapter_contracts.run(ROOT, mapping, "QuickSight.DataSource")
    assert result["base"]["status"] == "unverified"
    secret = result["base"]["properties"]["QuickSight.DataSource.Credentials.SecretArn"]
    assert secret["status"] == "unverified" and "Sensitive" in secret["reason"]
    athena = result["base"]["properties"][
        "QuickSight.DataSource.DataSourceParameters.AthenaParameters.WorkGroup"
    ]
    assert "other-source-type-missing" in athena["branches"]
    assert result["permissions"]["status"] == "verified"
    assert (
        "missing-permissions"
        in result["permissions"]["properties"][
            "QuickSight.DataSource.Permissions[].Actions"
        ]["branches"]
    )


def test_macie_session_contract_uses_execution_account():
    result = adapter_contracts.run(
        ROOT, runtime_registry(ROOT, "macie"), "Macie.Session"
    )["session"]
    assert result["status"] == "verified"
    assert result["selectors"] == []
    assert {"normal", "missing-value", "execution-account", "access-denied"} <= set(
        result["properties"]["Macie.Session.Status"]["branches"]
    )


def test_codebuild_contract_keeps_sensitive_fields_unverified():
    result = adapter_contracts.run(
        ROOT, runtime_registry(ROOT, "codebuild"), "CodeBuild.Project"
    )["base"]
    assert result["status"] == "unverified"
    assert "ambiguous" in result["properties"]["CodeBuild.Project.Name"]["branches"]
    assert (
        "missing-project" in result["properties"]["CodeBuild.Project.Name"]["branches"]
    )
    assert (
        result["properties"][
            "CodeBuild.Project.Environment.EnvironmentVariables[].Value"
        ]["status"]
        == "unverified"
    )


def test_vpc_contract_covers_id_name_and_attribute_paths():
    result = adapter_contracts.run(ROOT, runtime_registry(ROOT, "vpc"), "EC2.VPC")
    assert all(
        result[getter]["status"] == "verified"
        for getter in ("base", "hostnames", "support")
    )
    assert result["hostnames"]["fixtureAdditionalOperations"] == ["ec2.describe_vpcs"]
    assert (
        "attribute-access-denied"
        in result["support"]["properties"]["EC2.VPC.EnableDnsSupport"]["branches"]
    )


def test_invalid_shared_sdk_output_cannot_be_verified(monkeypatch):
    monkeypatch.setitem(
        contract_fixtures.PATCHES,
        ("ec2", "describe_flow_logs"),
        {"FlowLogs.FlowLogId": 7},
    )
    mapping = runtime_registry(ROOT, "vpc")
    with pytest.raises(adapter_contracts.InvalidFixture, match="describe_flow_logs"):
        adapter_contracts.shared_fixture_evidence(
            ROOT,
            mapping,
            "EC2.FlowLog",
            "base",
            adapter_contracts.contracts(mapping, "EC2.FlowLog")["base"],
        )


@pytest.mark.parametrize(
    "code",
    [{}, {"ResolvedS3Object": {"S3Bucket": "fixture-code", "S3Key": "handler.zip"}}],
)
def test_lambda_optional_code_source_capture(code):
    ctx = cli.import_context(
        ROOT, adapter_contracts.TARGET, service="lambda", no_profile=True
    )
    ctx.verified = True
    record = {
        "kind": "Lambda.Function",
        "identity": "fixture",
        "getters": {
            "base": {
                "Configuration": {
                    "FunctionName": "fixture",
                    "MemorySize": 128,
                    "PackageType": "Zip",
                },
                "Concurrency": {"ReservedConcurrentExecutions": 5},
                "Code": code,
            },
            "recursion": {},
            "provider-lambda-function": {},
        },
    }
    properties = cli.normalize_records(ctx, "lambda", [record])[0]["properties"]
    for name in ("S3Bucket", "S3Key"):
        capture = properties["Lambda.Function.Code." + name]
        assert capture["status"] == ("captured" if code else "unobservable")
        if not code:
            assert capture["reasonCode"] == "OPTIONAL_CODE_SOURCE_NOT_RETURNED"
    assert properties["Lambda.Function.MemorySize"]["value"] == 128
    assert properties["Lambda.Function.ReservedConcurrentExecutions"]["value"] == 5


def test_lambda_zip_missing_image_uri_does_not_fail_inventory():
    ctx = cli.import_context(
        ROOT, adapter_contracts.TARGET, service="lambda", no_profile=True
    )
    ctx.verified = True
    record = {
        "kind": "Lambda.Function",
        "identity": "fixture",
        "getters": {
            "base": {
                "Configuration": {
                    "FunctionName": "fixture",
                    "PackageType": "Zip",
                    "Role": "arn:aws:iam::123456789012:role/fixture",
                },
                "Code": {
                    "ResolvedS3Object": {
                        "S3Bucket": "fixture-code",
                        "S3Key": "handler.zip",
                    }
                },
            },
            "recursion": {"RecursiveLoop": "Allow"},
            "provider-lambda-function": {},
        },
    }
    cli.normalize_records(ctx, "lambda", [record])
    status = inventory.inventory_for(ctx).statuses.get("Lambda.Function", {})
    assert status.get("status") != "failed"


@pytest.mark.parametrize(
    "package,code,expected",
    [
        (
            "Zip",
            {"Location": "https://example.invalid/bucket/key"},
            ("unobservable", "unobservable"),
        ),
        (
            "Zip",
            {"ResolvedS3Object": {"S3Key": "file.zip"}},
            ("unobservable", "captured"),
        ),
        (
            "Zip",
            {"ResolvedS3Object": {"S3Bucket": "bucket"}},
            ("captured", "unobservable"),
        ),
        ("Image", {"ImageUri": "example/image:tag"}, ("missing", "missing")),
        ("Image", {}, ("missing", "missing")),
        ("Unknown", {}, ("unavailable", "unavailable")),
        ("Zip", {"Error": {"ErrorCode": "Failure"}}, ("unavailable", "unavailable")),
    ],
)
def test_lambda_code_source_classification(package, code, expected):
    ctx = cli.import_context(
        ROOT, adapter_contracts.TARGET, service="lambda", no_profile=True
    )
    ctx.verified = True
    record = {
        "kind": "Lambda.Function",
        "identity": "fixture",
        "getters": {
            "base": {
                "Configuration": {"FunctionName": "fixture", "PackageType": package},
                "Code": code,
            },
            "recursion": {},
            "provider-lambda-function": {},
        },
    }
    result = cli.normalize_records(ctx, "lambda", [record])[0]
    props = result["properties"]
    assert (
        tuple(
            props["Lambda.Function.Code." + name]["status"]
            for name in ("S3Bucket", "S3Key")
        )
        == expected
    )
    assert props["Lambda.Function.FunctionName"]["value"] == "fixture"
    for name, status in zip(("S3Bucket", "S3Key"), expected, strict=True):
        if status == "unobservable":
            assert limitations.valid_capture(
                ROOT,
                "Lambda.Function.Code." + name,
                props["Lambda.Function.Code." + name],
                result,
            )


def test_lambda_missing_source_requires_identity_and_propagates_denial(monkeypatch):
    ctx = cli.import_context(
        ROOT, adapter_contracts.TARGET, service="lambda", no_profile=True
    )
    ctx.verified = True
    record = {
        "kind": "Lambda.Function",
        "identity": "fixture",
        "identityStatus": "unknown",
        "identityProperty": "Lambda.Function.FunctionName",
        "identityProperties": ["Lambda.Function.FunctionName"],
        "identityComponents": [],
        "getters": {
            "base": {
                "Configuration": {"FunctionName": "fixture", "PackageType": "Zip"},
                "Code": {},
            },
            "recursion": {},
            "provider-lambda-function": {},
        },
    }
    props = cli.normalize_records(ctx, "lambda", [record])[0]["properties"]
    assert props["Lambda.Function.Code.S3Bucket"]["status"] == "unavailable"
    mapping = runtime_registry(ROOT, "lambda")
    monkeypatch.setattr(
        adapter_contracts,
        "direct_fixture",
        Mock(side_effect=adapter_contracts.InvalidFixture("invalid SDK input")),
    )
    with pytest.raises(adapter_contracts.InvalidFixture, match="invalid SDK input"):
        adapter_contracts.run(ROOT, mapping, "Lambda.Function")


def test_lambda_access_denied_is_not_a_limitation(monkeypatch):
    ctx = cli.import_context(
        ROOT, adapter_contracts.TARGET, service="lambda", no_profile=True
    )
    ctx.verified = True
    record = {"kind": "Lambda.Function", "identity": "fixture", "getters": {}}
    monkeypatch.setattr(
        cli,
        "mapping_value",
        Mock(
            side_effect=cli.comparator().AcquisitionError(
                "lambda.get_function", "AccessDenied"
            )
        ),
    )
    props = cli.normalize_records(ctx, "lambda", [record])[0]["properties"]
    for name in ("S3Bucket", "S3Key"):
        assert props["Lambda.Function.Code." + name]["status"] == "unavailable"
        assert props["Lambda.Function.Code." + name]["errorCode"] == "AccessDenied"


def test_sdk_fixture_request_shape_is_validation_error():
    fake = adapter_contracts.FakeCalls(
        SimpleNamespace(allowed={("lambda", "get_function")}), {}
    )
    with pytest.raises(
        adapter_contracts.InvalidFixture, match="Invalid fixture request"
    ):
        fake.request("lambda", "get_function", {"Wrong": "x"})


if __name__ == "__main__":
    raise SystemExit(run(__file__))

#!/usr/bin/env python3
"""Limitations are validated proposals; integrity bindings never authenticate a Human."""

import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from design.catalog import DesignSchemaCatalog
from model.format import FORMAT_FIELDS
from model.importing import (
    approval,
    cli,
    evidence,
    inventory,
    limitations,
    sources,
)
from model.importing.adapter_contract_cases import core
from support.import_model_fixtures import resource_values
from support.model_v2_fixtures import value_snapshot
from support.pytest_cli import run
from utils.json_format import document_sha256

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = cli.ROOT
ARN = "arn:aws:s3:::fixture"
PROP = "LakeFormation.Resource.UseServiceLinkedRole"


@pytest.mark.parametrize(
    ("response", "path", "expected"),
    [
        ({"Parent": {}}, "Parent.Optional", True),
        ({}, "Parent.Optional", False),
        ({"Parent": None}, "Parent.Optional", False),
        ({"Parent": "wrong"}, "Parent.Optional", False),
        ({"Parent": []}, "Parent.Optional", False),
        ({"Parent": {"Optional": None}}, "Parent.Optional", False),
        ({"Items": [{}]}, "Items[].Optional", False),
        ({"Parent": {}}, "Parent..Optional", False),
    ],
)
def test_missing_leaf_requires_intact_object_path(response, path, expected):
    assert limitations.missing_leaf(response, path) is expected


@pytest.mark.parametrize(
    "service,kind,identity,identity_key,prop",
    [
        ("ec2", "EC2.TransitGateway", "tgw-test", "Id", "Description"),
        (
            "ecs",
            "ECS.TaskDefinition",
            "arn:aws:ecs:ap-northeast-1:123456789012:task-definition/test:1",
            "TaskDefinitionArn",
            "ContainerDefinitions",
        ),
    ],
)
def test_provider_missing_capture_requires_verified_detail(
    service, kind, identity, identity_key, prop
):
    ctx = cli.import_context(ROOT, core.TARGET, service=service, no_profile=True)
    ctx.verified = True
    inv = inventory.inventory_for(ctx)
    mapping, mapped = inv.mapping(service)
    ctx.call = Mock(
        return_value={
            "ResourceDescription": {
                "Identifier": identity,
                "Properties": json.dumps({identity_key: identity}),
            }
        }
    )
    raw = inv.cloud_record(
        service, kind, {"Identifier": identity}, inv.schema(kind), mapping, mapped
    )
    record = cli.normalize_records(ctx, service, [raw])[0]
    capture = record["properties"][kind + "." + prop]
    assert capture["status"] == "not_returned"
    assert limitations.valid_capture(ROOT, kind + "." + prop, capture, record)
    changed = deepcopy(capture)
    changed["evidence"]["identity"] = "other"
    assert not limitations.valid_capture(ROOT, kind + "." + prop, changed, record)
    record["_action"] = "refresh"
    old = resource_values("001", kind, "existing", "IMPORT", [(prop, "`retained`")])
    old.update(
        {
            "observed.row.001-001.value": "`previous observation`",
            "display.row.001-001.show": "false",
            "desired.reference.001.consumerKey": "desired.row.001-001.value",
            "desired.reference.001.sourceResourceId": "002",
        }
    )
    selection = {
        "limitations": [
            {
                "record": record["record"],
                "property": kind + "." + prop,
                "reasonCode": capture["reasonCode"],
                "treatment": "retain_existing",
                "reason": "Human approved unchanged existing state",
            }
        ]
    }
    assert limitations.validate(selection, {"001": record}, old, dict(old), ROOT)
    for key in old:
        if key.startswith(
            ("desired.row.", "observed.row.", "display.row.", "desired.reference.")
        ):
            with pytest.raises(ValueError):
                limitations.validate(
                    selection, {"001": record}, old, {**old, key: "changed"}, ROOT
                )


@pytest.mark.parametrize(
    "payload",
    [
        {"Id": "different"},
        {"Id": None},
        {"Id": "tgw-test", "Tags": None},
        {"Id": "tgw-test", "Tags": {}},
        {"Id": "tgw-test", "Unexpected": True},
    ],
)
def test_provider_malformed_response_cannot_authorize_retention(payload):
    ctx = cli.import_context(ROOT, core.TARGET, service="ec2", no_profile=True)
    ctx.verified = True
    inv = inventory.inventory_for(ctx)
    mapping, mapped = inv.mapping("ec2")
    ctx.call = Mock(
        return_value={
            "ResourceDescription": {
                "Identifier": "tgw-test",
                "Properties": json.dumps(payload),
            }
        }
    )
    if "Tags" in payload:
        with pytest.raises(cli.comparator().Unresolved, match="invalid array type"):
            inv.cloud_record(
                "ec2",
                "EC2.TransitGateway",
                {"Identifier": "tgw-test"},
                inv.schema("EC2.TransitGateway"),
                mapping,
                mapped,
            )
    else:
        raw = inv.cloud_record(
            "ec2",
            "EC2.TransitGateway",
            {"Identifier": "tgw-test"},
            inv.schema("EC2.TransitGateway"),
            mapping,
            mapped,
        )
        assert not raw["verifiedDetailGetters"]


def test_required_and_unmapped_properties_cannot_be_waived():
    for prop in (
        "Logs.MetricFilter.FilterName",
        "QuickSight.Group.GroupName",
        "EC2.TransitGateway.NoSuchProperty",
    ):
        assert limitations.contract(ROOT, prop, "not_returned") is None


@pytest.mark.parametrize(
    "api,operation,result,path,response,expected",
    [
        ("s3", "get_bucket_versioning", "$", "Status", {}, True),
        ("s3", "get_bucket_versioning", "$", "Unknown", {}, False),
        (
            "lambda",
            "get_function",
            "Configuration",
            "Description",
            {"Configuration": {"FunctionName": "function"}},
            True,
        ),
        ("lambda", "get_function", "Configuration", "Description", {}, False),
        (
            "lambda",
            "get_function",
            "Configuration",
            "Description",
            {"Configuration": None},
            False,
        ),
        (
            "lambda",
            "get_function",
            "Configuration",
            "Description",
            {"Configuration": {"Environment": []}},
            False,
        ),
        (
            "datazone",
            "get_project",
            "$",
            "description",
            {
                "domainId": "domain",
                "id": "project",
                "name": "project",
                "createdBy": "user",
            },
            True,
        ),
        (
            "datazone",
            "get_project",
            "$",
            "description",
            {"domainId": "domain", "id": "project", "name": "project"},
            False,
        ),
        (
            "datazone",
            "get_project",
            "$",
            "createdBy",
            {"domainId": "domain", "id": "project", "name": "project"},
            False,
        ),
        ("s3", "get_bucket_versioning", "WrongParent", "Status", {}, False),
    ],
)
def test_sdk_omission_uses_schema_without_service_retention_exceptions(
    api, operation, result, path, response, expected
):
    getter = {"service": api, "operation": operation, "result": result}
    assert limitations.sdk_omission(ROOT, getter, response, path) is expected


def test_sdk_retention_preserves_row_metadata_and_references():
    prop = "QuickSight.Group.Description"
    capture = limitations.contract(ROOT, prop, "not_returned")
    assert capture is not None
    capture["evidence"]["identity"] = "group-identity"
    record = {
        "record": "group",
        "kind": "QuickSight.Group",
        "identity": "group-identity",
        "_action": "refresh",
        "properties": {prop: capture},
    }
    old = resource_values(
        "001", "QuickSight.Group", "group", "IMPORT", [("Description", "`keep this`")]
    )
    old.update(
        {
            "observed.row.001-001.value": "`previous observation`",
            "display.row.001-001.show": "false",
            "desired.row.001-001.comment": "existing metadata",
            "desired.reference.001.consumerKey": "desired.row.001-001.value",
            "desired.reference.001.sourceResourceId": "002",
        }
    )
    selection = {
        "limitations": [
            {
                "record": "group",
                "property": prop,
                "reasonCode": capture["reasonCode"],
                "treatment": "retain_existing",
                "reason": "Human approved retaining the exact existing Row",
            }
        ]
    }
    assert limitations.validate(selection, {"001": record}, old, dict(old), ROOT)
    for key in limitations.row_state(old, "001", prop):
        with pytest.raises(ValueError, match="unchanged existing"):
            limitations.validate(
                selection, {"001": deepcopy(record)}, old, {**old, key: "changed"}, ROOT
            )


def test_sdk_omit_unobserved_does_not_authorize_ordinary_missing():
    prop = "QuickSight.Group.Description"
    capture = limitations.contract(ROOT, prop, "not_returned")
    capture["evidence"]["identity"] = "group-identity"
    record = {
        "record": "group",
        "kind": "QuickSight.Group",
        "identity": "group-identity",
        "_action": "add",
        "properties": {prop: capture},
    }
    selection = {
        "limitations": [
            {
                "record": "group",
                "property": prop,
                "reasonCode": capture["reasonCode"],
                "treatment": "omit_unobserved",
                "reason": "Human approved leaving this optional Property unobserved",
            }
        ]
    }
    assert limitations.validate(selection, {"001": record}, {}, {}, ROOT)
    record["properties"][prop] = {"status": "missing", "reason": "No evidence"}
    with pytest.raises(ValueError, match="not eligible"):
        limitations.validate(selection, {"001": record}, {}, {}, ROOT)


def schema(prop):
    kind = ".".join(prop.split(".")[:2])
    return DesignSchemaCatalog(ROOT).property_schema(
        kind, prop.removeprefix(kind + ".")
    )


def case():
    before = resource_values(
        "001",
        "LakeFormation.Resource",
        "lake-one",
        "IMPORT",
        [
            ("ResourceArn", "`" + ARN + "`"),
            ("UseServiceLinkedRole", "`false`"),
            ("WithFederation", "`false`"),
        ],
    )
    record = {
        "record": "r1",
        "kind": "LakeFormation.Resource",
        "identity": ARN,
        "identityProperty": "LakeFormation.Resource.ResourceArn",
        "identityProperties": ["LakeFormation.Resource.ResourceArn"],
        "identityStatus": "known",
        "properties": {
            "LakeFormation.Resource.ResourceArn": {"status": "captured", "value": ARN},
            PROP: limitations.contract(ROOT, PROP, "unobservable"),
            "LakeFormation.Resource.WithFederation": {
                "status": "captured",
                "value": True,
            },
        },
    }
    after = {**before, "desired.row.001-003.value": "`true`"}
    selection = {
        "resources": [
            {
                "record": "r1",
                "resource": "001",
                "action": "refresh",
                "reason": "Human-selected proposal",
                "basis": [],
            }
        ],
        "excluded": [],
        "unreflected": [],
        "limitations": [
            {
                "record": "r1",
                "property": PROP,
                "reasonCode": "REQUEST_INPUT_NOT_OBSERVABLE",
                "treatment": "retain_existing",
                "reason": "Keep the prior input without claiming an AWS observation",
            }
        ],
    }
    acquisition = {
        "version": 3,
        **FORMAT_FIELDS,
        "root": "/synthetic/worktree",
        "task": "tasks/import.md",
        "scope": ["dev", "cde", "lake-formation"],
        "sources": {},
        "connection": {},
        "acquiredAt": datetime.now(timezone.utc).isoformat(),
        "records": [record],
        "inventory": {
            "LakeFormation.Resource": {
                "status": "limited",
                "enumerationComplete": True,
                "propertiesComplete": False,
                "limitations": [
                    {"record": "r1", "property": PROP, "status": "unobservable"}
                ],
            }
        },
    }
    return before, after, selection, acquisition


def review_case(data):
    before, after, selection, acquisition = data
    return approval.build_review(
        acquisition,
        selection,
        value_snapshot(before),
        after,
        {r["record"]: [] for r in acquisition["records"]},
        schema,
    )


def test_retain_is_reviewed_and_bound_without_becoming_observed():
    data = case()
    result = review_case(data)
    selected = sources.selection_records(
        data[2], data[3]["records"], data[0], data[1], schema
    )
    assert not sources.pending_items(data[2], selected, data[1], schema)
    assert data[0]["desired.row.001-002.value"] == data[1]["desired.row.001-002.value"]
    assert result["limitations"][0]["currentModelValuePresent"] is True
    assert result["limitations"][0]["treatment"] == "retain_existing"
    assert result["completion"] == {
        "acquisitionEstablished": True,
        "propertiesResolved": True,
        "allPropertiesObserved": False,
    }
    binding = approval.review_binding(result, data[3])
    assert binding["limitationsDigest"] == document_sha256(data[2]["limitations"])
    assert "approved" not in binding
    assert "_limitations" not in data[3]["records"][0]


def test_unobservable_without_treatment_stays_pending_and_cannot_bind():
    data = case()
    data[2]["limitations"] = []
    result = review_case(data)
    assert result["dispositions"][0]["unreflected"]
    with pytest.raises(ValueError, match="limitations/structure"):
        approval.review_binding(result, data[3])


@pytest.mark.parametrize(
    "failure",
    [
        "reason",
        "duplicate",
        "treatment",
        "record",
        "property",
        "value",
        "new-row",
        "delete-row",
        "unavailable",
        "access-denied",
        "getter",
        "identity",
        "approved-flag",
    ],
)
def test_forged_or_unsafe_limitations_are_rejected(failure):
    data = case()
    before, after, selection, acquisition = data
    item = selection["limitations"][0]
    if failure == "reason":
        item["reasonCode"] = "FAKE"
    elif failure == "duplicate":
        selection["limitations"].append(deepcopy(item))
    elif failure == "treatment":
        item["treatment"] = "omit_unobserved"
    elif failure == "record":
        item["record"] = "unknown"
    elif failure == "property":
        item["property"] = "LakeFormation.Resource.ResourceArn"
    elif failure == "value":
        after["desired.row.001-002.value"] = "`true`"
    elif failure == "new-row":
        after["desired.row.001-004.property"] = PROP
        after["desired.row.001-004.value"] = "`false`"
    elif failure == "delete-row":
        for key in list(after):
            if key.startswith("desired.row.001-002."):
                del after[key]
        item["treatment"] = "omit_unobserved"
    elif failure in {"unavailable", "access-denied", "getter"}:
        acquisition["records"][0]["properties"][PROP] = {
            "status": "unavailable",
            "reason": failure,
        }
    elif failure == "identity":
        acquisition["records"][0]["identityStatus"] = "unknown"
    else:
        item["approved"] = True
    with pytest.raises(ValueError):
        sources.selection_records(
            selection, acquisition["records"], before, after, schema
        )


def test_optional_new_property_can_be_omitted_but_required_input_cannot():
    kind, prop = "Glue.Table", "Glue.Table.Id"
    values = resource_values(
        "001",
        kind,
        "table-one",
        "IMPORT",
        [
            ("CatalogId", "`123456789012`"),
            ("DatabaseName", "`database`"),
            ("TableInput.Name", "`table`"),
        ],
    )
    components = [
        {"property": kind + "." + p, "value": v}
        for p, v in [
            ("CatalogId", "123456789012"),
            ("DatabaseName", "database"),
            ("TableInput.Name", "table"),
        ]
    ]
    record = {
        "record": "r1",
        "kind": kind,
        "identity": "table-identity",
        "identityProperty": None,
        "identityProperties": [item["property"] for item in components],
        "identityComponents": components,
        "identityStatus": "known",
        "properties": {
            item["property"]: {"status": "captured", "value": item["value"]}
            for item in components
        },
    }
    record["properties"][prop] = limitations.contract(ROOT, prop, "unobservable")
    selection = {
        "resources": [
            {
                "record": "r1",
                "resource": "001",
                "action": "add",
                "reason": "explicit new resource",
                "basis": [],
            }
        ],
        "excluded": [],
        "unreflected": [],
        "limitations": [
            {
                "record": "r1",
                "property": prop,
                "reasonCode": "PROVIDER_OUTPUT_NOT_OBSERVABLE",
                "treatment": "omit_unobserved",
                "reason": "No provider Id is returned",
            }
        ],
    }
    selected = sources.selection_records(selection, [record], {}, values, schema)
    assert not sources.pending_items(selection, selected, values, schema)
    assert (
        not sources.verify_values(
            value_snapshot({}), value_snapshot(values), selected, schema
        )
        == []
    )
    assert limitations.required(ROOT, "LakeFormation.Resource", PROP)
    invalid = case()
    invalid[2]["resources"][0]["action"] = "add"
    invalid[2]["limitations"][0]["treatment"] = "omit_unobserved"
    with pytest.raises(ValueError, match="optional"):
        sources.selection_records(
            invalid[2], invalid[3]["records"], {}, invalid[1], schema
        )


def test_withheld_review_does_not_expose_existing_secret():
    kind, prop = (
        "CodePipeline.Pipeline",
        "CodePipeline.Pipeline.Stages[].Actions[].Configuration",
    )
    before = resource_values(
        "001",
        kind,
        "pipeline-one",
        "IMPORT",
        [
            ("Name", "`pipeline`"),
            ("Stages[].Actions[].Configuration", '`{"private": "DO-NOT-EXPOSE"}`'),
        ],
    )
    capture = limitations.contract(ROOT, prop, "withheld")
    record = {
        "record": "r1",
        "kind": kind,
        "identity": "pipeline",
        "identityProperty": kind + ".Name",
        "properties": {
            kind + ".Name": {"status": "captured", "value": "pipeline"},
            prop: capture,
        },
    }
    selection = {
        "resources": [
            {
                "record": "r1",
                "resource": "001",
                "action": "refresh",
                "reason": "preserve secret configuration",
                "basis": [],
            }
        ],
        "excluded": [],
        "unreflected": [],
        "limitations": [
            {
                "record": "r1",
                "property": prop,
                "reasonCode": "SENSITIVE_VALUE_WITHHELD",
                "treatment": "retain_existing",
                "reason": "Do not expose configuration",
            }
        ],
    }
    acquisition = case()[3]
    acquisition["records"] = [record]
    acquisition["inventory"] = {
        kind: {
            "status": "limited",
            "enumerationComplete": True,
            "propertiesComplete": False,
            "limitations": [{"record": "r1", "property": prop, "status": "withheld"}],
        }
    }
    result = approval.build_review(
        acquisition, selection, value_snapshot(before), before, {"r1": []}, schema
    )
    assert "DO-NOT-EXPOSE" not in str(result)
    assert "value" not in capture


@pytest.mark.parametrize(
    "change", ["acquisition", "selection", "limitations", "review", "candidate"]
)
def test_changes_invalidate_the_old_binding(change):
    data = case()
    result = review_case(data)
    binding = approval.review_binding(result, data[3])
    changed = deepcopy(result)
    if change == "acquisition":
        altered = deepcopy(data[3])
        altered["records"][0]["identity"] = "other"
        with pytest.raises(ValueError):
            approval.review_binding(result, altered)
        return
    if change == "selection":
        changed["selection"]["resources"][0]["reason"] = "different"
    elif change == "limitations":
        changed["selection"]["limitations"][0]["reason"] = "different"
    elif change == "candidate":
        changed["proposedValuesDigest"] = "f" * 64
    else:
        changed["limitations"][0]["residualRisk"] = "changed"
    with pytest.raises(ValueError):
        approval.verify_review(changed, result)
    assert binding["reviewDigest"] == result["reviewDigest"]


@pytest.mark.parametrize(
    "status", ["failed", "permission_denied", "unsupported", "requires_filter"]
)
def test_acquisition_failure_cannot_be_waived(status):
    data = case()[3]
    data["inventory"]["LakeFormation.Resource"]["status"] = status
    assert not evidence.acquisition_complete(data)


def test_not_modelled_and_empty_remain_distinct():
    data = {
        "version": 3,
        **FORMAT_FIELDS,
        "records": [],
        "inventory": {
            "Test.Empty": {"status": "empty"},
            "Test.Excluded": {"status": "not_modelled"},
        },
    }
    assert evidence.acquisition_complete(data)
    assert (
        evidence.validate_inventory(data)["Test.Empty"]
        != evidence.validate_inventory(data)["Test.Excluded"]
    )


def test_queue_structure_cannot_be_waived_by_property_limitations():
    kind, url = (
        "SQS.QueuePolicy",
        "https://sqs.ap-northeast-1.amazonaws.com/123456789012/queue",
    )
    prop = kind + ".Id"
    policy = {"Version": "2012-10-17", "Statement": []}
    values = resource_values(
        "001",
        kind,
        "queue-policy",
        "IMPORT",
        [
            ("Queues[]", "`" + url + "`"),
            ("PolicyDocument", '`{"Version":"2012-10-17","Statement":[]}`'),
        ],
    )
    record = {
        "record": "r1",
        "kind": kind,
        "identity": url,
        "identityProperty": None,
        "identityProperties": [kind + ".Queues[]"],
        "identityComponents": [{"property": kind + ".Queues[]", "value": [url]}],
        "identityStatus": "known",
        "structureStatus": "unresolved",
        "structureReason": "Original grouping cannot be restored",
        "properties": {
            kind + ".Queues[]": {"status": "captured", "value": [url]},
            kind + ".PolicyDocument": {"status": "captured", "value": policy},
            prop: limitations.contract(ROOT, prop, "unobservable"),
        },
    }
    selection = {
        "resources": [
            {
                "record": "r1",
                "resource": "001",
                "action": "add",
                "reason": "Explicit candidate",
                "basis": [],
            }
        ],
        "excluded": [],
        "unreflected": [],
        "limitations": [
            {
                "record": "r1",
                "property": prop,
                "reasonCode": "PROVIDER_OUTPUT_NOT_OBSERVABLE",
                "treatment": "omit_unobserved",
                "reason": "No independent policy Id",
            }
        ],
    }
    selected = sources.selection_records(selection, [record], {}, values, schema)
    pending = sources.pending_items(selection, selected, values, schema)
    assert len(pending) == 1 and pending[0]["category"] == "structure"
    selection["resources"][0]["structure"] = {
        "queues": [url],
        "reason": "Human explicitly chooses one queue per resource",
    }
    selected = sources.selection_records(selection, [record], {}, values, schema)
    assert not sources.pending_items(selection, selected, values, schema)
    before = resource_values(
        "002",
        kind,
        "existing-group",
        "IMPORT",
        [
            ("Queues[]", "`" + url + "`"),
            ("Queues[]", "`" + url + "-other`"),
            ("PolicyDocument", '`{"Version":"2012-10-17","Statement":[]}`'),
        ],
    )
    combined = {
        **values,
        **before,
        "desired.service.identity.lastAllocated": '{"SQS.QueuePolicy":2}',
    }
    with pytest.raises(ValueError, match="overlaps"):
        sources.selection_records(selection, [record], before, combined, schema)
    selection["resources"][0]["structure"]["queues"].append(url + "-other")
    with pytest.raises(ValueError, match="single queue"):
        sources.selection_records(selection, [record], {}, values, schema)


def lambda_case(action, code_rows):
    kind = "Lambda.Function"
    props = [kind + ".Code.S3Bucket", kind + ".Code.S3Key"]
    values = resource_values(
        "001",
        kind,
        "lambda-one",
        "IMPORT",
        [("FunctionName", "`fixture`"), ("PackageType", "`Zip`")] + code_rows,
    )
    record = {
        "record": "r1",
        "kind": kind,
        "identity": "fixture",
        "identityProperty": kind + ".FunctionName",
        "identityProperties": [kind + ".FunctionName"],
        "identityStatus": "known",
        "properties": {
            kind + ".FunctionName": {"status": "captured", "value": "fixture"},
            kind + ".PackageType": {"status": "captured", "value": "Zip"},
            **{
                p: limitations.conditional_code_capture(
                    ROOT,
                    p,
                    {
                        "Configuration": {
                            "FunctionName": "fixture",
                            "PackageType": "Zip",
                        },
                        "Code": {},
                    },
                    "fixture",
                )
                for p in props
            },
        },
    }
    selection = {
        "resources": [
            {
                "record": "r1",
                "resource": "001",
                "action": action,
                "reason": "explicit",
                "basis": [],
            }
        ],
        "excluded": [],
        "unreflected": [],
        "limitations": [
            {
                "record": "r1",
                "property": p,
                "reasonCode": "OPTIONAL_CODE_SOURCE_NOT_RETURNED",
                "treatment": "retain_existing"
                if action == "refresh"
                else "omit_unobserved",
                "reason": "not returned",
            }
            for p in props
        ],
    }
    acquisition = {
        "version": 3,
        **FORMAT_FIELDS,
        "root": "/synthetic/worktree",
        "task": "tasks/import.md",
        "scope": ["dev", "cde", "lambda"],
        "sources": {},
        "connection": {},
        "acquiredAt": datetime.now(timezone.utc).isoformat(),
        "records": [record],
        "inventory": {
            kind: {
                "status": "limited",
                "enumerationComplete": True,
                "propertiesComplete": False,
                "limitations": [
                    {"record": "r1", "property": p, "status": "unobservable"}
                    for p in props
                ],
            }
        },
    }
    return values if action == "refresh" else {}, values, selection, acquisition


def test_lambda_retained_code_is_reviewed_as_unverified():
    data = lambda_case(
        "refresh", [("Code.S3Bucket", "`bucket`"), ("Code.S3Key", "`file.zip`")]
    )
    result = review_case(data)
    assert result["completion"]["propertiesResolved"]
    assert not result["completion"]["allPropertiesObserved"]
    assert all(
        item["currentModelValuePresent"] and "not verified" in item["residualRisk"]
        for item in result["limitations"]
    )
    approval.review_binding(result, data[3])


@pytest.mark.parametrize(
    "package,code,rows,complete",
    [
        (
            "Image",
            {"ImageUri": "example/image:tag"},
            [("Code.ImageUri", "`example/image:tag`")],
            True,
        ),
        ("Image", {}, [], False),
        (
            "Zip",
            {"ResolvedS3Object": {"S3Bucket": "bucket", "S3Key": "file.zip"}},
            [("Code.S3Bucket", "`bucket`"), ("Code.S3Key", "`file.zip`")],
            True,
        ),
        ("Zip", {}, [], False),
    ],
)
def test_lambda_new_resource_requires_code_source(package, code, rows, complete):
    ctx = cli.import_context(ROOT, core.TARGET, service="lambda", no_profile=True)
    ctx.verified = True
    ctx.call = Mock(
        return_value={
            "Configuration": {"FunctionName": "fixture", "PackageType": package},
            "Code": code,
        }
    )
    record = cli.normalize_records(
        ctx,
        "lambda",
        [
            {
                "kind": "Lambda.Function",
                "identity": "fixture",
                "seedProperties": {"Lambda.Function.FunctionName": "fixture"},
                "getters": {"recursion": {}, "provider-lambda-function": {}},
            }
        ],
    )[0]
    ctx.call.assert_called_once_with("lambda", "get_function", FunctionName="fixture")
    keep = {
        "FunctionName",
        "PackageType",
        "Code.ImageUri",
        "Code.S3Bucket",
        "Code.S3Key",
    }
    record["properties"] = {
        p: v
        for p, v in record["properties"].items()
        if p.removeprefix("Lambda.Function.") in keep
    }
    data = lambda_case("add", rows)
    data[1].update(
        resource_values(
            "001",
            "Lambda.Function",
            "lambda-one",
            "IMPORT",
            [("FunctionName", "`fixture`"), ("PackageType", "`" + package + "`")]
            + rows,
        )
    )
    data[2]["resources"][0]["record"] = record["record"]
    data[2]["limitations"] = [
        dict(item, record=record["record"])
        for item in data[2]["limitations"]
        if record["properties"][item["property"]]["status"] == "unobservable"
    ]
    data[3]["records"] = [record]
    gaps = [
        {"record": record["record"], "property": p, "status": v["status"]}
        for p, v in record["properties"].items()
        if v["status"] in {"unobservable", "withheld"}
    ]
    data[3]["inventory"]["Lambda.Function"].update(
        status="limited" if gaps else "complete",
        propertiesComplete=not gaps,
        limitations=gaps,
    )
    result = review_case(data)
    assert result["completion"]["propertiesResolved"] is complete
    if complete:
        approval.review_binding(result, data[3])
    else:
        with pytest.raises(ValueError, match="limitations/structure"):
            approval.review_binding(result, data[3])
    if package == "Image" and "ResolvedS3Object" not in code:
        assert all(
            record["properties"]["Lambda.Function.Code." + n]["status"] == "missing"
            for n in ("S3Bucket", "S3Key")
        )
        assert not gaps
        if code:
            assert (
                record["properties"]["Lambda.Function.Code.ImageUri"]["value"]
                == code["ImageUri"]
            )


@pytest.mark.parametrize(
    "package, code, rows",
    [
        (
            "Zip",
            {"ImageUri": "example/image:tag"},
            [("Code.ImageUri", "`example/image:tag`")],
        ),
        (
            "Image",
            {"ResolvedS3Object": {"S3Bucket": "bucket", "S3Key": "file.zip"}},
            [("Code.S3Bucket", "`bucket`"), ("Code.S3Key", "`file.zip`")],
        ),
    ],
)
def test_lambda_mismatched_package_cannot_complete(package, code, rows):
    test_lambda_new_resource_requires_code_source(package, code, rows, False)


def test_lambda_artificial_zipfile_capture_cannot_complete():
    data = lambda_case("add", [("Code.ZipFile", "`code`")])
    data[3]["records"][0]["properties"]["Lambda.Function.Code.ZipFile"] = {
        "status": "captured",
        "value": "code",
    }
    result = review_case(data)
    assert not result["completion"]["propertiesResolved"]
    with pytest.raises(ValueError, match="limitations/structure"):
        approval.review_binding(result, data[3])


def test_lambda_unacquired_image_uri_is_rejected():
    data = lambda_case("add", [("Code.ImageUri", "`example/image:tag`")])
    with pytest.raises(ValueError, match="unacquired Property"):
        review_case(data)


def test_lambda_retain_existing_requires_an_existing_row():
    data = lambda_case("refresh", [])
    with pytest.raises(ValueError, match="retain_existing"):
        sources.selection_records(data[2], data[3]["records"], data[0], data[1], schema)


@pytest.mark.parametrize(
    "alteration", ["package", "identity", "source", "missing-evidence"]
)
def test_lambda_limitation_rejects_inconsistent_acquisition(alteration):
    data = lambda_case(
        "refresh", [("Code.S3Bucket", "`bucket`"), ("Code.S3Key", "`file.zip`")]
    )
    record = data[3]["records"][0]
    capture = record["properties"]["Lambda.Function.Code.S3Bucket"]
    if alteration == "package":
        record["properties"]["Lambda.Function.PackageType"]["value"] = "Image"
    elif alteration == "identity":
        record["identityStatus"] = "unknown"
    elif alteration == "source":
        capture["evidence"]["codeSource"]["S3Bucket"] = True
    else:
        del capture["evidence"]["locationReturned"]
    with pytest.raises(ValueError):
        evidence.validate_inventory(data[3])


def test_lambda_limitation_needs_explicit_treatment():
    data = lambda_case(
        "refresh", [("Code.S3Bucket", "`bucket`"), ("Code.S3Key", "`file.zip`")]
    )
    data[2]["limitations"] = []
    result = review_case(data)
    assert not result["completion"]["propertiesResolved"]
    with pytest.raises(ValueError, match="limitations/structure"):
        approval.review_binding(result, data[3])


def test_missing_absence_is_valid_but_false_limited_evidence_is_not():
    data = case()
    data[3]["records"][0]["properties"]["LakeFormation.Resource.RoleArn"] = {
        "status": "missing",
        "reason": "Optional value absent from a successful read",
    }
    result = review_case(data)
    assert result["completion"]["propertiesResolved"]
    data[3]["inventory"]["LakeFormation.Resource"]["limitations"] = []
    with pytest.raises(ValueError, match="bind every"):
        evidence.validate_inventory(data[3])


def test_legacy_review_version_requires_new_review():
    result = review_case(case())
    result["version"] = 4
    with pytest.raises(ValueError, match="incompatible"):
        approval.verify_review(result, result)


@pytest.mark.parametrize(
    "response,expected",
    [
        (
            {"Status": 200, "ResponseMetadata": {"HTTPStatusCode": 200}, "Group": {}},
            True,
        ),
        ({"Status": 500, "Group": {}}, False),
        ({"Status": 403, "Group": {}}, False),
        ({"ResponseMetadata": {"HTTPStatusCode": 500}, "Group": {}}, False),
        ({"ResponseMetadata": {"HTTPStatusCode": "200"}, "Group": {}}, False),
    ],
)
def test_sdk_omission_rejects_non_success_transport_status(response, expected):
    getter = {"service": "quicksight", "operation": "describe_group", "result": "Group"}
    assert limitations.sdk_omission(ROOT, getter, response, "Description") is expected


def test_sdk_business_status_is_not_an_http_status():
    getter = {"service": "s3", "operation": "get_bucket_versioning", "result": "$"}
    assert limitations.sdk_response(ROOT, getter, {"Status": "Enabled"})


if __name__ == "__main__":
    raise SystemExit(run(__file__))

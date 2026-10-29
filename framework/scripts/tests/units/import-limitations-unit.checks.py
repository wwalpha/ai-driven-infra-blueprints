#!/usr/bin/env python3
"""Limitations are validated proposals; integrity bindings never authenticate a Human."""

import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from design.catalog import DesignSchemaCatalog
from model.format import FORMAT_FIELDS
from model.importing import approval, cli, evidence, limitations, sources
from support.import_model_fixtures import resource_values
from support.model_v2_fixtures import value_snapshot
from support.pytest_cli import run
from utils.json_format import document_sha256

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = cli.ROOT
ARN = "arn:aws:s3:::fixture"
PROP = "LakeFormation.Resource.UseServiceLinkedRole"


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
        acquisition, selection, value_snapshot(before), after, {"r1": []}, schema
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


def test_legacy_review_and_receipt_versions_require_new_review():
    result = review_case(case())
    result["version"] = 4
    with pytest.raises(ValueError, match="incompatible"):
        approval.verify_review(result, result)


if __name__ == "__main__":
    raise SystemExit(run(__file__))

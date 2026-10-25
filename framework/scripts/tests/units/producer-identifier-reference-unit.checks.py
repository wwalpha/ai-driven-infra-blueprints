#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

import pytest
from model.operations import prepare_edit, validate_candidates
from model.render import generate_files, generate_markdown, render_validated_model
from model.sources import Scope, SourceWriteContext
from model.validation import check_model_inputs as model_findings
from model.validation import validate_json_settings
from support.producer_identifier_reference_fixtures import (
    FileReads,
    Path,
    declarations,
    json,
    load_model,
    reference,
    rejected,
    resource,
    serialize,
    setup,
    write_model,
)
from utils.source_reads import CandidateReads

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_json_settings():
    path = Path("/synthetic/model/preview/team/vpc-endpoint.properties")
    key = "desired.row.008-001.document"
    values = resource(
        "008",
        "EC2.VPCEndpoint",
        "consumer",
        [("PolicyDocument", "[policy](vpc-endpoint/policy.json)")],
    )
    link = "[vpc](vpc.md#vpc-one)"
    for body, pointer in [
        (
            {"Condition": {"StringEquals": {"aws:SourceVpc": link}}},
            "/Condition/StringEquals/aws:SourceVpc",
        ),
        ({"Description": "prefix " + link + " suffix"}, "/Description"),
        ({"a/b~c": [link]}, "/a~1b~0c/0"),
        ({"PolicyText": json.dumps({"Resource": link})}, "/PolicyText"),
    ]:
        bad = {**values, key: json.dumps(body)}
        for field in ("document", "value"):
            candidate = (
                bad
                if field == "document"
                else {
                    **values,
                    key.replace(".document", ".value"): "`" + json.dumps(body) + "`",
                }
            )
            with pytest.raises(ValueError) as error:
                validate_json_settings(candidate, path)
            assert all(
                text in str(error.value)
                for text in (
                    str(path),
                    "EC2_VPCEndpoint_008",
                    "EC2.VPCEndpoint.PolicyDocument",
                    pointer,
                )
            )
    good = {
        **values,
        key: json.dumps(
            {
                "Condition": {
                    "StringEquals": {"aws:SourceVpc": "vpc-0123456789abcdef0"}
                },
                "URL": "https://example.com/vpc.md#guide",
                "Text": "[guide](https://example.com/guide#section)",
                "Artifact": "[policy](vpc-endpoint/policy.json)",
                "Literal": "ordinary [brackets] and $resource text",
            }
        ),
    }
    good.update(
        reference(
            "vpc",
            key,
            "vpc-0123456789abcdef0",
            "vpc",
            "001",
            "EC2.VPC",
            mode="identifier",
            prop="EC2.VPC.VpcId",
            pointer="/Condition/StringEquals/aws:SourceVpc",
        )
    )
    before = dict(good)
    with patch(
        "model.identity.Resolver.operand",
        side_effect=AssertionError("physical literals must not resolve"),
    ):
        validate_json_settings(good, path)
        assert declarations(good)["vpc"]["format"] == "identifier"
    assert good == before
    validate_json_settings(values, path)  # The artifact link is outside the JSON body.
    validate_json_settings({**values, key.replace(".document", ".value"): link}, path)


def check_json_boundaries(tmp_path):
    setup(tmp_path, ["vpc-endpoint"], ["EC2.VPCEndpoint"])
    path = tmp_path / "model/preview/team/vpc-endpoint.properties"
    view = tmp_path / "docs/designs/preview/team/vpc-endpoint.md"
    values = resource(
        "008",
        "EC2.VPCEndpoint",
        "consumer",
        [("PolicyDocument", "[policy](vpc-endpoint/policy.json)")],
    )
    values["desired.row.008-001.document"] = json.dumps(
        {"Resource": "[missing](vpc.md#missing)"}
    )
    write_model(path, values)
    before = path.read_bytes()
    findings = model_findings(path, values, tmp_path)
    assert any("JSON setting contains" in error for error in findings.errors), (
        findings.errors
    )
    for render in (generate_files, generate_markdown, render_validated_model):
        with pytest.raises(ValueError, match="JSON setting contains"):
            render(view, values, tmp_path)
    with pytest.raises(ValueError, match="JSON setting contains"):
        validate_candidates(
            tmp_path,
            {path.relative_to(tmp_path)},
            {},
            {("preview", "team", "vpc-endpoint")},
        )
    for action in ("edit", "import"):
        reads = FileReads()
        context = SourceWriteContext._authorized(
            tmp_path,
            reads,
            SimpleNamespace(action=action),
            lambda changes: None,
            frozenset({path}),
        )
        snapshot = load_model(path, reads)
        with pytest.raises(ValueError, match="JSON setting contains"):
            prepare_edit(snapshot, {path: serialize(values)}, context)
    assert path.read_bytes() == before and not view.exists()


def check_identifier_schema():
    key = "desired.row.008-001.value"
    values = resource(
        "008", "EC2.VPCEndpoint", "consumer", [("PolicyDocument", "saved")]
    )
    values.update(
        reference(
            "fixed",
            key,
            "saved",
            "vpc",
            "001",
            "EC2.VPC",
            mode="identifier",
            prop="EC2.VPC.VpcId",
        )
    )
    assert declarations(values)["fixed"]["format"] == "identifier"
    for fields, phrase in [
        ({"format": "unknown"}, "format/scope"),
        ({"labelPolicy": "fixed"}, "non-link"),
        ({"contextProperty": "environment"}, "forbidden"),
        ({"producerScope": "../team/vpc"}, "unsafe"),
        ({"selector": "first"}, "fields"),
    ]:
        bad = {
            **values,
            **{
                "desired.reference.fixed." + field: value
                for field, value in fields.items()
            },
        }
        rejected(lambda *, bad=bad: declarations(bad), phrase)
    bad = {
        key: value
        for key, value in values.items()
        if key != "desired.reference.fixed.property"
    }
    rejected(lambda: declarations(bad), "missing or forbidden")


def reference_snapshot(root, producer, *, mode="name", fields=None):
    scope = Scope(root, "preview", "team", "consumer")
    path = scope.path.with_name("iam.properties")
    key = "desired.note.producer.text"
    text = "[saved](iam.md#producer)" if mode == "link" else "saved"
    values = resource("002", "Logs.LogGroup", "consumer", [("LogGroupName", "`fixed`")])
    values[key] = text
    values.update(
        reference(
            "producer",
            key,
            text,
            "iam",
            "001",
            "IAM.Role",
            mode=mode,
            prop=None if mode == "link" else "IAM.Role.RoleName",
            label="display-name" if mode == "link" else "none",
        )
    )
    values.update(
        {
            "desired.reference.producer." + key: value
            for key, value in (fields or {}).items()
        }
    )
    topology = {
        "targets": [
            {
                "environment": "preview",
                "alias": "team",
                "awsAccountId": "123456789012",
                "awsRegion": "ap-northeast-1",
                "iacEngine": "cloudformation",
            }
        ]
    }
    reads = CandidateReads(
        FileReads(),
        {
            root / "project.json": json.dumps(topology),
            scope.path: serialize(values),
            path: None if producer is None else serialize(producer),
        },
    )
    return load_model(scope, reads), values


@pytest.mark.parametrize(
    "fault,phrase",
    [
        ("missing-producer", "Model is absent"),
        ("missing-resource", "absent or ambiguous"),
        ("wrong-type", "Type differs"),
        ("missing-property", "Property is absent"),
        ("duplicate-property", "Property is absent or ambiguous"),
        ("empty-name", "differs from saved text"),
        ("wrong-name-property", "not a raw name Property"),
    ],
)
def check_producer_name_conditions(tmp_path, fault, phrase):
    producer = resource("001", "IAM.Role", "producer", [("RoleName", "`saved`")])
    fields = {}
    if fault == "missing-producer":
        producer = None
    elif fault == "missing-resource":
        fields["producerLogicalId"] = "IAM_Role_999"
    elif fault == "wrong-type":
        fields.update(resourceType="Glue.Job", property="Glue.Job.Name")
    elif fault == "missing-property":
        producer["desired.row.001-001.property"] = "IAM.Role.Path"
    elif fault == "duplicate-property":
        producer.update(
            {
                "desired.row.001-002.property": "IAM.Role.RoleName",
                "desired.row.001-002.value": "`duplicate`",
                "desired.row.001-002.comment": "重複",
            }
        )
    elif fault == "empty-name":
        producer["desired.row.001-001.value"] = "``"
    else:
        fields["property"] = "IAM.Role.Path"
    snapshot, values = reference_snapshot(tmp_path, producer, fields=fields)
    assert any(phrase in warning["message"] for warning in snapshot.warnings), (
        snapshot.warnings
    )
    assert snapshot.authoritative == values


@pytest.mark.parametrize(
    "value,phrase",
    [
        (None, "unobserved"),
        ("`PENDING_DEPLOY`", "pending"),
        ("``", "nonempty non-ARN"),
        ("arn:aws:fixture", "nonempty non-ARN"),
    ],
)
def check_identifier_value_conditions(tmp_path, value, phrase):
    producer = resource("001", "IAM.Role", "producer", [("RoleName", "`saved`")])
    if value is not None:
        producer["observed.row.001-001.value"] = value
    snapshot, values = reference_snapshot(tmp_path, producer, mode="identifier")
    assert any(phrase in warning["message"] for warning in snapshot.warnings), (
        snapshot.warnings
    )
    assert snapshot.authoritative == values


@pytest.mark.parametrize("fault", ["missing", "empty", "duplicate"])
def check_link_reference_ignores_name_rows(tmp_path, fault):
    producer = resource("001", "IAM.Role", "producer", [("RoleName", "`saved`")])
    if fault == "missing":
        producer["desired.row.001-001.property"] = "IAM.Role.Path"
    elif fault == "empty":
        producer["desired.row.001-001.value"] = "``"
    else:
        producer.update(
            {
                "desired.row.001-002.property": "IAM.Role.RoleName",
                "desired.row.001-002.value": "`duplicate`",
                "desired.row.001-002.comment": "重複",
            }
        )
    snapshot, values = reference_snapshot(tmp_path, producer, mode="link")
    assert not snapshot.warnings
    assert snapshot.authoritative == values


@pytest.mark.parametrize(
    "kind,fields,phrase",
    [
        ("context", {"producerId": "007"}, "forbidden"),
        ("context", {"property": "Account"}, "forbidden"),
        ("context", {"contextProperty": "awsAccountId"}, "reference"),
        ("stack", {"resourceType": "IAM.Role"}, "forbidden"),
        ("stack", {"format": "link"}, "reference"),
        ("stack", {"property": "template"}, "reference"),
    ],
)
def check_context_and_stack_declarations(kind, fields, phrase):
    spec = {
        "consumerKey": "desired.note.account.text",
        "text": "saved",
        "occurrence": "1",
        "producerKind": kind,
        "producerScope": "preview/team",
        "format": "literal",
        "labelPolicy": "none",
        "contextProperty": "executionAccountId",
    }
    if kind == "stack":
        spec.update(
            producerScope="preview/team/cloudformation-stacks",
            producerId="001",
            format="name",
            property="name",
        )
        del spec["contextProperty"]
    values = {
        "desired.note.account.text": "saved",
        **{
            "desired.reference.input." + key: value
            for key, value in {**spec, **fields}.items()
        },
    }
    with pytest.raises(ValueError, match=phrase):
        declarations(values)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

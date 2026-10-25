"""Reference values use synthetic Models, the shared ARN contract and existing graph."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.sources as sources
import pytest
import sync_runtime
from model.core import ModelNeedsFixError
from model.identity import Resolver
from model.impact_graph import Graph
from model.projection import generated_document, reference_display, reference_resolver
from model.reference_nodes import display_value, parse
from model.reference_values import reference_value
from model.render import generate_files
from model.sources import load_model
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.json_format import document_sha256, validate_aws_document

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def fixture(tmp_path):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        _, _, consumer, policy = project(tmp_path)
        producer, values = resource(tmp_path, "s3", "S3.Bucket", attribute="BucketName")
        values["desired.row.001-001.value"] = "`fixture-materials`"
        save(producer, values)
        yield producer, values, consumer, policy


def result(scope, logical="S3_Bucket_001", attribute="Arn"):
    return reference_value(
        Resolver(scope.root), scope, parse(reference(logical, attribute))
    )


def test_desired_s3_and_name_change(fixture):
    producer, values, consumer, _ = fixture
    original = producer.path.read_bytes()
    value = result(consumer)
    assert (value.status, value.value) == ("resolved", "arn:aws:s3:::fixture-materials")
    assert producer.path.read_bytes() == original
    assert not any(key.startswith("observed.") for key in values)
    values["desired.row.001-001.value"] = "`fixture-renamed`"
    save(producer, values)
    assert result(consumer).value == "arn:aws:s3:::fixture-renamed"


def test_list_quarantine_display(fixture):
    _, _, consumer, policy = fixture
    before = copy.deepcopy(policy)
    policy["desired.row.001-002.document"] = json.dumps(
        {
            "Statement": [
                {
                    "Sid": "ListQuarantine",
                    "Effect": "Allow",
                    "Action": "s3:ListBucket",
                    "Resource": reference("S3_Bucket_001"),
                }
            ]
        }
    )
    display = reference_display(policy, consumer.path, consumer.root)
    assert (
        json.loads(display["desired.row.001-002.document"])["Statement"][0]["Resource"]
        == "arn:aws:s3:::fixture-materials"
    )
    assert policy["desired.row.001-001.value"] == before["desired.row.001-001.value"]
    assert "$modelRef" in policy["desired.row.001-002.document"]


def test_missing_generated_kms_value(fixture):
    _, _, consumer, _ = fixture
    value = result(consumer, "KMS_Key_001")
    assert value.status == "unresolved" and value.value is None and value.reason


@pytest.mark.parametrize(
    "mode,expected", [("CREATE", "pending_deploy"), ("IMPORT", "unresolved")]
)
def test_explicit_pending(fixture, mode, expected):
    producer, values, consumer, _ = fixture
    values["desired.resource.001.resourceMode"] = mode
    values["desired.row.001-002.property"] = "S3.Bucket.Arn"
    values["desired.row.001-002.value"] = "[self](#saved-001)"
    values["desired.row.001-002.comment"] = "合成"
    values["observed.row.001-002.value"] = "`PENDING_DEPLOY`"
    save(producer, values)
    if mode == "IMPORT":
        with pytest.raises(ModelNeedsFixError) as error:
            result(consumer)
        assert error.value.diagnostic["code"] == "MODEL_REF_INVALID_PENDING_STATE"
    else:
        value = result(consumer)
        assert value.status == expected and value.reason


@pytest.mark.parametrize(
    "fault",
    ["duplicate", "missing", "attribute", "invalid", "conflict", "arn-conflict"],
)
def test_refuses_unproven_values(fixture, fault):
    producer, values, consumer, _ = fixture
    logical, attribute = "S3_Bucket_001", "Arn"
    if fault == "duplicate":
        resource(consumer.root, "duplicate", "S3.Bucket")
    elif fault == "missing":
        logical = "S3_Bucket_999"
    elif fault == "attribute":
        attribute = "RoleName"
    else:
        if fault == "invalid":
            values["desired.row.001-001.value"] = "`invalid bucket`"
        elif fault == "conflict":
            values["observed.row.001-001.value"] = "`different-bucket`"
        else:
            values["desired.row.001-002.property"] = "S3.Bucket.Arn"
            values["desired.row.001-002.value"] = "[self](#saved-001)"
            values["desired.row.001-002.comment"] = "合成"
            values["observed.row.001-002.value"] = "`arn:aws:s3:::different-bucket`"
        save(producer, values)
    if fault in {"conflict", "arn-conflict"}:
        # Desired/Observed drift is not a contradiction of confirmed observations.
        value = result(consumer, logical, attribute)
        assert value.status == "unresolved" and value.category == "REFERENCE_UNRESOLVED"
        return
    with pytest.raises(ModelNeedsFixError) as error:
        result(consumer, logical, attribute)
    assert error.value.diagnostic["category"] == "MODEL_NEEDS_FIX"
    with pytest.raises(ModelNeedsFixError):
        display_value(
            Resolver(consumer.root), consumer, parse(reference(logical, attribute))
        )


def test_generated_json_and_hash_keep_authority(fixture):
    producer, values, consumer, policy = fixture
    node = reference("S3_Bucket_001")
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ListQuarantine",
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": node,
            },
            {
                "Sid": "Other",
                "Effect": "Deny",
                "Action": "s3:*",
                "Resource": [node, "arn:aws:s3:::fixture-materials/*"],
            },
        ],
    }
    policy["desired.row.001-002.document"] = json.dumps(document)
    save(consumer, policy)
    before = {scope.path: scope.path.read_bytes() for scope in (producer, consumer)}
    view = consumer.root / "docs/designs/qa/team/iam.md"
    artifact = view.with_suffix("") / "policy.json"
    files = generate_files(view, load_model(consumer).values, consumer.root)
    expected = copy.deepcopy(document)
    expected["Statement"][0]["Resource"] = "arn:aws:s3:::fixture-materials"
    expected["Statement"][1]["Resource"][0] = "arn:aws:s3:::fixture-materials"
    assert json.loads(files[artifact]) == expected
    assert (
        "arn:aws:s3:::fixture-materials" in files[view]
        and "$modelRef" not in files[view]
    )
    validate_aws_document(json.loads(files[artifact]))
    display = reference_display(policy, consumer.path, consumer.root)
    assert display["desired.row.001-002.artifactSha256"] == document_sha256(expected)
    assert {path: path.read_bytes() for path in before} == before
    resolver = reference_resolver(policy, consumer, consumer.root)
    assert (
        generated_document(
            document,
            consumer.root,
            resolver=resolver,
            scope=consumer,
            property_name="S3.BucketPolicy.PolicyDocument",
        )
        == expected
    )
    encoded = {"encoded": json.dumps({"items": [node, "keep", 3]})}
    resolved = generated_document(
        encoded, consumer.root, resolver=resolver, scope=consumer
    )
    assert json.loads(resolved["encoded"])["items"] == [
        "arn:aws:s3:::fixture-materials",
        "keep",
        3,
    ]
    validate_aws_document(resolved)
    intrinsic = {"Fn::Join": ["", [node, "/*"]]}
    assert (
        generated_document(
            intrinsic,
            consumer.root,
            resolver=resolver,
            scope=consumer,
        )
        == "arn:aws:s3:::fixture-materials/*"
    )
    assert (
        json.loads(
            generated_document(
                {"encoded": json.dumps(intrinsic)},
                consumer.root,
                resolver=resolver,
                scope=consumer,
            )["encoded"]
        )
        == "arn:aws:s3:::fixture-materials/*"
    )
    graph = Graph()
    graph.include(
        {
            ("qa", "team", "s3"): load_model(producer),
            ("qa", "team", "iam"): load_model(consumer),
        },
        sources.FileReads(),
    )
    assert ("qa", "team", "iam", "resource", "IAM_ManagedPolicy_001") in graph.traverse(
        {("qa", "team", "s3", "resource", "S3_Bucket_001")}
    )
    values["desired.row.001-001.value"] = "`fixture-renamed`"
    save(producer, values)
    updated = generate_files(view, load_model(consumer).values, consumer.root)
    assert (
        json.loads(updated[artifact])["Statement"][0]["Resource"]
        == "arn:aws:s3:::fixture-renamed"
    )
    assert (
        reference_display(policy, consumer.path, consumer.root)[
            "desired.row.001-002.artifactSha256"
        ]
        != display["desired.row.001-002.artifactSha256"]
    )


def test_unconfirmed_path_does_not_use_absence_default(fixture):
    _, _, consumer, _ = fixture
    scope, values = resource(consumer.root, "roles", "IAM.Role", attribute="RoleName")
    values.update(
        {
            "desired.row.001-001.value": "`fixture-role`",
            "desired.row.001-002.property": "IAM.Role.Path",
            "desired.row.001-002.value": "`UNSET`",
            "desired.row.001-002.comment": "未確定",
        }
    )
    save(scope, values)
    value = result(consumer, "IAM_Role_001")
    assert value.status == "unresolved" and "Path" in value.reason


def test_generated_json_reports_every_unresolved_pointer(fixture):
    _, _, consumer, policy = fixture
    document = {
        "a/b~": [reference("KMS_Key_001"), json.dumps(reference("S3_Bucket_999"))]
    }
    resolver = reference_resolver(policy, consumer, consumer.root)
    with pytest.raises(ValueError) as error:
        generated_document(
            document,
            consumer.root,
            resolver=resolver,
            scope=consumer,
            logical_id="IAM_ManagedPolicy_001",
        )
    message = str(error.value)
    for expected in (
        "KMS_Key_001",
        "S3_Bucket_999",
        '"attribute": "Arn"',
        "/a~1b~0/0",
        "/a~1b~0/1",
        "REFERENCE_UNRESOLVED",
        "KeyId",
        "producer logicalId is absent",
    ):
        assert expected in message
    with pytest.raises(ValueError, match="Model reference"):
        validate_aws_document(document)
    assert document["a/b~"][0] == reference("KMS_Key_001")


def test_sync_failure_retains_service_and_continues(fixture, tmp_path):
    producer, _, consumer, policy = fixture
    root, stage = consumer.root, tmp_path / "stage"
    bad = root / "docs/designs/qa/team/iam.md"
    good = bad.with_name("s3.md")
    artifact = bad.with_suffix("") / "policy.json"
    artifact.parent.mkdir(parents=True)
    bad.write_text("# Retained\n", encoding="utf-8")
    artifact.write_text("{}\n", encoding="utf-8")
    original = {path: path.read_bytes() for path in (bad, artifact)}
    failures, unavailable = [], {}
    with (
        patch(
            "model.validation.check_model_inputs",
            return_value=SimpleNamespace(errors=(), warnings=(), unverified=False),
        ),
        patch.object(sync_runtime, "markdown_for", return_value="# Generated\n"),
        patch.object(sync_runtime, "rendered_design", return_value="# Generated\n"),
    ):
        generated = sync_runtime.generate_views(
            stage,
            root,
            {bad: load_model(consumer).values, good: load_model(producer).values},
            failures,
            unavailable=unavailable,
        )
    assert list(generated) == [good]
    assert not failures and bad in unavailable
    assert unavailable[bad]["status"] == "NOT_RUN"
    assert {path: path.read_bytes() for path in original} == original
    assert {(stage / path.relative_to(root)).read_bytes() for path in original} == set(
        original.values()
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

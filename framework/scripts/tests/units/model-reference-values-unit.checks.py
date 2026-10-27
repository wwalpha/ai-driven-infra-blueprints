"""Reference values use synthetic Models, the shared ARN contract and existing graph."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.projection as projection
import model.sources as sources
import pytest
import sync_runtime
from deploy.model_cache import RunModels
from model.core import ModelNeedsFixError, ReferenceResolutionError
from model.format import patch as patch_properties
from model.format import serialize
from model.identity import Resolver
from model.impact_graph import Graph
from model.projection import (
    design_document,
    generated_document,
    reference_display,
    reference_resolver,
)
from model.reference_nodes import display_value, parse
from model.reference_values import reference_value
from model.render import generate_files
from model.sources import load_model
from model.validation import validate_json_settings
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.input_cache import input_context
from utils.json_format import validate_aws_document

from model import dependency_index

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


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_explicit_pending(fixture, mode):
    producer, values, consumer, policy = fixture
    values["desired.resource.001.resourceMode"] = mode
    values["desired.row.001-002.property"] = "S3.Bucket.Arn"
    values["desired.row.001-002.value"] = "[self](#saved-001)"
    values["desired.row.001-002.comment"] = "合成"
    values["observed.row.001-002.value"] = "`PENDING_DEPLOY`"
    save(producer, values)
    value = result(consumer)
    assert (value.status, value.value) == ("resolved", "arn:aws:s3:::fixture-materials")
    document = json.loads(policy["desired.row.001-002.document"])
    document["Statement"][0]["Resource"] = reference("S3_Bucket_001")
    policy["desired.row.001-002.document"] = json.dumps(document)
    save(consumer, policy)
    view = consumer.root / "docs/designs/qa/team/iam.md"
    files = generate_files(view, load_model(consumer).values, consumer.root)
    assert (
        json.loads(files[view.with_suffix("") / "policy.json"])["Statement"][0][
            "Resource"
        ]
        == value.value
    )
    assert "$modelRef" in consumer.path.read_text(encoding="utf-8")


def test_generated_vpc_identity_modes_match(fixture):
    _, _, consumer, _ = fixture
    scope, values = resource(
        consumer.root, "vpc", "EC2.VPC", attribute="VpcId", observed="PENDING_DEPLOY"
    )
    outcomes = []
    for mode in ("CREATE", "IMPORT"):
        values["desired.resource.001.resourceMode"] = mode
        save(scope, values)
        value = result(consumer, "EC2_VPC_001", "VpcId")
        outcomes.append(
            (value.status, value.value, value.category, value.diagnostic["code"])
        )
    assert outcomes[0] == outcomes[1]
    assert outcomes[0] == (
        "pending_deploy",
        None,
        "REFERENCE_PENDING_DEPLOY",
        "REFERENCE_PENDING_DEPLOY",
    )
    values["observed.row.001-001.value"] = "`vpc-0123456789abcdef0`"
    save(scope, values)
    value = result(consumer, "EC2_VPC_001", "VpcId")
    assert (value.status, value.value) == ("resolved", "vpc-0123456789abcdef0")


@pytest.mark.parametrize(
    "kind,fields,pending,expected",
    [
        (
            "CodeBuild.Project",
            {"Name": "fixture-build"},
            "Id",
            "arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build",
        ),
        (
            "IAM.Role",
            {"RoleName": "fixture-role", "Path": "/team/"},
            "Arn",
            "arn:aws:iam::123456789012:role/team/fixture-role",
        ),
        (
            "Lambda.Function",
            {"FunctionName": "fixture-function"},
            "Arn",
            "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture-function",
        ),
        (
            "Glue.Table",
            {
                "CatalogId": "123456789012",
                "DatabaseName": "db",
                "TableInput.Name": "table",
            },
            "Id",
            "arn:aws:glue:ap-northeast-1:123456789012:table/db/table",
        ),
        (
            "Events.Rule",
            {"Name": "fixture-rule", "EventBusName": "custom"},
            "Arn",
            "arn:aws:events:ap-northeast-1:123456789012:rule/custom/fixture-rule",
        ),
    ],
)
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_named_arn_with_pending_output(fixture, kind, fields, pending, expected, mode):
    _, _, consumer, _ = fixture
    scope, values = resource(
        consumer.root, "named", kind, attribute=pending, observed="PENDING_DEPLOY"
    )
    values["desired.resource.001.resourceMode"] = mode
    for index, (field, value) in enumerate(fields.items(), 2):
        prefix = f"desired.row.001-{index:03d}."
        values.update(
            {
                prefix + "property": kind + "." + field,
                prefix + "value": "`" + value + "`",
                prefix + "comment": "合成",
            }
        )
    save(scope, values)
    resolved = result(consumer, kind.replace(".", "_") + "_001")
    assert (resolved.status, resolved.value) == ("resolved", expected)


@pytest.mark.parametrize(
    "kind,field",
    [
        ("KMS.Key", "KeyId"),
        ("EC2.Instance", "InstanceId"),
        ("SecretsManager.Secret", "Id"),
    ],
)
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_only_generated_identity_waits(fixture, kind, field, mode):
    _, _, consumer, _ = fixture
    scope, values = resource(
        consumer.root, "waiting", kind, attribute=field, observed="PENDING_DEPLOY"
    )
    values["desired.resource.001.resourceMode"] = mode
    logical = kind.replace(".", "_") + "_001"
    if kind == "KMS.Key":
        logical = "KMS_Key_002"
        values["desired.resource.001.logicalId"] = logical
        values["desired.service.identity.lastAllocated"] = json.dumps({kind: 2})
    save(scope, values)
    resolved = result(consumer, logical)
    assert (
        resolved.status,
        resolved.value,
        resolved.category,
        resolved.diagnostic["code"],
    ) == (
        "pending_deploy",
        None,
        "REFERENCE_PENDING_DEPLOY",
        "REFERENCE_PENDING_DEPLOY",
    )
    assert (
        display_value(Resolver(consumer.root), consumer, parse(reference(logical)))
        == "PENDING_DEPLOY"
    )


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


@pytest.mark.parametrize(
    "document",
    [
        {"Resource": {"Fn::Join": ["", ["arn:aws:s3:::", "my-bucket", "/*"]]}},
        {
            "Resource": [
                reference("S3_Bucket_001"),
                {"Fn::Join": ["", [reference("S3_Bucket_001"), "/*"]]},
            ]
        },
        {
            "Encoded": ' { "Resource": { "Fn::Join": ["", ["arn:aws:s3:::", "my-bucket", "/*"]] }, "items": [3, true, "keep"] } '
        },
        {"Items": ["3", 3, 2.5, True, False, None, {"Nested": [2, 1]}]},
        {"Fn::Select": [4, ["authored"]]},
    ],
)
def test_design_projection_preserves_structure(fixture, document):
    _, _, consumer, policy = fixture
    before = copy.deepcopy(document)
    warnings = []
    with patch.object(
        projection._imports_json_intrinsics._imports_iac_evaluation,
        "Evaluation",
        side_effect=AssertionError("design validation must not evaluate intrinsics"),
    ):
        assert (
            design_document(
                document,
                consumer.root,
                resolver=reference_resolver(policy, consumer, consumer.root),
                scope=consumer,
                warnings=warnings,
            )
            == before
        )
    assert document == before


@pytest.mark.parametrize("strict", [False, True])
def test_sync_design_structure_matches_normal_generation(fixture, tmp_path, strict):
    _, _, consumer, policy = fixture
    document = json.loads(policy["desired.row.001-002.document"])
    document["Statement"][0]["Action"] = "s3:GetObject"
    document["Statement"][0]["Resource"] = {
        "Fn::Join": ["", [reference("S3_Bucket_001"), "/*"]]
    }
    document["Statement"].append(
        {
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": {"Fn::Join": ["", ["arn:aws:s3:::", "my-bucket", "/*"]]},
        }
    )
    policy["desired.row.001-002.document"] = json.dumps(document)
    save(consumer, policy)
    root, stage = consumer.root, tmp_path / "stage"
    view = root / "docs/designs/qa/team/iam.md"
    artifact = view.with_suffix("") / "policy.json"
    before = consumer.path.read_bytes()
    files = generate_files(view, load_model(consumer).values, root)
    expected = copy.deepcopy(document)
    expected["Statement"][0]["Resource"] = "arn:aws:s3:::fixture-materials/*"
    expected["Statement"][1]["Resource"] = "arn:aws:s3:::my-bucket/*"
    assert json.loads(files[artifact]) == expected
    failures, warnings, unavailable = [], [], {}
    with (
        patch.object(sync_runtime, "markdown_for", return_value="# Generated\n"),
    ):
        generated = sync_runtime.generate_views(
            stage,
            root,
            {view: load_model(consumer).values},
            failures,
            definitions_root=FRAMEWORK,
            warnings=warnings,
            unavailable=unavailable,
            strict=strict,
        )
    assert not failures and not unavailable, (failures, unavailable)
    assert view in generated
    assert (stage / artifact.relative_to(root)).read_text(encoding="utf-8") == files[
        artifact
    ]
    assert consumer.path.read_bytes() == before


def test_generated_json_keeps_authority(fixture):
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
    assert generate_files(view, load_model(consumer).values, consumer.root) == files
    assert (
        "arn:aws:s3:::fixture-materials" in files[view]
        and "$modelRef" not in files[view]
    )
    validate_aws_document(json.loads(files[artifact]))
    display = reference_display(policy, consumer.path, consumer.root)
    assert json.loads(display["desired.row.001-002.document"]) == expected
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
        design_document(intrinsic, consumer.root, resolver=resolver, scope=consumer)
        == intrinsic
    )
    assert (
        design_document(encoded, consumer.root, resolver=resolver, scope=consumer)
        == encoded
    )
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
    assert json.loads(updated[artifact])["Statement"][0]["Resource"] == (
        "arn:aws:s3:::fixture-renamed"
    )


@pytest.mark.parametrize("strict", [False, True])
def test_artifact_nested_and_encoded_references(fixture, tmp_path, strict):
    _, _, consumer, policy = fixture
    node = reference("S3_Bucket_001")
    document = {"Nested": {"items": [node, {"encoded": json.dumps([node, node])}]}}
    policy["desired.row.001-002.document"] = json.dumps(document)
    save(consumer, policy)
    original = consumer.path.read_bytes()
    view = consumer.root / "docs/designs/qa/team/iam.md"
    files = generate_files(view, load_model(consumer).values, consumer.root)
    result = json.loads(files[view.with_suffix("") / "policy.json"])
    arn = "arn:aws:s3:::fixture-materials"
    assert result["Nested"]["items"][0] == arn
    assert json.loads(result["Nested"]["items"][1]["encoded"]) == [arn, arn]
    assert "$modelRef" not in json.dumps(result)
    failures = []
    generated = sync_runtime.generate_views(
        tmp_path / "stage",
        consumer.root,
        {view: load_model(consumer).values},
        failures,
        definitions_root=FRAMEWORK,
        strict=strict,
    )
    assert not failures and view in generated
    artifact = next(path for path in generated[view] if path.suffix == ".json")
    assert json.loads(artifact.read_text(encoding="utf-8")) == result
    assert consumer.path.read_bytes() == original


@pytest.mark.parametrize(
    "value",
    [
        "PENDING_DEPLOY",
        {"items": ["PENDING_DEPLOY"]},
        json.dumps({"items": ["PENDING_DEPLOY"]}),
    ],
)
def test_artifact_literal_pending_is_not_success(fixture, value):
    _, _, consumer, policy = fixture
    document = {"Resource": value}
    with pytest.raises(ReferenceResolutionError) as caught:
        generated_document(
            document,
            consumer.root,
            resolver=reference_resolver(policy, consumer, consumer.root),
            scope=consumer,
        )
    assert caught.value.diagnostic["category"] == "REFERENCE_PENDING_DEPLOY"
    assert caught.value.diagnostic["pointer"].startswith("/Resource")
    assert document == {"Resource": value}


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
            return_value=SimpleNamespace(
                errors=(), warnings=(), diagnostics=[], unverified=False
            ),
        ),
        patch.object(sync_runtime, "markdown_for", return_value="# Generated\n"),
    ):
        generated = sync_runtime.generate_views(
            stage,
            root,
            {bad: load_model(consumer).values, good: load_model(producer).values},
            failures,
            unavailable=unavailable,
        )
    assert set(generated) == {good}
    assert not failures and bad in unavailable
    assert unavailable[bad]["diagnostics"][0]["category"] == "REFERENCE_UNRESOLVED"
    assert {path: path.read_bytes() for path in original} == original
    assert (stage / artifact.relative_to(root)).read_bytes() == original[artifact]


@pytest.mark.parametrize("empty_snapshot", [False, True])
def test_partial_json_reference_context(fixture, empty_snapshot):
    producer, values, _, _ = fixture
    selected = {
        "desired.row.001-002.property": "S3.Bucket.Tags[].Value",
        "desired.row.001-002.value": "`"
        + json.dumps(reference("S3_Bucket_001", "BucketName"))
        + "`",
        "desired.row.001-002.comment": "合成参照",
    }
    snapshot = (
        {}
        if empty_snapshot
        else {
            **values,
            # Unselected JSON is reference context only, never another validation target.
            "desired.row.001-099.property": "S3.Bucket.NotificationConfiguration",
            "desired.row.001-099.document": "invalid JSON",
            "desired.row.001-099.value": "[Settings](s3/settings.json)",
            "desired.row.001-099.comment": "未選択",
        }
    )
    if empty_snapshot:
        with pytest.raises(ValueError, match="MODEL_REF_TARGET_MISSING"):
            validate_json_settings(selected, producer.path, reference_values=snapshot)
    else:
        validate_json_settings(selected, producer.path, reference_values=snapshot)
        shown = reference_display(
            selected, producer.path, producer.root, reference_values=snapshot
        )
        assert shown["desired.row.001-002.value"] == "`fixture-materials`"
    assert "$modelRef" in selected["desired.row.001-002.value"]


@pytest.mark.parametrize("fixed", [True, False])
def test_snapshot_reference_cache_and_unbound_inputs(fixture, fixed):
    _, _, consumer, policy = fixture
    key = "desired.row.001-002.document"
    document = json.loads(policy[key])
    document["Statement"][0]["Resource"] = reference("S3_Bucket_001")
    policy[key] = json.dumps(document)
    save(consumer, policy)
    with input_context():
        snapshot = load_model(consumer)
        assert sources.runtime_values(snapshot.authoritative) is snapshot.values
    values = snapshot.authoritative
    if not fixed:
        values = dict(values)
    with (
        input_context(),
        patch.object(projection, "nodes", wraps=projection.nodes) as scan,
        patch.object(
            projection, "reference_value", wraps=projection.reference_value
        ) as evaluate,
        patch.object(
            projection._imports_utils_json_format,
            "fingerprint",
            side_effect=AssertionError("content hash"),
        ),
        patch.object(
            projection._imports_utils_json_format,
            "document_sha256",
            side_effect=AssertionError("derived hash"),
        ),
    ):
        resolver = reference_resolver(values, consumer, consumer.root)
        contract = dict(
            resolver=resolver,
            scope=consumer,
            model_key=key,
            property_name="IAM.ManagedPolicy.PolicyDocument",
            logical_id="IAM_ManagedPolicy_001",
        )
        for _ in range(100):
            resolutions, diagnostics = projection.document_references(
                document, **contract
            )
            assert not diagnostics and len(resolutions) == 1
            resolutions.clear()
        expected_calls = 100
        if fixed:
            expected_calls = 1
        assert evaluate.call_count == expected_calls
        assert scan.call_count == expected_calls
        assert projection.document_references({}, **contract) == ({}, [])
        assert evaluate.call_count == expected_calls
        assert scan.call_count == expected_calls + 1
        document["Statement"][0]["Resource"] = reference("S3_Bucket_999")
        if not fixed:
            values[key] = json.dumps(document)
        _, diagnostics = projection.document_references(document, **contract)
        assert diagnostics[0]["code"] == "MODEL_REF_TARGET_MISSING"
        assert evaluate.call_count == expected_calls + 1
        assert scan.call_count == expected_calls + 2
        document["Statement"][0]["Resource"] = reference("S3_Bucket_001")
        # Context and exclusion changes cannot reuse the earlier receiving contract.
        projection.document_references(
            document, context={"Name": "unbound"}, **contract
        )
        assert evaluate.call_count == expected_calls + 2
        assert scan.call_count == expected_calls + 3
        resolutions, diagnostics = projection.document_references(
            document, excluded_references=("/Statement/0/Resource",), **contract
        )
        assert not resolutions and not diagnostics
        assert evaluate.call_count == expected_calls + 2
        assert scan.call_count == expected_calls + 4


def test_reference_cache_observed_generation_and_invocation(fixture):
    _, _, consumer, _ = fixture
    producer, _ = resource(consumer.root, "kms", "KMS.Key", attribute="KeyId")
    dependency_index.rebuild(consumer.root)
    shared = RunModels(consumer.root, {})
    with (
        sources.model_session(shared),
        patch.object(projection, "nodes", wraps=projection.nodes) as scan,
        patch.object(
            projection, "reference_value", wraps=projection.reference_value
        ) as evaluate,
    ):
        with input_context():
            snapshot = load_model(consumer)
            key = "desired.row.001-002.document"
            document = json.loads(snapshot.authoritative[key])
            resolver = reference_resolver(
                snapshot.authoritative, consumer, consumer.root
            )
            contract = dict(
                resolver=resolver,
                scope=consumer,
                model_key=key,
                property_name="IAM.ManagedPolicy.PolicyDocument",
                logical_id="IAM_ManagedPolicy_001",
            )
            _, first = projection.document_references(document, **contract)
            expected = copy.deepcopy(first)
            first[0]["message"] = "external contamination"
            assert projection.document_references(document, **contract)[1] == expected
            assert evaluate.call_count == 1
            assert scan.call_count == 1
            categories = [expected[0]["category"]]
            for value in (
                "PENDING_DEPLOY",
                "12345678-1234-1234-1234-123456789012",
            ):
                before = load_model(producer)
                text = patch_properties(
                    before.documents[producer.path],
                    {"observed.row.001-001.value": "`" + value + "`"},
                )
                producer.path.write_text(text, encoding="utf-8")
                shared.apply_observed({producer.path: text})
                resolutions, diagnostics = projection.document_references(
                    document, **contract
                )
                if diagnostics:
                    categories.append(diagnostics[0]["category"])
                else:
                    categories.append("RESOLVED")
                    assert (
                        next(iter(resolutions.values())).value
                        == "arn:aws:kms:ap-northeast-1:123456789012:key/" + value
                    )
                assert projection.document_references(document, **contract) == (
                    resolutions,
                    diagnostics,
                )
            assert categories == [
                "REFERENCE_UNRESOLVED",
                "REFERENCE_PENDING_DEPLOY",
                "RESOLVED",
            ]
            assert evaluate.call_count == 3
            assert scan.call_count == 3
        with input_context():
            projection.document_references(document, **contract)
            assert evaluate.call_count == 4
            assert scan.call_count == 4


@pytest.mark.parametrize("read_only, expected_calls", [(False, 3), (True, 2)])
def test_reference_cache_candidate_and_rollback(fixture, read_only, expected_calls):
    _, _, consumer, policy = fixture
    key = "desired.row.001-002.document"
    with (
        input_context(read_only=read_only),
        patch.object(
            projection, "reference_value", wraps=projection.reference_value
        ) as evaluate,
    ):
        reads = sources.FileReads()
        original = load_model(consumer, reads)
        candidate_values = dict(policy)
        changed = json.loads(policy[key])
        changed["Statement"][0]["Resource"] = reference("S3_Bucket_001")
        candidate_values[key] = json.dumps(changed)
        candidate = load_model(
            consumer,
            sources.CandidateReads(reads, {consumer.path: serialize(candidate_values)}),
        )
        diagnostics = []
        for snapshot in (original, candidate, original):
            document = json.loads(snapshot.authoritative[key])
            _, found = projection.document_references(
                document,
                resolver=reference_resolver(
                    snapshot.authoritative, consumer, consumer.root
                ),
                scope=consumer,
                model_key=key,
            )
            diagnostics.append(found)
        assert (
            diagnostics[0] == diagnostics[2] and diagnostics[0] and not diagnostics[1]
        )
        assert evaluate.call_count == expected_calls


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

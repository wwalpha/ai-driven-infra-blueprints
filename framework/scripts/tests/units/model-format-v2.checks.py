"""Synthetic format/discovery checks; never inspect the executing project's Models."""

import sys
from concurrent.futures import Future
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch as mock_patch

import model.core as _imports_model_core
import model.identity as _imports_model_identity
import model.importing.approval as _imports_model_importing_approval
import model.projection as projection
import model.references as _imports_model_references
import model.render as _imports_model_render
import pytest
from aws_mapping_compare import value as mapped_value
from design.catalog import DesignSchemaCatalog
from model.adapters.task import (
    source_write_context,
)
from model.core import (
    SnapshotValues,
    entries,
    validate_authority,
    validate_runtime_keys,
)
from model.format import FORMAT, INDEX, owner, serialize
from model.format import parse as parse
from model.format import patch as patch
from model.format import split as split
from model.importing import inventory
from model.importing.approval import (
    build_review,
    review_binding,
    verify_review,
)
from model.observed import observed_outputs
from model.operations import verify_model_operation
from model.references import declarations, incoming, usages
from model.references import diagnose as diagnose
from model.render import display_name, render_model, resource_details
from model.sources import Scope, load_model, runtime_values
from support.model_sources import write_model
from support.model_v2_fixtures import (
    FRAMEWORK,
    acquisition_fixture,
    format_fixture,
    properties_fixture,
    retarget_fixture,
    role_operation_fixture,
    source_context,
)
from task_contract_core import MergePair, ModelOperation, ReferenceChange
from utils.input_cache import input_context
from utils.script_loader import module
from utils.source_reads import CandidateReads, FileReads

import model as _imports_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_scalar_spelling_and_patch():
    text = FORMAT + '\r\n# comment\r\na.value= 010 \\ " \r\nb.value=`true`\r\n'
    document = parse(text)
    assert document.values == {"a.value": ' 010 \\ " ', "b.value": "`true`"}
    edited = patch(document, {"b.value": "`false`"})
    assert edited == text.replace("`true`", "`false`")
    for value in (False, 0, None):
        with pytest.raises(ValueError, match="strings"):
            serialize({"observed.row.017-023.value": value})
    for raw in (
        "`{{resolve:secretsmanager:secret:SecretString:token}}`",
        "`[Policy](iam/policy.json)`",
        "`[Role](iam.md#role)`",
    ):
        assert (
            parse(FORMAT + "\ndesired.row.007-001.value=" + raw + "\n").values[
                "desired.row.007-001.value"
            ]
            == raw
        )
        _json = _imports_model_references._json
        assert _json("desired.row.007-001.value", raw) == (raw, False)


def check_json_continuation_and_types():
    text = (
        FORMAT
        + '\ndesired.row.007-003.document={\\\n  "a": [true, 10, null, "1"],\\\n  "b": "slash\\\\"} \ndesired.row.007-004.value=`[\\\n"first", "second"]`\n'
    )
    values = parse(text).values
    assert json.loads(values["desired.row.007-003.document"]) == {
        "a": [True, 10, None, "1"],
        "b": "slash\\",
    }
    assert json.loads(values["desired.row.007-004.value"][1:-1]) == ["first", "second"]


@pytest.mark.parametrize(
    "body",
    [
        'a.document={"a":1,"a":2}',
        'a.document={"x":NaN}',
        "a.document={\\",
        "a.document={\\\n# comment\n}",
        "a.document={\\ \n}",
        'a.document={"x":"broken\\\nstring"}',
        'a.document={\n"a":1}',
        'a.document={"x":Infinity}',
        'a.document={"x":1e999}',
        "a.value=`[-1e999]`",
        "a.value=`[1,]`",
        "a=1\na=2",
    ],
)
def check_invalid_properties(body):
    with pytest.raises(ValueError):
        parse(FORMAT + "\n" + body + "\n")


@pytest.mark.parametrize("header", ["", "# model-format: 3"])
def check_unsupported_version(header):
    with pytest.raises(ValueError):
        parse(header + "\na=1\n")


def check_observed_insertion_is_local_without_reflow():
    text = (
        FORMAT
        + "\r\n# original comment  \r\n"
        + (
            "desired.row.007-001.property=EC2.VPC.VpcId\r\n"
            "desired.row.007-001.value=[network](#network)\r\n"
            "desired.row.007-001.comment=日本語の説明\r\n"
            "# next Row must keep its exact original bytes  \r\n"
            "desired.row.007-002.property=EC2.VPC.Name\r\n"
            'desired.row.007-002.value= 010 \\ " \r\n'
        )
    )
    marker = "desired.row.007-001.comment=日本語の説明\r\n"
    observed = "observed.row.007-001.value=\r\n"
    updated = patch(parse(text), {"observed.row.007-001.value": ""})
    assert updated == text.replace(marker, marker + observed)
    assert patch(parse(updated), {"observed.row.007-001.value": None}) == text


def check_import_observation_foreign_reference_and_identity_spoof(tmp_path):
    scope, values = format_fixture(tmp_path)
    values.update(
        {
            "desired.resource.008.resourceType": "EC2.Subnet",
            "desired.resource.008.anchor": "subnet-existing",
            "desired.resource.008.resourceMode": "IMPORT",
            "desired.resource.008.logicalId": "EC2_Subnet_001",
            "desired.service.identity.lastAllocated": '{"EC2.VPC":1,"EC2.Subnet":1}',
            "desired.row.008-001.property": "EC2.Subnet.VpcId",
            "desired.row.008-001.value": "[vpc](#network-existing)",
            "desired.row.008-001.comment": "foreign VPC",
            "observed.row.008-001.value": "vpc-before",
            "desired.row.008-002.property": "EC2.Subnet.SubnetId",
            "desired.row.008-002.value": "[subnet](#subnet-existing)",
            "desired.row.008-002.comment": "own ID",
            "observed.row.008-002.value": "subnet-before",
        }
    )
    scope.path.write_text(serialize(values))
    snapshot = load_model(scope)
    outputs = observed_outputs(
        scope.path, {**snapshot.values, "observed.row.008-001.value": "PENDING_DEPLOY"}
    )
    assert outputs[scope.path] == patch(
        parse(scope.path.read_text()), {"observed.row.008-001.value": "PENDING_DEPLOY"}
    )
    assert "observed.row.008-002.value=subnet-before" in outputs[scope.path]
    with pytest.raises(ValueError, match="IMPORT physical identity"):
        observed_outputs(
            scope.path,
            {**snapshot.values, "observed.row.008-002.value": "subnet-other"},
        )
    # A forged foreign link cannot make a native primary identifier writable.
    values["desired.row.008-002.value"] = "[vpc](#network-existing)"
    scope.path.write_text(serialize(values))
    snapshot = load_model(scope)
    with pytest.raises(ValueError, match="IMPORT physical identity"):
        observed_outputs(
            scope.path,
            {**snapshot.values, "observed.row.008-002.value": "subnet-other"},
        )


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize(
    "existing",
    [
        None,
        '{"bucketDefinitions":[{"accountId":"123456789012","buckets":["stale"]}]}',
        "broken JSON",
    ],
)
def check_macie_renders_current_document_without_artifact_reads(
    tmp_path, existing, inline
):
    scope, _ = format_fixture(tmp_path, service="macie")
    document = {
        "bucketDefinitions": [
            {"accountId": "123456789012", "buckets": ["current-a", "current-b"]}
        ]
    }
    values = {
        "desired.service.macie.serviceId": "macie",
        "desired.service.macie.ownedCatalogResourceTypes": "Macie.ClassificationJob",
        "display.service.title": "# Fixture",
        "desired.resource.007.resourceType": "Macie.ClassificationJob",
        "desired.resource.007.logicalId": "Macie_ClassificationJob_001",
        "desired.resource.007.anchor": "macie-fixture-job",
        "desired.service.identity.lastAllocated": '{"Macie.ClassificationJob":1}',
        "desired.resource.007.resourceMode": "IMPORT",
        "display.resource.007.comment": "fixture",
    }
    for index, (prop, value) in enumerate(
        [
            ("name", "`fixture-job`"),
            ("s3JobDefinition", "[definition](macie/definition.json)"),
        ],
        1,
    ):
        values.update(
            {
                f"desired.row.007-{index:03d}.property": "Macie.ClassificationJob."
                + prop,
                f"desired.row.007-{index:03d}.value": value,
                f"desired.row.007-{index:03d}.comment": "fixture",
            }
        )
    if inline:
        document = {"bucketCriteria": {}}
        values["desired.row.007-002.value"] = "`" + json.dumps(document) + "`"
    else:
        values["desired.row.007-002.document"] = json.dumps(document)
    scope.path.write_text(serialize(values), encoding="utf-8")
    artifact = (
        tmp_path
        / "docs/designs"
        / scope.environment
        / scope.target
        / "macie/definition.json"
    )
    if existing is not None:
        artifact.parent.mkdir(parents=True)
        artifact.write_text(existing, encoding="utf-8")
    original = scope.path.read_bytes()
    files = render_model(load_model(scope), None)
    if inline:
        assert artifact not in files
    else:
        assert json.loads(files[artifact]) == document
    markdown = files[artifact.parent.with_suffix(".md")]
    assert ("#### 対象S3 bucket" in markdown) == (not inline)
    for bucket in document.get("bucketDefinitions", [{"buckets": []}])[0]["buckets"]:
        assert f"`{bucket}`" in markdown
    assert "`stale`" not in markdown
    assert scope.path.read_bytes() == original
    assert (
        artifact.read_text(encoding="utf-8") if artifact.exists() else None
    ) == existing


@pytest.mark.parametrize(
    "kind,label,rows,expected",
    [
        ("EC2.VPC", None, [], "EC2.VPC"),
        (
            "CodeBuild.Project",
            "fallback",
            [("CodeBuild.Project.Name", "`raw-name`")],
            "raw-name",
        ),
        ("KMS.Key", "fallback", [], "fallback"),
        ("EC2.SecurityGroupIngress", None, [], "EC2_SecurityGroupIngress_001"),
        ("KMS.Key", None, [("KMS.Alias.AliasName", "`alias/grouped`")], "grouped"),
    ],
)
def check_shared_display_selection_and_diagnostics(
    tmp_path, kind, label, rows, expected
):
    scope, _ = format_fixture(tmp_path)
    values = {
        "desired.resource.007.anchor": "resource-existing",
        "desired.resource.007.resourceType": kind,
        "desired.resource.007.logicalId": kind.replace(".", "_") + "_001",
        "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
        "desired.resource.007.resourceMode": "IMPORT",
    }
    if label:
        values["display.resource.007.label"] = label
    for index, (prop, value) in enumerate(rows, 1):
        rid = "008" if prop.startswith("KMS.Alias.") else "007"
        values.update(
            {
                f"desired.row.{rid}-{index:03d}.property": prop,
                f"desired.row.{rid}-{index:03d}.value": value,
                f"desired.row.{rid}-{index:03d}.comment": "fixture",
            }
        )
        if rid == "008":
            values.update(
                {
                    "desired.resource.008.resourceType": "KMS.Alias",
                    "desired.resource.008.logicalId": "KMS_Alias_001",
                    "desired.service.identity.lastAllocated": json.dumps(
                        {kind: 1, "KMS.Alias": 1}
                    ),
                    "desired.resource.008.resourceMode": "IMPORT",
                    "desired.resource.008.parentReference": "[key](#resource-existing)",
                }
            )
    resource = dict(entries(values, "desired.resource."))["007"]
    assert (
        display_name(
            values,
            "007",
            resource,
            [[str(i), prop, value, "fixture"] for i, (prop, value) in enumerate(rows)],
            tmp_path,
        )[0]
        == expected
    )
    if kind == "EC2.VPC":
        resource_details = _imports_model_render.resource_details
        details, _ = resource_details(
            values,
            tmp_path,
            "network",
            {kind},
            [
                (identity, item)
                for identity, item in entries(values, "desired.resource.")
            ],
            {},
        )
        assert details[0][2] == expected
    text = "[resource](#resource-existing)"
    values["desired.note.001.text"] = text
    spec = {
        "consumerKey": "desired.note.001.text",
        "text": text,
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "/".join((scope.environment, scope.target, scope.service)),
        "producerLogicalId": resource["logicalId"],
        "resourceType": kind,
        "format": "link",
        "labelPolicy": "display-name",
    }
    values.update(
        {"desired.reference.name." + key: value for key, value in spec.items()}
    )
    scope.path.write_text(serialize(values), encoding="utf-8")
    assert load_model(scope).warnings == ()


@pytest.mark.parametrize(
    "kind,mode,multiple",
    [
        ("EC2.VPC", "IMPORT", True),
        ("EC2.VPC", "CREATE", False),
        ("KMS.Alias", "IMPORT", False),
        ("CodeBuild.Project", "IMPORT", False),
    ],
)
def check_type_display_constraints(tmp_path, kind, mode, multiple):
    values = {
        "desired.resource.007.resourceType": kind,
        "desired.resource.007.resourceMode": mode,
        "desired.resource.007.logicalId": "fixed",
        "desired.resource.007.anchor": "network",
    }
    if multiple:
        values.update(
            {
                "desired.resource.008.resourceType": kind,
                "desired.resource.008.logicalId": "second",
            }
        )
    resource = dict(entries(values, "desired.resource."))["007"]
    if multiple:
        assert display_name(values, "007", resource, [], FRAMEWORK)[0] is None
    else:
        with pytest.raises(ValueError):
            display_name(values, "007", resource, [], FRAMEWORK)
    with pytest.raises(ValueError):
        resource_details(
            values,
            FRAMEWORK,
            "network",
            {kind},
            list(entries(values, "desired.resource.")),
            {},
        )


def _callback_check_resource_acquisition_scope_call(calls, /, *args, **kwargs):
    calls.append(args)
    return {"ResourceDescription": {"Properties": '{"TransitGatewayId":"tgw-fixture"}'}}


def _callback_check_resource_acquisition_scope_fetch(calls, provider, /, *args):
    calls.append(provider)
    return {"id": "tgw-fixture"}


@pytest.mark.parametrize("scope", ["dev/one", "dev/two", "prod/one", "prod/two"])
@pytest.mark.parametrize("provider", ["adapter", "sdk", "cloudcontrol"])
def check_resource_acquisition_scope(tmp_path, monkeypatch, scope, provider):
    m = module("model/adapters/aws.py", "model.adapters.aws")
    target = {
        "environment": "dev",
        "directory": "one",
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
    }
    calls = []
    monkeypatch.setattr(
        m, "DesignSchemaCatalog", lambda root: DesignSchemaCatalog(FRAMEWORK)
    )
    ctx = m.Context(tmp_path, target)
    ctx.verified = True
    getter = {
        "kind": "cloudcontrol",
        "service": "cloudcontrol",
        "operation": "get_resource",
        "resourceType": "EC2.TransitGateway",
        "identifier": ["/properties/TransitGatewayId"],
    }
    mapping = SimpleNamespace(identities={}, getters={"provider": getter})
    monkeypatch.setattr(ctx, "comparison", lambda service: (mapping, {}))
    monkeypatch.setattr(
        inventory,
        "inventory_for",
        lambda ctx: SimpleNamespace(
            schema=lambda kind: {
                "primaryIdentifier": getter["identifier"],
                "handlers": {"read": {}},
            }
        ),
    )
    call = _bind_framework_callback(
        _callback_check_resource_acquisition_scope_call, calls
    )
    monkeypatch.setattr(ctx, "call", call)
    fetch = _bind_framework_callback(
        _callback_check_resource_acquisition_scope_fetch, calls, provider
    )
    model = SimpleNamespace(
        path=tmp_path / "model" / (scope + "/ec2.properties"),
        ctx=ctx,
        service="ec2",
        values={
            "desired.row.007-001.property": "EC2.TransitGateway.TransitGatewayId",
            "desired.row.007-001.value": "`tgw-fixture`",
        },
    )
    resource = m.Resource(
        model,
        "007",
        {"resourceType": "EC2.TransitGateway", "anchor": "gateway"},
        [
            (
                "007-001",
                {
                    "property": "EC2.TransitGateway.TransitGatewayId",
                    "value": "`tgw-fixture`",
                },
            )
        ],
    )
    resource.module = SimpleNamespace(
        CLOUDCONTROL_RESOURCE_TYPES={"EC2.TransitGateway"}, fetch=fetch, fetch_sdk=fetch
    )
    definition = {"operation": "get_resource"} if provider == "sdk" else None
    if provider == "cloudcontrol":
        entries = [
            lambda: resource.identity(),
            lambda: inventory.cloudcontrol_value(ctx, resource, getter),
        ]
    else:
        entries = [
            lambda: ctx.fetch(resource, "provider", definition),
            lambda: ctx._fetch(resource, "provider", definition),
        ]
    if scope == "dev/one":
        for acquire in entries:
            assert acquire()
        assert calls
    else:
        # Populate both caches to prove that authorization precedes every cache hit.
        cache_key = (model.path, "007", "provider")
        ctx.fetch_cache[cache_key] = {"id": "cached"}
        ctx.fetch_trace[cache_key] = []
        future = Future()
        future.set_result({"id": "cached"})
        ctx._flights[("fetch", *cache_key)] = future
        prop = SimpleNamespace(field=SimpleNamespace(getter="provider"))
        if provider == "cloudcontrol":
            entries.append(
                lambda: mapped_value(
                    ctx, resource, mapping, prop, "EC2.TransitGateway.TransitGatewayId"
                )
            )
        for acquire in entries:
            with pytest.raises(
                m.Unresolved, match="outside authorized AWS retrieval scope"
            ):
                acquire()
        assert calls == []


def check_runtime_metadata_is_not_authority():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        model = load_model(scope)
        assert (
            model.values["observed.row.007-001.property"]
            == values["desired.row.007-001.property"]
        )
        assert "observed.row.007-001.property" not in model.authoritative
        assert model.values["observed.row.007-001.value"] == ""
        del values["observed.row.007-001.value"]
        scope.path.write_text(serialize(values), encoding="utf-8")
        assert "observed.row.007-001.value" not in load_model(scope).values
        values["observed.row.007-001.value"] = "PENDING_DEPLOY"
        scope.path.write_text(serialize(values), encoding="utf-8")
        assert (
            load_model(scope).values["observed.row.007-001.value"] == "PENDING_DEPLOY"
        )


def check_reference_schema_and_pointer():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        key = "desired.row.007-002.value"
        values[key] = '`{"value":"vpc-one"}`'
        spec = {
            "consumerKey": key,
            "pointer": "/value",
            "text": "vpc-one",
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "qa-custom/one/network",
            "producerLogicalId": "EC2_VPC_001",
            "resourceType": "EC2.VPC",
            "format": "identifier",
            "property": "EC2.VPC.VpcId",
            "labelPolicy": "none",
        }
        values.update(
            {
                f"desired.reference.stable.{field}": value
                for field, value in spec.items()
            }
        )
        scope.path.write_text(serialize(values), encoding="utf-8")
        model = load_model(scope)
        assert declarations(model.authoritative) == {"stable": spec}
        warnings, _ = diagnose(model)
        assert warnings and "nonempty non-ARN" in warnings[0]["message"]
        broken = {**values, "desired.reference.stable.pointer": "/missing"}
        with pytest.raises(ValueError, match="existing string leaf"):
            declarations(broken)
        for orphan in ("display.resource.999.comment", "display.stack.999.comment"):
            broken = {
                key: value
                for key, value in values.items()
                if key != "desired.reference.stable.pointer"
            }
            broken[orphan] = "vpc-one"
            broken["desired.reference.stable.consumerKey"] = orphan
            with pytest.raises(ValueError, match="consumer owner is absent"):
                declarations(broken)


def check_stack_metadata_is_not_runtime_input():
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = format_fixture(Path(directory))
        stack = Scope(
            scope.root, scope.environment, scope.target, "cloudformation-stacks"
        )
        values = {
            "desired.stack.009.name": "NewStackName",
            "desired.stack.009.placementName": "OriginalPlacement",
            "desired.stack.009.template": "stack.yaml",
            "desired.stack.009.parameters": "stack.json",
            "desired.stack.009.deployOrder": "1",
            "desired.service.cloudformation-stacks.serviceId": "cloudformation-stacks",
            "desired.service.cloudformation-stacks.ownedCatalogResourceTypes": "CloudFormation.Stack",
            "desired.note.001.text": "保存する設計注記",
        }
        stack.path.write_text(serialize(values), encoding="utf-8")
        model = load_model(stack)
        assert (
            model.authoritative["desired.stack.009.placementName"]
            == "OriginalPlacement"
        )
        assert "desired.stack.009.placementName" not in model.values
        stack_model = _imports_model_core.stack_model
        assert stack_model(model.values)[1][0][1]["name"] == "NewStackName"
        assert "placementName" not in stack_model(model.authoritative)[1][0][1]
        assert (
            model.authoritative["desired.note.001.text"]
            == model.values["desired.note.001.text"]
        )
        validate_authority = _imports_model_core.validate_authority
        for placement in ("", "invalid_name", None):
            bad = {**values, "desired.stack.009.placementName": placement}
            if placement is None:
                del bad["desired.stack.009.placementName"]
            with pytest.raises(ValueError, match="placementName"):
                validate_authority(bad)
        with pytest.raises(TypeError):
            model.authoritative["desired.stack.009.name"] = "mutated"


def check_reference_occurrence_identifies_overlapping_text():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        key = "desired.row.007-002.value"
        values[key] = "aaa"
        spec = {
            "consumerKey": key,
            "text": "aa",
            "occurrence": "2",
            "producerKind": "resource",
            "producerScope": "qa-custom/one/network",
            "producerLogicalId": "EC2_VPC_001",
            "resourceType": "EC2.VPC",
            "format": "name",
            "property": "EC2.VPC.Name",
            "labelPolicy": "none",
        }
        values.update(
            {
                f"desired.reference.stable.{field}": value
                for field, value in spec.items()
            }
        )
        scope.path.write_text(serialize(values), encoding="utf-8")
        matches = [
            usage
            for usage in usages(load_model(scope))
            if usage.metadata_id == "stable"
        ]
        assert len(matches) == 1 and matches[0].start == 1 and matches[0].end == 3


def check_runtime_projection_validation_and_metadata_separation():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        projected = runtime_values(values)
        validate_runtime_keys(projected)
        with pytest.raises(ValueError, match="unknown Model field"):
            validate_authority(projected)
        projected["observed.row.007-001.comment"] = "different from desired"
        with pytest.raises(ValueError, match="derived observed metadata"):
            validate_runtime_keys(projected)


def check_observed_cannot_bypass_import_or_change_authority():
    prepare_edit = _imports_model.prepare_edit
    prepare_observed = _imports_model.prepare_observed
    with tempfile.TemporaryDirectory() as directory:
        scope, _ = format_fixture(Path(directory))
        snapshot, context = source_context(scope, imported=True)
        try:
            with pytest.raises(ValueError, match="IMPORT physical identity"):
                prepare_observed(
                    snapshot, {"observed.row.007-001.value": "vpc-other"}, context
                )
            with pytest.raises(ValueError, match="observed.row"):
                prepare_observed(
                    snapshot, {"desired.row.007-001.value": "changed"}, context
                )
            with pytest.raises(ValueError, match="unregistered"):
                prepare_edit(
                    snapshot,
                    {scope.path.with_name("other.properties"): FORMAT + "\n"},
                    context,
                )
            with pytest.raises(ValueError, match="names and flags"):
                prepare_edit(snapshot, {}, {"approved": True})
        finally:
            context.close()


@pytest.mark.parametrize(
    "failure",
    ["missing", "duplicate", "unlisted", "escape", "symlink", "split", "duplicate-key"],
)
def check_unsafe_parts(failure):
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        part = scope.path.with_suffix("") / "part-001.properties"
        part.parent.mkdir()
        part.write_text(serialize(values), encoding="utf-8")
        index = FORMAT + "\n" + INDEX + "\n# part: network/part-001.properties\n"
        if failure == "missing":
            part.unlink()
        elif failure == "duplicate":
            index += "# part: network/part-001.properties\n"
        elif failure == "escape":
            index = index.replace("network/part-001", "../part-001")
        elif failure == "symlink":
            part.unlink()
            part.symlink_to(scope.root / "project.json")
        else:
            extra = part.with_name("part-003.properties")
            extra.write_text(
                serialize({"desired.resource.007.logicalId": "EC2_VPC_001"}),
                encoding="utf-8",
            )
            if failure != "unlisted":
                index += "# part: network/part-003.properties\n"
            if failure == "split":
                del values["desired.resource.007.logicalId"]
                part.write_text(serialize(values), encoding="utf-8")
        scope.path.write_text(index, encoding="utf-8")
        with pytest.raises(ValueError):
            load_model(scope)


def check_declared_and_direct_links_coalesce_or_retain_conflicts():
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        key = "desired.row.007-001.value"
        spec = {
            "consumerKey": key,
            "text": values[key],
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "qa-custom/one/network",
            "producerLogicalId": "EC2_VPC_001",
            "resourceType": "EC2.VPC",
            "format": "link",
            "labelPolicy": "fixed",
        }
        values.update(
            {
                f"desired.reference.stable.{field}": value
                for field, value in spec.items()
            }
        )
        scope.path.write_text(serialize(values), encoding="utf-8")
        model = load_model(scope)
        assert len([usage for usage in usages(model) if usage.consumer_key == key]) == 1
        values.update(
            {
                "desired.resource.008.resourceType": "EC2.VPC",
                "desired.resource.008.logicalId": "EC2_VPC_002",
                "desired.resource.008.anchor": "resource-EC2_VPC_002",
                "desired.service.identity.lastAllocated": '{"EC2.VPC":2}',
                "desired.reference.stable.producerLogicalId": "EC2_VPC_002",
            }
        )
        scope.path.write_text(serialize(values), encoding="utf-8")
        original = scope.path.read_bytes()
        model = load_model(scope)
        assert len([usage for usage in usages(model) if usage.consumer_key == key]) == 2
        assert any("both meanings" in warning["message"] for warning in model.warnings)
        assert len(incoming(model, "007")) == len(incoming(model, "008")) == 1
        assert scope.path.read_bytes() == original
        values["desired.reference.stable.producerLogicalId"] = "EC2_VPC_001"
        values["desired.resource.008.logicalId"] = values[
            "desired.resource.007.logicalId"
        ]
        scope.path.write_text(serialize(values), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate logicalId"):
            load_model(scope)
        assert parse(scope.path.read_text()).values[key] == values[key]


@pytest.mark.parametrize("action", ["add", "refresh", "bind", "replace"])
def check_properties_import_review_operations(action):
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        values["observed.row.007-001.value"] = (
            "vpc-original" if action != "bind" else "PENDING_DEPLOY"
        )
        values["desired.row.007-002.value"] = "10.0.0.0/16"
        scope.path.write_text(serialize(values), encoding="utf-8")
        before = load_model(scope)
        rid = "008" if action == "add" else "007"
        acquisition, selection = acquisition_fixture(
            before, action=action, resource=rid
        )
        after = dict(before.authoritative)
        if action == "add":
            after.update(
                {
                    key.replace(".007.", ".008.").replace(
                        ".007-", ".008-"
                    ): value.replace("#network", "#added")
                    for key, value in values.items()
                }
            )
            allocate = _imports_model_identity.allocate
            del after["desired.resource.008.logicalId"]
            after = allocate(after, ["008"])
            after["desired.row.008-001.value"] = (
                "[EC2_VPC_002](network.md#resource-EC2_VPC_002)"
            )
        after[f"observed.row.{rid}-001.value"] = acquisition["records"][0]["identity"]
        review = build_review(
            acquisition,
            selection,
            before,
            after,
            {"record-one": []},
            lambda prop: {"type": "string"},
        )
        assert review["version"] == 4 and len(review["dispositions"]) == 1
        assert review["dispositions"][0]["operation"] == action
        assert (
            review["dispositions"][0]["physicalId"]
            == acquisition["records"][0]["identity"]
        )
        verify_review(review, review)
        assert review_binding(review, acquisition)["version"] == 2
        assert scope.path.read_text(encoding="utf-8") == serialize(values)


@pytest.mark.parametrize(
    "change", ["delete-selected", "delete-unselected", "move-unselected", "meaning"]
)
def check_properties_reference_review_after_map_and_ownership(change):
    build_review = _imports_model_importing_approval.build_review
    reference_provenance = _imports_model_importing_approval.reference_provenance
    verify_review = _imports_model_importing_approval.verify_review
    with tempfile.TemporaryDirectory() as directory:
        scope, values = format_fixture(Path(directory))
        values.update(
            {
                "desired.resource.008.resourceType": "EC2.VPC",
                "desired.resource.008.logicalId": "EC2_VPC_002",
                "desired.resource.008.anchor": "resource-EC2_VPC_002",
                "desired.service.identity.lastAllocated": '{"EC2.VPC":2}',
                "desired.resource.008.resourceMode": "IMPORT",
                "desired.row.008-001.property": "EC2.VPC.VpcId",
                "desired.row.008-001.value": "[EC2_VPC_002](network.md#resource-EC2_VPC_002)",
                "desired.row.008-001.comment": "合成",
                "observed.row.008-001.value": "vpc-second",
                "observed.row.007-001.value": "vpc-original",
            }
        )
        spec = {
            "consumerKey": "desired.row.007-001.value",
            "text": values["desired.row.007-001.value"],
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "qa-custom/one/network",
            "producerLogicalId": "EC2_VPC_001",
            "resourceType": "EC2.VPC",
            "format": "link",
            "labelPolicy": "fixed",
        }
        values.update(
            {
                f"desired.reference.stable.{field}": value
                for field, value in spec.items()
            }
        )
        scope.path.write_text(serialize(values), encoding="utf-8")
        before = load_model(scope)
        acquisition, selection = acquisition_fixture(before)
        proposed = (
            {}
            if change.startswith("delete")
            else {
                "stable": {
                    **spec,
                    **(
                        {
                            "consumerKey": "desired.row.008-001.value",
                            "text": "[EC2_VPC_002](network.md#resource-EC2_VPC_002)",
                        }
                        if change == "move-unselected"
                        else {
                            "producerLogicalId": "EC2_VPC_002",
                            "labelPolicy": "display-name",
                        }
                    ),
                }
            }
        )
        if change == "delete-unselected":
            acquisition["records"][0]["identity"] = "vpc-second"
            acquisition["records"][0]["properties"]["EC2.VPC.VpcId"]["value"] = (
                "vpc-second"
            )
            selection["resources"][0]["resource"] = "008"
        if change in {"delete-unselected", "move-unselected"}:
            with pytest.raises(ValueError, match="unselected"):
                build_review(
                    acquisition,
                    selection,
                    before,
                    dict(values),
                    {"record-one": []},
                    lambda prop: {"type": "string"},
                    proposed_references=proposed,
                )
        else:
            review = build_review(
                acquisition,
                selection,
                before,
                dict(values),
                {"record-one": []},
                lambda prop: {"type": "string"},
                proposed_references=proposed,
            )
            assert review["referenceProvenance"]["before"] == {"stable": spec}
            assert review["referenceProvenance"]["after"] == proposed
            unchanged = build_review(
                acquisition,
                selection,
                before,
                dict(values),
                {"record-one": []},
                lambda prop: {"type": "string"},
            )
            assert unchanged["referenceProvenance"]["after"] == reference_provenance(
                before
            )
            with pytest.raises(ValueError, match="changed or stale"):
                verify_review(review, unchanged)


def check_properties_context_requires_managed_running_task(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    properties_fixture(tmp_path)
    with pytest.raises(ValueError, match="selected task contract missing"):
        with source_write_context(tmp_path, "tasks/missing.md"):
            raise AssertionError("missing Task granted Model publication")


@pytest.mark.parametrize(
    "change", ["delete", "merge", "identity", "observation", "native", "unselected"]
)
def check_properties_model_operation_preservation(tmp_path, monkeypatch, change):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    before, after = tmp_path / "before", tmp_path / "after"
    scope, values = role_operation_fixture(before)
    shutil.copytree(before, after)
    identity = scope.environment, scope.target, scope.service
    source = "/".join((*identity, "007"))
    destination = "/".join((*identity, "008"))
    operation = ModelOperation(
        "import-delete" if change == "delete" else "import-merge",
        identity,
        pairs=() if change == "delete" else (MergePair(source, destination),),
        delete_sources=(source,) if change == "delete" else (),
    )
    candidate = {
        key: value
        for key, value in values.items()
        if owner(key, values) != ("resource", "007")
    }
    if change != "delete":
        candidate["observed.row.008-001.value"] = values["observed.row.007-001.value"]
        candidate["desired.row.008-002.document"] = values[
            "desired.row.007-002.document"
        ].replace("[role](#role-source)", "[role](#role-destination)")
    if change == "identity":
        candidate["desired.resource.008.logicalId"] = "changed"
    elif change == "observation":
        candidate["observed.row.008-001.value"] = "`lost-source-identity`"
    elif change == "native":
        candidate["desired.row.008-002.document"] = candidate[
            "desired.row.008-002.document"
        ].replace('[1, "1", false]', '[true, "1", false]')
    elif change == "unselected":
        candidate["display.resource.009.comment"] = "changed unrelated display"
    path = after / scope.path.relative_to(before)
    path.write_text(serialize(candidate), encoding="utf-8")
    sources = {scope.path.relative_to(before).as_posix()}
    if change in {"delete", "merge"}:
        verify_model_operation(before, after, operation, sources)
    else:
        with pytest.raises(
            ValueError, match="identity|logicalId|observation|undeclared|unspecified"
        ):
            verify_model_operation(before, after, operation, sources)


@pytest.mark.parametrize(
    "change",
    ["retarget", "prefix", "context-scope", "context-text", "format", "rename-id"],
)
def check_properties_retarget_keeps_other_fragments_and_reference_ids(
    tmp_path, monkeypatch, change
):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    before, after = tmp_path / "before", tmp_path / "after"
    scope, values = retarget_fixture(before)
    shutil.copytree(before, after)
    values["desired.row.001-001.value"] = "qa-synthetic:123456789012:vpc-destination"
    values["desired.reference.resource-use.producerLogicalId"] = "EC2_VPC_008"
    values["desired.reference.resource-use.text"] = "vpc-destination"
    if change == "prefix":
        values["desired.row.001-001.value"] = (
            "changed-prefix:123456789012:vpc-destination"
        )
    elif change == "context-scope":
        values["desired.reference.context-use.producerScope"] = "qa-synthetic/team-b"
    elif change == "context-text":
        values["desired.reference.context-use.text"] = "123"
    elif change == "format":
        values["desired.reference.resource-use.format"] = "name"
    elif change == "rename-id":
        values = {
            key.replace(
                "desired.reference.resource-use.", "desired.reference.renumbered."
            ): value
            for key, value in values.items()
        }
    path = after / scope.path.relative_to(before)
    path.write_text(serialize(values), encoding="utf-8")
    identity = scope.environment, scope.target, scope.service
    reference = ReferenceChange(
        "/".join((*identity, "001")),
        "value",
        "qa-synthetic/team-a/network/007",
        "qa-synthetic/team-a/network/008",
        "EC2.SecurityGroup.VpcId",
    )
    operation = ModelOperation("import-retarget", identity, references=(reference,))
    if change == "retarget":
        verify_model_operation(
            before, after, operation, {path.relative_to(after).as_posix()}
        )
    else:
        with pytest.raises(
            ValueError,
            match="affixes|another reference|format|fixed reference|renumber",
        ):
            verify_model_operation(
                before, after, operation, {path.relative_to(after).as_posix()}
            )


def check_incoming_missing_producer_does_not_match_unrelated_metadata(tmp_path):
    scope, values = format_fixture(tmp_path)
    key = "desired.row.007-002.value"
    values[key] = "original missing"
    for identity, producer, text in (
        ("stable-one", "007", "original"),
        ("stable-two", "009", "missing"),
    ):
        for field, value in {
            "consumerKey": key,
            "text": text,
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "/".join((scope.environment, scope.target, scope.service)),
            "producerLogicalId": "EC2_VPC_"
            + ("001" if producer == "007" else producer),
            "resourceType": "EC2.VPC",
            "format": "name",
            "property": "EC2.VPC.Name",
            "labelPolicy": "none",
        }.items():
            values["desired.reference." + identity + "." + field] = value
    scope.path.write_text(serialize(values), encoding="utf-8")
    uses = incoming(load_model(scope), "EC2_VPC_009")
    assert len(uses) == 1 and uses[0][1].logical_id == "EC2_VPC_009"
    assert uses[0][1].text == "missing"


def check_common_shape(tmp_path):
    root = tmp_path
    scope, _ = format_fixture(root)
    path = scope.path.with_name("shared.properties")
    minimal = {
        "desired.resource.017.resourceType": "S3.Bucket",
        "desired.resource.017.logicalId": "S3_Bucket_001",
        "desired.resource.017.anchor": "resource-S3_Bucket_001",
        "desired.service.identity.lastAllocated": '{"S3.Bucket":1}',
        "desired.row.017-023.property": "S3.Bucket.BucketName",
        "desired.row.017-023.value": "`fixed-name`",
        "desired.row.017-023.comment": "名前",
        "desired.row.017-025.property": "S3.Bucket.Tags",
        "desired.row.017-025.value": '`{"Items":[1,3],"Value":"","Keep":null}`',
        "desired.row.017-025.comment": "明示した配列と型",
        "desired.note.bucket.text": "[S3_Bucket_001](shared.md#resource-S3_Bucket_001)",
    }
    write_model(path, minimal)
    assert load_model(path).authoritative == minimal
    missing = {
        key: value
        for key, value in minimal.items()
        if key != "desired.resource.017.logicalId"
    }
    with pytest.raises(ValueError):
        load_model(path, CandidateReads(FileReads(), {path: serialize(missing)}))
    assert not any(key.startswith("desired.row.017-024.") for key in minimal)
    full = {
        **minimal,
        "desired.resource.017.logicalId": "S3_Bucket_001",
        "desired.row.017-024.property": "S3.BucketPolicy.PolicyDocument",
        "desired.row.017-024.value": "[policy.json](shared/policy.json)",
        "desired.row.017-024.comment": "明示した権限",
        "desired.row.017-024.document": '{"Statement":[{"Resource":"*"}]}',
    }
    write_model(path, full)
    assert json.loads(
        load_model(path).authoritative["desired.row.017-024.document"]
    ) == {"Statement": [{"Resource": "*"}]}
    assert (
        load_model(path).authoritative["desired.resource.017.logicalId"]
        == "S3_Bucket_001"
    )
    full.update(
        {
            "desired.row.017-023.value": "[S3_Bucket_001](shared.md#resource-S3_Bucket_001)",
            "desired.note.bucket.text": "[S3_Bucket_001](shared.md#resource-S3_Bucket_001)",
            "desired.row.017-025.value": '`{"Drop":null,"Items":[0,1,2,3],"Value":false,"Keep":null}`',
            "desired.row.017-024.document": '{"Statement":[{"Resource":"*"},{"Resource":"explicit-target"}]}',
        }
    )
    write_model(path, full)
    model = load_model(path)
    assert model.authoritative == full
    assert json.loads(model.authoritative["desired.row.017-025.value"][1:-1]) == {
        "Drop": None,
        "Items": [0, 1, 2, 3],
        "Value": False,
        "Keep": None,
    }
    assert (
        json.loads(model.authoritative["desired.row.017-024.document"])["Statement"][1][
            "Resource"
        ]
        == "explicit-target"
    )
    assert (
        "desired.row.017-024.artifactSha256" not in model.values
        and "desired.row.017-024.artifactSha256" not in model.authoritative
    )
    for bad in (
        {**full, "desired.row.017-025.value": '`{"a":1,"a":2}`'},
        {
            key: value
            for key, value in full.items()
            if key != "desired.row.017-024.property"
        },
    ):
        try:
            raw = serialize(bad)
            path.write_text(raw)
            load_model(path)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid explicit shape accepted")


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "missing",
        "missing-property",
        "missing-comment",
        "orphan-row",
        "orphan-observed",
        "resource-type",
        "resource-extra",
        "logical-id",
        "observed-property",
        "observed-state",
    ],
)
def check_explicit_row_inputs(tmp_path, fault):
    scope, values = format_fixture(tmp_path)
    if fault == "unknown":
        values["desired.row.007-002.unknown"] = "1"
    elif fault == "missing":
        del values["desired.row.007-002.value"]
    elif fault.startswith("missing-"):
        del values["desired.row.007-002." + fault.removeprefix("missing-")]
    elif fault == "resource-extra":
        values["desired.resource.007.definition"] = "old"
    elif fault == "resource-type":
        del values["desired.resource.007.resourceType"]
    elif fault == "logical-id":
        del values["desired.resource.007.logicalId"]
    elif fault == "observed-property":
        values["observed.row.007-001.property"] = "wrong"
    elif fault == "observed-state":
        values["observed.row.007-001.state"] = "unknown"
    elif fault == "orphan-row":
        values.update(
            {
                "desired.row.099-004.property": "IAM.Role.RoleName",
                "desired.row.099-004.value": "x",
                "desired.row.099-004.comment": "orphan",
            }
        )
    else:
        values["observed.row.999-001.value"] = "x"
    with pytest.raises(ValueError):
        load_model(scope, CandidateReads(FileReads(), {scope.path: serialize(values)}))


@pytest.mark.parametrize("fault", ["absent", "duplicate", "number", "malformed"])
def check_context_topology_inputs(tmp_path, fault):
    scope, values = format_fixture(tmp_path)
    target = json.loads((tmp_path / "project.json").read_text())["targets"][0]
    targets = [target]
    if fault == "absent":
        targets = []
    elif fault == "duplicate":
        targets = [target, target]
    else:
        target["awsExecutionAccountId"] = 123 if fault == "number" else "bad"
    reads = CandidateReads(
        FileReads(),
        {
            scope.path: serialize(values),
            tmp_path / "project.json": json.dumps({"targets": targets}),
        },
    )
    with pytest.raises((ValueError, OSError)):
        load_model(scope, reads)


class CountedSnapshot(SnapshotValues):
    scans = 0

    def items(self):
        self.scans += 1
        return super().items()


def check_snapshot_row_index_and_mutable_entries():
    values = {
        "desired.row.001-001.property": "S3.Bucket.BucketName",
        "desired.row.001-001.value": "`before`",
        "desired.row.001-001.comment": "fixture",
    }
    fixed = CountedSnapshot(values)
    with pytest.raises(TypeError):
        fixed.update({"desired.row.001-001.value": "contaminated"})
    with pytest.raises(TypeError):
        fixed.pop("desired.row.001-001.value")
    fixed.__init__({"desired.row.001-001.value": "contaminated"})
    assert fixed["desired.row.001-001.value"] == "`before`"
    with (
        input_context(),
        projection.resource_row_scope(),
        mock_patch.object(projection, "entries", wraps=entries) as parse_rows,
    ):
        first = projection._resource_row_entries(fixed)
        for _ in range(100):
            assert projection._resource_row_entries(fixed) is first
        assert parse_rows.call_count == 1
        with pytest.raises(TypeError):
            first[0][1]["value"] = "contaminated"
        for _ in range(100):
            entries(fixed, "desired.row.")
        assert fixed.scans == 1
        returned = entries(fixed, "desired.row.")
        returned[0][1]["value"] = "contaminated"
        assert entries(fixed, "desired.row.")[0][1]["value"] == "`before`"
        values["desired.row.001-001.value"] = "`after`"
        updated = SnapshotValues(values)
        assert projection._resource_row_entries(updated)[0][1]["value"] == "`after`"
        assert projection._resource_row_entries(fixed)[0][1]["value"] == "`before`"
        assert parse_rows.call_count == 2
        assert entries(values, "desired.row.")[0][1]["value"] == "`after`"
        values["desired.row.001-001.value"] = "`mutated`"
        assert entries(values, "desired.row.")[0][1]["value"] == "`mutated`"
        assert projection._resource_row_entries(values)[0][1]["value"] == "`mutated`"
    with (
        input_context(),
        mock_patch.object(projection, "entries", wraps=entries) as parse_rows,
    ):
        projection._resource_row_entries(fixed)
        assert parse_rows.call_count == 1


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

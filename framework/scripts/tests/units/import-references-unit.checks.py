#!/usr/bin/env python3
"""Exact IMPORT references use synthetic Models and immutable Framework definitions."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from contextlib import closing, contextmanager
from unittest.mock import patch

import design.services.codebuild as _imports_codebuild
import model.sources
import pytest
from design.document import DesignIndex
from design.layout import expanded_display_rows
from design.layout_schema import ALIGNMENT, HEADER
from design.services.definitions.codebuild import CODEBUILD_FORMAL_VARIABLE
from generation_inputs import GenerationInputs
from import_guard import require_import_changes, resource_config
from model.core import entries as entries
from model.core import literal, resource_row_index
from model.display import display_rows
from model.format import serialize
from model.identity import resource_link
from model.importing.approval import build_review
from model.importing.cli import replacement_inputs
from model.importing.references import Resolver
from model.importing.scope import read_consumers, reference_reader, restrict
from model.importing.sources import property_values, verify_values
from model.operations import (
    CandidateReads,
    ConfigurationIndex,
    _observed_index,
    preserve_fixed_fields,
    resource_configuration,
)
from model.projection import identifier_outputs
from model.references import declarations, incoming
from model.render import generate_markdown
from model.sources import Scope, candidate_sources, json_text
from model.sources import load_model as load_for_edit
from support.model_sources import write_model
from support.model_v2_fixtures import value_snapshot as Expansion
from support.producer_identifier_reference_fixtures import reference
from task_contract_core import start
from utils.aws_mappings import owners
from utils.input_cache import input_context
from utils.json_format import document_sha256
from utils.reference_contracts import contract
from utils.source_reads import FileReads
from validation.design_links import check_design_links as _check_design_links
from validation.findings import Findings

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]


@contextmanager
def warned(resolver, match):
    before = len(resolver.warnings)
    yield
    assert any(match in warning["message"] for warning in resolver.warnings[before:]), (
        resolver.warnings[before:]
    )


@pytest.fixture(autouse=True)
def project(tmp_path):
    (tmp_path / "project.json").write_text(
        json_text(
            {
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "cde",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        )
    )


def values(kind, attributes, rid="001", mode="IMPORT", anchor="producer"):
    serial = (
        (int(rid) - 8 if int(rid) >= 9 else int(rid))
        if rid.isdigit()
        else (2 if rid.endswith("-child") else 1)
    )
    result = {
        f"desired.resource.{rid}.resourceType": kind,
        f"desired.resource.{rid}.anchor": anchor,
        f"desired.resource.{rid}.resourceMode": mode,
        f"desired.resource.{rid}.logicalId": kind.replace(".", "_") + f"_{serial:03d}",
        "desired.service.identity.lastAllocated": json.dumps({kind: serial}),
    }
    for n, (prop, raw) in enumerate(attributes.items(), 1):
        prefix = f"desired.row.{rid}-{n:03d}."
        result.update(
            {
                prefix + "property": kind + "." + prop,
                prefix + "value": "`" + raw + "`",
                prefix + "comment": "合成入力",
            }
        )
    return result


def local_snapshot(source, root, service):
    snapshot = Expansion(source, {}, {})
    snapshot.scope = Scope(root, "dev", "cde", service)
    return snapshot


def producer(
    root,
    kind,
    attributes,
    mode="IMPORT",
    env="dev",
    rid="001",
    anchor="producer",
    previous=None,
):
    service = owners(ROOT)[kind]
    path = root / "model" / env / "cde" / (service + ".properties")
    fields = {**(previous or {}), **values(kind, attributes, rid, mode, anchor)}
    for index, raw in enumerate(attributes.values(), 1):
        if resource_link(raw):
            fields[f"desired.row.{rid}-{index:03d}.value"] = raw
    write_model(path, fields)
    return service, path


CASES = [
    (
        "GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName",
        "S3.Bucket",
        {"BucketName": "audit-bucket"},
        "audit-bucket",
    ),
    (
        "CloudTrail.Trail.S3BucketName",
        "S3.Bucket",
        {"BucketName": "audit-bucket"},
        "audit-bucket",
    ),
    (
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN",
        "S3.Bucket",
        {"BucketName": "audit-bucket"},
        "arn:aws:s3:::audit-bucket",
    ),
    ("EC2.SecurityGroup.VpcId", "EC2.VPC", {"VpcId": "vpc-confirmed"}, "vpc-confirmed"),
    (
        "EC2.TransitGatewayVpcAttachment.VpcId",
        "EC2.VPC",
        {"VpcId": "vpc-confirmed"},
        "vpc-confirmed",
    ),
    (
        "CodeBuild.Project.VpcConfig.Subnets[]",
        "EC2.Subnet",
        {"SubnetId": "subnet-confirmed"},
        "subnet-confirmed",
    ),
    (
        "Lambda.Function.VpcConfig.SecurityGroupIds[]",
        "EC2.SecurityGroup",
        {"GroupId": "sg-confirmed"},
        "sg-confirmed",
    ),
    ("Glue.Job.Role", "IAM.Role", {"RoleName": "glue-role"}, "glue-role"),
    (
        "GuardDuty.MalwareProtectionPlan.Role",
        "IAM.Role",
        {"RoleName": "scanner", "Path": "/service-role/"},
        "arn:aws:iam::123456789012:role/service-role/scanner",
    ),
    (
        "KMS.Alias.TargetKeyId",
        "KMS.Key",
        {"KeyId": "12345678-1234-1234-1234-123456789012"},
        "12345678-1234-1234-1234-123456789012",
    ),
    (
        "CloudTrail.Trail.KMSKeyId",
        "KMS.Alias",
        {"AliasName": "alias/audit"},
        "alias/audit",
    ),
]


@pytest.mark.parametrize("prop,kind,attrs,raw", CASES)
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
@pytest.mark.parametrize("present", [False, True])
def check_exact_reference(tmp_path, prop, kind, attrs, raw, mode, present):
    if present:
        service, _ = producer(tmp_path, kind, attrs, mode)
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with (
        input_context(),
        patch(
            "subprocess.run", side_effect=AssertionError("no AWS or other subprocess")
        ),
    ):
        result = resolver.match(prop, raw)
        assert bool(result) == present
        if present:
            assert result["service"] == service and result["id"] == "001"
            resolver.verify(prop, "[target](" + service + ".md#producer)", raw)
            with warned(resolver, "requires a Resource reference"):
                resolver.verify(prop, "`" + raw + "`", raw)
        else:
            resolver.verify(prop, "`" + raw + "`", raw)
            with warned(resolver, "differs from acquired"):
                resolver.verify(prop, "[target](s3.md#producer)", raw)


def check_guardduty_bucket_reference_contract(tmp_path):
    prop = "GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName"
    assert contract(prop) == {"S3.Bucket": ("BucketName",)}
    assert contract("Unknown.Resource.ProtectedResource.S3Bucket.BucketName") == {}
    first = values("S3.Bucket", {"BucketName": "audit-bucket"})
    producer(
        tmp_path,
        "S3.Bucket",
        {"BucketName": "other-bucket"},
        rid="002",
        anchor="other",
        previous=first,
    )
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    source = values(
        "GuardDuty.MalwareProtectionPlan",
        {"ProtectedResource.S3Bucket.BucketName": "unused"},
        rid="009",
    )
    source["desired.row.009-001.value"] = "[target](s3.md#producer)"
    source["observed.row.009-001.value"] = "audit-bucket"
    record = {
        "record": "synthetic",
        "identityProperty": None,
        "identity": "synthetic-plan",
        "properties": {prop: {"status": "captured", "value": "audit-bucket"}},
    }
    before = Expansion({}, {}, {})
    with patch(
        "subprocess.run", side_effect=AssertionError("no AWS or other subprocess")
    ):
        assert verify_values(
            before,
            Expansion(source, {}, {}),
            {"009": record},
            lambda _: {"type": "string"},
            resolver,
        )
        resolver.verify_resource(source, "009", require_links=False, observed_only=True)
        assert not resolver.warnings
        source["desired.row.009-001.value"] = "[target](s3.md#other)"
        with warned(resolver, "differs from acquired physical reference"):
            verify_values(
                before,
                Expansion(source, {}, {}),
                {"009": record},
                lambda _: {"type": "string"},
                resolver,
            )
        source["desired.row.009-001.value"] = "[target](s3.md#producer)"
        source["observed.row.009-001.value"] = "other-bucket"
        with pytest.raises(ValueError, match="differs from the acquired Property"):
            verify_values(
                before,
                Expansion(source, {}, {}),
                {"009": record},
                lambda _: {"type": "string"},
                resolver,
            )
        with pytest.raises(
            ValueError, match="literal differs from acquired physical value"
        ):
            resolver.verify(prop, "`other-bucket`", "audit-bucket")


def check_no_guessed_or_foreign_identity(tmp_path):
    prop = "EC2.SecurityGroup.VpcId"
    producer(tmp_path, "EC2.VPC", {"VpcId": "vpc-confirmed"}, env="stg")
    producer(tmp_path, "EC2.VPC", {"VpcId": "vpc-other", "Name": "vpc-confirmed"})
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    assert resolver.match(prop, "vpc-confirmed") is None
    assert resolver.match("Unregistered.Resource.VpcId", "vpc-other") is None
    assert resolver.match(prop, "UNSET") is None
    assert resolver.match(prop, "PENDING_DEPLOY") is None


def check_ambiguous_and_wrong_explicit_link(tmp_path):
    first = values("EC2.VPC", {"VpcId": "vpc-confirmed"})
    producer(
        tmp_path,
        "EC2.VPC",
        {"VpcId": "vpc-confirmed"},
        rid="002",
        anchor="other",
        previous=first,
    )
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with pytest.raises(ValueError, match="ambiguous physical reference"):
        resolver.match("EC2.SecurityGroup.VpcId", "vpc-confirmed")
    producer(tmp_path, "EC2.VPC", {"VpcId": "vpc-confirmed"})
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with warned(resolver, "differs from acquired"):
        resolver.verify(
            "EC2.SecurityGroup.VpcId", "[target](vpc.md#other)", "vpc-confirmed"
        )
    with warned(resolver, "differs from acquired"):
        resolver.verify(
            "EC2.SecurityGroup.VpcId",
            "[target](../other/vpc.md#producer)",
            "vpc-confirmed",
        )


def check_publication_mixed_array_and_physical_value(tmp_path):
    service, _ = producer(tmp_path, "EC2.Subnet", {"SubnetId": "subnet-confirmed"})
    prop = "CodeBuild.Project.VpcConfig.Subnets[]"
    raw = json.dumps(["[target](" + service + ".md#producer)", "subnet-external"])
    new = values(
        "CodeBuild.Project", {"VpcConfig.Subnets[]": raw}, rid="009", anchor="consumer"
    )
    new["desired.row.009-001.valueShape"] = "projection"
    new["observed.row.009-001.value"] = '["subnet-confirmed","subnet-external"]'
    after, before = Expansion(new, {}, {}), Expansion({}, {}, {})
    record = {
        "record": "synthetic",
        "identityProperty": None,
        "identity": "synthetic-project",
        "properties": {
            prop: {
                "status": "captured",
                "value": ["subnet-confirmed", "subnet-external"],
            }
        },
    }
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    assert verify_values(
        before, after, {"009": record}, lambda _: {"type": "string"}, resolver
    )
    wrong = {
        **new,
        "observed.row.009-001.value": '["subnet-external","subnet-external"]',
    }
    with pytest.raises(ValueError, match="differs from the acquired Property"):
        verify_values(
            before,
            Expansion(wrong, {}, {}),
            {"009": record},
            lambda _: {"type": "string"},
            resolver,
        )
    assert (
        property_values(new, "009", prop, {"type": "string"})
        == record["properties"][prop]["value"]
    )


def check_observed_and_reused_index(tmp_path):
    observed = values("EC2.VPC", {"VpcId": "PENDING_DEPLOY"})
    observed["desired.row.001-001.value"] = "[target](vpc.md#producer)"
    observed["observed.row.001-001.value"] = "vpc-confirmed"
    write_model(tmp_path / "model/dev/cde/vpc.properties", observed)
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with (
        input_context(),
        patch.object(
            model.sources, "_read_model", wraps=model.sources._read_model
        ) as read,
    ):
        for _ in range(20):
            assert resolver.match("EC2.SecurityGroup.VpcId", "vpc-confirmed")
        assert read.call_count == 1
        assert resolver.metrics["referenceModelReads"] == 1
    assert resolver.match("EC2.SecurityGroup.VpcId", "PENDING_DEPLOY") is None


@pytest.mark.parametrize("physical", ["PENDING_DEPLOY", "vpc-confirmed", "UNSET"])
@pytest.mark.parametrize("local", [None, "vpc", "ec2"])
def check_pending_explicit_reference_after_destroy(tmp_path, physical, local):
    source = values("EC2.VPC", {"VpcId": physical})
    source["desired.row.001-001.value"] = "[target](vpc.md#producer)"
    source["observed.row.001-001.value"] = physical
    write_model(tmp_path / "model/dev/cde/vpc.properties", source)
    resolver = Resolver(
        tmp_path,
        "dev",
        "cde",
        definitions_root=ROOT,
        local={local: local_snapshot(source, tmp_path, local)} if local else None,
    )
    prop = "EC2.Subnet.VpcId"
    reference = "[target](" + (local or "vpc") + ".md#producer)"
    assert resolver.match(prop, "PENDING_DEPLOY") is None
    if physical == "PENDING_DEPLOY":
        resolver.verify(prop, reference, "PENDING_DEPLOY", require_links=False)
    else:
        with warned(resolver, "differs from acquired"):
            resolver.verify(prop, reference, "PENDING_DEPLOY", require_links=False)
    for wrong in (
        "[target](vpc.md#missing)",
        "[target](../other/vpc.md#producer)",
        "[target](subnet.md#producer)",
    ):
        with warned(resolver, "differs from acquired"):
            resolver.verify(prop, wrong, "PENDING_DEPLOY", require_links=False)
    with warned(resolver, "differs from acquired"):
        resolver.verify(prop, reference, "PENDING_DEPLOY")
    with warned(resolver, "differs from acquired"):
        resolver.verify(
            "Unknown.Resource.Value",
            reference,
            "PENDING_DEPLOY",
            contracts={},
            require_links=False,
        )


def check_append_only_and_later_import(tmp_path):
    _ = "CloudTrail.Trail.S3BucketName"
    old = values("CloudTrail.Trail", {"S3BucketName": "audit-bucket"})
    expansion = Expansion(old, {}, {})
    producer(tmp_path, "S3.Bucket", {"BucketName": "audit-bucket"})
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    assert (
        verify_values(expansion, expansion, {}, lambda _: {"type": "string"}, resolver)
        == []
    )
    changed = {**old, "desired.row.001-001.value": "[target](s3.md#producer)"}
    warnings = []
    with pytest.raises(ValueError, match="unselected Resource"):
        verify_values(
            expansion,
            Expansion(changed, {}, {}),
            {},
            lambda _: {"type": "string"},
            resolver,
            warnings=warnings,
        )
    assert old["desired.row.001-001.value"] == "`audit-bucket`"


def check_selected_new_import_can_resolve_only_its_declared_producer(tmp_path):
    _, producer_path = producer(
        tmp_path,
        "EC2.Subnet",
        {"SubnetId": "subnet-confirmed", "Name": "private-subnet"},
    )
    producer_before = producer_path.read_bytes()
    path = tmp_path / "model/dev/cde/codebuild.properties"
    write_model(path, {"desired.service.codebuild.serviceId": "codebuild"})
    before = load_for_edit(path)
    fields = {
        **before.authoritative,
        **values(
            "CodeBuild.Project",
            {"VpcConfig.Subnets": "unused"},
            rid="009",
            anchor="codebuild-new",
        ),
    }
    fields["desired.row.009-001.value"] = "[target](vpc.md#producer)"
    fields["observed.row.009-001.value"] = "subnet-confirmed"
    with (
        restrict(("dev", "cde", "codebuild")),
        read_consumers({("dev", "cde", "codebuild")}),
    ):
        candidate = load_for_edit(
            path, CandidateReads(FileReads(), {path: serialize(fields)})
        )
        assert (
            candidate.authoritative["desired.row.009-001.value"]
            == "[target](vpc.md#producer)"
        )
        assert producer_path in candidate.dependencies
        with pytest.raises(ValueError, match="outside selected"):
            load_for_edit(producer_path)
        external = dict(fields)
        external["desired.row.009-001.value"] = "subnet-external"
        del external["observed.row.009-001.value"]
        assert (
            load_for_edit(
                path, CandidateReads(FileReads(), {path: serialize(external)})
            ).authoritative["desired.row.009-001.value"]
            == "subnet-external"
        )
        directory = tmp_path.parent / (tmp_path.name + "-candidate")
        own = directory / path.relative_to(tmp_path)
        own.parent.mkdir(parents=True)
        own.write_text(serialize(fields), encoding="utf-8")
        (directory / producer_path.relative_to(tmp_path)).write_bytes(producer_before)
        with pytest.raises(ValueError, match="outside the selected service"):
            candidate_sources(tmp_path, directory, before)
    assert producer_path.read_bytes() == producer_before


@pytest.mark.parametrize(
    "prop,kind,attrs,raw,context",
    [
        (
            "CloudTrail.Trail.KMSKeyId",
            "KMS.Key",
            {"KeyId": "12345678-1234-1234-1234-123456789012"},
            "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
            {},
        ),
        (
            "CloudTrail.Trail.KMSKeyId",
            "KMS.Alias",
            {"AliasName": "alias/audit"},
            "arn:aws:kms:ap-northeast-1:123456789012:alias/audit",
            {},
        ),
        (
            "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
            "SecretsManager.Secret",
            {"Name": "audit-secret"},
            "audit-secret:password:AWSCURRENT:",
            {
                "CodeBuild.Project.Environment.EnvironmentVariables[].Type": "SECRETS_MANAGER"
            },
        ),
        (
            "CloudTrail.Trail.EventSelectors[].DataResources[].Values",
            "S3.Bucket",
            {"BucketName": "audit-bucket"},
            "arn:aws:s3:::audit-bucket/prefix/",
            {
                "CloudTrail.Trail.EventSelectors[].DataResources[].Type": "AWS::S3::Object"
            },
        ),
    ],
)
def check_declared_identifier_forms(tmp_path, prop, kind, attrs, raw, context):
    producer(tmp_path, kind, attrs)
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    assert resolver.match(prop, raw, context)
    assert (
        resolver.match(prop, raw.replace("123456789012:", "999999999999:"), context)
        is None
        if "123456789012:" in raw
        else True
    )
    assert (
        resolver.match(prop, raw.replace("arn:aws:", "arn:aws-cn:"), context) is None
        if raw.startswith("arn:aws:")
        else True
    )


def check_import_compact_display_and_create_guards():
    CODEBUILD_FORMAL_VARIABLE = _imports_codebuild.CODEBUILD_FORMAL_VARIABLE
    codebuild_display_row = _imports_codebuild.codebuild_display_row
    codebuild_formal_rows = _imports_codebuild.codebuild_formal_rows
    prop = "CodeBuild.Project.VpcConfig.Subnets"
    raw = '`["[private](vpc.md#resource-EC2_Subnet_001)","subnet-external"]`'
    rows = [["001-001", prop, raw, "合成入力"]]
    rendered = display_rows("CodeBuild.Project", rows, ROOT, mode="IMPORT")
    assert [r[2] for r in rendered] == [
        "[private](vpc.md#resource-EC2_Subnet_001)",
        "`subnet-external`",
    ]
    lines = [
        '<a id="codebuild-new"></a>',
        "### CodeBuild.Project: audit",
        HEADER,
        ALIGNMENT,
    ]
    lines += [
        "| " + " | ".join([str(i), *row[1:]]) + " |"
        for i, row in enumerate(rendered, 1)
    ]
    restored = expanded_display_rows(lines, ROOT, modes={"codebuild-new": "IMPORT"})
    assert any(raw in line for line in restored)
    with pytest.raises(ValueError, match="must be a resource link"):
        display_rows("CodeBuild.Project", rows, ROOT)
    variables = [
        [
            "001-" + str(n),
            CODEBUILD_FORMAL_VARIABLE + key,
            "`" + value + "`",
            "合成入力",
        ]
        for n, (key, value) in enumerate(
            [
                ("Name", "SECRET"),
                ("Type", "SECRETS_MANAGER"),
                ("Value", "audit-secret:key"),
            ]
        )
    ]
    compact = codebuild_display_row(variables, 0, "合成入力", mode="IMPORT")
    assert "SECRETS_MANAGER" in compact[3]
    assert (
        codebuild_formal_rows(compact, set(), mode="IMPORT")[1][2]
        == "`SECRETS_MANAGER`"
    )
    with pytest.raises(ValueError, match="require a resource link"):
        codebuild_display_row(variables, 0, "合成入力")


@pytest.mark.parametrize(
    "kind,name,prop,desired,observed",
    [
        (
            "KinesisFirehose.DeliveryStream",
            "DeliveryStreamName",
            "S3DestinationConfiguration.BucketARN",
            "[target](s3.md#producer)",
            "`arn:aws:s3:::audit-bucket`",
        ),
        (
            "CloudTrail.Trail",
            "TrailName",
            "S3BucketName",
            "[target](s3.md#producer)",
            "`audit-bucket`",
        ),
        (
            "CodeBuild.Project",
            "Name",
            "VpcConfig.Subnets",
            '`["subnet-confirmed","subnet-external"]`',
            '["subnet-confirmed","subnet-external"]',
        ),
    ],
)
def check_markdown_roundtrip_keeps_physical_values(
    tmp_path, kind, name, prop, desired, observed
):
    service = owners(ROOT)[kind]
    source = values(
        kind, {name: "audit", prop: "unused"}, rid="009", anchor=service + "-audit"
    )
    source.update(
        {
            "desired.service." + service + ".serviceId": service,
            "desired.service." + service + ".ownedCatalogResourceTypes": kind,
            "display.service.title": "# 合成詳細設計",
            "display.resource.009.comment": "合成設定",
            "desired.row.009-002.value": desired,
            "observed.row.009-002.value": observed,
        }
    )
    if kind == "CodeBuild.Project":
        del source["observed.row.009-002.value"]
    path = tmp_path / "docs/designs/dev/cde" / (service + ".md")
    path.parent.mkdir(parents=True)
    first = generate_markdown(path, source, ROOT)
    path.write_text(first)
    normalized = expanded_display_rows(
        first.splitlines(), ROOT, modes={service + "-audit": "IMPORT"}
    )
    if resource_link(desired):
        expected = "[" + literal(observed) + "](s3.md#producer)"
    else:
        expected = "subnet-confirmed"
    assert any(expected in line for line in normalized), normalized
    assert source["desired.row.009-002.value"] == desired
    if kind != "CodeBuild.Project":
        assert source["observed.row.009-002.value"] == observed
    assert path.read_text() == first


def check_mixed_literals_cannot_hide_behind_observations(tmp_path):
    producer(tmp_path, "EC2.Subnet", {"SubnetId": "subnet-confirmed"})
    source = values("CodeBuild.Project", {"VpcConfig.Subnets": "unused"}, rid="009")
    source["desired.row.009-001.value"] = (
        '`["[target](vpc.md#producer)","subnet-wrong"]`'
    )
    source["observed.row.009-001.value"] = '["subnet-confirmed","subnet-external"]'
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with pytest.raises(ValueError, match="literal differs"):
        resolver.verify_resource(source, "009")


@pytest.mark.parametrize(
    "prop", ["Lambda.Function.Role", "GuardDuty.MalwareProtectionPlan.Role"]
)
def check_role_arn_requires_account_and_explicit_path(tmp_path, prop):
    producer(tmp_path, "IAM.Role", {"RoleName": "runner", "Path": "/service-role/"})
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    assert resolver.match(prop, "arn:aws:iam::123456789012:role/service-role/runner")
    assert resolver.match(prop, "arn:aws:iam::123456789012:role/runner") is None
    assert (
        resolver.match(prop, "arn:aws:iam::999999999999:role/service-role/runner")
        is None
    )
    assert (
        resolver.match(prop, "arn:aws-cn:iam::123456789012:role/service-role/runner")
        is None
    )
    assert resolver.match(prop, "runner") is None


def check_guardduty_role_acquired_value_consistency(tmp_path):
    prop = "GuardDuty.MalwareProtectionPlan.Role"
    assert contract(prop) == {"IAM.Role": ("Arn",)}
    assert contract("Unknown.Resource.Role") == {}
    service, _ = producer(
        tmp_path, "IAM.Role", {"RoleName": "scanner", "Path": "/service-role/"}
    )
    physical = "arn:aws:iam::123456789012:role/service-role/scanner"
    source = values("GuardDuty.MalwareProtectionPlan", {"Role": "unused"}, rid="002")
    source["desired.resource.002.logicalId"] = "GuardDuty_MalwareProtectionPlan_001"
    source["desired.service.identity.lastAllocated"] = json.dumps(
        {"GuardDuty.MalwareProtectionPlan": 1}
    )
    source["desired.row.002-001.value"] = "[target](" + service + ".md#producer)"
    source["observed.row.002-001.value"] = physical
    record = {
        "record": "synthetic",
        "identityProperty": None,
        "identity": "synthetic-plan",
        "properties": {prop: {"status": "captured", "value": physical}},
    }
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    before = Expansion({}, {}, {})
    with patch(
        "subprocess.run", side_effect=AssertionError("no AWS or other subprocess")
    ):
        assert verify_values(
            before,
            Expansion(source, {}, {}),
            {"002": record},
            lambda _: {"type": "string"},
            resolver,
        )
        resolver.verify_resource(source, "002", require_links=False, observed_only=True)
        assert not resolver.warnings
        wrong = {**source, "desired.row.002-001.value": "[target](s3.md#producer)"}
        with warned(resolver, "differs from acquired physical reference"):
            verify_values(
                before,
                Expansion(wrong, {}, {}),
                {"002": record},
                lambda _: {"type": "string"},
                resolver,
            )
        wrong = {
            **source,
            "observed.row.002-001.value": "arn:aws:iam::123456789012:role/other",
        }
        with pytest.raises(ValueError, match="differs from the acquired Property"):
            verify_values(
                before,
                Expansion(wrong, {}, {}),
                {"002": record},
                lambda _: {"type": "string"},
                resolver,
            )
        with warned(resolver, "differs from acquired physical reference"):
            resolver.verify_resource(
                wrong, "002", require_links=False, observed_only=True
            )


def check_import_reference_observation_sync_remains_guarded(tmp_path):
    producer(tmp_path, "EC2.VPC", {"VpcId": "vpc-confirmed"})
    source = values("EC2.TransitGatewayVpcAttachment", {"VpcId": "unused"})
    source["desired.row.001-001.value"] = "[target](vpc.md#producer)"
    source["observed.row.001-001.value"] = "PENDING_DEPLOY"
    updated = {**source, "observed.row.001-001.value": "vpc-confirmed"}
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with warned(resolver, "differs from acquired physical reference"):
        resolver.verify_resource(source, "001", require_links=False, observed_only=True)
    resolver.warnings.clear()
    resolver.verify_resource(updated, "001", require_links=False, observed_only=True)
    assert not resolver.warnings
    old, new = resource_config(source, "001"), resource_config(updated, "001")
    assert old["rows"] == new["rows"] and old["resource"] == new["resource"]
    assert document_sha256(old) != document_sha256(new)
    (tmp_path / ".git").mkdir()
    start(
        tmp_path,
        "tasks/sync.md",
        "## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
        "## Validation scope\n- `framework`\n## Required changes\n- [R1] Synthetic sync guard\n"
        "## Acceptance checks\n- [R1] `exists:tasks/sync.md`\n## Modified files\n- `tasks/sync.md`\n"
        "## Allowed paths\n- `tasks/sync.md`\n",
    )
    with pytest.raises(ValueError, match="outside Modified files/Allowed paths"):
        require_import_changes(
            tmp_path, supplied={"model/dev/cde/transit-gateway.properties"}
        )


@pytest.mark.parametrize("wrong", [False, True])
@pytest.mark.parametrize("observed", [False, True])
def check_design_link_validation_uses_physical_identity(tmp_path, wrong, observed):
    source = values(
        "KinesisFirehose.DeliveryStream",
        {
            "DeliveryStreamName": "audit",
            "S3DestinationConfiguration.BucketARN": "unused",
        },
        rid="009",
        anchor="data-firehose-audit",
    )
    source.update(
        {
            "desired.service.data-firehose.serviceId": "data-firehose",
            "desired.service.data-firehose.ownedCatalogResourceTypes": "KinesisFirehose.DeliveryStream",
            "display.service.title": "# Firehose",
            "display.resource.009.comment": "合成入力",
            "desired.row.009-002.value": "[target](s3.md#producer)",
            "observed.row.009-002.value": "`arn:aws:s3:::audit-bucket`",
        }
    )
    if not observed:
        del source["observed.row.009-002.value"]
    bucket = values(
        "S3.Bucket", {"BucketName": "other-bucket" if wrong else "audit-bucket"}
    )
    bucket.update(
        {
            "desired.service.s3.serviceId": "s3",
            "desired.service.s3.ownedCatalogResourceTypes": "S3.Bucket",
            "display.service.title": "# S3",
            "display.resource.001.comment": "合成入力",
        }
    )
    write_model(tmp_path / "model/dev/cde/s3.properties", bucket)
    write_model(tmp_path / "model/dev/cde/data-firehose.properties", source)
    document = tmp_path / "docs/designs/dev/cde/data-firehose.md"
    document.parent.mkdir(parents=True)
    document.write_text(generate_markdown(document, source, ROOT))
    (document.parent / "s3.md").write_text(
        generate_markdown(document.parent / "s3.md", bucket, ROOT)
    )
    findings = Findings(tmp_path)
    _check_design_links(
        identifier_outputs(ROOT),
        [document],
        design_index=DesignIndex(ROOT),
        design_sources={document: source},
        findings=findings,
        root=tmp_path,
        scope=None,
        definitions_root=ROOT,
    )
    physical_warnings = [
        warning
        for warning in findings.warnings
        if "physical reference" in warning["message"]
    ]
    assert bool(physical_warnings) == (wrong and observed), findings.warnings
    assert not findings.errors


def check_unknown_link_like_aws_data_is_not_inferred(tmp_path):
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    raw = "[a literal AWS string](foreign.md#something)"
    resolver.verify("Custom.Resource.Configuration.Text", raw, raw)
    assert resolver.metrics["referenceModelReads"] == 0
    with pytest.raises(ValueError, match="literal differs"):
        resolver.verify("Custom.Resource.Configuration.Text", raw, "actual-id")


def check_packed_variable_roundtrip_and_tamper():
    rows = [
        [
            "009-" + str(i),
            CODEBUILD_FORMAL_VARIABLE + prop,
            "`" + json.dumps(value) + "`",
            "合成変数",
        ]
        for i, (prop, value) in enumerate(
            [
                ("Name", ["SECRET", "PLAIN"]),
                ("Type", ["SECRETS_MANAGER", "PLAINTEXT"]),
                ("Value", ["audit-secret:key", "text"]),
            ]
        )
    ]
    rendered = display_rows("CodeBuild.Project", rows, ROOT, mode="IMPORT")
    assert (
        "<!-- compact-source:" in rendered[0][3] and "SECRETS_MANAGER" in rendered[0][3]
    )
    lines = [
        '<a id="codebuild-audit"></a>',
        "### CodeBuild.Project: audit",
        HEADER,
        ALIGNMENT,
    ]
    lines += [
        "| " + " | ".join([str(i), *row[1:]]) + " |"
        for i, row in enumerate(rendered, 1)
    ]
    restored = expanded_display_rows(lines, ROOT, modes={"codebuild-audit": "IMPORT"})
    assert all(any(row[2] in line for line in restored) for row in rows)
    changed = [
        line.replace("`audit-secret:key`", "`wrong-secret`")
        if line.startswith("| 1 |")
        else line
        for line in lines
    ]
    with pytest.raises(ValueError, match="differs from source"):
        expanded_display_rows(changed, ROOT, modes={"codebuild-audit": "IMPORT"})
    with pytest.raises(ValueError, match="requires IMPORT"):
        expanded_display_rows(lines, ROOT)


def check_packed_pipeline_configuration_roundtrip(tmp_path):
    kind = "CodePipeline.Pipeline"
    producer(tmp_path, "CodeBuild.Project", {"Name": "audit-build"})
    config = [[{"ProjectName": "audit-build", "EnvironmentVariables": "literal-json"}]]
    actual = [[{"ProjectName": "audit-build", "EnvironmentVariables": "literal-json"}]]
    attrs = {
        "Name": "pipeline-audit",
        "Stages[].Actions[].ActionTypeId.Provider": json.dumps([["CodeBuild"]]),
        "Stages[].Actions[].Configuration": json.dumps(config),
        "Stages[].Actions[].Name": json.dumps([["Build"]]),
        "Stages[].Name": json.dumps(["Build"]),
    }
    source = values(kind, attrs, rid="009", anchor="codepipeline-audit")
    source.update(
        {
            "desired.service.codepipeline.serviceId": "codepipeline",
            "desired.service.codepipeline.ownedCatalogResourceTypes": kind,
            "display.service.title": "# Pipeline",
            "display.resource.009.comment": "合成Pipeline",
            "observed.row.009-003.value": json.dumps(actual),
            "desired.row.009-003.comment": "ProjectName: 合成Build / EnvironmentVariables: 合成変数",
        }
    )
    source.update(
        reference(
            "build",
            "desired.row.009-003.value",
            "audit-build",
            "codebuild",
            "001",
            "CodeBuild.Project",
            mode="name",
            prop="CodeBuild.Project.Name",
            pointer="/0/0/ProjectName",
            environment="dev",
        )
    )
    # This fixture uses cde rather than the shared helper's team alias.
    source["desired.reference.build.producerScope"] = "dev/cde/codebuild"
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    resolver.verify_resource(source, "009")
    assert not resolver.warnings, resolver.warnings
    assert "CodeBuild.Project" not in resolver.indexes
    changed_acquired = [[{**actual[0][0], "ProjectName": "different-build"}]]
    with pytest.raises(ValueError, match="literal differs"):
        resolver.verify_resource(
            {**source, "observed.row.009-003.value": json.dumps(changed_acquired)},
            "009",
        )
    del source["observed.row.009-003.value"]
    path = tmp_path / "docs/designs/dev/cde/codepipeline.md"
    path.parent.mkdir(parents=True)
    first = generate_markdown(path, source, ROOT)
    path.write_text(first)
    assert (
        "audit-build" in first and "[audit-build](codebuild.md#producer)" not in first
    )
    projections = []
    assert generate_markdown(path, source, ROOT, reference_tables=projections) == first
    normalized = expanded_display_rows(
        first.splitlines(),
        ROOT,
        modes={"codepipeline-audit": "IMPORT"},
        reference_tables=projections,
    )
    assert any("literal-json" in line and "audit-build" in line for line in normalized)
    assert json.loads(source["desired.row.009-003.value"].strip("`")) == actual
    assert path.read_text() == first
    wrong = json.loads(json.dumps(config))
    wrong[0][0]["EnvironmentVariables"] = "wrong"
    source["desired.row.009-003.value"] = "`" + json.dumps(wrong) + "`"
    with pytest.raises(ValueError, match="literal differs"):
        resolver.verify_resource(
            {**source, "observed.row.009-003.value": json.dumps(actual)}, "009"
        )


def check_native_cloudtrail_all_bucket_display():
    prefix = "CloudTrail.Trail.EventSelectors[].DataResources[]."
    rows = [
        ["009-001", prefix + "Type", '`[["AWS::S3::Object"]]`', "合成対象"],
        ["009-002", prefix + "Values", '`[[["arn:aws:s3"]]]`', "合成対象"],
    ]
    rendered = display_rows("CloudTrail.Trail", rows, ROOT, mode="IMPORT")
    assert rendered[0][2] == "`All current and future S3 buckets`"
    lines = [
        '<a id="cloudtrail-audit"></a>',
        "### CloudTrail.Trail: audit",
        HEADER,
        ALIGNMENT,
    ]
    lines += [
        "| " + " | ".join([str(i), *row[1:]]) + " |"
        for i, row in enumerate(rendered, 1)
    ]
    restored = expanded_display_rows(lines, ROOT, modes={"cloudtrail-audit": "IMPORT"})
    assert any(rows[1][2] in line for line in restored)


def check_native_array_literals_cannot_evade_matching_model(tmp_path):
    producer(tmp_path, "S3.Bucket", {"BucketName": "audit-bucket"})
    source = values(
        "CloudTrail.Trail",
        {
            "EventSelectors[].DataResources[].Type": '[["AWS::S3::Object"]]',
            "EventSelectors[].DataResources[].Values": '[[["arn:aws:s3:::audit-bucket/"]]]',
        },
        rid="009",
    )
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    with warned(resolver, "requires a Resource reference"):
        resolver.verify_resource(source, "009")
    # Old literals remain untouched when a producer is imported later.
    resolver.verify_resource(source, "009", require_links=False)


@pytest.mark.parametrize(
    "reference",
    [
        "[target](cloudwatch-logs.md#producer)",
        "[target](cloudwatch-logs.md#missing)",
        "[target](s3.md#producer)",
        "[target](missing.md#producer)",
        "[target](../other/cloudwatch-logs.md#producer)",
    ],
)
def check_unobserved_link_requires_typed_target(tmp_path, reference):
    # A producer's logical identity is sufficient even without any physical identifier.
    producer(
        tmp_path,
        "Logs.LogGroup",
        {"LogGroupName": "[target](cloudwatch-logs.md#producer)"},
    )
    producer(tmp_path, "S3.Bucket", {"BucketName": "audit-bucket"})
    source = values(
        "CloudTrail.Trail", {"CloudWatchLogsLogGroupArn": "unused"}, rid="009"
    )
    source["desired.row.009-001.value"] = reference
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    if reference == "[target](cloudwatch-logs.md#producer)":
        with patch.object(
            resolver,
            "match",
            side_effect=AssertionError("unobserved physical comparison"),
        ):
            resolver.verify_resource(
                source, "009", require_links=False, observed_only=True
            )
    else:
        with warned(resolver, "no unique producer"):
            resolver.verify_resource(
                source, "009", require_links=False, observed_only=True
            )
    source["desired.row.009-001.property"] = "CloudTrail.Trail.Unknown"
    with warned(resolver, "no unique producer"):
        resolver.verify_resource(source, "009", require_links=False, observed_only=True)


@pytest.mark.parametrize("shape", ["scalar", "array", "document", "configuration"])
def check_unobserved_structured_links_and_strict_import(tmp_path, shape):
    if shape == "scalar":
        producer(tmp_path, "Logs.LogGroup", {"LogGroupName": "audit"})
        source = values(
            "CloudTrail.Trail", {"CloudWatchLogsLogGroupArn": "unused"}, rid="009"
        )
        source["desired.row.009-001.value"] = "[target](cloudwatch-logs.md#producer)"
    elif shape in {"array", "document"}:
        producer(tmp_path, "EC2.Subnet", {"SubnetId": "subnet-confirmed"})
        raw = ["[target](vpc.md#producer)", "subnet-external"]
        prop = "VpcConfig.Subnets" if shape == "array" else "VpcConfig"
        source = values(
            "CodeBuild.Project",
            {prop: json.dumps(raw if shape == "array" else {"Subnets": raw})},
            rid="009",
        )
        if shape == "document":
            source["desired.row.009-001.document"] = json.dumps({"Subnets": raw})
    else:
        producer(tmp_path, "CodeBuild.Project", {"Name": "audit-build"})
        source = values(
            "CodePipeline.Pipeline",
            {
                "Stages[].Actions[].ActionTypeId.Provider": '[["CodeBuild"]]',
                "Stages[].Actions[].Configuration": '[[{"ProjectName":"[audit-build](codebuild.md#producer)"}]]',
            },
            rid="009",
        )
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    snapshot = dict(source)
    resolver.verify_resource(source, "009", require_links=False, observed_only=True)
    assert source == snapshot
    invalid = {
        key: value.replace("#producer)", "#missing)") for key, value in source.items()
    }
    with warned(resolver, "no unique producer"):
        resolver.verify_resource(
            invalid, "009", require_links=False, observed_only=True
        )
    for require_links in (True, False):
        with warned(resolver, "differs from acquired physical reference"):
            resolver.verify_resource(source, "009", require_links=require_links)
    record = {
        "record": "synthetic",
        "identityProperty": None,
        "identity": "synthetic",
        "properties": {},
    }
    with pytest.raises(ValueError, match="unacquired Property"):
        verify_values(
            Expansion({}, {}, {}),
            Expansion(source, {}, {}),
            {"009": record},
            lambda _: {"type": "string"},
            resolver,
        )
    for key in list(source):
        if (
            key.startswith("desired.row.")
            and key.endswith(".value")
            and any(token in source[key] for token in ("[target](", "[audit-build]("))
        ):
            source["observed." + key.removeprefix("desired.")] = "null"
    if shape == "scalar":
        with warned(resolver, "differs from acquired"):
            resolver.verify_resource(
                source, "009", require_links=False, observed_only=True
            )
    else:
        with pytest.raises(
            ValueError, match="structure differs|Configuration array dimensions differ"
        ):
            resolver.verify_resource(
                source, "009", require_links=False, observed_only=True
            )


@pytest.mark.parametrize("physical", ["audit-bucket", "wrong-bucket"])
def check_observed_comparison_in_design_and_import(tmp_path, physical):
    producer(tmp_path, "S3.Bucket", {"BucketName": "audit-bucket"})
    source = values("CloudTrail.Trail", {"S3BucketName": "unused"}, rid="009")
    source["desired.row.009-001.value"] = "[target](s3.md#producer)"
    source["observed.row.009-001.value"] = physical
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    for kwargs in (
        {},
        {"require_links": False},
        {"require_links": False, "observed_only": True},
    ):
        if physical == "audit-bucket":
            resolver.verify_resource(source, "009", **kwargs)
        else:
            with warned(resolver, "differs from acquired physical reference"):
                resolver.verify_resource(source, "009", **kwargs)


def check_unobserved_local_and_identity_self_links(tmp_path):
    source = values("EC2.VPC", {"VpcId": "unused"})
    source["desired.row.001-001.value"] = "[target](vpc.md#producer)"
    source.update(
        values("EC2.Subnet", {"VpcId": "unused"}, rid="009", anchor="consumer")
    )
    source["desired.service.identity.lastAllocated"] = json.dumps(
        {"EC2.VPC": 1, "EC2.Subnet": 1}
    )
    source["desired.row.009-001.value"] = "[target](vpc.md#producer)"
    resolver = Resolver(
        tmp_path,
        "dev",
        "cde",
        definitions_root=ROOT,
        local={"vpc": local_snapshot(source, tmp_path, "vpc")},
    )
    resolver.verify_resource(source, "001", require_links=False, observed_only=True)
    resolver.verify_resource(source, "009", require_links=False, observed_only=True)
    source["desired.row.009-001.value"] = "[target](vpc.md#missing)"
    with warned(resolver, "no unique producer"):
        resolver.verify_resource(source, "009", require_links=False, observed_only=True)


@pytest.mark.parametrize("physical", ["PENDING_DEPLOY", "vpc-confirmed", "UNSET"])
def check_design_pending_observation_retains_target_guard(tmp_path, physical):
    producer(tmp_path, "EC2.VPC", {"VpcId": physical})
    source = values("EC2.Subnet", {"VpcId": "unused"}, rid="009")
    source["desired.row.009-001.value"] = "[target](vpc.md#producer)"
    source["observed.row.009-001.value"] = "PENDING_DEPLOY"
    resolver = Resolver(tmp_path, "dev", "cde", definitions_root=ROOT)
    if physical == "PENDING_DEPLOY":
        resolver.verify_resource(source, "009", require_links=False, observed_only=True)
    else:
        with warned(resolver, "differs from acquired physical reference"):
            resolver.verify_resource(
                source, "009", require_links=False, observed_only=True
            )
    with warned(resolver, "differs from acquired physical reference"):
        resolver.verify_resource(source, "009")


def impact_fixture(root):
    producer(
        root, "EC2.Subnet", {"SubnetId": "subnet-confirmed", "Name": "private-subnet"}
    )
    path = root / "model/dev/cde/codebuild.properties"
    source = values(
        "CodeBuild.Project", {"VpcConfig.Subnets": "unused"}, rid="009", anchor="build"
    )
    source.update(
        values("CodeBuild.Project", {"Name": "sibling"}, rid="010", anchor="sibling")
    )
    source["desired.row.009-001.value"] = "[target](vpc.md#producer)"
    source["observed.row.009-001.value"] = "subnet-confirmed"
    source["desired.row.010-001.value"] = "[audit-build](codebuild.md#build)"
    for key, value in {
        "consumerKey": "desired.row.009-001.value",
        "text": source["desired.row.009-001.value"],
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "dev/cde/vpc",
        "producerLogicalId": "EC2_Subnet_001",
        "resourceType": "EC2.Subnet",
        "format": "link",
        "labelPolicy": "fixed",
    }.items():
        source["desired.reference.subnet." + key] = value
    write_model(path, source)
    consumer = values(
        "CodePipeline.Pipeline", {"RoleArn": "unused"}, rid="003", anchor="pipeline"
    )
    consumer["desired.row.003-001.value"] = "[audit-build](codebuild.md#build)"
    write_model(root / "model/dev/cde/codepipeline.properties", consumer)
    dependency_index.rebuild(root)
    return path


@pytest.mark.parametrize("action", ["bind", "replace"])
def check_saved_import_impact_analysis(tmp_path, action):
    path = impact_fixture(tmp_path)
    snapshot = {
        p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()
    }
    with (
        input_context(),
        restrict(("dev", "cde", "codebuild")),
        read_consumers({("dev", "cde", "codebuild")}),
    ):
        with closing(GenerationInputs(tmp_path)) as reads:
            before = load_for_edit(path, reads)
            impact = replacement_inputs(before, {"009": {"_action": action}}, reads)
            assert impact["inputs"] and impact["fileSets"]
            impacts = [
                w for w in impact["warnings"] if w["code"] == "reference.replace_impact"
            ]
            assert any(w["consumer"] == "dev/cde/codebuild/010" for w in impacts)
            assert any(
                w["consumer"] == "dev/cde/codepipeline/003"
                and w["producer"] == "dev/cde/codebuild/009"
                and w["consumer_key"] == "desired.row.003-001.value"
                for w in impacts
            )
            assert load_for_edit(path, reads) is before
    assert snapshot == {
        p: p.read_bytes() for p in (tmp_path / "model").rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("permission_first", [False, True])
def check_preserved_analysis_cache_boundary(tmp_path, permission_first):
    path = impact_fixture(tmp_path)
    producer_path = path.with_name("vpc.properties")
    with (
        input_context(read_only=True),
        restrict(("dev", "cde", "codebuild")),
        read_consumers({("dev", "cde", "codebuild")}),
    ):
        before = load_for_edit(path)
        if not permission_first:
            with pytest.raises(ValueError, match="outside selected"):
                load_for_edit(producer_path)
        with reference_reader(producer_path):
            first = load_for_edit(producer_path)
            assert not first.warnings
            assert load_for_edit(producer_path) is first
        assert load_for_edit(path) is before
        assert (
            before.authoritative["desired.row.009-001.value"]
            == "[target](vpc.md#producer)"
        )
        with pytest.raises(ValueError, match="outside selected"):
            load_for_edit(producer_path)


@pytest.mark.parametrize("invalid", ["999", "bad-id", "wrong-type", "undeclared"])
def check_impact_keeps_invalid_reference_diagnostics(tmp_path, invalid):
    path = impact_fixture(tmp_path)
    fields = dict(load_for_edit(path).authoritative)
    field, value = (
        ("consumerKey", "desired.row.absent.value")
        if invalid == "undeclared"
        else (
            ("resourceType", "EC2.VPC")
            if invalid == "wrong-type"
            else (
                "producerLogicalId",
                "EC2_Subnet_999" if invalid == "999" else invalid,
            )
        )
    )
    fields["desired.reference.subnet." + field] = value
    path.write_text(serialize(fields), encoding="utf-8")
    with restrict(("dev", "cde", "codebuild")):
        if invalid == "undeclared":
            with pytest.raises(ValueError, match="consumerKey|orphan row"):
                load_for_edit(path)
        else:
            with closing(GenerationInputs(tmp_path)) as reads:
                before = load_for_edit(path, reads)
                impact = replacement_inputs(
                    before, {"009": {"_action": "replace"}}, reads
                )
                assert any(
                    w["code"] == "reference.mismatch" for w in impact["warnings"]
                )


def check_analysis_permission_restores_after_exception_and_foreign_scope(tmp_path):
    path = impact_fixture(tmp_path)
    producer_path = path.with_name("vpc.properties")
    with (
        input_context(),
        restrict(("dev", "cde", "codebuild")),
        read_consumers({("dev", "cde", "codebuild")}),
    ):
        with pytest.raises(RuntimeError, match="analysis failed"):
            with reference_reader(producer_path):
                assert load_for_edit(producer_path).authoritative
                for foreign in (
                    tmp_path / "model/stg/cde/codebuild.properties",
                    tmp_path / "model/dev/other/codebuild.properties",
                ):
                    with pytest.raises(ValueError, match="outside selected"):
                        load_for_edit(foreign)
                raise RuntimeError("analysis failed")
        with pytest.raises(ValueError, match="outside selected"):
            load_for_edit(producer_path)


@pytest.mark.parametrize("action", ["bind", "replace"])
def check_review_runs_saved_reference_impact(tmp_path, action):
    path = impact_fixture(tmp_path)
    with input_context(), closing(GenerationInputs(tmp_path)) as reads:
        before = load_for_edit(path, reads)
        impact = replacement_inputs(before, {"009": {"_action": action}}, reads)
        acquisition = {
            "version": 3,
            "modelFormat": 2,
            "snapshotVersion": 2,
            "referenceMeaningVersion": 1,
            "task": "tasks/import-fixture.md",
            "root": str(tmp_path),
            "scope": ["dev", "cde", "codebuild"],
            "connection": {
                "awsAccountId": "123456789012",
                "awsRegion": "ap-northeast-1",
            },
            "acquiredAt": datetime.now(timezone.utc).isoformat(),
            "sources": impact["inputs"],
            "records": [],
            "inventory": {"CodeBuild.Project": {"status": "complete"}},
        }
        review = build_review(
            acquisition,
            {"resources": [], "excluded": [], "unreflected": []},
            before,
            dict(before.authoritative),
            {},
            lambda _: {"type": "string"},
            reference_impact=impact,
        )
        assert any(
            w.get("consumer") == "dev/cde/codepipeline/003"
            for w in review["referenceImpact"]["warnings"]
        )
        assert review["referenceImpact"]["inputs"] == impact["inputs"]


def check_preserved_read_does_not_authorize_writes(tmp_path):
    path = impact_fixture(tmp_path)
    with restrict(("dev", "cde", "codebuild")):
        before = load_for_edit(path)
        assert incoming(before, "009")
        fields = {**before.authoritative, "desired.row.010-001.comment": "changed"}
        with pytest.raises(ValueError, match="unselected Resource"):
            verify_values(before, Expansion(fields), {}, lambda _: {"type": "string"})


def check_configuration_index_reuses_scans_and_keeps_raw_fields():
    source = {
        **values("Logs.LogGroup", {"LogGroupName": "first"}, rid="001"),
        **values("Logs.LogGroup", {"LogGroupName": "second"}, rid="002"),
    }
    del source["desired.resource.001.logicalId"]
    source["observed.row.001-001.value"] = "first"
    source["desired.row.002-001.document"] = (
        '{"items":[1,true,"[first](logs.md#producer)"]}'
    )
    del source["desired.row.002-001.value"]
    source["desired.row.001-001.value"] = "[first](logs.md#producer)"
    for identity in ("z-last", "a-first"):
        for field, value in {
            "consumerKey": "desired.row.001-001.value",
            "text": "[first](logs.md#producer)",
            "occurrence": "1",
            "producerKind": "resource",
            "producerScope": "dev/cde/logs",
            "producerLogicalId": "Logs_LogGroup_002",
            "resourceType": "Logs.LogGroup",
            "format": "link",
            "labelPolicy": "fixed",
        }.items():
            source[f"desired.reference.{identity}.{field}"] = value
    index = ConfigurationIndex(source)
    with (
        patch("model.core.resource_row_index", wraps=resource_row_index) as rows,
        patch("model.configuration.declarations", wraps=declarations) as refs,
    ):
        actual = [
            resource_configuration(source, rid, index=index) for rid in ("001", "002")
        ]
        assert rows.call_count == refs.call_count == 1
    assert list(actual[0]["references"]) == ["a-first", "z-last"]
    assert actual[1]["references"] == {}
    assert index.values is source
    assert "logicalId" not in actual[0]["resource"]
    assert actual[0]["observed"] == {"observed.row.001-001.value": "first"}
    assert actual[1]["rows"][0][2] == {
        "object": {
            "items": {
                "array": [
                    {"int": 1},
                    {"bool": True},
                    {"string": "[first](logs.md#producer)"},
                ]
            }
        }
    }
    assert actual == [resource_configuration(source, rid) for rid in ("001", "002")]
    source["desired.row.001-001.value"] = "changed [first](logs.md#producer)"
    assert resource_configuration(source, "001")["rows"][0][2] == {
        "string": "changed [first](logs.md#producer)"
    }


def check_configuration_index_preserves_exception_priority():
    source = values("Logs.LogGroup", {"LogGroupName": "first"})
    source["desired.reference.bad.consumerKey"] = "missing"
    for indexed in (False, True):
        kwargs = {"index": ConfigurationIndex(source)} if indexed else {}
        with pytest.raises(KeyError) as error:
            resource_configuration(source, "missing", **kwargs)
        assert error.value.args == ("missing",)
        with pytest.raises(ValueError, match="invalid reference fields: bad"):
            resource_configuration(source, "001", **kwargs)
    source["desired.row.orphan-001.property"] = "Logs.LogGroup.LogGroupName"
    with pytest.raises(ValueError, match="orphan desired row: orphan-001"):
        resource_configuration(source, "001", index=ConfigurationIndex(source))


def check_observation_index_keeps_every_legacy_prefix():
    source = {
        **values("Logs.LogGroup", {}, rid="legacy"),
        **values("Logs.LogGroup", {}, rid="legacy-child"),
        "observed.row.legacy-child-001.value": "old",
        "observed.row.legacy-002.value": "same",
    }
    indexed = _observed_index(source)
    for rid in ("legacy", "legacy-child"):
        assert indexed[rid] == {
            key: value
            for key, value in source.items()
            if key.startswith(f"observed.row.{rid}-")
        }
    updated = {**source, "observed.row.legacy-child-001.value": "new"}
    with (
        patch("model.observed.require_observable_row") as require,
        patch("model.operations._observed_index", wraps=_observed_index) as build,
    ):
        preserve_fixed_fields(
            SimpleNamespace(authoritative=source),
            SimpleNamespace(authoritative=updated),
            SimpleNamespace(action="design"),
        )
        assert build.call_count == 2
        assert require.call_count == 2
        assert all(
            call.args[1] == "legacy-child-001" for call in require.call_args_list
        )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

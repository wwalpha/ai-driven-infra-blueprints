#!/usr/bin/env python3
"""Model generation connections and service-local publication protection."""

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import model.validations.policies as _model_validation_policies
import support.model_design_fixtures as fixtures
from design.document import DesignIndex
from model.format import FORMAT
from model.format import INDEX as INDEX_HEADER
from model.format import PART as PART_PREFIX
from model.identity import Resolver
from model.projection import validate_json_documents
from model.render import generate_files, generate_markdown
from model.sources import scope_for, source_inputs
from support.model_design_fixtures import (
    ROOT,
    SYNC,
    json,
    load_model,
    main,
    markdown_for,
    model,
    patch,
    properties,
    pytest,
    read_model,
    roundtrip,
    snapshot_model,
    sync_views,
    text,
    write_fixture_files,
    write_model,
)
from support.model_design_fixtures import pytestmark as pytestmark
from support.model_reference_fixtures import reference
from support.validator import diagnostics
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.iac_values import cfn_resource_identity
from validation import runner as validation_runner
from validation.design_links import endpoint_dns_reference

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

project = fixtures.project
root = fixtures.root


def _callback_check_route53_endpoint_dns_roundtrip_errors(
    outputs, path, root, validator_module, /, content
):
    path.write_text(content, encoding="utf-8")
    validator = validator_module.Validator(root)
    validator.check_design_links(outputs)
    return diagnostics(validator)


def check_route53_endpoint_dns_roundtrip(root, project):
    directory = root / "docs/designs/dev/123456789012"
    endpoint = model(
        "vpc-endpoint",
        "EC2.VPCEndpoint",
        "vpce-app-dev-snowflake",
        [
            (
                "Id",
                "`" + json.dumps(reference("EC2_VPCEndpoint_001", "Id")) + "`",
                "一意に識別するID",
            ),
            (
                "ServiceName",
                "`com.amazonaws.vpce.ap-northeast-1.vpce-svc-04feb508c997b211e`",
                "接続先service",
            ),
            ("Tags[].Key", "`Name`", "タグのキー"),
            ("Tags[].Value", "`vpce-app-dev-snowflake`", "エンドポイント名"),
            ("VpcEndpointType", "`Interface`", "接続方式"),
            ("VpcId", "`vpc-00000000000000001`", "所属VPC"),
        ],
        logical_id="Endpoint",
    )
    for field, value in [
        ("property", "EC2.VPCEndpoint.Id"),
        ("value", "vpce-014d2843ef114f19d"),
        ("comment", "一意に識別するID"),
    ]:
        endpoint[f"observed.row.001-001.{field}"] = value
    roundtrip(directory / "vpc-endpoint.md", endpoint, root)
    dns = "vpce-014d2843ef114f19d-m2klm0hu.vpce-svc-04feb508c997b211e.ap-northeast-1.vpce.amazonaws.com"
    route = model(
        "route53",
        "Route53.RecordSet",
        "snow.example.com",
        [
            ("Name", "`snow.example.com`", "レコード名"),
            (
                "ResourceRecords",
                "`" + json.dumps(reference("EC2_VPCEndpoint_001", "DnsEntries")) + "`",
                "CNAMEの接続先DNS",
            ),
            ("TTL", "`300`", "キャッシュ時間"),
            ("Type", "`CNAME`", "レコード種別"),
        ],
    )
    for field, value in [
        ("property", "Route53.RecordSet.ResourceRecords"),
        ("value", dns),
        ("comment", "CNAMEの接続先DNS"),
    ]:
        route[f"observed.row.001-002.{field}"] = value
    path = directory / "route53.md"
    valid = roundtrip(path, route, root)
    validator_module = validation_runner
    outputs = validator_module.Validator(ROOT).catalog_design_properties()[2]
    errors = _bind_framework_callback(
        _callback_check_route53_endpoint_dns_roundtrip_errors,
        outputs,
        path,
        root,
        validator_module,
    )
    initial_errors = errors(valid)
    assert not initial_errors, initial_errors
    endpoint_path = directory / "vpc-endpoint.md"
    dns_reference = _bind_framework_callback(
        endpoint_dns_reference,
        path,
        "Route53.RecordSet.ResourceRecords",
        target=endpoint_path,
        resource=("EC2.VPCEndpoint", {"EC2.VPCEndpoint.Id": "vpce-014d2843ef114f19d"}),
        configuration={
            "EC2.VPCEndpoint.VpcEndpointType": "Interface",
            "EC2.VPCEndpoint.ServiceName": "com.amazonaws.vpce.ap-northeast-1.vpce-svc-04feb508c997b211e",
        },
        record_type="CNAME",
    )
    TestCase().assertTrue(dns_reference(dns))
    for bad in (
        dns.replace("014d2843ef114f19d", "014d2843ef114f190"),
        dns.replace("vpce-svc-04feb508c997b211e", "vpce-svc-04feb508c997b2110"),
        dns.replace(
            "ap-northeast-1.vpce.amazonaws.com", "us-east-1.vpce.amazonaws.com"
        ),
    ):
        assert not dns_reference(bad)
    TestCase().assertTrue(
        errors(
            valid.replace(
                "vpc-endpoint.md#vpc-endpoint-vpce-app-dev-snowflake",
                "route53.md#route53-snow.example.com",
            )
        )
    )
    assert not dns_reference(dns, record_type="A")
    for label in (
        dns,
        "Interface",
        "com.amazonaws.vpce.ap-northeast-1.vpce-svc-04feb508c997b211e",
    ):
        assert not endpoint_dns_reference(
            path,
            "HostedZoneId",
            label,
            endpoint_path,
            ("EC2.VPCEndpoint", {}),
            {},
            "CNAME",
        )
    assert not dns_reference(
        dns, configuration={"EC2.VPCEndpoint.VpcEndpointType": "Gateway"}
    )
    path.write_text(valid, encoding="utf-8")


def check_route53_typed_expression_roundtrip(root, project):
    directory = root / "docs/designs/dev/123456789012"
    endpoint = model(
        "vpc-endpoint",
        "EC2.VPCEndpoint",
        "vpce-example",
        [
            ("VpcEndpointType", "`Interface`", "接続方式"),
            ("Tags[].Key", "`Name`", "タグ"),
            ("Tags[].Value", "`vpce-example`", "名前"),
        ],
        logical_id="Endpoint",
    )
    roundtrip(directory / "vpc-endpoint.md", endpoint, root)
    expression = {
        "Fn::Select": [
            1,
            {
                "Fn::Split": [
                    ":",
                    {"Fn::Select": [0, reference("EC2_VPCEndpoint_001", "DnsEntries")]},
                ]
            },
        ]
    }
    encoded = "`" + json.dumps([expression]) + "`"
    route = model(
        "route53",
        "Route53.RecordSet",
        "example.com",
        [
            ("Name", "`example.com`", "レコード名"),
            ("ResourceRecords", encoded, "接続先"),
            ("Type", "`CNAME`", "種別"),
        ],
    )
    path = directory / "route53.md"
    rendered = roundtrip(path, route, root)
    source = root / "model/dev/123456789012/route53.properties"
    case = TestCase()
    validate_json_documents(load_model(source).authoritative, source)
    case.assertEqual(
        load_model(source).authoritative["desired.row.001-002.value"], encoded
    )
    case.assertIn("vpc-endpoint.md#", rendered)
    case.assertNotIn(
        "vpce-", load_model(source).authoritative["desired.row.001-002.value"]
    )


def check_s3_policy_kms_reference_roundtrip(root, project):
    directory = root / "docs/designs/dev/123456789012"
    kms = model(
        "kms",
        "KMS.Key",
        "test-key",
        [("KeyId", "`" + json.dumps(reference("KMS_Key_001", "KeyId")) + "`", "ID")],
        label="test-key",
    )
    kms["observed.row.001-001.value"] = "`12345678-1234-1234-1234-123456789012`"
    roundtrip(directory / "kms.md", kms, root)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": "arn:aws:s3:::example-bucket/*",
                "Condition": {
                    "StringNotEquals": {
                        "s3:x-amz-server-side-encryption-aws-kms-key-id": reference(
                            "KMS_Key_001", "Arn"
                        )
                    }
                },
            }
        ],
    }
    values = model(
        "s3",
        "S3.BucketPolicy",
        "example-bucket",
        [
            ("Bucket", "`example-bucket`", "対象"),
            ("PolicyDocument", "[Policy](s3/policy.json)", "ポリシー"),
        ],
        label="example-bucket",
    )
    values = {key.replace(".001", ".002"): value for key, value in values.items()}
    values["desired.resource.002.logicalId"] = "S3_BucketPolicy_001"
    values["desired.resource.002.anchor"] = "s3-example-bucket-policy"
    values["desired.resource.002.parentReference"] = (
        "`" + json.dumps(reference("S3_Bucket_001", "BucketName")) + "`"
    )
    values["desired.resource.002.parentProperty"] = "S3.BucketPolicy.Bucket"
    values["desired.row.002-001.value"] = values["desired.resource.002.parentReference"]
    values["desired.row.002-002.document"] = json.dumps(policy)
    bucket = model(
        "s3",
        "S3.Bucket",
        "example-bucket",
        [("BucketName", "`example-bucket`", "名前")],
    )
    values.update(
        {
            key: value
            for key, value in bucket.items()
            if key.startswith(
                ("desired.resource.", "desired.row.", "display.resource.")
            )
        }
    )
    values["desired.service.s3.ownedCatalogResourceTypes"] = "S3.Bucket,S3.BucketPolicy"
    values["desired.service.identity.lastAllocated"] = (
        '{"S3.Bucket":1,"S3.BucketPolicy":1}'
    )
    path = directory / "s3.md"
    output = roundtrip(path, values, root)
    source = root / "model/dev/123456789012/s3.properties"
    case = TestCase()
    validate_json_documents(load_model(source).authoritative, source)
    case.assertEqual(
        json.loads(load_model(source).authoritative["desired.row.002-002.document"]),
        policy,
    )
    case.assertIn("[Policy](s3/policy.json)", output)
    artifact = generate_files(path, values, root)[directory / "s3/policy.json"]
    case.assertIn(
        "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
        artifact,
    )


def check_import_optional_name_label(root, project):
    kind, label, logical_id = (
        "Config.ConfigurationRecorder",
        "Config recorder",
        "Config_ConfigurationRecorder_001",
    )
    path = root / "docs/designs/dev/123456789012/config.md"
    source = root / "model/dev/123456789012/config.properties"
    anchor = "config-saved-recorder-anchor"
    values = model(
        "config",
        kind,
        label,
        [
            (
                "Id",
                "`" + json.dumps(reference(logical_id, "Name")) + "`",
                "一意に識別するID",
            ),
            (
                "RoleARN",
                "`arn:aws:iam::123456789012:role/ConfigRecorderRole`",
                "記録用IAM Role",
            ),
        ],
        label=label,
    )
    values.update(
        {
            "desired.resource.001.resourceMode": "IMPORT",
            "desired.resource.001.anchor": anchor,
            "observed.row.001-001.value": "`PENDING_DEPLOY`",
            "desired.note.001.text": f"参照: [{label}](#{anchor})",
        }
    )
    values.pop("desired.resource.001.cfn-logicalId")
    valid = roundtrip(path, values, root)
    before = snapshot_model(source)
    original = dict(values)
    assert f"<!-- resource-logical-id: {logical_id} -->" in valid
    assert f'<a id="{anchor}"></a>' in valid and f"### {kind}: {label}" in valid
    sync_views.validate_views(root, root, [path], {path: values})
    assert snapshot_model(source) == before and values == original
    assert path.read_text(encoding="utf-8") == valid
    _, _, producer = Resolver(root).resolve(
        reference(logical_id, "Name"), scope_for(source)
    )
    assert (producer["resourceType"], producer["logicalId"]) == (kind, logical_id)

    named = {
        **values,
        "desired.row.001-003.property": kind + ".Name",
        "desired.row.001-003.value": "`default`",
        "desired.row.001-003.comment": "記録設定名",
        "desired.note.001.text": f"参照: [default](#{anchor})",
    }
    output = roundtrip(path, named, root)
    named_before = snapshot_model(source)
    sync_views.validate_views(root, root, [path], {path: named})
    assert f"### {kind}: default" in output and f'<a id="{anchor}"></a>' in output
    _, _, producer = Resolver(root).resolve(
        reference(logical_id, "Name"), scope_for(source)
    )
    assert (producer["resourceType"], producer["logicalId"]) == (kind, logical_id)
    assert snapshot_model(source) == named_before


def check_kms_policy_execution_account(root):
    identity, execution = "111111111111", "222222222222"
    key_id = "12345678-1234-1234-1234-123456789012"
    target = {
        "environment": "dev",
        "awsAccountId": identity,
        "awsExecutionAccountId": execution,
        "awsRegion": "ap-northeast-1",
        "iacEngine": "cloudformation",
    }
    root_arn = f"arn:aws:iam::{execution}:root"
    macie_arn = f"arn:aws:iam::{execution}:role/aws-service-role/macie.amazonaws.com/AWSServiceRoleForAmazonMacie"
    policy = {
        "Version": "2012-10-17",
        "Id": "key-default",
        "Statement": [
            {
                "Sid": "EnableIamUserPermissions",
                "Effect": "Allow",
                "Principal": {"AWS": root_arn},
                "Action": "kms:*",
                "Resource": "*",
            },
            {
                "Sid": "AllowMacieToDecryptObjects",
                "Effect": "Allow",
                "Principal": {"AWS": macie_arn},
                "Action": "kms:Decrypt",
                "Resource": "*",
            },
        ],
    }
    values = model(
        "kms",
        "KMS.Key",
        "test-key",
        [
            (
                "KeyId",
                '`{"$modelRef":{"logicalId":"KMS_Key_001","attribute":"KeyId"}}`',
                "キーを識別するID",
            ),
            ("KeyPolicy", "[Policy](kms/test-key-policy.json)", "キーの利用権限"),
        ],
        "Key",
        "test-key",
    )
    values.update(
        {
            "observed.row.001-001.property": "KMS.Key.KeyId",
            "observed.row.001-001.value": f"`{key_id}`",
            "observed.row.001-001.comment": "キーを識別するID",
        }
    )
    values.update(
        {
            "desired.row.001-003.property": "KMS.Key.Description",
            "desired.row.001-003.value": "`"
            + json.dumps(
                {"$modelRef": {"logicalId": "KMS_Key_001", "attribute": "Arn"}}
            )
            + "`",
            "desired.row.001-003.comment": "Model参照の生成接続",
        }
    )
    document_key = "desired.row.001-002.document"
    values[document_key] = json.dumps(policy, separators=(",", ":"))
    (root / "project.json").write_text(
        json.dumps({"projectName": "test", "targets": [target]}) + "\n",
        encoding="utf-8",
    )
    source = root / f"model/dev/{identity}/kms.properties"
    source.parent.mkdir(parents=True, exist_ok=True)
    write_model(
        source.with_name("cloudformation-stacks.properties"),
        {
            "desired.stack.001.name": "fixture",
            "desired.stack.001.placementName": "fixture",
            "desired.stack.001.template": "fixture.yaml",
            "desired.stack.001.parameters": "fixture.json",
            "desired.stack.001.deployOrder": "1",
            "display.stack.001.comment": "合成Stack",
        },
    )
    write_model(source, text(values))
    dependency_index.rebuild(root)
    path = root / f"docs/designs/dev/{identity}/kms.md"
    assert SYNC.sync(root, True, "dev", identity, services=["kms"]) == 0
    artifact = path.with_suffix("") / "test-key-policy.json"
    saved = path.read_bytes(), artifact.read_bytes()
    assert b"reference-rows" not in saved[0] and b"reference-value" not in saved[0]
    assert key_id in saved[0].decode("utf-8")
    assert "$modelRef" in "\n".join(DesignIndex(root).get(path).raw.display_lines)
    assert SYNC.sync(root, False, "dev", identity, services=["kms"]) == 0
    invalid = {
        **values,
        document_key: values[document_key].replace(execution, identity),
    }
    write_model(source, text(invalid))
    with pytest.raises(ValueError, match=f"must use AWS execution account {execution}"):
        _model_validation_policies.validate_kms_policy_accounts(invalid, target)
    assert (path.read_bytes(), artifact.read_bytes()) == saved
    assert properties(read_model(source)) == properties(text(invalid))
    # Account rejection also protects a matching authored view.
    path.write_text(
        generate_markdown(path, load_model(source).values, ROOT), encoding="utf-8"
    )
    saved = path.read_bytes(), artifact.read_bytes()
    for _write in (False, True):
        with pytest.raises(ValueError) as error:
            _model_validation_policies.validate_kms_policy_accounts(invalid, target)
        assert "Principal.AWS" in str(error.value) and execution in str(error.value), (
            str(error.value)
        )
        assert (path.read_bytes(), artifact.read_bytes()) == saved
        assert properties(read_model(source)) == properties(text(invalid))


def _callback_check_config_typed_anchors_failures(
    catalog, metadata, path, root, /, markdown
):
    path.write_text(markdown, encoding="utf-8")
    validator = sync_views.view_validator(root, root)
    validator.check_resource_names(metadata, [path])
    validator.check_design_tables(metadata, *catalog, [path])
    validator.check_design_overviews([path])
    validator.check_design_links(catalog[2], [path])
    return diagnostics(validator)


def check_config_typed_anchors(root):
    recorder, channel = "Config.ConfigurationRecorder", "Config.DeliveryChannel"
    recorder_anchor = "config-configuration-recorder-default"
    channel_anchor = "resource-Config_DeliveryChannel_001"
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        "alias": alias,
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for alias in ("cde", "non-cde")
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    path = root / "docs/designs/dev/cde/config.md"
    values = model(
        "config",
        recorder,
        "default",
        [
            ("Name", "`default`", "構成情報を記録するrecorderの名前"),
            (
                "Id",
                '`{"$modelRef":{"logicalId":"Config_ConfigurationRecorder_001","attribute":"Name"}}`',
                "recorderを識別するID",
            ),
            (
                "RoleARN",
                "`AWSServiceRoleForConfig`",
                "記録に使用するservice linked role",
            ),
        ],
        "Recorder",
    )
    values.update(
        {
            "desired.service.config.ownedCatalogResourceTypes": recorder
            + ","
            + channel,
            "desired.service.identity.lastAllocated": json.dumps(
                {recorder: 1, channel: 1}
            ),
            "observed.row.001-002.property": recorder + ".Id",
            "observed.row.001-002.value": "`default`",
            "observed.row.001-002.comment": values["desired.row.001-002.comment"],
            "desired.resource.002.resourceType": channel,
            "desired.resource.002.logicalId": "Config_DeliveryChannel_001",
            "desired.resource.002.anchor": "resource-Config_DeliveryChannel_001",
            "desired.resource.002.cfn-logicalId": "fixture-Channel",
            "display.resource.002.comment": "構成情報をS3へ配信するchannel",
            "desired.row.002-001.property": channel + ".Name",
            "desired.row.002-001.value": "`default`",
            "desired.row.002-001.comment": "構成情報を配信するchannelの名前",
            "desired.row.002-002.property": channel + ".S3BucketName",
            "desired.row.002-002.value": "`config-records`",
            "desired.row.002-002.comment": "構成情報を保存するS3 bucketの名前",
        }
    )
    output = roundtrip(path, values, root)
    sync_views.validate_views(root, root, [path], {path: values})
    for kind, anchor, logical_id in (
        (recorder, recorder_anchor, "Config_ConfigurationRecorder_001"),
        (channel, channel_anchor, "Config_DeliveryChannel_001"),
    ):
        assert f"### {kind}: default" in output
        assert f"| 1 | [default](#{anchor}) |" in output
        _, _, producer = Resolver(root).resolve(
            reference(logical_id, "Name"),
            scope_for(root / "model/dev/cde/config.properties"),
        )
        assert (producer["resourceType"], producer["logicalId"]) == (kind, logical_id)
    metadata = {path: ("config", (recorder, channel))}
    catalog = sync_views.view_validator(root, root).catalog_design_properties()

    failures = _bind_framework_callback(
        _callback_check_config_typed_anchors_failures, catalog, metadata, path, root
    )

    assert not failures(output)
    for key, wrong in (
        ("001", "config-default"),
        ("001", channel_anchor),
        ("002", "config-default"),
        ("002", recorder_anchor),
    ):
        correct = values[f"desired.resource.{key}.anchor"]
        assert failures(output.replace(correct, wrong)), (correct, wrong)
    path.write_text(output, encoding="utf-8")

    hub = model(
        "securityhub",
        "SecurityHub.Hub",
        "securityhub.hub",
        [
            ("EnableDefaultStandards", "`true`", "標準を有効にする設定"),
        ],
        "Hub",
    )
    hub["desired.note.001.text"] = (
        "記録先: [Config_ConfigurationRecorder_001](config.md#config-configuration-recorder-default)"
    )
    hub["desired.note.002.text"] = (
        "配信先: [Config_DeliveryChannel_001](config.md#resource-Config_DeliveryChannel_001)"
    )
    roundtrip(path.with_name("securityhub.md"), hub, root)
    validator = sync_views.view_validator(root, root)
    validator.check_design_links(catalog[2])
    assert not validator.errors, validator.errors
    source = root / "model/dev/cde/config.properties"
    assert properties(read_model(source)) == properties(text(values))
    assert path.read_text(encoding="utf-8") == output


def check_stack_mapping_roundtrip(root):
    path = root / "docs/designs/dev/123456789012/ec2.md"
    values = model(
        "ec2",
        "EC2.VPC",
        "vpc-app-dev-data",
        [
            ("Name", "`vpc-app-dev-data`", "ネットワークの名称"),
            (
                "VpcId",
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                "ネットワークのID",
            ),
            ("CidrBlock", "`10.0.0.0/16`", "ネットワークの範囲"),
        ],
    )
    values["desired.resource.001.resourceMode"] = "CREATE"
    values.update(
        {
            "observed.row.001-002.property": "EC2.VPC.VpcId",
            "observed.row.001-002.value": "`PENDING_DEPLOY`",
            "observed.row.001-002.comment": "ネットワークのID",
        }
    )
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    values["desired.resource.001.cfn-logicalId"] = "cfn-stack-app-dev-ism-DepartmentVpc"
    stack_source = root / "model/dev/123456789012/cloudformation-stacks.properties"
    stack_source.parent.mkdir(parents=True, exist_ok=True)
    stack_values = {}
    for index, purpose in enumerate(("ism", "key"), 1):
        stack_values.update(
            {
                f"desired.stack.{index:03d}.{field}": value
                for field, value in {
                    "name": "cfn-stack-app-dev-" + purpose,
                    "placementName": "cfn-stack-app-dev-" + purpose,
                    "template": "shared.yaml",
                    "parameters": purpose + ".json",
                    "deployOrder": "10",
                }.items()
            }
        )
        stack_values[f"display.stack.{index:03d}.comment"] = "合成Stack"
    write_model(stack_source, stack_values)
    rendered = roundtrip(path, values, root)
    assert cfn_resource_identity(values["desired.resource.001.cfn-logicalId"]) == (
        "cfn-stack-app-dev-ism",
        "DepartmentVpc",
    )
    assert "cfn-logical-id:" not in rendered
    assert "resource-entry:" not in rendered and "resource-mode:" not in rendered
    sync_views.validate_views(root, root, [path], {path: values})
    source = stack_source.with_name("ec2.properties")
    before = {
        file: file.read_bytes()
        for model in (source, stack_source)
        for file in load_model(model).files
    }
    assert SYNC.sync(root, True, "dev", "123456789012", services=["ec2"]) == 0
    assert path.read_text(encoding="utf-8") == rendered
    assert SYNC.sync(root, False, "dev", "123456789012", services=["ec2"]) == 0
    assert {file: file.read_bytes() for file in before} == before
    assert (
        properties(read_model(source))["desired.resource.001.cfn-logicalId"]
        == values["desired.resource.001.cfn-logicalId"]
    )
    # Independent numbering survives grouped display order; Key and Alias each have a CFn ID.
    kms_path = path.with_name("kms.md")
    kms = model(
        "kms",
        "KMS.Key",
        "app-dev-data",
        [
            (
                "KeyId",
                '`{"$modelRef":{"logicalId":"KMS_Key_001","attribute":"KeyId"}}`',
                "一意に識別するID",
            )
        ],
        label="app-dev-data",
    )
    kms = {key.replace(".001", ".007"): value for key, value in kms.items()}
    kms.update(
        {
            "desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
            "desired.resource.007.cfn-logicalId": "cfn-stack-app-dev-key-Key",
            "observed.row.007-001.property": "KMS.Key.KeyId",
            "observed.row.007-001.value": "`PENDING_DEPLOY`",
            "observed.row.007-001.comment": "一意に識別するID",
            "desired.resource.021.resourceType": "KMS.Alias",
            "desired.resource.021.logicalId": "KMS_Alias_001",
            "desired.resource.021.anchor": "resource-KMS_Alias_001",
            "desired.service.identity.lastAllocated": '{"KMS.Key":1,"KMS.Alias":1}',
            "desired.resource.021.cfn-logicalId": "cfn-stack-app-dev-key-Alias",
            "desired.resource.021.parentProperty": "KMS.Alias.TargetKeyId",
            "desired.resource.021.parentReference": '`{"$modelRef":{"logicalId":"KMS_Key_001","attribute":"KeyId"}}`',
            "desired.row.021-001.property": "KMS.Alias.AliasName",
            "desired.row.021-001.value": "`alias/app-dev-data`",
            "desired.row.021-001.comment": "keyを識別するalias",
        }
    )
    grouped = roundtrip(kms_path, kms, root)
    assert "resource-entry:" not in grouped and "resource-mode:" not in grouped
    assert "cfn-logical-id:" not in grouped
    sync_views.validate_views(root, root, [kms_path], {kms_path: kms})
    # The normal parser reads indexed models without renumbering grouped children.
    kms_source = stack_source.with_name("kms.properties")
    part = kms_source.with_suffix("") / "part-001.properties"
    part.parent.mkdir()
    write_fixture_files(
        {
            part: text(kms),
            kms_source: FORMAT
            + "\n"
            + INDEX_HEADER
            + "\n"
            + PART_PREFIX
            + "kms/part-001.properties\n",
        }
    )
    authority = source_inputs(kms_source)
    before = {file: file.read_bytes() for file in authority}
    assert load_model(kms_source).values == properties(text(kms))
    assert kms_path.read_text() == markdown_for(kms_path, kms, root)
    assert SYNC.sync(root, True, "dev", "123456789012", services=["kms"]) == 0
    assert SYNC.sync(root, False, "dev", "123456789012", services=["kms"]) == 0
    assert {file: file.read_bytes() for file in before} == before


def _callback_check_service_failure_protection_fail_iam(
    original_write, docs, /, path, data, *args, **kwargs
):
    if path == docs / "iam.md":
        raise OSError("test IAM write failure")
    return original_write(path, data, *args, **kwargs)


def check_service_failure_protection(root, project):
    base = root / "model/dev/123456789012"
    base.mkdir(parents=True, exist_ok=True)
    vpc = model(
        "vpc",
        "EC2.VPC",
        "vpc-net-dev",
        [
            ("Name", "`vpc-net-dev`", "識別するNameタグ"),
            (
                "VpcId",
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                "一意に識別するID",
            ),
            ("CidrBlock", "`10.1.0.0/16`", "IPv4のアドレス範囲"),
        ],
        "Vpc",
    )
    vpc["observed.row.001-002.property"] = "EC2.VPC.VpcId"
    vpc["observed.row.001-002.value"] = "`PENDING_DEPLOY`"
    vpc["observed.row.001-002.comment"] = "一意に識別するID"
    logs = model(
        "logs",
        "Logs.LogGroup",
        "cwlogs-net-dev-flow",
        [
            ("LogGroupName", "`cwlogs-net-dev-flow`", "ログを保存する名前"),
            ("RetentionInDays", "`30`", "ログを保持する日数"),
        ],
    )
    iam = model(
        "iam",
        "IAM.Role",
        "net-dev-flow-role",
        [
            ("RoleName", "`net-dev-flow-role`", "権限を識別する名前"),
            (
                "AssumeRolePolicyDocument",
                "[信頼ポリシー](iam/iam-role-001-trust-policy.json)",
                "引受元に許可する権限",
            ),
        ],
        "FlowRole",
    )
    iam["desired.row.001-002.document"] = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "vpc-flow-logs.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        },
        separators=(",", ":"),
    )
    sources = {
        base / "vpc.properties": vpc,
        base / "logs.properties": logs,
        base / "iam.properties": iam,
    }
    for path, values in sources.items():
        write_model(path, text(values))
    assert SYNC.sync(root, True, "dev", "123456789012") == 0
    saved_sources = {
        file: file.read_bytes() for model in sources for file in load_model(model).files
    }
    docs = root / "docs/designs/dev/123456789012"
    assert "Version" in (docs / "iam.md").read_text(encoding="utf-8")
    assert "$modelRef" not in (docs / "vpc.md").read_text(
        encoding="utf-8"
    ) and "](#vpc-vpc-net-dev)" in (docs / "vpc.md").read_text(encoding="utf-8")
    saved_views = {
        path: path.read_bytes() for path in docs.rglob("*") if path.is_file()
    }
    assert saved_sources == {file: file.read_bytes() for file in saved_sources}
    document = json.loads(iam["desired.row.001-002.document"])
    document["Statement"][0]["Sid"] = "Trust"
    iam["desired.row.001-002.document"] = json.dumps(document)
    iam["desired.row.001-002.comment"] = "引受元に許可する権限を定義する設定"
    logs["desired.row.001-002.value"] = "`7`"
    write_model(base / "iam.properties", text(iam))
    write_model(base / "logs.properties", text(logs))
    saved_sources = {
        file: file.read_bytes()
        for source in sources
        for file in load_model(source).files
    }
    fail_iam = _bind_framework_callback(
        _callback_check_service_failure_protection_fail_iam, Path.write_text, docs
    )
    with patch.object(Path, "write_text", fail_iam):
        with pytest.raises(ValueError, match="test IAM write failure"):
            SYNC.sync(root, True, "dev", "123456789012")
    assert (docs / "iam.md").read_bytes() == saved_views[docs / "iam.md"]
    assert (docs / "iam/iam-role-001-trust-policy.json").read_bytes() == saved_views[
        docs / "iam/iam-role-001-trust-policy.json"
    ]
    assert "`7`" in (docs / "logs.md").read_text(encoding="utf-8")
    assert (docs / "vpc.md").read_bytes() == saved_views[docs / "vpc.md"]
    assert {file: file.read_bytes() for file in saved_sources} == saved_sources


def check_dynamic_reference_candidates(root, project):
    source = root / "model/dev/123456789012/quicksight.properties"
    reference = "{{resolve:secretsmanager:example/dev/snowflake-pat/iad/pii:SecretString:username}}"
    values = model(
        "quicksight",
        "QuickSight.DataSource",
        "datasource",
        [
            ("Name", "`datasource`", "接続名"),
            ("Type", "`SNOWFLAKE`", "接続の種類"),
            ("AwsAccountId", "`123456789012`", "アカウント"),
            ("DataSourceId", "`datasource`", "接続ID"),
            (
                "DataSourceParameters.SnowflakeParameters.Database",
                "`example`",
                "データベース",
            ),
            (
                "DataSourceParameters.SnowflakeParameters.Host",
                "`example.snowflakecomputing.com`",
                "接続先",
            ),
            (
                "DataSourceParameters.SnowflakeParameters.Warehouse",
                "`example`",
                "ウェアハウス",
            ),
            (
                "Credentials.CredentialPair.Username",
                "`" + reference + "`",
                "認証ユーザー",
            ),
            (
                "Credentials.CredentialPair.Password",
                "`" + reference.replace(":username}}", ":password}}") + "`",
                "認証パスワード",
            ),
        ],
    )
    values["desired.resource.001.resourceMode"] = "IMPORT"
    values.pop("desired.resource.001.cfn-logicalId", None)
    write_model(source, text(values))
    dependency_index.rebuild(root)
    inputs = {path: path.read_bytes() for path in load_model(source).files}
    assert SYNC.sync(root, True, "dev", "123456789012", {"quicksight"}) == 0
    design = root / "docs/designs/dev/123456789012/quicksight.md"
    saved = design.read_bytes()
    assert reference in saved.decode("utf-8")
    assert reference.replace(":username}}", ":password}}") in saved.decode("utf-8")
    assert inputs == {path: path.read_bytes() for path in inputs}
    assert SYNC.sync(root, False, "dev", "123456789012", {"quicksight"}) == 0


if __name__ == "__main__":
    raise SystemExit(main())

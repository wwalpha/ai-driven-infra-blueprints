#!/usr/bin/env python3
"""Checks for authoritative properties, service displays and service failure protection."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import redirect_stderr
import io
import importlib.util
import json
import os
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from model_design import properties, markdown_for, naming_errors, stack_model, display_rows
from design_layout import stack_design, stack_deployment_policy, SUBNET_LIST_PROPERTIES, CODEBUILD_VPC_PROPERTIES, HEADER, ALIGNMENT, expanded_display_rows
from model_design import row_table
from design_layout import resource_display_name, resource_anchor, resource_has_name_property
from security_group_tables import COMMENTS, GROUP_COMMENTS


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("model_sync", Path(__file__).with_name("sync-model.py"))
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def model(service, kind, name, rows, logical_id=None, label=None):
    anchor = resource_anchor(service, name, kind)
    result = {
        f"desired.service.{service}.serviceId": service,
        f"desired.service.{service}.ownedCatalogResourceTypes": kind,
        "display.service.title": f"# {service} 詳細設計",
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.logicalId": logical_id or name,
        "desired.resource.001.anchor": anchor,
        "display.resource.001.comment": "対象環境のデータ処理を提供するresource",
    }
    if label:
        result["display.resource.001.label"] = label
    for number, (field, value, comment) in enumerate(rows, 1):
        key = f"001-{number:03d}"
        result[f"desired.row.{key}.property"] = kind + "." + field
        result[f"desired.row.{key}.value"] = value
        result[f"desired.row.{key}.comment"] = comment
    return result


def text(values):
    return "# Authoritative design values\n" + "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def roundtrip(path, values, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_for(path, values, root), encoding="utf-8")
    projected = properties(SYNC.model_for(path, root))
    expected = {key: value for key, value in values.items() if not key.startswith("display.")}
    assert projected == expected, (path.name, {key: (projected.get(key), expected.get(key)) for key in projected.keys() | expected.keys() if projected.get(key) != expected.get(key)})
    return path.read_text(encoding="utf-8")


def check_config_typed_anchors():
    recorder, channel = "Config.ConfigurationRecorder", "Config.DeliveryChannel"
    recorder_anchor = "config-configuration-recorder-default"
    channel_anchor = "config-delivery-channel-default"
    assert resource_anchor("config", "default", recorder) == recorder_anchor
    assert resource_anchor("config", "default", channel) == channel_anchor
    assert resource_anchor("config", "DEFAULT", recorder) == recorder_anchor
    assert resource_anchor("s3", "app/data", "S3.Bucket") == "s3-app-data"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "alias": alias, "awsAccountId": "123456789012",
             "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}
            for alias in ("cde", "non-cde")
        ]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/cde/config.md"
        values = model("config", recorder, "default", [
            ("Name", "`default`", "構成情報を記録するrecorderの名前"),
            ("Id", f"[Recorder](#{recorder_anchor})", "recorderを識別するID"),
            ("RoleARN", "`AWSServiceRoleForConfig`", "記録に使用するservice linked role"),
        ], "Recorder")
        values.update({
            "desired.service.config.ownedCatalogResourceTypes": recorder + "," + channel,
            "desired.resource.001.anchor": recorder_anchor,
            "observed.row.001-002.property": recorder + ".Id",
            "observed.row.001-002.value": "`default`",
            "observed.row.001-002.comment": values["desired.row.001-002.comment"],
            "desired.resource.002.resourceType": channel,
            "desired.resource.002.logicalId": "Channel",
            "desired.resource.002.anchor": channel_anchor,
            "display.resource.002.comment": "構成情報をS3へ配信するchannel",
            "desired.row.002-001.property": channel + ".Name",
            "desired.row.002-001.value": "`default`",
            "desired.row.002-001.comment": "構成情報を配信するchannelの名前",
            "desired.row.002-002.property": channel + ".S3BucketName",
            "desired.row.002-002.value": "`config-records`",
            "desired.row.002-002.comment": "構成情報を保存するS3 bucketの名前",
        })
        output = roundtrip(path, values, root)
        assert properties(SYNC.imported_model(path, root)) == values
        for kind, anchor, logical_id in ((recorder, recorder_anchor, "Recorder"), (channel, channel_anchor, "Channel")):
            assert f"### {kind}: default" in output
            assert f"| 1 | [default](#{anchor}) |" in output
            assert SYNC.linked_resource(path, f"[default](#{anchor})") == (kind, logical_id)
        metadata = {path: ("config", (recorder, channel))}
        catalog = SYNC.view_validator(root, root).catalog_design_properties()

        def failures(markdown):
            path.write_text(markdown, encoding="utf-8")
            validator = SYNC.view_validator(root, root)
            validator.check_resource_names(metadata, [path])
            validator.check_design_tables(metadata, *catalog, [path])
            validator.check_design_overviews([path])
            validator.check_design_links(catalog[2], [path])
            return validator.errors

        assert not failures(output), failures(output)
        for key, wrong in (("001", "config-default"), ("001", channel_anchor),
                           ("002", "config-default"), ("002", recorder_anchor)):
            invalid = {**values, f"desired.resource.{key}.anchor": wrong}
            try:
                markdown_for(path, invalid, root)
            except ValueError as error:
                assert "anchor must be unique and match its name" in str(error)
            else:
                raise AssertionError("untyped or wrong-type Config anchor accepted")
            correct = values[f"desired.resource.{key}.anchor"]
            assert any("anchor must use display name" in error for error in failures(output.replace(correct, wrong)))

        # Case normalization still rejects collisions within the same type.
        collision = {key: value for key, value in values.items() if not key.startswith(("desired.resource.002.", "desired.row.002-"))}
        collision["desired.service.config.ownedCatalogResourceTypes"] = recorder
        for key, value in list(values.items()):
            if key.startswith(("desired.resource.001.", "desired.row.001-", "observed.row.001-")):
                collision[key.replace("001", "002", 1)] = value.replace("Recorder", "SecondRecorder") if key.endswith(("logicalId", "value")) else value
        collision["desired.row.002-001.value"] = "`DEFAULT`"
        try:
            markdown_for(path, collision, root)
        except ValueError as error:
            assert "anchor must be unique and match its name" in str(error)
        else:
            raise AssertionError("same-type normalized anchor collision accepted")

        assert not failures(output), failures(output)
        hub = model("securityhub", "SecurityHub.Hub", "securityhub.hub", [
            ("EnableDefaultStandards", "`true`", "標準を有効にする設定"),
        ], "Hub")
        hub["desired.note.001.text"] = f"記録先: [default](config.md#{recorder_anchor})"
        hub["desired.note.002.text"] = f"配信先: [default](config.md#{channel_anchor})"
        roundtrip(path.with_name("securityhub.md"), hub, root)
        validator = SYNC.view_validator(root, root)
        validator.check_design_links(catalog[2])
        assert not validator.errors, validator.errors
        source = root / "model/dev/cde/config.properties"
        source.parent.mkdir(parents=True)
        source.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "cde", services=["config"]) == 0
        assert SYNC.sync(root, False, "dev", "cde", services=["config"]) == 0
        assert source.read_text(encoding="utf-8") == text(values)
        assert path.read_text(encoding="utf-8") == output
    print("Config anchors: PASS (same-name resources, typed links, roundtrip, namespaces and collision rejection)")


def check_kms_alias_display():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        path = root / "docs/designs/dev/123456789012/kms.md"
        name, logical_id = "venus-dev-log-cde", "CdeLogKey"
        anchor = resource_anchor("kms", name)
        values = model("kms", "KMS.Key", name, [("KeyId", f"[{logical_id}](#{anchor})", "一意に識別するID")], logical_id)
        values.update({"desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
                       "observed.row.001-001.property": "KMS.Key.KeyId",
                       "observed.row.001-001.value": "`PENDING_DEPLOY`",
                       "observed.row.001-001.comment": "一意に識別するID"})

        def add_alias(identity, alias):
            values.update({f"desired.resource.{identity}.resourceType": "KMS.Alias",
                           f"desired.resource.{identity}.logicalId": "Alias" + identity,
                           f"desired.resource.{identity}.anchor": resource_anchor("kms", alias),
                           f"desired.resource.{identity}.parentProperty": "KMS.Alias.TargetKeyId",
                           f"desired.resource.{identity}.parentReference": f"[{logical_id}](#{anchor})",
                           f"desired.row.{identity}-001.property": "KMS.Alias.AliasName",
                           f"desired.row.{identity}-001.value": f"`{alias}`",
                           f"desired.row.{identity}-001.comment": "keyを識別するalias"})

        add_alias("002", "alias/" + name)
        output = roundtrip(path, values, root)
        assert f"| 1 | [{name}](#{anchor}) |" in output
        assert f"### KMS.Key: {name}" in output
        assert "`alias/venus-dev-log-cde`" in output
        assert "<!-- resource-logical-id: CdeLogKey -->" in output
        assert properties(SYNC.imported_model(path, root)) == values
        metadata = {path: ("kms", ("KMS.Key", "KMS.Alias"))}
        validator = SYNC.view_validator(root, root)
        validator.check_resource_names(metadata, [path])
        validator.check_design_overviews([path])
        validator.check_design_links(validator.catalog_design_properties()[2], [path])
        assert not validator.errors, validator.errors
        path.write_text(output.replace(f"### KMS.Key: {name}", "### KMS.Key: CDE用ログキー（log）"), encoding="utf-8")
        validator = SYNC.view_validator(root, root)
        validator.check_resource_names(metadata, [path])
        assert any("heading must display resource name" in error for error in validator.errors), validator.errors

        add_alias("003", "alias/venus-dev-audit-cde")
        for label in (None, "CDE用ログキー（log）"):
            invalid = dict(values)
            if label:
                invalid["display.resource.001.label"] = label
            try:
                markdown_for(path, invalid, root)
            except ValueError as error:
                assert "multiple aliases" in str(error), error
            else:
                raise AssertionError("ambiguous KMS alias was selected automatically")
        values["display.resource.001.label"] = name
        roundtrip(path, values, root)
        assert properties(SYNC.imported_model(path, root)) == values
        assert resource_display_name("KMS.Key", []) is None
        for alias in ("alias/", "venus-dev-log-cde"):
            try:
                resource_display_name("KMS.Key", [["1", "KMS.Alias.AliasName", alias, "alias"]])
            except ValueError:
                pass
            else:
                raise AssertionError("invalid AliasName was used as a Key display name")


def check_nameless_type_display():
    spec = importlib.util.spec_from_file_location("nameless_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        docs = root / "docs/designs/dev/123456789012"
        kind, logical_id = "GuardDuty.Detector", "SecurityDetector"
        anchor = resource_anchor("guardduty", kind)
        rows = [("Id", f"[{logical_id}](#{anchor})", "検出器を識別するID"), ("Enable", "`true`", "脅威検出を有効にする設定")]
        values = model("guardduty", kind, kind.lower(), rows, logical_id)
        values.update({"observed.row.001-001.property": kind + ".Id", "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": rows[0][2],
                       "desired.note.001.text": f"参照: [{kind}](#{anchor})"})
        path = docs / "guardduty.md"
        output = roundtrip(path, values, root)
        assert output.count(f"### {kind}\n") == 2  # Overview and detail.
        assert f"### {kind}:" not in output
        assert f"<!-- resource-logical-id: {logical_id} -->" in output
        imported = properties(SYNC.imported_model(path, root))
        assert "display.resource.001.label" not in imported
        assert imported == values
        assert SYNC.linked_resource(path, f"[{kind}](#{anchor})") == (kind, logical_id)
        metadata = {path: ("guardduty", (kind,))}
        catalog = validator_module.Validator(root).catalog_design_properties()

        def failures(markdown):
            path.write_text(markdown, encoding="utf-8")
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata, [path])
            validator.check_design_tables(metadata, *catalog, [path])
            validator.check_design_overviews([path])
            validator.check_design_links(catalog[2], [path])
            return validator.errors

        assert not failures(output), failures(output)
        for invalid, message in (
            (output.replace(f"<!-- resource-logical-id: {logical_id} -->", ""), "hidden logical ID"),
            (output.replace(anchor, "guardduty-wrong"), "anchor must use display name"),
            (output.replace(f"参照: [{kind}]", "参照: [wrong]"), "nameless resource link"),
            (output.replace(f"参照: [{kind}]", f"参照: [{logical_id}]"), "must not display internal logical ID"),
        ):
            errors = failures(invalid)
            assert any(message in error for error in errors), (message, errors)
        assert not failures(output), failures(output)
        source = root / "model/dev/123456789012/guardduty.properties"
        source.parent.mkdir(parents=True)
        source.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        assert source.read_text(encoding="utf-8") == text(values)
        assert path.read_text(encoding="utf-8") == output
        hub = model("securityhub", "SecurityHub.Hub", "securityhub.hub", [("EnableDefaultStandards", "`true`", "標準を有効にする設定")], "Hub")
        hub["desired.note.001.text"] = f"参照: [{kind}](guardduty.md#{anchor})"
        hub_path = docs / "securityhub.md"
        roundtrip(hub_path, hub, root)
        validator = validator_module.Validator(root)
        validator.check_design_links(catalog[2])
        assert not validator.errors, validator.errors
        hub_path.unlink()
        # Generated identifiers remain observed values and do not become display names.
        current = {**values, "observed.row.001-001.value": "`0123456789abcdef0123456789abcdef`"}
        assert f"### {kind}:" not in roundtrip(path, current, root)
        # Confirmed labels are preserved, including for a single nameless resource.
        labeled = {key: value.replace(anchor, "guardduty-primary-detector") for key, value in values.items()}
        labeled["display.resource.001.label"] = "primary-detector"
        assert f"### {kind}: primary-detector" in roundtrip(path, labeled, root)
        assert properties(SYNC.imported_model(path, root))["display.resource.001.label"] == "primary-detector"
        second = model("guardduty", kind, "secondary-detector", [("Id", "[SecondDetector](#guardduty-secondary-detector)", rows[0][2]), rows[1]], "SecondDetector", "secondary-detector")
        second.update({"observed.row.001-001.property": kind + ".Id", "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": rows[0][2]})
        additional = {key.replace(".001", ".002", 1): value for key, value in second.items()
                      if key.startswith(("desired.resource.", "desired.row.", "observed.row.", "display.resource."))}
        try:
            markdown_for(path, {**values, **additional}, root)
        except ValueError as error:
            assert "single nameless independent resource" in str(error)
        else:
            raise AssertionError("multiple resources accepted a type-only display")
        multiple = roundtrip(path, {**labeled, **additional}, root)
        assert not failures(multiple), failures(multiple)
        mixed = multiple.replace("guardduty-primary-detector", anchor).replace("primary-detector", kind)
        assert any("single nameless independent resource" in error for error in failures(mixed))
        # An optional name property omitted from rows is still a named resource type.
        assert resource_has_name_property(root, "CodeCommit.Repository")
        assert resource_has_name_property(root, "SNS.Topic")
        assert not resource_has_name_property(root, kind)
        topic = model("sns", "SNS.Topic", "sns.topic", [], "Topic")
        try:
            markdown_for(docs / "sns.md", topic, root)
        except ValueError as error:
            assert "single nameless independent resource" in str(error)
        else:
            raise AssertionError("omitted optional name accepted a type-only display")
        path.write_text(output.replace(kind, "SNS.Topic").replace(anchor, "guardduty-sns.topic"), encoding="utf-8")
        validator = validator_module.Validator(root)
        validator.check_resource_names({path: ("guardduty", ("SNS.Topic",))}, [path])
        assert any("single nameless independent resource" in error for error in validator.errors)
        assert resource_display_name(kind, [["1", "Tags[].Key", "`Name`", "キー"], ["2", "Tags[].Value", "`selected-name`", "名前"]]) == "selected-name"
    print("Nameless type display: PASS (generation, import, identity, references, single/multiple and named types)")


def check_nameless_logical_id_label():
    spec = importlib.util.spec_from_file_location("label_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/guardduty.md"
        source = root / "model/dev/123456789012/guardduty.properties"
        source.parent.mkdir(parents=True)
        kind = "GuardDuty.MalwareProtectionPlan"
        assert not resource_has_name_property(root, kind)
        values = {}
        for number, label in enumerate(("BuildProtectionPlan", "QuarantineProtectionPlan"), 1):
            anchor = resource_anchor("guardduty", label)
            rows = [("MalwareProtectionPlanId", f"[{label}](#{anchor})", "検査planを識別するID"),
                    ("ProtectedResource.S3Bucket.BucketName", "`app-dev-data`", "検査対象のbucket"),
                    ("Role", "`scan-role`", "検査に使用するrole")]
            item = model("guardduty", kind, label.lower(), rows, label, label)
            item.update({"observed.row.001-001.property": kind + ".MalwareProtectionPlanId",
                         "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": rows[0][2],
                         "display.resource.001.comment": f"{label}の対象bucketを検査するplan"})
            values.update({key.replace(".001", f".{number:03d}", 1): value for key, value in item.items()})
        source.write_text(text(values), encoding="utf-8")
        output = roundtrip(path, values, root)
        metadata = {path: ("guardduty", (kind,))}

        def failures(model_values, markdown=output):
            source.write_text(text(model_values), encoding="utf-8")
            path.write_text(markdown, encoding="utf-8")
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata, [path])
            return validator.errors

        assert not failures(values), failures(values)
        assert properties(SYNC.imported_model(path, root)) == values
        for identity, label in (("001", "BuildProtectionPlan"), ("002", "QuarantineProtectionPlan")):
            assert f"<!-- resource-logical-id: {label} -->" in output
            assert f"[{label}](#guardduty-{label.lower()})" in output
            assert values[f"desired.row.{identity}-001.value"] == f"[{label}](#guardduty-{label.lower()})"
            assert values[f"observed.row.{identity}-001.value"] == "`PENDING_DEPLOY`"
            key = f"display.resource.{identity}.label"
            invalid = [{name: value for name, value in values.items() if name != key}]
            invalid += [{**values, key: value} for value in ("", "UNSET", "PENDING_DEPLOY", "wrong-label")]
            invalid += [{**values, f"desired.resource.{identity}.{field}": value}
                        for field, value in (("resourceType", "GuardDuty.Detector"), ("logicalId", "OtherPlan"))]
            for bad in invalid:
                errors = failures(bad)
                assert any("resource without a name requires a display label" in error for error in errors), errors
            assert any("hidden logical ID" in error for error in failures(values, output.replace(f"<!-- resource-logical-id: {label} -->", "")))
        assert any("anchor must use display name" in error for error in failures(values, output.replace("guardduty-buildprotectionplan", "guardduty-wrong")))
        # Resource entry numbers belong to the model, not the Markdown order.
        renumbered = {key.replace(".001", ".007", 1): value for key, value in values.items()}
        assert not failures(renumbered), failures(renumbered)
        named = {key: value.replace(kind, "SNS.Topic") for key, value in values.items()}
        assert any("resource without a name requires a display label" in error for error in failures(named, output.replace(kind, "SNS.Topic")))
        failures(values)
        source.unlink()
        validator = validator_module.Validator(root)
        validator.check_resource_names(metadata, [path])
        assert any("resource without a name requires a display label" in error for error in validator.errors)
        assert not failures(values), failures(values)
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        assert source.read_text(encoding="utf-8") == text(values)
        assert path.read_text(encoding="utf-8") == output
    print("Nameless logical ID label: PASS (explicit labels, missing labels, identity, hidden IDs, anchors and namespaces)")


def check_required_name_tag(kind):
    spec = importlib.util.spec_from_file_location("endpoint_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    if kind == "EC2.VPCEndpoint":
        service, name, logical_id = "vpc", "vpce-app-dev-s3", "S3Endpoint"
        identifier, current_id, reference_property = "Id", "vpce-0123456789abcdef0", "VpcEndpointId"
        before = [("ServiceName", "`com.amazonaws.ap-northeast-1.s3`", "接続先service")]
        after = [("VpcEndpointType", "`Gateway`", "Endpointの接続方式"), ("VpcId", "`vpc-0123456789abcdef0`", "所属VPC")]
    else:
        service, name, logical_id = "ec2", "dev-app-vulnerability-scan-01", "VULNERABILITYSCANINSTANCE01"
        identifier, current_id, reference_property = "InstanceId", "i-0123456789abcdef0", "InstanceId"
        before = [("ImageId", "`ami-0123456789abcdef0`", "起動するAMI"), ("InstanceType", "`t3.micro`", "Instanceの種類")]
        after = []
    tags = [("Tags[].Key", "`Name`", "名前を識別するタグのキー"), ("Tags[].Value", f"`{name}`", "resourceを識別する名前")]
    invalid_tags = [[], tags[:1], [("Tags[].Key", "`name`", "キー"), tags[1]],
                    [("Tags[].Key", "`NAME`", "キー"), tags[1]], tags * 2,
                    [("Name", f"`{name}`", "設計専用property")],
                    [("Name", f"`{name}`", "設計専用property"), *tags],
                    [("Tags", f'`{{"Name":"{name}"}}`', "正式arrayではないタグ")],
                    [tags[0], before[0], tags[1]]]
    invalid_tags += [[tags[0], ("Tags[].Value", value, "未確定の名前")]
                     for value in ("", "``", "`   `", "`UNSET`", "` UNSET `", "`PENDING_DEPLOY`", "`Pending`", "`TBD`", "`none`", "`not-used`", "`{{application}}`", f"[{name}](#{service}-{name})")]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / f"docs/designs/dev/123456789012/{service}.md"
        path.parent.mkdir(parents=True)
        rows = [(identifier, f"[{logical_id}](#{service}-{name})", "resourceを識別するID"), *before, *tags, *after]
        values = model(service, kind, name, rows, logical_id, "fallback-label")
        values.update({"observed.row.001-001.property": kind + "." + identifier, "observed.row.001-001.value": f"`{current_id}`", "observed.row.001-001.comment": rows[0][2],
                       "desired.note.001.text": f"参照: [{name}](#{service}-{name})"})
        output = roundtrip(path, values, root)
        assert f"### {kind}: {name}" in output
        assert f"[{name}](#{service}-{name})" in output and "fallback-label" not in output
        assert f"<!-- resource-logical-id: {logical_id} -->" in output
        assert f"| 1 | {identifier} | `{current_id}` |" in output
        assert kind + ".Name" not in properties(SYNC.model_for(path, root)).values()
        base = root / "model/dev/123456789012"
        base.mkdir(parents=True)
        source = base / f"{service}.properties"
        source.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        saved = path.read_bytes()
        metadata = {path: (service, (kind,))}
        outputs = validator_module.Validator(root).catalog_design_properties()[2]
        validator = validator_module.Validator(root)
        validator.check_resource_names(metadata)
        validator.check_design_links(outputs)
        assert not validator.errors, validator.errors
        # Ordinary navigation uses Name, while identifier references retain observed IDs.
        for label in ("wrong-label", current_id, logical_id):
            path.write_text(output.replace(f"参照: [{name}]", f"参照: [{label}]"), encoding="utf-8")
            validator = validator_module.Validator(root)
            validator.check_design_links(outputs)
            assert any("link must display Name tag" in error for error in validator.errors)
        reference = path.with_name("route.md")
        reference.write_text(f'''# Route参照検証
- Design service ID: `route`
- Owned catalog resource types: `EC2.RouteTable`
<a id="vpc-route"></a>
### EC2.RouteTable: route
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.Route.{reference_property} | [{current_id}]({service}.md#{service}-{name}) | 宛先EndpointのID |
''', encoding="utf-8")
        path.write_bytes(saved)
        validator = validator_module.Validator(root)
        validator.check_design_links(outputs)
        assert not validator.errors, validator.errors
        projected = properties(SYNC.model_for(reference, root))
        assert projected["desired.row.001-001.value"] == f"[{logical_id}]({service}.md#{service}-{name})"
        assert projected["observed.row.001-001.value"] == current_id
        reference.unlink()
        path.write_text(output.replace(f"### {kind}: {name}", f"### {kind}: wrong-name"), encoding="utf-8")
        validator = validator_module.Validator(root)
        validator.check_resource_names(metadata)
        assert any("heading must display resource name" in error for error in validator.errors)
        path.write_bytes(saved)
        for bad_tags in invalid_tags:
            bad_rows = [rows[0], *before, *bad_tags, *after]
            bad = model(service, kind, name, bad_rows, logical_id, name)
            formal_rows = [[str(i), kind + "." + field, value, comment] for i, (field, value, comment) in enumerate(bad_rows, 1)]
            validator = validator_module.Validator(root)
            validator.check_required_name_tag(path, kind, name, formal_rows)
            assert validator.errors, bad_tags
            for generate in (lambda: resource_display_name(kind, formal_rows), lambda: markdown_for(path, bad, root)):
                try:
                    generate()
                except ValueError as error:
                    assert str(error) in validator.errors[0], (error, validator.errors)
                else:
                    raise AssertionError(f"invalid Name tag accepted: {bad_tags}")
            # Design-name validation reports the same shared error, without crashing.
            rendered = output[:output.index(f"| 1 | {identifier} |")]
            rendered += "\n".join(f"| {i} | {field} | {value} | {comment} |" for i, (field, value, comment) in enumerate(bad_rows, 1)) + "\n"
            path.write_text(rendered, encoding="utf-8")
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata)
            assert validator.errors, bad_tags
        path.write_bytes(saved)
        # A missing tag rejects this service before saved Markdown changes.
        source.write_text(text(model(service, kind, name, [rows[0], *before, *after], logical_id, name)), encoding="utf-8")
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "Tags[].Key=Name" in str(error)
        else:
            raise AssertionError("service generation accepted a display label without Name tag")
        assert path.read_bytes() == saved
        pending = {**values, "observed.row.001-001.value": "`PENDING_DEPLOY`"}
        roundtrip(path, pending, root)
        wrong_anchor = {**values, "desired.resource.001.anchor": f"{service}-{logical_id.lower()}"}
        try:
            markdown_for(path, wrong_anchor, root)
        except ValueError as error:
            assert "anchor" in str(error)
        else:
            raise AssertionError("logical-ID-derived anchor accepted")
    print(f"{kind} Name tag checks: PASS ({len(invalid_tags)} rejected cases; design, generation, IDs and references)")


def check_codebuild_required_name():
    spec = importlib.util.spec_from_file_location("codebuild_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    kind, name = "CodeBuild.Project", "cbld-app-dev-build"
    name_row = ("Name", f"`{name}`", "projectの名前")
    rows = [("Id", f"[BuildProject](#codebuild-{name})", "projectを識別するID"),
            ("Artifacts.Type", "`NO_ARTIFACTS`", "成果物の方式"),
            ("Environment.ComputeType", "`BUILD_GENERAL1_SMALL`", "計算能力"),
            ("Environment.Image", "`aws/codebuild/standard:7.0`", "build環境のimage"),
            ("Environment.Type", "`LINUX_CONTAINER`", "build環境の方式"),
            ("ServiceRole", "`build-role`", "buildの実行権限"),
            ("Source.Type", "`NO_SOURCE`", "入力の方式")]
    invalid = [[], [name_row, name_row], [("name", f"`{name}`", "誤ったproperty")],
               [("Tags[].Key", "`Name`", "タグのキー"), ("Tags[].Value", f"`{name}`", "タグの値")]]
    invalid += [[("Name", value, "未確定の名前")] for value in
                ("", "``", "`   `", "`UNSET`", "` UNSET `", "`PENDING_DEPLOY`", "`Pending`", "`TBD`", "`none`", "`未確定`", "`{{application}}`", f"[{name}](#codebuild-{name})")]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        path = root / "docs/designs/dev/123456789012/codebuild.md"
        values = model("codebuild", kind, name, [name_row, *rows], "BuildProject", name)
        values.update({"observed.row.001-002.property": kind + ".Id", "observed.row.001-002.value": "`PENDING_DEPLOY`", "observed.row.001-002.comment": rows[0][2]})
        output = roundtrip(path, values, root)
        source = root / "model/dev/123456789012/codebuild.properties"
        source.parent.mkdir(parents=True)
        source.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        saved = path.read_bytes()
        metadata = {path: ("codebuild", (kind,))}
        validator = validator_module.Validator(root)
        validator.check_resource_names(metadata)
        assert not validator.errors, validator.errors
        for bad_names in invalid:
            bad_rows = [*bad_names, *rows]
            formal_rows = [[str(i), kind + "." + field, value, comment] for i, (field, value, comment) in enumerate(bad_rows, 1)]
            assert naming_errors(root, kind, formal_rows), bad_names
            assert naming_errors(root, kind, [[row[0], row[1].removeprefix(kind + "."), *row[2:]] for row in formal_rows]), bad_names
            bad = model("codebuild", kind, name, bad_rows, "BuildProject", name)
            try:
                markdown_for(path, bad, root)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid CodeBuild Name accepted: {bad_names}")
            rendered = output[:output.index("| 1 | Name |")]
            rendered += "\n".join(f"| {i} | {field} | {value} | {comment} |" for i, (field, value, comment) in enumerate(bad_rows, 1)) + "\n"
            path.write_text(rendered, encoding="utf-8")
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata)
            assert any("CodeBuild.Project.Name" in error for error in validator.errors), (bad_names, validator.errors)
        path.write_bytes(saved)
        source.write_text(text(model("codebuild", kind, name, rows, "BuildProject", name)), encoding="utf-8")
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "CodeBuild.Project.Name" in str(error), error
        else:
            raise AssertionError("service generation accepted a label without CodeBuild Name")
        assert path.read_bytes() == saved
    print(f"CodeBuild required Name checks: PASS ({len(invalid)} rejected cases; design, generation and saved view)")


def check_iam_role_name():
    spec = importlib.util.spec_from_file_location("iam_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    kind, name, logical_id = "IAM.Role", "app-dev-worker-role", "WorkerRole"
    name_row = ("RoleName", f"`{name}`", "workerの実行権限を識別するロール名")
    trust_row = ("AssumeRolePolicyDocument", "[WorkerTrust](iam/worker-role-trust-policy.json)", "workerからの引受を許可する信頼ポリシー")
    document = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}, separators=(",", ":"))
    invalid = [[], [name_row, name_row], [("Tags[].Key", "`Name`", "タグのキー"), ("Tags[].Value", f"`{name}`", "タグの値")]]
    invalid += [[("RoleName", value, "未確定の名前")] for value in
                ("", "``", "`   `", "`UNSET`", "` UNSET `", "`PENDING_DEPLOY`", "`Pending`", "`TBD`", "`none`", "`未確定`", "`{{application}}`", f"[{name}](#iam-{name})")]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        source = root / "model/dev/123456789012/iam.properties"
        source.parent.mkdir(parents=True)
        values = model("iam", kind, name, [name_row, trust_row], logical_id, "fallback-label")
        values["desired.row.001-002.document"] = document
        source.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        path = root / "docs/designs/dev/123456789012/iam.md"
        output = path.read_text(encoding="utf-8")
        assert f"| 1 | [{name}](#iam-{name}) |" in output
        assert f"### IAM.Role: {name}" in output and "fallback-label" not in output
        assert f"<!-- resource-logical-id: {logical_id} -->" in output
        projected = properties(SYNC.model_for(path, root))
        assert projected["desired.resource.001.logicalId"] == logical_id
        assert projected["desired.row.001-001.value"] == f"`{name}`"
        assert source.read_text(encoding="utf-8") == text(values)
        metadata = {path: ("iam", (kind,))}
        outputs = validator_module.Validator(root).catalog_design_properties()[2]

        def failures(markdown):
            path.write_text(markdown, encoding="utf-8")
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata, [path])
            validator.check_design_overviews([path])
            validator.check_design_links(outputs)
            return validator.errors

        assert not failures(output), failures(output)
        reference = path.with_name("reference.md")
        for label in (name, logical_id, "wrong-name", "/service-role/" + name):
            reference.write_text(f"参照: [{label}](iam.md#iam-{name})\n", encoding="utf-8")
            errors = failures(output)
            assert bool(errors) == (label != name), (label, errors)
        reference.unlink()
        assert failures(output.replace(f"[{name}](#iam-{name})", f"[{logical_id}](#iam-{name})"))
        assert failures(output.replace(f"### IAM.Role: {name}", f"### IAM.Role: {logical_id}"))
        for bad_names in invalid:
            bad_rows = [*bad_names, trust_row]
            formal_rows = [[str(i), kind + "." + field, value, comment] for i, (field, value, comment) in enumerate(bad_rows, 1)]
            assert naming_errors(root, kind, formal_rows), bad_names
            assert naming_errors(root, kind, [[row[0], row[1].removeprefix(kind + "."), *row[2:]] for row in formal_rows]), bad_names
            bad = model("iam", kind, name, bad_rows, logical_id, name)
            try:
                markdown_for(path, bad, root)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid IAM RoleName accepted: {bad_names}")
            rendered = output[:output.index("| 1 | RoleName |")]
            rendered += "\n".join(f"| {i} | {field} | {value} | {comment} |" for i, (field, value, comment) in enumerate(bad_rows, 1)) + "\n"
            assert any("IAM.Role.RoleName" in error for error in failures(rendered)), bad_names
    print(f"IAM RoleName checks: PASS ({len(invalid)} rejected cases; generation, names, links and model)")


def check_naming_exclusions():
    spec = importlib.util.spec_from_file_location("naming_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        for kind, field in (("IAM.ManagedPolicy", "ManagedPolicyName"), ("IAM.User", "UserName"), ("IAM.InstanceProfile", "InstanceProfileName"),
                            ("Config.ConfigurationRecorder", "Name"), ("Config.DeliveryChannel", "Name"),
                            ("Glue.Connection", "ConnectionInput.Name"), ("GuardDuty.Detector", "Name"),
                            ("Glue.Database", "DatabaseInput.Name"), ("Glue.Table", "TableInput.Name"),
                            ("SecretsManager.Secret", "Name"),
                            ("Route53.HostedZone", "Name"), ("Route53.RecordSet", "Name")):
            service = kind.split(".")[0].lower()
            path = root / f"docs/designs/dev/123456789012/{service}.md"
            for prop in (field, kind + "." + field):
                assert not naming_errors(root, kind, [["1", prop, "`example`", "名前"]])
            required_rows = {
                "IAM.ManagedPolicy": [("PolicyDocument", '`{"Version":"2012-10-17","Statement":[]}`', "権限の文書")],
                "IAM.InstanceProfile": [("Roles", '`["example"]`', "所属するロール")],
                "Config.ConfigurationRecorder": [("RoleARN", "[example](iam.md#iam-example)", "記録に使用するロール")],
                "Config.DeliveryChannel": [("S3BucketName", "`example`", "配信先のバケット")],
                "Glue.Connection": [("CatalogId", "`123456789012`", "カタログのID"),
                                    ("ConnectionInput", '`{"Name":"example","ConnectionType":"JDBC"}`', "接続の設定")],
                "Glue.Database": [("CatalogId", "`123456789012`", "カタログのID")],
                "Glue.Table": [("CatalogId", "`123456789012`", "カタログのID"),
                               ("DatabaseName", "`example`", "所属するデータベース")],
                "GuardDuty.Detector": [("Enable", "`true`", "検出の有効化")],
                "Route53.RecordSet": [("Type", "`A`", "レコードの種類")],
            }
            values = model(service, kind, "example", [(field, "`example`", "名前"), *required_rows.get(kind, [])])
            output = roundtrip(path, values, root)
            metadata = {path: (service, (kind,))}
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata, [path])
            assert not validator.errors, validator.errors
            # Exemption does not bypass value checks or apply to Name tags.
            for invalid in ("", "UNSET", "PENDING_DEPLOY"):
                path.write_text(output.replace("`example`", f"`{invalid}`"), encoding="utf-8")
                validator = validator_module.Validator(root)
                validator.check_resource_names(metadata, [path])
                assert any("resource display name must be confirmed" in error for error in validator.errors)
                values["desired.row.001-001.value"] = f"`{invalid}`"
                try:
                    markdown_for(path, values, root)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"naming exemption accepted an unconfirmed display name: {kind}: {invalid}")
            assert naming_errors(root, kind, [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"example"', "名前"]]) == [f"naming rule missing: {kind}: Name tag"]
    assert not naming_errors(ROOT, "IAM.Role", [["1", "RoleName", "`example`", "名前"]])
    assert naming_errors(ROOT, "IAM.Group", [["1", "GroupName", "`example`", "名前"]]) == ["naming rule missing: IAM.Group: GroupName"]
    assert naming_errors(ROOT, "Glue.Job", [["1", "name", "`example`", "名前"]]) == ["naming rule missing: Glue.Job: name"]
    schema = validator_module.DesignSchemaCatalog(ROOT)
    assert schema.literal_errors("Config.ConfigurationRecorder", "Name", "UNSET")
    assert schema.literal_errors("Route53.HostedZone", "Name", "x" * 1025)
    for kind, field in (("SecretsManager.Secret", "Name"), ("Glue.Database", "DatabaseInput.Name"), ("Glue.Table", "TableInput.Name")):
        assert schema.literal_errors(kind, field, "UNSET")
    try:
        schema.property_schema("GuardDuty.Detector", "Name")
    except KeyError:
        pass
    else:
        raise AssertionError("naming exemption added an unsupported GuardDuty property")
    print("Naming exclusions: PASS (12 properties; design, generation, value/schema checks and coverage boundaries)")


def check_security_group_and_glue_catalog_naming():
    text = (ROOT / "framework/rules/aws-resource-naming.md").read_text(encoding="utf-8")
    group_pattern = "{{environment}}-{{application}}-{{service}}-{{purpose}}-{{number}}-sg"
    assert f"| `EC2.SecurityGroup` | `GroupName` | `{group_pattern}` |" in text
    assert f"| `EC2.SecurityGroup` | Name tag | `{group_pattern}` |" in text
    assert "| `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |" in text
    for kind, fields in (
        ("EC2.SecurityGroup", [("GroupName", "dev-app-glue-data-01-sg")]),
        ("EC2.SecurityGroup", [("Tags[].Key", "Name"), ("Tags[].Value", "dev-app-glue-data-01-sg")]),
        ("Glue.Catalog", [("Name", "glct-app-dev-data")]),
    ):
        for prefix in ("", kind + "."):
            rows = [[str(number), prefix + field, f"`{value}`", "名称"]
                    for number, (field, value) in enumerate(fields, 1)]
            assert not naming_errors(ROOT, kind, rows), kind
    assert not naming_errors(ROOT, "EC2.SecurityGroup", [])
    print("Security Group and Glue Catalog naming: PASS (exact patterns, formal/short properties, optional Name tag)")


def check_security_naming():
    from design_catalog import DesignSchemaCatalog
    schema = DesignSchemaCatalog(ROOT)
    text = (ROOT / "framework/rules/aws-resource-naming.md").read_text(encoding="utf-8")
    patterns = {}
    for line in text.splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[2] and cells[4].startswith(("waf", "nfw", "scp", "fmsp", "sspb", "ssma", "ssmw", "mwtg", "mwts", "cfgr", "vbpe")):
            patterns[cells[2]] = (cells[3], cells[4])
    assert len(patterns) == 15
    for kind, (field, pattern) in patterns.items():
        if kind.startswith("WAFv2."):
            assert pattern.startswith("waf")
        for shared in (False, True) if kind == "Organizations.Policy" else (False,):
            name = pattern.replace("[-{{environment}}]", "" if shared else "-dev")
            for key, value in (("application", "app"), ("environment", "dev"), ("purpose", "patching")):
                name = name.replace("{{" + key + "}}", value)
            assert "{{" not in name
            fields = [("Tags[].Key", "Name"), ("Tags[].Value", name)] if field == "Name tag" else [(field, name)]
            rows = [[str(number), prop, f"`{value}`", "名称"] for number, (prop, value) in enumerate(fields, 1)]
            assert not naming_errors(ROOT, kind, rows), kind
            assert not naming_errors(ROOT, kind, [[row[0], kind + "." + row[1], *row[2:]] for row in rows]), kind
            for prop, value in fields:
                assert schema.literal_errors(kind, prop, value) == [], (kind, prop)
                selected = (ROOT / "framework/materials/aws" / (kind.replace(".", "_", 1) + ".properties")).read_text(encoding="utf-8")
                assert f"{kind}.{prop}=" in selected
    for kind in ("EC2.TransitGateway", "EC2.TransitGatewayVpcAttachment", "EC2.TransitGatewayRouteTable"):
        assert not naming_errors(ROOT, kind, [["1", "Tags[].Key", "`Name`", "タグ"], ["2", "Tags[].Value", "`tgw-app-dev-patching-01`", "名称"]])
    assert not naming_errors(ROOT, "SSM.Association", [["1", "Name", "`AWS-RunPatchBaseline`", "参照document"]])
    assert not naming_errors(ROOT, "EC2.VPCBlockPublicAccessOptions", [["1", "InternetGatewayBlockMode", "`block-ingress`", "遮断設定"]])
    assert not naming_errors(ROOT, "EC2.VPCBlockPublicAccessExclusion", [["1", "InternetGatewayExclusionMode", "`allow-egress`", "除外設定"]])
    print("Security naming: PASS (15 patterns, catalog/schema, formal/short properties, TGW and optional names)")


def check_stack_policy():
    naming = (ROOT / "framework/rules/aws-resource-naming.md").read_text(encoding="utf-8")
    assert "| `CloudFormation.Stack` | `StackName` | `cfn-stack-{{application}}-{{environment}}-{{purpose}}[-{{number}}]` |" in naming
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{
            "environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        values = {"desired.deployment.maxConcurrentStacks": "3"}
        for i, (name, order) in enumerate((("app-b", "20"), ("network", "10"), ("app-a", "20")), 1):
            key = f"{i:03d}"
            values.update({f"desired.stack.{key}.name": f"cfn-stack-app-dev-{name}" + ("-01" if name == "app-b" else ""),
                           f"desired.stack.{key}.template": "app.yaml" if order == "20" else "network.yaml",
                           f"desired.stack.{key}.parameters": name + ".json",
                           f"desired.stack.{key}.deployOrder": order,
                           f"display.stack.{key}.comment": name + "を配置するstack"})
        source = root / "model/dev/123456789012/cloudformation-stacks.properties"
        source.parent.mkdir(parents=True)
        source.write_text(text(values), encoding="utf-8")
        before = source.read_bytes()
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert source.read_bytes() == before
        path = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        rendered = path.read_text(encoding="utf-8")
        assert "## Deployment設定" not in rendered and "| MaxConcurrentStacks |" not in rendered
        assert "<!-- max-concurrent-stacks: 3 -->" in rendered
        assert "| Deploy<br>Order |" in rendered
        assert stack_deployment_policy(path) == 3
        stacks = stack_design(path)
        assert [s["name"] for s in stacks] == ["cfn-stack-app-dev-network", "cfn-stack-app-dev-app-a", "cfn-stack-app-dev-app-b-01"]
        assert [s["deployOrder"] for s in stacks] == ["10", "20", "20"]
        assert [s["parameters"] for s in stacks] == ["network.json", "app-a.json", "app-b.json"]
        assert [s["comment"] for s in stacks] == ["networkを配置するstack", "app-aを配置するstack", "app-bを配置するstack"]
        assert stacks[1]["template"] == stacks[2]["template"]
        projected = properties(SYNC.model_for(path, root))
        assert stack_model(projected)[0] == stack_model(values)[0]
        assert [s for _, s in stack_model(projected)[1]] == [s for _, s in stack_model(values)[1]]
        assert "dependsOn" not in projected
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        # Default policy stays hidden and preserves the model.
        del values["desired.deployment.maxConcurrentStacks"]
        source.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert stack_deployment_policy(path) == 1
        saved = path.read_bytes()
        for field, value in (("desired.stack.001.deployOrder", "0"), ("desired.stack.001.deployOrder", "-1"),
                             ("desired.stack.001.deployOrder", "abc"), ("desired.deployment.maxConcurrentStacks", "0"),
                             ("desired.deployment.maxConcurrentStacks", "-1"), ("desired.deployment.maxConcurrentStacks", "1.5")):
            source.write_text(text(values | {field: value}), encoding="utf-8")
            try:
                SYNC.sync(root, True, "dev", "123456789012")
            except ValueError as error:
                assert "integer >= 1" in str(error), error
            else:
                raise AssertionError((field, value))
            assert path.read_bytes() == saved
        del values["desired.stack.001.deployOrder"]
        source.write_text(text(values), encoding="utf-8")
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "migration required" in str(error)
        else:
            raise AssertionError("legacy order silently inferred")
        assert path.read_bytes() == saved
    print("Stack policy model checks: PASS (sorting, identity, comments, default 1, invalid policy, legacy fail closed)")



def check_stack_mapping_roundtrip():
    from model_design import cfn_resource_identity
    from design_layout import resource_identity_metadata
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        path = root / "docs/designs/dev/123456789012/ec2.md"
        values = model("ec2", "EC2.VPC", "vpc-app-dev-data", [
            ("Name", "`vpc-app-dev-data`", "ネットワークの名称"),
            ("VpcId", "[001](#ec2-vpc-app-dev-data)", "ネットワークのID"),
            ("CidrBlock", "`10.0.0.0/16`", "ネットワークの範囲")])
        del values["desired.resource.001.logicalId"]
        values.update({"observed.row.001-002.property": "EC2.VPC.VpcId",
                       "observed.row.001-002.value": "`PENDING_DEPLOY`",
                       "observed.row.001-002.comment": "ネットワークのID"})
        # Terraform needs neither a generic logicalId nor a CFn identity.
        rendered = roundtrip(path, values, root)
        assert "cfn-logical-id:" not in rendered
        assert "desired.resource.001.logicalId" not in SYNC.model_for(path, root)
        project = root / "project.json"
        project.write_text(json.dumps({"projectName": "fixture", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "terraform"}]}))
        roundtrip(path, values, root)
        values["desired.resource.001.cfn-logicalId"] = "cfn-stack-app-dev-ism-DepartmentVpc"
        try:
            markdown_for(path, values, root)
        except ValueError as error:
            assert "forbidden for Terraform" in str(error)
        else:
            raise AssertionError("Terraform accepted CFn metadata")
        project.write_text(project.read_text().replace('"terraform"', '"cloudformation"'))
        stack_source = root / "model/dev/123456789012/cloudformation-stacks.properties"
        stack_source.parent.mkdir(parents=True)
        stack_source.write_text("\n".join(f"desired.stack.{index:03d}.{field}={value}" for index, purpose in enumerate(("ism", "key"), 1)
                                          for field, value in {"name": "cfn-stack-app-dev-" + purpose, "template": "shared.yaml", "parameters": purpose + ".json", "deployOrder": "10"}.items()))
        without_id = {key: value for key, value in values.items() if not key.endswith(".cfn-logicalId")}
        try:
            markdown_for(path, without_id, root)
        except ValueError as error:
            assert "cfn-logicalId required" in str(error)
        else:
            raise AssertionError("new CloudFormation model has no stack/resource ID")
        rendered = roundtrip(path, values, root)
        assert cfn_resource_identity(values["desired.resource.001.cfn-logicalId"]) == ("cfn-stack-app-dev-ism", "DepartmentVpc")
        assert "cfn-logical-id: ec2-vpc-app-dev-data cfn-stack-app-dev-ism-DepartmentVpc" in rendered
        for invalid in ("", "invalid", "stack-resource", "stack-Bad_Id", "stack-Resource-With-Hyphens", " stack-Resource", "stack-Resource "):
            try:
                cfn_resource_identity(invalid)
            except ValueError:
                pass
            else:
                # Hyphens are valid inside StackName; only its final segment is the resource ID.
                assert invalid == "stack-Resource-With-Hyphens"
        for candidate in (rendered.replace("ism-DepartmentVpc -->", "ism-OtherVpc -->"),
                          rendered.replace("<!-- resource-entry: ec2-vpc-app-dev-data 001 -->", "")):
            path.write_text(candidate)
            try:
                SYNC.validate_views(root, root, [path], {path: values})
            except ValueError as error:
                assert "projection mismatch" in str(error), error
            else:
                raise AssertionError("identity metadata change silently accepted")
        try:
            resource_identity_metadata(rendered.splitlines() + ["<!-- cfn-logical-id: absent stack-Resource -->"])
        except ValueError:
            pass
        else:
            raise AssertionError("orphan CFn marker accepted")
        # Independent numbering survives grouped display order; Key and Alias each have a CFn ID.
        kms_path = path.with_name("kms.md")
        anchor = "kms-app-dev-data"
        kms = model("kms", "KMS.Key", "app-dev-data", [("KeyId", f"[007](#{anchor})", "一意に識別するID")], label="app-dev-data")
        kms = {key.replace(".001", ".007"): value for key, value in kms.items() if not key.endswith(".logicalId")}
        kms.update({"desired.service.kms.ownedCatalogResourceTypes": "KMS.Key,KMS.Alias",
                    "desired.resource.007.cfn-logicalId": "cfn-stack-app-dev-key-Key",
                    "observed.row.007-001.property": "KMS.Key.KeyId", "observed.row.007-001.value": "`PENDING_DEPLOY`", "observed.row.007-001.comment": "一意に識別するID",
                    "desired.resource.021.resourceType": "KMS.Alias", "desired.resource.021.anchor": "kms-alias-app-dev-data",
                    "desired.resource.021.cfn-logicalId": "cfn-stack-app-dev-key-Alias",
                    "desired.resource.021.parentProperty": "KMS.Alias.TargetKeyId", "desired.resource.021.parentReference": f"[007](#{anchor})",
                    "desired.row.021-001.property": "KMS.Alias.AliasName", "desired.row.021-001.value": "`alias/app-dev-data`", "desired.row.021-001.comment": "keyを識別するalias"})
        grouped = roundtrip(kms_path, kms, root)
        assert "<!-- resource-entry: kms-alias-app-dev-data 021 -->" in grouped
        # Stack identity is owned by each resource; a separate mapping table is rejected.
        stacks = {"desired.stack.001.name": "cfn-stack-app-dev-ism", "desired.stack.001.template": "shared.yaml",
                  "desired.stack.001.parameters": "ism.json", "desired.stack.001.deployOrder": "10"}
        try:
            stack_model(stacks | {"desired.mapping.001.stack": "cfn-stack-app-dev-ism"})
        except ValueError as error:
            assert "unknown stack design" in str(error)
        else:
            raise AssertionError("obsolete stack mapping accepted")
    print("Resource identity checks: PASS (CFn stack/resource metadata, Terraform without logicalId, lossless projection, obsolete table rejection)")


def check_subnet_list_display():
    # Catalog coverage is explicit: single IDs and arrays of objects keep their format.
    catalog = {line.partition("=")[0] for path in (ROOT / "framework/materials/aws").glob("*.properties")
               for line in path.read_text(encoding="utf-8").splitlines() if "=" in line}
    subnet_lists = {prop for prop in catalog if prop.rsplit(".", 1)[-1].removesuffix("[]") in {"SubnetIds", "Subnets", "VpcSubnetIds"}}
    assert SUBNET_LIST_PROPERTIES == subnet_lists
    assert len(subnet_lists) == 15  # 14 arrays and Secrets Manager's string list.
    for prop in sorted(subnet_lists):
        kind = ".".join(prop.split(".")[:2])
        field = prop.removeprefix(kind + ".").removesuffix("[]")
        links = ["[subnet-a](vpc.md#subnet-a)", "[PENDING_DEPLOY](vpc.md#subnet-b)"]
        inputs = [[["1", prop, value, "配置先Subnet"] for value in links]]
        if prop not in CODEBUILD_VPC_PROPERTIES:
            raw = "`subnet-a, subnet-b`" if kind == "SecretsManager.RotationSchedule" else '`[ "subnet-a" , "subnet-b" ]`'
            inputs += [[["1", prop, raw, "配置先Subnet"]]]
            if prop.endswith("[]"):
                inputs += [[["1", prop, "`subnet-a`", "配置先Subnet"], ["2", prop, "`subnet-b`", "配置先Subnet"]]]
            if kind != "SecretsManager.RotationSchedule":
                inputs += [[["1", prop, json.dumps(links), "参照先Subnet"]]]
        for rows in inputs:
            shown = display_rows(kind, rows)
            assert [row[1] for row in shown] == [field + "[1]", field + "[2]"], (prop, shown)
            document = [f"### {kind}: list-owner", "", *row_table(shown)]
            restored = expanded_display_rows(document)
            formal = [line for line in restored if line.startswith("|") and line not in {HEADER, ALIGNMENT}]
            assert formal == ["| " + " | ".join([str(number), *row[1:]]) + " |" for number, row in enumerate(rows, 1)], (prop, formal)
            assert display_rows(kind, rows) == shown  # Counts reset for every resource.
            for bad in (
                document[:-1],  # Missing second list element.
                [line.replace(field + "[2]", field + "[3]") for line in document],
                [line.replace(field + "[2]", field + "[1]") for line in document],
                [line.replace(field + "[1]", field + "[0]") for line in document],
                [line.replace(field + "[1]", field) for line in document],
            ):
                # A shortened link-only list is valid; saved-array markers require all elements.
                if bad == document[:-1] and len(rows) == 2:
                    continue
                try:
                    expanded_display_rows(bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError((prop, bad))
            if len(rows) == 1:
                for bad in (
                    [line.replace("| " + shown[0][2] + " |", "| `subnet-other` |") for line in document],
                    [*document[:-1], document[-1].replace(shown[-1][3], "別の説明")],
                ):
                    try:
                        expanded_display_rows(bad)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError((prop, bad))
        if prop not in CODEBUILD_VPC_PROPERTIES:
            bad_values = ["`subnet-a,,subnet-b`", "` `"] if kind == "SecretsManager.RotationSchedule" else ["[]", "[1]", '[null]', '[""]', '{}', '["a|b"]']
            for value in bad_values:
                try:
                    display_rows(kind, [["1", prop, value, "配置先Subnet"]])
                except ValueError:
                    pass
                else:
                    raise AssertionError((prop, value))
    # The motivating Lambda array survives full generation and model projection unchanged.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        values = model("lambda", "Lambda.Function", "lambda-app-dev", [
            ("FunctionName", "`lambda-app-dev`", "関数の名称"),
            ("Code.S3Bucket", "`lambda-code`", "コードの保管先"),
            ("Role", "[lambda-role](iam.md#lambda-role)", "実行権限"),
            ("VpcConfig.SubnetIds", '`["subnet-a", "subnet-b"]`', "配置先Subnet"),
        ])
        output = roundtrip(root / "docs/designs/dev/123456789012/lambda.md", values, root)
        assert "VpcConfig.SubnetIds[1]" in output and "VpcConfig.SubnetIds[2]" in output
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [
            {"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"},
        ]}) + "\n", encoding="utf-8")
        base = root / "model/dev/123456789012"
        base.mkdir(parents=True)
        iam = model("iam", "IAM.Role", "net-dev-flow-role", [
            ("RoleName", "`net-dev-flow-role`", "実行権限を識別する名称"),
            ("AssumeRolePolicyDocument", "[信頼ポリシー](iam/net-dev-flow-role-trust-policy.json)", "Lambdaによる引受けを許可"),
        ])
        iam["desired.row.001-002.document"] = json.dumps({"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"},
        ]})
        values = model("lambda", "Lambda.Function", "lambda-app-dev", [
            ("FunctionName", "`lambda-app-dev`", "関数の名称"),
            ("Code.S3Bucket", "`lambda-code`", "コードの保管先"),
            ("Handler", "`index.handler`", "実行する入口"),
            ("Role", "[net-dev-flow-role](iam.md#iam-net-dev-flow-role)", "実行権限"),
            ("Runtime", "`nodejs22.x`", "コードの実行環境"),
            ("VpcConfig.SubnetIds", '`[ "subnet-00000000000000001", "subnet-00000000000000002" ]`', "配置先Subnet"),
        ])
        source = base / "lambda.properties"
        source.write_text(text(values), encoding="utf-8")
        (base / "iam.properties").write_text(text(iam), encoding="utf-8")
        before = source.read_bytes()
        assert SYNC.sync(root, True, "dev", "123456789012", services=["iam", "lambda"]) == 0
        path = root / "docs/designs/dev/123456789012/lambda.md"
        saved = path.read_bytes()
        assert source.read_bytes() == before
        assert SYNC.sync(root, False, "dev", "123456789012", services=["lambda"]) == 0
        values["desired.row.001-006.value"] = "[]"
        source.write_text(text(values), encoding="utf-8")
        invalid = source.read_bytes()
        try:
            SYNC.sync(root, True, "dev", "123456789012", services=["lambda"])
        except ValueError as error:
            assert "Subnet list" in str(error), str(error)
        else:
            raise AssertionError("invalid Subnet list was saved")
        assert path.read_bytes() == saved and source.read_bytes() == invalid
    print("Subnet list display: PASS (15 properties, links, JSON/CSV source preservation, invalid displays, Lambda model roundtrip)")


def check_athena_configuration_display():
    kind = "Athena.WorkGroup"
    prefix = kind + ".WorkGroupConfiguration."
    fields = [line.partition("=")[0] for line in
              (ROOT / "framework/materials/aws/athena_workgroup.properties").read_text(encoding="utf-8").splitlines()]
    rows = [[str(index), field, "値", "設定の説明"] for index, field in enumerate(fields, 1)]
    displayed = display_rows(kind, rows)
    from design_layout import DISPLAY_PROPERTY_ALIASES, formal_property
    encryption_labels = {
        prefix + "ResultConfiguration.EncryptionConfiguration.EncryptionOption": "ResultConfiguration.Encryption.Option",
        prefix + "ResultConfiguration.EncryptionConfiguration.KmsKey": "ResultConfiguration.Encryption.KmsKey",
    }
    for original, shown in zip(rows, displayed):
        expected = encryption_labels.get(original[1], original[1].removeprefix(prefix if original[1].startswith(prefix) else kind + "."))
        assert shown == [original[0], expected, *original[2:]], (original, shown)
        restored = formal_property(shown[1], kind)
        assert DISPLAY_PROPERTY_ALIASES.get(restored, restored) == original[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
        values = model("athena", kind, "athwg-app-dev", [
            ("Name", "`athwg-app-dev`", "クエリ実行用の名前"),
            ("WorkGroupConfiguration.EnforceWorkGroupConfiguration", "true", "設定を強制する"),
            ("WorkGroupConfiguration.EngineVersion.SelectedEngineVersion", "`Athena engine version 3`", "使用するエンジン"),
            ("WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.EncryptionOption", "`SSE_KMS`", "結果を暗号化する方式"),
            ("WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey", "`12345678-1234-1234-1234-123456789012`", "結果の暗号化に使用するキー"),
        ])
        output = roundtrip(root / "docs/designs/dev/123456789012/athena.md", values, root)
        assert "| EnforceWorkGroupConfiguration | true |" in output
        assert "| EngineVersion.SelectedEngineVersion |" in output
        assert "| ResultConfiguration.Encryption.Option | `SSE_KMS` |" in output
        assert "| ResultConfiguration.Encryption.KmsKey | `12345678-1234-1234-1234-123456789012` |" in output
        assert "ResultConfiguration.EncryptionConfiguration.EncryptionOption" not in output
        assert "ResultConfiguration.EncryptionConfiguration.KmsKey" not in output
        assert "WorkGroupConfiguration." not in output
    print("Athena configuration display checks: PASS (catalog aliases and model roundtrip)")


def main():
    check_subnet_list_display()
    check_athena_configuration_display()
    check_config_typed_anchors()
    check_kms_alias_display()
    check_nameless_type_display()
    check_nameless_logical_id_label()
    check_stack_policy()
    check_stack_mapping_roundtrip()
    check_security_naming()
    check_security_group_and_glue_catalog_naming()
    check_naming_exclusions()
    check_codebuild_required_name()
    check_iam_role_name()
    for kind in ("EC2.VPCEndpoint", "EC2.Instance"):
        check_required_name_tag(kind)
    for kind, field in (("Logs.LogGroup", "LogGroupName"), ("Scheduler.Schedule", "Name"), ("EC2.VPC", "Name"), ("Athena.WorkGroup", "Name"), ("CloudTrail.Trail", "TrailName")):
        assert not naming_errors(ROOT, kind, [["1", field, "`example`", "名前"]])
    assert naming_errors(ROOT, "CloudFront.CachePolicy", [["1", "CachePolicyConfig.Name", "`example`", "名前"]])
    assert not naming_errors(ROOT, "Glue.Connection", [["1", "Name", "`PENDING_DEPLOY`", "生成される名前"]])
    assert not naming_errors(ROOT, "Glue.Connection", [["1", "ConnectionInput.Name", "`example`", "作成する接続の名前"]])
    assert not naming_errors(ROOT, "Scheduler.Schedule", [["1", "GroupName", "`default`", "所属先"]])
    assert not naming_errors(ROOT, "SecurityHub.Hub", [["1", "EnableDefaultStandards", "`true`", "標準を有効化"]])
    assert not naming_errors(ROOT, "SecurityHub.Hub", [["1", "Tags[].Key", '"purpose"', "タグ"], ["2", "Tags[].Value", '"security"', "用途"]])
    assert naming_errors(ROOT, "SecurityHub.Hub", [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"security"', "名前"]])
    assert not naming_errors(ROOT, "EC2.Instance", [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"app"', "名前"]])
    for invalid in ("x=1\nx=2\n", "missing-separator\n"):
        try:
            properties(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid model accepted")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        shutil.copytree(ROOT / "framework", root / "framework")
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        base = root / "model/dev/123456789012"
        base.mkdir(parents=True)
        vpc = model("vpc", "EC2.VPC", "vpc-net-dev", [("Name", "`vpc-net-dev`", "識別するNameタグ"), ("VpcId", "[Vpc](#vpc-vpc-net-dev)", "一意に識別するID"), ("CidrBlock", "`10.1.0.0/16`", "IPv4のアドレス範囲")], "Vpc")
        vpc["observed.row.001-002.property"] = "EC2.VPC.VpcId"
        vpc["observed.row.001-002.value"] = "`PENDING_DEPLOY`"
        vpc["observed.row.001-002.comment"] = "一意に識別するID"
        logs = model("logs", "Logs.LogGroup", "cwlogs-net-dev-flow", [("LogGroupName", "`cwlogs-net-dev-flow`", "ログを保存する名前"), ("RetentionInDays", "`30`", "ログを保持する日数")])
        iam = model("iam", "IAM.Role", "net-dev-flow-role", [("RoleName", "`net-dev-flow-role`", "権限を識別する名前"), ("AssumeRolePolicyDocument", "[信頼ポリシー](iam/flow-role-trust-policy.json)", "引受元に許可する権限")], "FlowRole")
        iam["desired.row.001-002.document"] = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "vpc-flow-logs.amazonaws.com"}, "Action": "sts:AssumeRole"}]}, separators=(",", ":"))
        sources = {base / "vpc.properties": vpc, base / "logs.properties": logs, base / "iam.properties": iam}
        for path, values in sources.items():
            path.write_text(text(values), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        saved_sources = {path: path.read_bytes() for path in sources}
        docs = root / "docs/designs/dev/123456789012"
        assert "Version" in (docs / "iam.md").read_text(encoding="utf-8")
        assert "PENDING_DEPLOY" in (docs / "vpc.md").read_text(encoding="utf-8")
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        assert saved_sources == {path: path.read_bytes() for path in sources}
        logs["desired.row.001-002.value"] = "`14`"
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        old_docs = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "vpc.properties").write_text(text(vpc) + "desired.row.001-003.value=bad-duplicate\n", encoding="utf-8")
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "duplicate model property" in str(error)
        else:
            raise AssertionError("invalid service was not reported")
        assert "`14`" in (docs / "logs.md").read_text(encoding="utf-8")
        assert (docs / "vpc.md").read_bytes() == old_docs[docs / "vpc.md"]
        assert (docs / "iam.md").read_bytes() == old_docs[docs / "iam.md"]
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert "`14`" in (docs / "logs.md").read_text(encoding="utf-8")
        logs["desired.row.001-002.value"] = "`not-a-number`"
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        old_docs = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "provider schema violation" in str(error)
        else:
            raise AssertionError("invalid property value bypassed validation")
        assert old_docs == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        def fails_with(message, write=True):
            try:
                SYNC.sync(root, write, "dev", "123456789012")
            except ValueError as error:
                assert message in str(error), error
                return str(error)
            else:
                raise AssertionError(f"service failure was not reported: {message}")

        # Missing JSON input preserves this service's Markdown and JSON; others save.
        logs["desired.row.001-002.value"] = "`7`"
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        without_document = {key: value for key, value in iam.items() if not key.endswith(".document")}
        (base / "iam.properties").write_text(text(without_document), encoding="utf-8")
        fails_with("authoritative JSON document missing")
        assert (docs / "iam.md").read_bytes() == old_docs[docs / "iam.md"]
        assert (docs / "iam/flow-role-trust-policy.json").read_bytes() == old_docs[docs / "iam/flow-role-trust-policy.json"]
        assert "`7`" in (docs / "logs.md").read_text(encoding="utf-8")
        assert (base / "iam.properties").read_text(encoding="utf-8") == text(without_document)
        # Read-only checks report stale successes without modifying any view.
        logs["desired.row.001-002.value"] = "`14`"
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        fails_with("generated Markdown is stale or missing", write=False)
        assert snapshot == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "iam.properties").write_text(text(iam), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0

        # Failed targets use saved anchors; dependents must not publish broken links.
        renamed_logs = {**logs, "desired.resource.001.anchor": "logs-cwlogs-new-dev-flow",
                        "desired.row.001-001.value": "`cwlogs-new-dev-flow`",
                        "desired.row.001-002.value": "`not-a-number`"}
        (base / "logs.properties").write_text(text(renamed_logs), encoding="utf-8")
        vpc["desired.note.001.text"] = "参照: [cwlogs-new-dev-flow](logs.md#logs-cwlogs-new-dev-flow)"
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        fails_with("missing design anchor")
        assert snapshot == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        renamed_logs["desired.row.001-002.value"] = "`14`"
        (base / "logs.properties").write_text(text(renamed_logs), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert "logs-cwlogs-new-dev-flow" in (docs / "vpc.md").read_text(encoding="utf-8")
        del vpc["desired.note.001.text"]
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0

        # A failed source retains its old link, but must not block its valid target.
        old_link = "logs.md#logs-cwlogs-net-dev-flow"
        new_link = "logs.md#logs-cwlogs-new-dev-flow"
        vpc["desired.note.001.text"] = f"参照: [cwlogs-net-dev-flow]({old_link})"
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "logs.properties").write_text(text(renamed_logs), encoding="utf-8")
        iam["desired.row.001-002.comment"] = "引受元に許可する権限を定義する設定"
        (base / "iam.properties").write_text(text(iam), encoding="utf-8")
        saved_sources = {path: path.read_bytes() for path in sources}
        warnings = io.StringIO()
        with redirect_stderr(warnings):
            error = fails_with("missing design anchor")
        assert "2 services succeeded; 1 services failed" in error
        assert f"vpc.md: {old_link}" in warnings.getvalue()
        assert new_link.partition("#")[2] in (docs / "logs.md").read_text(encoding="utf-8")
        assert (docs / "vpc.md").read_bytes() == snapshot[docs / "vpc.md"]
        assert (docs / "iam.md").read_bytes() != snapshot[docs / "iam.md"]
        assert (docs / "iam/flow-role-trust-policy.json").read_bytes() == snapshot[docs / "iam/flow-role-trust-policy.json"]
        assert saved_sources == {path: path.read_bytes() for path in sources}
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        fails_with("missing design anchor", write=False)
        assert snapshot == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        assert saved_sources == {path: path.read_bytes() for path in sources}

        # Matching source/target changes publish together, including in read-only verification.
        vpc["desired.note.001.text"] = f"参照: [cwlogs-new-dev-flow]({new_link})"
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        saved_sources = {path: path.read_bytes() for path in sources}
        # A source write failure retains its old link without rolling back the target.
        (docs / "logs.md").write_bytes(old_docs[docs / "logs.md"])
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        original_write = Path.write_text
        def fail_source(path, *args, **kwargs):
            if path == docs / "vpc.md":
                raise OSError("test source write failure")
            return original_write(path, *args, **kwargs)
        warnings = io.StringIO()
        with patch.object(Path, "write_text", fail_source), redirect_stderr(warnings):
            error = fails_with("test source write failure")
        assert "saved reference needs repair" in warnings.getvalue()
        assert (docs / "vpc.md").read_bytes() == snapshot[docs / "vpc.md"]
        assert (docs / "logs.md").read_bytes() != snapshot[docs / "logs.md"]
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        assert saved_sources == {path: path.read_bytes() for path in sources}
        fails_with("generated Markdown is stale or missing", write=False)
        assert snapshot == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert new_link in (docs / "vpc.md").read_text(encoding="utf-8")
        assert new_link.partition("#")[2] in (docs / "logs.md").read_text(encoding="utf-8")
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        assert saved_sources == {path: path.read_bytes() for path in sources}

        # Already broken links in a retained source do not reject an unrelated candidate.
        retained = docs / "retained.md"
        retained.write_text("参照: [旧参照](logs.md#logs-already-missing)\n", encoding="utf-8")
        logs["desired.row.001-002.value"] = "`7`"
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        del vpc["desired.note.001.text"]
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        error = fails_with("authoritative model missing")
        assert "candidate breaks saved reference" not in error
        assert "`7`" in (docs / "logs.md").read_text(encoding="utf-8")
        # Retained sources without a model also warn without blocking a scoped write.
        retained.write_text(retained.read_text(encoding="utf-8") + f"参照: [ログ]({old_link})\n", encoding="utf-8")
        (base / "logs.properties").write_text(text(renamed_logs), encoding="utf-8")
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        warnings = io.StringIO()
        with redirect_stderr(warnings):
            assert SYNC.sync(root, True, "dev", "123456789012", services=["logs"]) == 0
        assert "retained.md: " + old_link in warnings.getvalue()
        assert "logs-already-missing" not in warnings.getvalue()
        assert (docs / "logs.md").read_bytes() != snapshot[docs / "logs.md"]
        assert all(path.read_bytes() == content for path, content in snapshot.items() if path.name != "logs.md")
        assert SYNC.sync(root, False, "dev", "123456789012", services=["logs"]) == 0
        retained.unlink()
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0

        # A JSON write followed by a Markdown write failure rolls back only IAM.
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        document = json.loads(iam["desired.row.001-002.document"])
        document["Statement"][0]["Sid"] = "Trust"
        iam["desired.row.001-002.document"] = json.dumps(document)
        iam["desired.row.001-002.comment"] = "引受元に許可する権限を定義する設定"
        (base / "iam.properties").write_text(text(iam), encoding="utf-8")
        logs["desired.row.001-002.value"] = "`7`"
        (base / "logs.properties").write_text(text(logs), encoding="utf-8")
        saved_sources = {path: path.read_bytes() for path in sources}
        original_write = Path.write_text
        def fail_iam(path, *args, **kwargs):
            if path == docs / "iam.md":
                raise OSError("test IAM write failure")
            return original_write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_iam):
            fails_with("test IAM write failure")
        assert (docs / "iam.md").read_bytes() == snapshot[docs / "iam.md"]
        assert (docs / "iam/flow-role-trust-policy.json").read_bytes() == snapshot[docs / "iam/flow-role-trust-policy.json"]
        assert "`7`" in (docs / "logs.md").read_text(encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert json.loads((docs / "iam/flow-role-trust-policy.json").read_text(encoding="utf-8")) == document
        assert {path: path.read_bytes() for path in sources} == saved_sources
        # If saving a target fails, roll back views that reference its new anchor.
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "logs.properties").write_text(text(renamed_logs), encoding="utf-8")
        vpc["desired.note.001.text"] = "参照: [cwlogs-new-dev-flow](logs.md#logs-cwlogs-new-dev-flow)"
        (base / "vpc.properties").write_text(text(vpc), encoding="utf-8")
        iam["desired.row.001-002.comment"] = "引受元に許可する権限と条件を定義する設定"
        (base / "iam.properties").write_text(text(iam), encoding="utf-8")
        def fail_logs(path, *args, **kwargs):
            if path == docs / "logs.md":
                raise OSError("test target write failure")
            return original_write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_logs):
            fails_with("missing design anchor")
        assert (docs / "logs.md").read_bytes() == snapshot[docs / "logs.md"]
        assert (docs / "vpc.md").read_bytes() == snapshot[docs / "vpc.md"]
        assert (docs / "iam.md").read_bytes() != snapshot[docs / "iam.md"]
        # The CLI returns failure while persisting an unrelated successful service.
        (root / "tasks").mkdir()
        (root / "tasks/active.md").write_text("## Validation scope\n- `dev/123456789012/iam`\n- `dev/123456789012/logs`\n- `dev/123456789012/vpc`\n", encoding="utf-8")
        (base / "iam.properties").write_text(text(without_document), encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT / "framework/scripts/sync-model.py"),
                                 "--repository-root", str(root), "--write", "--environment", "dev",
                                 "--aws-account-id", "123456789012"], capture_output=True, encoding="utf-8")
        assert result.returncode == 1 and "authoritative JSON document missing" in result.stderr
        assert "logs.md" in result.stdout and "iam.md" not in result.stdout
        assert "cwlogs-new-dev-flow" in (docs / "logs.md").read_text(encoding="utf-8")
        (base / "iam.properties").write_text(text(iam), encoding="utf-8")
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        old_docs = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        # A late filesystem failure restores every previously changed generated file.
        first, last = docs / "logs.md", docs / "vpc.md"
        original_write = Path.write_text
        def fail_last(path, *args, **kwargs):
            if path == last:
                raise OSError("test write failure")
            return original_write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_last):
            try:
                SYNC.save_files({first: "changed\n", last: "changed\n"})
            except OSError:
                pass
            else:
                raise AssertionError("late write failure was swallowed")
        assert old_docs == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}

    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        build = model("codebuild", "CodeBuild.Project", "cbld-app-dev-build", [("Name", "`cbld-app-dev-build`", "projectの名前"), ("Environment.EnvironmentVariables[].Name", "`TARGET`", "実行対象"), ("Environment.EnvironmentVariables[].Type", "`PLAINTEXT`", "実行対象"), ("Environment.EnvironmentVariables[].Value", "`cde`", "実行対象")])
        build.update({"desired.row.001-005.property": "CodeBuild.Project.ServiceRole", "desired.row.001-005.value": "[BuildRole](iam.md#iam-build-role)", "desired.row.001-005.comment": "実行に使用するロール"})
        output = roundtrip(base / "codebuild.md", build, ROOT)
        assert "Environment.Variables.TARGET" in output and "EnvironmentVariables[]" not in output
        detector = model("guardduty", "GuardDuty.Detector", "security-detector", [("Features[].Name", "`S3_DATA_EVENTS`", "検査を有効にする設定"), ("Features[].Status", "`ENABLED`", "検査を有効にする設定")], "Detector", "security-detector")
        detector.update({"desired.row.001-003.property": "GuardDuty.Detector.Enable", "desired.row.001-003.value": "`true`", "desired.row.001-003.comment": "検出の有効化"})
        output = roundtrip(base / "guardduty.md", detector, ROOT)
        assert "Features.S3_DATA_EVENTS" in output
        trail = model("cloudtrail", "CloudTrail.Trail", "audit", [
            ("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`", "操作を記録するS3 bucket"),
            ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`', "操作を記録するS3 bucket"),
            ("EventSelectors[].IncludeManagementEvents", "`true`", "管理イベントを記録する"),
            ("EventSelectors[].ReadWriteType", "`All`", "読み取りと書き込みを記録する"),
            ("IsLogging", "`true`", "記録の有効化"),
            ("S3BucketName", "`audit-logs`", "記録先のバケット"),
        ], "Trail", "audit")
        output = roundtrip(base / "cloudtrail.md", trail, ROOT)
        assert "EventSelectors.DataResources[1].S3" in output and "All current and future" in output
        assert "| EventSelectors.IncludeManagementEvents | `true` | 管理イベントを記録する |" in output
        assert "| EventSelectors.ReadWriteType | `All` | 読み取りと書き込みを記録する |" in output
        assert "EventSelectors[].IncludeManagementEvents" not in output
        assert "EventSelectors[].ReadWriteType" not in output
        pipeline = model("codepipeline", "CodePipeline.Pipeline", "cpln-app-dev-build", [("Name", "`cpln-app-dev-build`", "pipelineの名前"), ("Stages[].Name", "`Source`", "入力を取得するstage"), ("Stages[].Actions[].Name", "`Source`", "入力を取得するaction"), ("Stages[].Actions[].Configuration", '`{"BranchName":"main","PollForSourceChanges":"false"}`', "BranchName: 対象branch / PollForSourceChanges: polling設定"), ("Stages[].Name", "`Build`", "buildを実行するstage"), ("Stages[].Actions[].Name", "`BuildOne`", "最初のbuild"), ("Stages[].Actions[].Configuration", '`{"ProjectName":"one"}`', "ProjectName: 実行するproject"), ("Stages[].Actions[].Name", "`BuildTwo`", "次のbuild")])
        pipeline.update({"desired.row.001-009.property": "CodePipeline.Pipeline.RoleArn", "desired.row.001-009.value": "[PipelineRole](iam.md#iam-pipeline-role)", "desired.row.001-009.comment": "実行に使用するロール"})
        output = roundtrip(base / "codepipeline.md", pipeline, ROOT)
        assert "Stages[1].Actions.Configuration.BranchName" in output
        assert "Stages[2].Actions[1].Name" in output and "Stages[2].Actions[2].Name" in output
        pipeline["desired.row.001-010.property"] = "CodePipeline.Pipeline.Tags[].Key"
        pipeline["desired.row.001-010.value"] = "`purpose`"
        pipeline["desired.row.001-010.comment"] = "タグのキー"
        roundtrip(base / "codepipeline.md", pipeline, ROOT)
        trailing_names = model("codepipeline", "CodePipeline.Pipeline", "cpln-app-dev-build", [
            ("Name", "`cpln-app-dev-build`", "pipelineの名前"),
            ("RoleArn", "[PipelineRole](iam.md#iam-pipeline-role)", "実行に使用するロール"),
            ("Stages[].Actions[].ActionTypeId.Provider", "`CodeCommit`", "source provider"),
            ("Stages[].Actions[].Configuration", '`{"BranchName":"main","PollForSourceChanges":"false"}`', "BranchName: 対象branch / PollForSourceChanges: polling設定"),
            ("Stages[].Actions[].Name", "`SourceAction`", "入力を取得するaction"),
            ("Stages[].Name", "`Source`", "入力を取得するstage"),
            ("Stages[].Actions[].ActionTypeId.Provider", "`CodeBuild`", "build provider"),
            ("Stages[].Actions[].Configuration", '`{"ProjectName":"one"}`', "ProjectName: 実行するproject"),
            ("Stages[].Actions[].InputArtifacts[].Name", "`source-one`", "最初の入力artifact"),
            ("Stages[].Actions[].InputArtifacts[].Name", "`source-two`", "次の入力artifact"),
            ("Stages[].Actions[].Name", "`BuildAction`", "最初のbuild"),
            ("Stages[].Actions[].ActionTypeId.Provider", "`CodeBuild`", "test provider"),
            ("Stages[].Actions[].Configuration", '`{"ProjectName":"two"}`', "ProjectName: 実行するproject"),
            ("Stages[].Actions[].Name", "`TestAction`", "次のbuild"),
            ("Stages[].Name", "`BuildAndTest`", "buildを実行するstage"),
            ("Tags[].Key", "`purpose`", "タグのキー"),
            ("Tags[].Value", "`build`", "タグの値"),
        ])
        output = roundtrip(base / "codepipeline.md", trailing_names, ROOT)
        assert "Stages[1].Actions.Name | `SourceAction`" in output
        assert "Stages[2].Actions[1].Name | `BuildAction`" in output
        assert "Stages[2].Actions[2].Name | `TestAction`" in output
        assert output.index("Stages[1].Actions.Name") < output.index("Stages[1].Name") < output.index("Stages[2].Actions[1].Name")
        hub = model("securityhub", "SecurityHub.Hub", "security-hub", [("EnableDefaultStandards", "`true`", "標準を有効にする設定")], "Hub", "security-hub")
        roundtrip(base / "securityhub.md", hub, ROOT)
        s3 = model("s3", "S3.Bucket", "app-dev-data", [("BucketName", "`app-dev-data`", "データを保管する名前"), ("Region", "`ap-northeast-1`", "配置するregion"), ("BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm", "`aws:kms`", "暗号化方式")])
        output = roundtrip(base / "s3.md", s3, ROOT)
        assert "BucketEncryption[].SSEAlgorithm" in output
        kms = model("kms", "KMS.Key", "app-dev-data", [("KeyId", "[Key](#kms-app-dev-data)", "一意に識別するID")], "Key")
        kms["desired.service.kms.ownedCatalogResourceTypes"] = "KMS.Key,KMS.Alias"
        kms.update({"observed.row.001-001.property": "KMS.Key.KeyId", "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": "一意に識別するID", "desired.resource.002.resourceType": "KMS.Alias", "desired.resource.002.logicalId": "Alias", "desired.resource.002.anchor": "kms-alias-app-dev-data", "desired.resource.002.parentProperty": "KMS.Alias.TargetKeyId", "desired.resource.002.parentReference": "[Key](#kms-app-dev-data)", "desired.row.002-001.property": "KMS.Alias.AliasName", "desired.row.002-001.value": "`alias/app-dev-data`", "desired.row.002-001.comment": "keyを識別するalias"})
        output = roundtrip(base / "kms.md", kms, ROOT)
        assert "### KMS.Alias" not in output and "<!-- logical-id: Alias -->" in output
        sg = model("security_group", "EC2.SecurityGroup", "dev-app-data-01-sg", [("Id", "[Group](#security_group-dev-app-data-01-sg)", GROUP_COMMENTS["Id"]), ("GroupDescription", "`Data access`", GROUP_COMMENTS["GroupDescription"]), ("GroupName", "`dev-app-data-01-sg`", GROUP_COMMENTS["GroupName"]), ("VpcId", "[vpc-app-dev](vpc.md#vpc-vpc-app-dev)", GROUP_COMMENTS["VpcId"]), ("Tags[].Key", '"purpose"', GROUP_COMMENTS["Tags[].Key"]), ("Tags[].Value", '"data"', GROUP_COMMENTS["Tags[].Value"]), ("SecurityGroupIngress[].IpProtocol", "`tcp`", COMMENTS["IpProtocol"]), ("SecurityGroupIngress[].FromPort", "`443`", COMMENTS["FromPort"]), ("SecurityGroupIngress[].ToPort", "`443`", COMMENTS["ToPort"]), ("SecurityGroupIngress[].CidrIp", "`10.1.0.0/16`", COMMENTS["CidrIp"]), ("SecurityGroupEgress[].IpProtocol", "`-1`", COMMENTS["IpProtocol"]), ("SecurityGroupEgress[].CidrIp", "`0.0.0.0/0`", COMMENTS["CidrIp"])], "Group")
        sg.update({"observed.row.001-001.property": "EC2.SecurityGroup.Id", "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": GROUP_COMMENTS["Id"], "desired.service.security_group.ownedCatalogResourceTypes": "EC2.SecurityGroup,EC2.SecurityGroupIngress", "desired.resource.002.resourceType": "EC2.SecurityGroupIngress", "desired.resource.002.logicalId": "Rule", "desired.resource.002.anchor": "security_group-rule", "desired.resource.002.parentProperty": "EC2.SecurityGroupIngress.GroupId", "desired.resource.002.parentReference": "[Group](#security_group-dev-app-data-01-sg)"})
        for number, (field, value) in enumerate((("Id", "[Rule](#security_group-rule)"), ("IpProtocol", "`tcp`"), ("FromPort", "`22`"), ("ToPort", "`22`"), ("SourceSecurityGroupId", "[PENDING_DEPLOY](#security_group-dev-app-data-01-sg)")), 1):
            key = f"002-{number:03d}"
            sg.update({f"desired.row.{key}.property": "EC2.SecurityGroupIngress." + field, f"desired.row.{key}.value": value, f"desired.row.{key}.comment": COMMENTS[field]})
        sg.update({"observed.row.002-001.property": "EC2.SecurityGroupIngress.Id", "observed.row.002-001.value": "PENDING_DEPLOY", "observed.row.002-001.comment": COMMENTS["Id"]})
        # Self references use the parent's canonical logical identity and observed ID.
        sg["desired.row.002-005.value"] = "[Group](#security_group-dev-app-data-01-sg)"
        sg.update({"observed.row.002-005.property": "EC2.SecurityGroupIngress.SourceSecurityGroupId", "observed.row.002-005.value": "PENDING_DEPLOY", "observed.row.002-005.comment": COMMENTS["SourceSecurityGroupId"]})
        output = roundtrip(base / "security_group.md", sg, ROOT)
        assert "| Direction | IpProtocol | Port |" in output
        assert "<!-- security-group-id:" in output and "<!-- rule-id:" in output
        assert "### EC2.SecurityGroupIngress" not in output
        for direction in ("Ingress", "Egress"):
            variant = sg.copy()
            if direction == "Egress":
                variant = {key: value.replace("EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress").replace("SourceSecurityGroupId", "DestinationSecurityGroupId") for key, value in variant.items()}
                variant["desired.row.002-005.comment"] = COMMENTS["DestinationSecurityGroupId"]
                variant["observed.row.002-005.comment"] = COMMENTS["DestinationSecurityGroupId"]
            for identifier in ("PENDING_DEPLOY", "`PENDING_DEPLOY`", "sgr-00000001", "`sgr-00000001`"):
                variant["observed.row.002-001.value"] = identifier
                output = roundtrip(base / "security_group.md", variant, ROOT)
                assert f"<!-- rule-id: {identifier} -->" in output
    print("model_design: PASS (authoritative updates, service rollback, naming coverage and service displays)")


if __name__ == "__main__":
    if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
        import cProfile
        import pstats
        profile = cProfile.Profile()
        try:
            profile.runcall(main)
        finally:
            profile.dump_stats(str(Path(directory) / (Path(__file__).stem + ".prof")))
            pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(25)
    else:
        main()

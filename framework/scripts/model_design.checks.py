#!/usr/bin/env python3
"""Checks for authoritative properties, service displays and service failure protection."""

import importlib.util
import json
import tempfile
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from model_design import properties, markdown_for, naming_errors
from design_layout import resource_display_name
from security_group_tables import COMMENTS, GROUP_COMMENTS


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("model_sync", Path(__file__).with_name("sync-model.py"))
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def model(service, kind, name, rows, logical_id=None, label=None):
    anchor = service + "-" + name
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


def check_endpoint_name_tag():
    spec = importlib.util.spec_from_file_location("endpoint_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    kind, name, logical_id = "EC2.VPCEndpoint", "vpce-app-dev-s3", "S3Endpoint"
    tags = [("Tags[].Key", "`Name`", "名前を識別するタグのキー"), ("Tags[].Value", f"`{name}`", "Endpointを識別する名前")]
    invalid_tags = [[], tags[:1], [("Tags[].Key", "`name`", "キー"), tags[1]],
                    [("Tags[].Key", "`NAME`", "キー"), tags[1]], tags * 2,
                    [("Name", f"`{name}`", "設計専用property")],
                    [("Name", f"`{name}`", "設計専用property"), *tags],
                    [("Tags", f'`{{"Name":"{name}"}}`', "正式arrayではないタグ")],
                    [tags[0], ("VpcEndpointType", "`Gateway`", "対応Valueのないタグ"), tags[1]]]
    invalid_tags += [[tags[0], ("Tags[].Value", value, "未確定の名前")]
                     for value in ("", "``", "`   `", "`UNSET`", "` UNSET `", "`PENDING_DEPLOY`", "`Pending`", "`TBD`", "`none`", "`not-used`", "`{{application}}`", f"[{name}](#vpc-{name})")]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "framework").symlink_to(ROOT / "framework", target_is_directory=True)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        path = root / "docs/designs/dev/123456789012/vpc.md"
        path.parent.mkdir(parents=True)
        rows = [("Id", f"[{logical_id}](#vpc-{name})", "Endpointを識別するID"),
                ("ServiceName", "`com.amazonaws.ap-northeast-1.s3`", "接続先service"), *tags,
                ("VpcEndpointType", "`Gateway`", "Endpointの接続方式"), ("VpcId", "`vpc-0123456789abcdef0`", "所属VPC")]
        values = model("vpc", kind, name, rows, logical_id, "fallback-label")
        values.update({"observed.row.001-001.property": kind + ".Id", "observed.row.001-001.value": "`vpce-0123456789abcdef0`", "observed.row.001-001.comment": rows[0][2],
                       "desired.note.001.text": f"参照: [{name}](#vpc-{name})"})
        output = roundtrip(path, values, root)
        assert f"### {kind}: {name}" in output
        assert f"[{name}](#vpc-{name})" in output and "fallback-label" not in output
        assert f"<!-- resource-logical-id: {logical_id} -->" in output
        assert "| 1 | Id | `vpce-0123456789abcdef0` |" in output
        assert kind + ".Name" not in properties(SYNC.model_for(path, root)).values()
        base = root / "model/dev/123456789012"
        base.mkdir(parents=True)
        source = base / "vpc.properties"
        source.write_text(text(values))
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        saved = path.read_bytes()
        metadata = {path: ("vpc", (kind,))}
        outputs = validator_module.Validator(root).catalog_design_properties()[2]
        validator = validator_module.Validator(root)
        validator.check_resource_names(metadata)
        validator.check_design_links(outputs)
        assert not validator.errors, validator.errors
        # Ordinary navigation uses Name, while identifier references retain observed IDs.
        for label in ("wrong-label", "vpce-0123456789abcdef0", logical_id):
            path.write_text(output.replace(f"参照: [{name}]", f"参照: [{label}]"))
            validator = validator_module.Validator(root)
            validator.check_design_links(outputs)
            assert any("Endpoint link must display" in error for error in validator.errors)
        reference = path.with_name("route.md")
        reference.write_text(f'''# Route参照検証
- Design service ID: `route`
- Owned catalog resource types: `EC2.RouteTable`
<a id="vpc-route"></a>
### EC2.RouteTable: route
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.Route.VpcEndpointId | [vpce-0123456789abcdef0](vpc.md#vpc-{name}) | 宛先EndpointのID |
''')
        path.write_bytes(saved)
        validator = validator_module.Validator(root)
        validator.check_design_links(outputs)
        assert not validator.errors, validator.errors
        projected = properties(SYNC.model_for(reference, root))
        assert projected["desired.row.001-001.value"] == f"[{logical_id}](vpc.md#vpc-{name})"
        assert projected["observed.row.001-001.value"] == "vpce-0123456789abcdef0"
        reference.unlink()
        path.write_text(output.replace(f"### {kind}: {name}", f"### {kind}: wrong-name"))
        validator = validator_module.Validator(root)
        validator.check_resource_names(metadata)
        assert any("heading must display resource name" in error for error in validator.errors)
        path.write_bytes(saved)
        for bad_tags in invalid_tags:
            bad_rows = [rows[0], rows[1], *bad_tags, rows[-1]]
            bad = model("vpc", kind, name, bad_rows, logical_id, name)
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
            rendered = output[:output.index("| 1 | Id |")]
            rendered += "\n".join(f"| {i} | {field} | {value} | {comment} |" for i, (field, value, comment) in enumerate(bad_rows, 1)) + "\n"
            path.write_text(rendered)
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata)
            assert validator.errors, bad_tags
        path.write_bytes(saved)
        # A missing tag rejects this service before saved Markdown changes.
        source.write_text(text(model("vpc", kind, name, rows[:2] + rows[-2:], logical_id, name)))
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "Tags[].Key=Name" in str(error)
        else:
            raise AssertionError("service generation accepted a display label without Name tag")
        assert path.read_bytes() == saved
        pending = {**values, "observed.row.001-001.value": "`PENDING_DEPLOY`"}
        roundtrip(path, pending, root)
        wrong_anchor = {**values, "desired.resource.001.anchor": "vpc-s3endpoint"}
        try:
            markdown_for(path, wrong_anchor, root)
        except ValueError as error:
            assert "anchor" in str(error)
        else:
            raise AssertionError("logical-ID-derived anchor accepted")
    print(f"Endpoint Name tag checks: PASS ({len(invalid_tags)} rejected cases; design, generation, IDs and references)")


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
        (root / "framework").symlink_to(ROOT / "framework", target_is_directory=True)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        path = root / "docs/designs/dev/123456789012/codebuild.md"
        values = model("codebuild", kind, name, [name_row, *rows], "BuildProject", name)
        values.update({"observed.row.001-002.property": kind + ".Id", "observed.row.001-002.value": "`PENDING_DEPLOY`", "observed.row.001-002.comment": rows[0][2]})
        output = roundtrip(path, values, root)
        source = root / "model/dev/123456789012/codebuild.properties"
        source.parent.mkdir(parents=True)
        source.write_text(text(values))
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
            path.write_text(rendered)
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata)
            assert any("CodeBuild.Project.Name" in error for error in validator.errors), (bad_names, validator.errors)
        path.write_bytes(saved)
        source.write_text(text(model("codebuild", kind, name, rows, "BuildProject", name)))
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "CodeBuild.Project.Name" in str(error), error
        else:
            raise AssertionError("service generation accepted a label without CodeBuild Name")
        assert path.read_bytes() == saved
    print(f"CodeBuild required Name checks: PASS ({len(invalid)} rejected cases; design, generation and saved view)")


def check_iam_naming_exclusions():
    spec = importlib.util.spec_from_file_location("iam_validator", Path(__file__).with_name("validate-blueprint.py"))
    validator_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator_module)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "framework").symlink_to(ROOT / "framework", target_is_directory=True)
        path = root / "docs/designs/dev/123456789012/iam.md"
        for kind, field in (("IAM.ManagedPolicy", "ManagedPolicyName"), ("IAM.User", "UserName"), ("IAM.InstanceProfile", "InstanceProfileName")):
            for prop in (field, kind + "." + field):
                assert not naming_errors(root, kind, [["1", prop, "`example`", "名前"]])
            values = model("iam", kind, "example", [(field, "`example`", "名前")])
            output = roundtrip(path, values, root)
            metadata = {path: ("iam", (kind,))}
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata)
            assert not validator.errors, validator.errors
            # Exemption does not bypass value checks or apply to Name tags.
            path.write_text(output.replace("`example`", "`PENDING_DEPLOY`"))
            validator = validator_module.Validator(root)
            validator.check_resource_names(metadata)
            assert any("resource display name must be confirmed" in error for error in validator.errors)
            assert naming_errors(root, kind, [["1", "Tags[].Key", '"Name"', "タグ"], ["2", "Tags[].Value", '"example"', "名前"]]) == [f"naming rule missing: {kind}: Name tag"]
    assert not naming_errors(ROOT, "IAM.Role", [["1", "RoleName", "`example`", "名前"]])
    assert naming_errors(ROOT, "IAM.Group", [["1", "GroupName", "`example`", "名前"]]) == ["naming rule missing: IAM.Group: GroupName"]
    print("IAM naming exclusions: PASS (3 properties; design, generation, value checks and coverage boundaries)")


def main():
    check_iam_naming_exclusions()
    check_codebuild_required_name()
    check_endpoint_name_tag()
    for kind, field in (("Logs.LogGroup", "LogGroupName"), ("Scheduler.Schedule", "Name"), ("EC2.VPC", "Name"), ("Athena.WorkGroup", "Name"), ("CloudTrail.Trail", "TrailName")):
        assert not naming_errors(ROOT, kind, [["1", field, "`example`", "名前"]])
    assert naming_errors(ROOT, "CloudFront.CachePolicy", [["1", "CachePolicyConfig.Name", "`example`", "名前"]])
    assert not naming_errors(ROOT, "Glue.Connection", [["1", "Name", "`PENDING_DEPLOY`", "生成される名前"]])
    assert naming_errors(ROOT, "Glue.Connection", [["1", "ConnectionInput.Name", "`example`", "作成する接続の名前"]])
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
        (root / "framework").symlink_to(ROOT / "framework", target_is_directory=True)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
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
        assert "Version" in (docs / "iam.md").read_text()
        assert "PENDING_DEPLOY" in (docs / "vpc.md").read_text()
        assert SYNC.sync(root, False, "dev", "123456789012") == 0
        assert saved_sources == {path: path.read_bytes() for path in sources}
        logs["desired.row.001-002.value"] = "`14`"
        (base / "logs.properties").write_text(text(logs))
        old_docs = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "vpc.properties").write_text(text(vpc) + "desired.row.001-003.value=bad-duplicate\n")
        try:
            SYNC.sync(root, True, "dev", "123456789012")
        except ValueError as error:
            assert "duplicate model property" in str(error)
        else:
            raise AssertionError("invalid service was not reported")
        assert "`14`" in (docs / "logs.md").read_text()
        assert (docs / "vpc.md").read_bytes() == old_docs[docs / "vpc.md"]
        assert (docs / "iam.md").read_bytes() == old_docs[docs / "iam.md"]
        (base / "vpc.properties").write_text(text(vpc))
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert "`14`" in (docs / "logs.md").read_text()
        logs["desired.row.001-002.value"] = "`not-a-number`"
        (base / "logs.properties").write_text(text(logs))
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
            else:
                raise AssertionError(f"service failure was not reported: {message}")

        # Missing JSON input preserves this service's Markdown and JSON; others save.
        logs["desired.row.001-002.value"] = "`7`"
        (base / "logs.properties").write_text(text(logs))
        without_document = {key: value for key, value in iam.items() if not key.endswith(".document")}
        (base / "iam.properties").write_text(text(without_document))
        fails_with("authoritative JSON document missing")
        assert (docs / "iam.md").read_bytes() == old_docs[docs / "iam.md"]
        assert (docs / "iam/flow-role-trust-policy.json").read_bytes() == old_docs[docs / "iam/flow-role-trust-policy.json"]
        assert "`7`" in (docs / "logs.md").read_text()
        assert (base / "iam.properties").read_text() == text(without_document)
        # Read-only checks report stale successes without modifying any view.
        logs["desired.row.001-002.value"] = "`14`"
        (base / "logs.properties").write_text(text(logs))
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        fails_with("generated Markdown is stale or missing", write=False)
        assert snapshot == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "iam.properties").write_text(text(iam))
        assert SYNC.sync(root, True, "dev", "123456789012") == 0

        # Failed targets use saved anchors; dependents must not publish broken links.
        renamed_logs = {**logs, "desired.resource.001.anchor": "logs-cwlogs-new-dev-flow",
                        "desired.row.001-001.value": "`cwlogs-new-dev-flow`",
                        "desired.row.001-002.value": "`not-a-number`"}
        (base / "logs.properties").write_text(text(renamed_logs))
        vpc["desired.note.001.text"] = "参照: [cwlogs-new-dev-flow](logs.md#logs-cwlogs-new-dev-flow)"
        (base / "vpc.properties").write_text(text(vpc))
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        fails_with("missing design anchor")
        assert snapshot == {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        renamed_logs["desired.row.001-002.value"] = "`14`"
        (base / "logs.properties").write_text(text(renamed_logs))
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert "logs-cwlogs-new-dev-flow" in (docs / "vpc.md").read_text()
        del vpc["desired.note.001.text"]
        (base / "vpc.properties").write_text(text(vpc))
        (base / "logs.properties").write_text(text(logs))
        assert SYNC.sync(root, True, "dev", "123456789012") == 0

        # A JSON write followed by a Markdown write failure rolls back only IAM.
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        document = json.loads(iam["desired.row.001-002.document"])
        document["Statement"][0]["Sid"] = "Trust"
        iam["desired.row.001-002.document"] = json.dumps(document)
        iam["desired.row.001-002.comment"] = "引受元に許可する権限を定義する設定"
        (base / "iam.properties").write_text(text(iam))
        logs["desired.row.001-002.value"] = "`7`"
        (base / "logs.properties").write_text(text(logs))
        original_write = Path.write_text
        def fail_iam(path, *args, **kwargs):
            if path == docs / "iam.md":
                raise OSError("test IAM write failure")
            return original_write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_iam):
            fails_with("test IAM write failure")
        assert (docs / "iam.md").read_bytes() == snapshot[docs / "iam.md"]
        assert (docs / "iam/flow-role-trust-policy.json").read_bytes() == snapshot[docs / "iam/flow-role-trust-policy.json"]
        assert "`7`" in (docs / "logs.md").read_text()
        assert SYNC.sync(root, True, "dev", "123456789012") == 0
        assert json.loads((docs / "iam/flow-role-trust-policy.json").read_text()) == document
        assert {path: path.read_bytes() for path in sources} == {
            base / "vpc.properties": text(vpc).encode(), base / "logs.properties": text(logs).encode(), base / "iam.properties": text(iam).encode()}
        # If saving a target fails, roll back views that reference its new anchor.
        snapshot = {path: path.read_bytes() for path in docs.rglob("*") if path.is_file()}
        (base / "logs.properties").write_text(text(renamed_logs))
        vpc["desired.note.001.text"] = "参照: [cwlogs-new-dev-flow](logs.md#logs-cwlogs-new-dev-flow)"
        (base / "vpc.properties").write_text(text(vpc))
        iam["desired.row.001-002.comment"] = "引受元に許可する権限と条件を定義する設定"
        (base / "iam.properties").write_text(text(iam))
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
        (base / "iam.properties").write_text(text(without_document))
        result = subprocess.run([sys.executable, str(ROOT / "framework/scripts/sync-model.py"),
                                 "--repository-root", str(root), "--write", "--environment", "dev",
                                 "--aws-account-id", "123456789012"], capture_output=True, text=True)
        assert result.returncode == 1 and "authoritative JSON document missing" in result.stderr
        assert "logs.md" in result.stdout and "iam.md" not in result.stdout
        assert "cwlogs-new-dev-flow" in (docs / "logs.md").read_text()
        (base / "iam.properties").write_text(text(iam))
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
        output = roundtrip(base / "codebuild.md", build, ROOT)
        assert "Environment.Variables.TARGET" in output and "EnvironmentVariables[]" not in output
        detector = model("guardduty", "GuardDuty.Detector", "security-detector", [("Features[].Name", "`S3_DATA_EVENTS`", "検査を有効にする設定"), ("Features[].Status", "`ENABLED`", "検査を有効にする設定")], "Detector", "security-detector")
        output = roundtrip(base / "guardduty.md", detector, ROOT)
        assert "Features.S3_DATA_EVENTS" in output
        trail = model("cloudtrail", "CloudTrail.Trail", "audit", [("EventSelectors[].DataResources[].Type", "`AWS::S3::Object`", "操作を記録するS3 bucket"), ("EventSelectors[].DataResources[].Values", '`["arn:aws:s3"]`', "操作を記録するS3 bucket")], "Trail", "audit")
        output = roundtrip(base / "cloudtrail.md", trail, ROOT)
        assert "EventSelectors.DataResources[1].S3" in output and "All current and future" in output
        pipeline = model("codepipeline", "CodePipeline.Pipeline", "cpln-app-dev-build", [("Name", "`cpln-app-dev-build`", "pipelineの名前"), ("Stages[].Name", "`Source`", "入力を取得するstage"), ("Stages[].Actions[].Name", "`Source`", "入力を取得するaction"), ("Stages[].Actions[].Configuration", '`{"BranchName":"main","PollForSourceChanges":"false"}`', "BranchName: 対象branch / PollForSourceChanges: polling設定"), ("Stages[].Name", "`Build`", "buildを実行するstage"), ("Stages[].Actions[].Name", "`BuildOne`", "最初のbuild"), ("Stages[].Actions[].Configuration", '`{"ProjectName":"one"}`', "ProjectName: 実行するproject"), ("Stages[].Actions[].Name", "`BuildTwo`", "次のbuild")])
        output = roundtrip(base / "codepipeline.md", pipeline, ROOT)
        assert "Stages[1].Actions.Configuration.BranchName" in output
        assert "Stages[2].Actions[1].Name" in output and "Stages[2].Actions[2].Name" in output
        pipeline["desired.row.001-009.property"] = "CodePipeline.Pipeline.Tags[].Key"
        pipeline["desired.row.001-009.value"] = "`purpose`"
        pipeline["desired.row.001-009.comment"] = "タグのキー"
        roundtrip(base / "codepipeline.md", pipeline, ROOT)
        hub = model("securityhub", "SecurityHub.Hub", "security-hub", [("EnableDefaultStandards", "`true`", "標準を有効にする設定")], "Hub", "security-hub")
        roundtrip(base / "securityhub.md", hub, ROOT)
        s3 = model("s3", "S3.Bucket", "app-dev-data", [("BucketName", "`app-dev-data`", "データを保管する名前"), ("Region", "`ap-northeast-1`", "配置するregion"), ("BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.SSEAlgorithm", "`aws:kms`", "暗号化方式")])
        output = roundtrip(base / "s3.md", s3, ROOT)
        assert "BucketEncryption[].SSEAlgorithm" in output
        kms = model("kms", "KMS.Key", "data-key", [("KeyId", "[Key](#kms-data-key)", "一意に識別するID")], "Key", "data-key")
        kms["desired.service.kms.ownedCatalogResourceTypes"] = "KMS.Key,KMS.Alias"
        kms.update({"observed.row.001-001.property": "KMS.Key.KeyId", "observed.row.001-001.value": "`PENDING_DEPLOY`", "observed.row.001-001.comment": "一意に識別するID", "desired.resource.002.resourceType": "KMS.Alias", "desired.resource.002.logicalId": "Alias", "desired.resource.002.anchor": "kms-alias-app-dev-data", "desired.resource.002.parentProperty": "KMS.Alias.TargetKeyId", "desired.resource.002.parentReference": "[Key](#kms-data-key)", "desired.row.002-001.property": "KMS.Alias.AliasName", "desired.row.002-001.value": "`alias/app-dev-data`", "desired.row.002-001.comment": "keyを識別するalias"})
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
    print("model_design: PASS (authoritative updates, service rollback, naming coverage and service displays)")


if __name__ == "__main__":
    main()

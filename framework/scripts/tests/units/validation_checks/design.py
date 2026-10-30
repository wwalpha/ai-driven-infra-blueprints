"""Schema, required names, CIDR and catalog row order."""

from __future__ import annotations

import subprocess
import sys
from functools import partial as _bind_framework_callback
from unittest import TestCase
from unittest.mock import patch

import validation.design_tables as _imports_validation_design_tables
from support.validator import (
    MODULE,
    SCRIPT,
    diagnostics,
    project,
    schema_validator,
    write,
)
from support.validator import (
    load as load,
)

_CALLBACK_DEFAULT = object()


def check_catalog_inputs() -> None:
    repository = SCRIPT.parents[2]
    script = repository / "framework/scripts/update-catalog-lock.py"
    normal = subprocess.run([sys.executable, str(script)], capture_output=True)
    isolated = subprocess.run([sys.executable, "-S", str(script)], capture_output=True)
    TestCase().assertEqual(
        (normal.returncode, normal.stdout, normal.stderr),
        (isolated.returncode, isolated.stdout, isolated.stderr),
    )
    validator = MODULE.Validator(repository)
    validator.check_catalog_inputs()
    assert not validator.errors, validator.errors


def check_schema_backed_design_rows() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(
        repository
    ).catalog_design_properties()
    with project() as root:
        design = root / "docs" / "designs" / "stg" / "123456789012" / "logs.md"
        design.parent.mkdir(parents=True)
        invalid = """# CloudWatch Logs

- Design service ID: `logs`
- Owned catalog resource types: `Logs.LogGroup`

## リソース詳細

<a id="logs-vpcflowloggroup01"></a>
### Logs.LogGroup: VPCFLOWLOGGROUP01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |
| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |
"""
        write(design, invalid)
        validator = schema_validator(root)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))},
            catalog_types,
            property_owners,
            identifier_outputs,
        )
        assert any("provider schema violation" in error for error in validator.errors)
        assert any(
            "not selected by design catalog" in error for error in validator.errors
        )

        write(
            design,
            invalid.replace(
                "| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |",
                "| 1 | LogGroupName | `cwlogs-app-stg-flow-logs` | ロググループの名前 |\n"
                "| 2 | LogGroupClass | `STANDARD` | ロググループの保存クラス |\n"
                "| 3 | KmsKeyId | [LOGKEY01](kms.md#kms-logkey01) | ログ暗号化に使用するKMSキーのARN |",
            ),
        )
        validator = schema_validator(root)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))},
            catalog_types,
            property_owners,
            identifier_outputs,
        )
        assert not validator.errors, validator.errors


def check_name_tag_and_identifier_order_contract() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(
        repository
    ).catalog_design_properties()
    assert MODULE.REQUIRED_NAME_PROPERTIES == {
        "EC2.FlowLog": "EC2.FlowLog.Name",
        "EC2.RouteTable": "EC2.RouteTable.Name",
        "EC2.Subnet": "EC2.Subnet.Name",
        "EC2.VPC": "EC2.VPC.Name",
    }
    for resource_type, property_name in MODULE.REQUIRED_NAME_PROPERTIES.items():
        assert resource_type in property_owners[property_name]

    path = repository / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
    name_cases = [
        (
            "vpc-name",
            "EC2.VPC",
            "vpc-app-dev",
            [["1", "EC2.VPC.Name", "vpc-app-dev", "Nameタグの値"]],
            None,
        ),
        (
            "subnet-heading",
            "EC2.Subnet",
            "SUBNET01",
            [["1", "EC2.Subnet.Name", "sbnt-app-dev-private-01", "Nameタグの値"]],
            "heading identifier must match",
        ),
        (
            "subnet-upper-case",
            "EC2.Subnet",
            "PRIVATE_SUBNET_01",
            [["1", "EC2.Subnet.Name", "PRIVATE_SUBNET_01", "Nameタグの値"]],
            "lower-kebab-case",
        ),
        (
            "flowlog-name",
            "EC2.FlowLog",
            "flowlog-venus-stg-non-cde",
            [["1", "EC2.FlowLog.Name", "flowlog-venus-stg-non-cde", "Nameタグの値"]],
            None,
        ),
        ("api-without-name", "ApiGatewayV2.Api", "API01", [], None),
    ]
    for case, resource_type, identifier, rows, expected in name_cases:
        validator = MODULE.Validator(repository)
        validator.check_required_name_tag(path, resource_type, identifier, rows)
        if expected is None:
            assert not validator.errors, (case, validator.errors)
        else:
            assert any(expected in error for error in validator.errors), (
                case,
                validator.errors,
            )

    identifier_cases = [
        (
            "eip-catalog-order",
            [
                [
                    "1",
                    "EC2.EIP.AllocationId",
                    "eipalloc-0123456789abcdef0",
                    "Allocation ID",
                ],
                ["2", "EC2.EIP.PublicIp", "192.0.2.1", "Public IP"],
            ],
            None,
        ),
        (
            "eip-reversed-order",
            [
                ["1", "EC2.EIP.PublicIp", "192.0.2.1", "Public IP"],
                [
                    "2",
                    "EC2.EIP.AllocationId",
                    "eipalloc-0123456789abcdef0",
                    "Allocation ID",
                ],
            ],
            "catalog file order",
        ),
    ]
    for case, rows, expected in identifier_cases:
        validator = MODULE.Validator(repository)
        validator.check_generated_identifier(
            path, "EC2.EIP", "EIP01", rows, identifier_outputs
        )
        if expected is None:
            assert not validator.errors, (case, validator.errors)
        else:
            assert any(expected in error for error in validator.errors), (
                case,
                validator.errors,
            )


def _callback_check_cidr_pending_deploy_errors(
    catalog, path, repository, root, schema, /, text
):
    write(path, text)
    validator = MODULE.Validator(root, definitions_root=repository)
    validator.schema_catalog = schema
    validator.check_design_tables({path: ("vpc", ("EC2.VPC",))}, *catalog)
    validator.check_design_overviews()
    return validator.errors


def check_cidr_pending_deploy() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    schema = MODULE.DesignSchemaCatalog(repository)
    with project() as root:
        path = root / "docs/designs/stg/123456789012/vpc.md"
        path.parent.mkdir(parents=True)
        valid = """# VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`

## リソース一覧

### EC2.VPC

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [vpc-app-stg](#vpc-saved-original) | アプリケーションのネットワーク |

## リソース詳細

<a id="vpc-saved-original"></a>

### EC2.VPC: vpc-app-stg

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `vpc-app-stg` | VPCの名前 |
| 2 | VpcId | `PENDING_DEPLOY` | VPCのID |
| 3 | CidrBlock | `10.0.0.0/16` | VPCのIPv4アドレス範囲 |
"""

        errors = _bind_framework_callback(
            _callback_check_cidr_pending_deploy_errors,
            catalog,
            path,
            repository,
            root,
            schema,
        )

        assert not errors(valid), errors(valid)
        design_tables = _imports_validation_design_tables

        without_name = (
            valid.replace("| 1 | Name | `vpc-app-stg` | VPCの名前 |\n", "")
            .replace("| 2 | VpcId", "| 1 | VpcId")
            .replace("| 3 | CidrBlock", "| 2 | CidrBlock")
        )
        for mode, text, expected in (
            ("CREATE", valid, None),
            ("CREATE", without_name, "required Name property"),
            ("IMPORT", without_name, None),
        ):
            with (
                patch.object(
                    design_tables,
                    "expanded_design",
                    wraps=design_tables.expanded_design,
                ) as expand,
                patch.object(
                    design_tables,
                    "expanded_display_rows",
                    wraps=design_tables.expanded_display_rows,
                ) as display,
            ):
                with patch.object(
                    design_tables,
                    "design_model_values",
                    return_value={
                        "desired.resource.001.resourceType": "EC2.VPC",
                        "desired.resource.001.logicalId": "EC2_VPC_001",
                        "desired.resource.001.anchor": "vpc-saved-original",
                        "desired.resource.001.resourceMode": mode,
                    },
                ):
                    diagnostics = errors(text)
                if expected is None:
                    assert not diagnostics, (mode, diagnostics)
                else:
                    assert any(expected in error for error in diagnostics), diagnostics
                assert expand.call_args.kwargs["modes"] == {"vpc-saved-original": mode}
                assert display.call_args.kwargs["modes"] == {"vpc-saved-original": mode}

        failed = path.with_name("network.md")
        write(failed, valid.replace("vpc-saved-original", "network-vpc-app-stg"))
        write(path, valid)
        for source, failure in (
            ("resource_logical_ids", ValueError("識別情報が曖昧")),
            ("design_model_values", OSError("Model読み込み失敗")),
        ):
            original = getattr(design_tables, source)
            for paths in ([failed], [failed, path]):
                validator = schema_validator(root)
                with (
                    patch.object(
                        design_tables,
                        source,
                        side_effect=[
                            failure,
                            original(
                                design_tables.resource_heading_lines(valid.splitlines())
                            )
                            if source == "resource_logical_ids"
                            else None,
                        ],
                    ),
                    patch.object(
                        design_tables,
                        "expanded_design",
                        wraps=design_tables.expanded_design,
                    ) as expand,
                    patch.object(
                        design_tables,
                        "expanded_display_rows",
                        wraps=design_tables.expanded_display_rows,
                    ) as display,
                    patch.object(
                        design_tables,
                        "check_required_name_tag",
                        wraps=design_tables.check_required_name_tag,
                    ) as names,
                ):
                    result = validator.findings.evaluate(
                        "design.tables",
                        None,
                        lambda *,
                        paths=paths,
                        validator=validator: validator.check_design_tables(
                            {path: ("vpc", ("EC2.VPC",))}, *catalog, paths=paths
                        ),
                    )
                diagnostic = f"invalid resource identity: {failed.relative_to(root).as_posix()}: {failure}"
                assert validator.errors == [diagnostic], validator.errors
                assert result.status == "FAIL" and result.errors == (diagnostic,), (
                    result
                )
                assert expand.call_count == display.call_count == len(paths) - 1
                assert [call.args[0] for call in names.call_args_list] == paths[1:]
        failed.unlink()

        for pending in (
            "PENDING_DEPLOY",
            "`PENDING_DEPLOY`",
            "[PENDING_DEPLOY](#vpc-saved-original)",
        ):
            # Reject either table independently, not merely when both agree.
            assert any(
                "CIDR must not use" in error
                for error in errors(valid.replace("`10.0.0.0/16`", pending, 1))
            )
            assert any(
                "CIDR must not use" in error
                for error in errors(
                    valid.replace("CidrBlock | `10.0.0.0/16`", "CidrBlock | " + pending)
                )
            )
        for prop in (
            "EC2.Subnet.CidrBlock",
            "EC2.Route.CidrBlock",
            "EC2.Route.DestinationCidrBlock",
            "EC2.SecurityGroupIngress.CidrIp",
            "EC2.TransitGateway.TransitGatewayCidrBlocks",
        ):
            validator = MODULE.Validator(root)
            validator.check_cidr_value(path, prop, '["10.0.0.0/16","PENDING_DEPLOY"]')
            assert validator.errors, prop
            validator = MODULE.Validator(root)
            validator.check_cidr_value(path, prop, "10.0.0.0/16")
            assert not validator.errors, prop


def _callback_check_event_rule_row_order_errors(
    catalog, design, header, repository, root, schema, /, selected
):
    write(
        design,
        header
        + "".join(
            f"| {number} | {prop} | `{value}` | ルールの設定 |\n"
            for number, (prop, value) in enumerate(selected, 1)
        ),
    )
    validator = MODULE.Validator(root, definitions_root=repository)
    validator.schema_catalog = schema
    validator.check_design_tables({design: ("eventbridge", ("Events.Rule",))}, *catalog)
    return validator.errors


def check_event_rule_row_order() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    schema = MODULE.DesignSchemaCatalog(repository)
    with project() as root:
        design = root / "docs/designs/dev/123456789012/eventbridge.md"
        design.parent.mkdir(parents=True)
        header = """# EventBridge 詳細設計

- Design service ID: `eventbridge`
- Owned catalog resource types: `Events.Rule`

## リソース詳細

<a id="eventbridge-hulftretrievaldetectrule"></a>

### Events.Rule: HulftRetrievalDetectRule

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
"""
        rows = [
            ("Name", "ebr-event-venus-dev-hulft-retrieval-detect"),
            ("State", "DISABLED"),
            ("EventBusName", "default"),
        ]

        errors = _bind_framework_callback(
            _callback_check_event_rule_row_order_errors,
            catalog,
            design,
            header,
            repository,
            root,
            schema,
        )

        assert not errors(rows), errors(rows)
        for selected in (
            rows[2:3] + rows[:2] + rows[3:],
            [rows[1], rows[0], *rows[2:]],
        ):
            assert any("catalog file order" in error for error in errors(selected))
        for index in (0, 1):
            for selected in (rows[:index] + rows[index + 1 :], rows + [rows[index]]):
                assert any(
                    "must appear exactly once" in error for error in errors(selected)
                )
            for value in ("", "UNSET", "PENDING_DEPLOY"):
                selected = rows.copy()
                selected[index] = (rows[index][0], value)
                assert any(
                    "must have a confirmed value" in error for error in errors(selected)
                )
        assert not errors([rows[0], ("State", "ENABLED"), *rows[2:]])


def _callback_check_description_design_constraints_validate_82(
    catalog,
    iam,
    metadata,
    root,
    sg,
    _default_role_text,
    _default_group_text,
    /,
    role_text=_CALLBACK_DEFAULT,
    group_text=_CALLBACK_DEFAULT,
):
    if role_text is _CALLBACK_DEFAULT:
        role_text = _default_role_text
    if group_text is _CALLBACK_DEFAULT:
        group_text = _default_group_text
    write(iam, role_text)
    write(sg, group_text)
    validator = schema_validator(root)
    validator.check_design_tables(metadata, *catalog, paths=[iam, sg])
    validator.check_design_overviews(paths=[iam, sg])
    return validator


def check_description_design_constraints() -> None:
    repository = SCRIPT.parents[2]
    catalog = MODULE.Validator(repository).catalog_design_properties()
    with project() as root:
        target = root / "docs/designs/dev/123456789012"
        target.mkdir(parents=True)
        iam = target / "iam.md"
        sg = target / "security-group.md"
        iam_text = """# IAM 詳細設計

- Design service ID: `iam`
- Owned catalog resource types: `IAM.Role`

## リソース一覧

### IAM.Role

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-role](#iam-app-role) | アプリケーションの権限 |

## リソース詳細

<!-- resource-logical-id: RoleOne -->
<a id="iam-app-role"></a>
### IAM.Role: app-role

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `app-role` | ロール名 |
| 2 | AssumeRolePolicyDocument | [Trust](iam/role-one-trust-policy.json) | 信頼ポリシー |
| 3 | Description | `Application role` | 用途の説明 |
"""
        sg_text = """# Security Group 詳細設計

- Design service ID: `security-group`
- Owned catalog resource types: `EC2.SecurityGroup`

## リソース一覧

### EC2.SecurityGroup

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-sg](#security-group-app-sg) | アプリケーションの通信制御 |

## リソース詳細

<!-- resource-logical-id: GroupOne -->
<a id="security-group-app-sg"></a>
### EC2.SecurityGroup: app-sg

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | GroupDescription | `Application access` | 用途の説明 |
| 3 | GroupName | `app-sg` | 名前 |
| 4 | VpcId | [PENDING_DEPLOY](vpc.md#vpc-app-vpc) | 所属するVPCのID |
"""
        metadata = {
            iam: ("iam", ("IAM.Role",)),
            sg: ("security-group", ("EC2.SecurityGroup",)),
        }

        validate = _bind_framework_callback(
            _callback_check_description_design_constraints_validate_82,
            catalog,
            iam,
            metadata,
            root,
            sg,
            iam_text,
            sg_text,
        )

        # Both Japanese overview Comments and Source / Comments remain valid.
        assert not validate().errors, validate().errors
        for resource, prop, filename, role_text, group_text in (
            (
                "RoleOne",
                "IAM.Role.Description",
                "iam.md",
                iam_text.replace("Application role", "日本語の説明"),
                sg_text,
            ),
            (
                "GroupOne",
                "EC2.SecurityGroup.GroupDescription",
                "security-group.md",
                iam_text,
                sg_text.replace("Application access", "日本語の説明"),
            ),
            (
                "GroupOne",
                "EC2.SecurityGroup.GroupDescription",
                "security-group.md",
                iam_text,
                sg_text.replace("Application access", "Why?"),
            ),
        ):
            errors = validate(role_text, group_text).errors
            assert len(errors) == 1, errors
            assert all(
                text in errors[0] for text in (filename, resource, prop, "must match")
            ), errors

        # Existing validators collect independent property and dependency failures.
        validator = validate(
            iam_text.replace("Application role", "日本語"),
            sg_text.replace("Application access", "日本語"),
        )
        validator.check_design_links(catalog[2], paths=[iam, sg])
        assert any(
            "RoleOne: IAM.Role.Description" in error for error in diagnostics(validator)
        )
        assert any(
            "GroupOne: EC2.SecurityGroup.GroupDescription" in error
            for error in diagnostics(validator)
        )
        assert any(
            "broken design link" in error and "vpc.md" in error
            for error in diagnostics(validator)
        )
        assert any(
            "design JSON artifact is missing" in error and "trust-policy.json" in error
            for error in diagnostics(validator)
        )
        assert iam.read_text(encoding="utf-8") == iam_text.replace(
            "Application role", "日本語"
        )
        assert sg.read_text(encoding="utf-8") == sg_text.replace(
            "Application access", "日本語"
        )

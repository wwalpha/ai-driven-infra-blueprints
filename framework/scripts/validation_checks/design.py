"""Schema, required names, CIDR and catalog row order."""

from __future__ import annotations
from test_support.validator import MODULE, SCRIPT, project, write, schema_validator


def check_schema_backed_design_rows() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
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
            {design: ("logs", ("Logs.LogGroup",))}, catalog_types, property_owners, identifier_outputs
        )
        assert any("provider schema violation" in error for error in validator.errors)
        assert any("not selected by design catalog" in error for error in validator.errors)

        write(design,
            invalid.replace(
                "| 1 | KmsKeyId | `not-used` | ログ暗号化に使用するKMSキーのARN |\n"
                "| 2 | Encryption | `AWS-managed standard encryption` | ログの暗号化方式 |",
                "| 1 | LogGroupClass | `STANDARD` | ロググループの保存クラス |\n"
                "| 2 | KmsKeyId | [LOGKEY01](kms.md#kms-logkey01) | ログ暗号化に使用するKMSキーのARN |\n"
                "| 3 | Tags[].Key | `Name` | ロググループを識別するNameタグのキー |\n"
                "| 4 | Tags[].Value | `cwlogs-app-stg-flow-logs` | ロググループを識別するNameタグの値 |",
            )
        )
        validator = schema_validator(root)
        validator.check_design_tables(
            {design: ("logs", ("Logs.LogGroup",))}, catalog_types, property_owners, identifier_outputs
        )
        assert not validator.errors, validator.errors


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
        metadata = {iam: ("iam", ("IAM.Role",)), sg: ("security-group", ("EC2.SecurityGroup",))}

        def validate(role_text=iam_text, group_text=sg_text):
            write(iam, role_text)
            write(sg, group_text)
            validator = schema_validator(root)
            validator.check_design_tables(metadata, *catalog, paths=[iam, sg])
            validator.check_design_overviews(paths=[iam, sg])
            return validator

        # Both Japanese overview Comments and Source / Comments remain valid.
        assert not validate().errors, validate().errors
        for resource, prop, filename, role_text, group_text in (
            ("RoleOne", "IAM.Role.Description", "iam.md", iam_text.replace("Application role", "日本語の説明"), sg_text),
            ("GroupOne", "EC2.SecurityGroup.GroupDescription", "security-group.md", iam_text, sg_text.replace("Application access", "日本語の説明")),
            ("GroupOne", "EC2.SecurityGroup.GroupDescription", "security-group.md", iam_text, sg_text.replace("Application access", "Why?")),
        ):
            errors = validate(role_text, group_text).errors
            assert len(errors) == 1, errors
            assert all(text in errors[0] for text in (filename, resource, prop, "must match")), errors

        # Existing validators collect independent property and dependency failures.
        validator = validate(iam_text.replace("Application role", "日本語"), sg_text.replace("Application access", "日本語"))
        validator.check_design_links(catalog[2], paths=[iam, sg])
        assert any("RoleOne: IAM.Role.Description" in error for error in validator.errors)
        assert any("GroupOne: EC2.SecurityGroup.GroupDescription" in error for error in validator.errors)
        assert any("broken design link" in error and "vpc.md" in error for error in validator.errors)
        assert any("broken design link" in error and "trust-policy.json" in error for error in validator.errors)
        assert iam.read_text(encoding="utf-8") == iam_text.replace("Application role", "日本語")
        assert sg.read_text(encoding="utf-8") == sg_text.replace("Application access", "日本語")


def check_name_tag_and_identifier_order_contract() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
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
        ('vpc-name', 'EC2.VPC', 'vpc-app-dev',
         [['1', 'EC2.VPC.Name', 'vpc-app-dev', 'Nameタグの値']], None),
        ('vpc-two-row-name-tag', 'EC2.VPC', 'vpc-app-dev',
         [['1', 'EC2.VPC.Tags[].Key', 'Name', 'Nameタグのキー'],
          ['2', 'EC2.VPC.Tags[].Value', 'vpc-app-dev', 'Nameタグの値']], 'one-row property'),
        ('subnet-heading', 'EC2.Subnet', 'SUBNET01',
         [['1', 'EC2.Subnet.Name', 'sbnt-app-dev-private-01', 'Nameタグの値']], 'heading identifier must match'),
        ('subnet-upper-case', 'EC2.Subnet', 'PRIVATE_SUBNET_01',
         [['1', 'EC2.Subnet.Name', 'PRIVATE_SUBNET_01', 'Nameタグの値']], 'lower-kebab-case'),
        ('flowlog-name', 'EC2.FlowLog', 'flowlog-venus-stg-non-cde',
         [['1', 'EC2.FlowLog.Name', 'flowlog-venus-stg-non-cde', 'Nameタグの値']], None),
        ('flowlog-two-row-name-tag', 'EC2.FlowLog', 'flowlog-venus-stg-non-cde',
         [['1', 'EC2.FlowLog.Tags[].Key', 'Name', 'Nameタグのキー'],
          ['2', 'EC2.FlowLog.Tags[].Value', 'flowlog-venus-stg-non-cde', 'Nameタグの値']], 'one-row property'),
        ('api-without-name', 'ApiGatewayV2.Api', 'API01',
         [], None),
    ]
    for case, resource_type, identifier, rows, expected in name_cases:
        validator = MODULE.Validator(repository)
        validator.check_required_name_tag(path, resource_type, identifier, rows)
        if expected is None:
            assert not validator.errors, (case, validator.errors)
        else:
            assert any(expected in error for error in validator.errors), (case, validator.errors)

    identifier_cases = [
        ('eip-catalog-order',
         [['1', 'EC2.EIP.AllocationId', 'eipalloc-0123456789abcdef0', 'Allocation ID'],
          ['2', 'EC2.EIP.PublicIp', '192.0.2.1', 'Public IP']], None),
        ('eip-reversed-order',
         [['1', 'EC2.EIP.PublicIp', '192.0.2.1', 'Public IP'],
          ['2', 'EC2.EIP.AllocationId', 'eipalloc-0123456789abcdef0', 'Allocation ID']], 'catalog file order'),
    ]
    for case, rows, expected in identifier_cases:
        validator = MODULE.Validator(repository)
        validator.check_generated_identifier(path, "EC2.EIP", "EIP01", rows, identifier_outputs)
        if expected is None:
            assert not validator.errors, (case, validator.errors)
        else:
            assert any(expected in error for error in validator.errors), (case, validator.errors)


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
| 1 | [vpc-app-stg](#vpc-vpc-app-stg) | アプリケーションのネットワーク |

## リソース詳細

<a id="vpc-vpc-app-stg"></a>

### EC2.VPC: vpc-app-stg

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `vpc-app-stg` | VPCの名前 |
| 2 | VpcId | `PENDING_DEPLOY` | VPCのID |
| 3 | CidrBlock | `10.0.0.0/16` | VPCのIPv4アドレス範囲 |
"""

        def errors(text):
            write(path, text)
            validator = MODULE.Validator(root)
            validator.schema_catalog = schema
            validator.check_design_tables({path: ("vpc", ("EC2.VPC",))}, *catalog)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(valid), errors(valid)
        for pending in ("PENDING_DEPLOY", "`PENDING_DEPLOY`", "[PENDING_DEPLOY](#vpc-vpc-app-stg)"):
            # Reject either table independently, not merely when both agree.
            assert any("CIDR must not use" in error for error in errors(valid.replace("`10.0.0.0/16`", pending, 1)))
            assert any("CIDR must not use" in error for error in errors(valid.replace("CidrBlock | `10.0.0.0/16`", "CidrBlock | " + pending)))
        for prop in ("EC2.Subnet.CidrBlock", "EC2.Route.CidrBlock", "EC2.Route.DestinationCidrBlock", "EC2.SecurityGroupIngress.CidrIp", "EC2.TransitGateway.TransitGatewayCidrBlocks"):
            validator = MODULE.Validator(root)
            validator.check_cidr_value(path, prop, '["10.0.0.0/16","PENDING_DEPLOY"]')
            assert validator.errors, prop
            validator = MODULE.Validator(root)
            validator.check_cidr_value(path, prop, "10.0.0.0/16")
            assert not validator.errors, prop


def check_catalog_display_order() -> None:
    from design_layout import catalog_order_errors

    with project() as root:
        material = root / "framework/materials/aws/Example_Resource.properties"
        material.parent.mkdir(parents=True)
        lines = ["Example.Resource.Name=", "Example.Resource.Hidden=", "Example.Resource.Id=IDENTIFIER_OUTPUT", "Example.Resource.Tags[].Key=", "Example.Resource.Tags[].Value="]
        write(material, "\n".join(lines) + "\n")
        def rows(*properties):
            return [[str(n), "Example.Resource." + prop, "value", "属性"] for n, prop in enumerate(properties, 1)]
        selected = rows("Name", "Id", "Tags[].Key", "Tags[].Value", "Tags[].Key", "Tags[].Value")
        assert not catalog_order_errors("Example.Resource", selected, root)
        assert catalog_order_errors("Example.Resource", rows("Id", "Name"), root)
        assert catalog_order_errors("Example.Resource", rows("Tags[].Value", "Tags[].Key"), root)
        assert catalog_order_errors("Example.Resource", rows("Tags[].Key", "Name", "Tags[].Key"), root)
        write(material, "\n".join([lines[2], *lines[:2], *lines[3:]]) + "\n")
        assert not catalog_order_errors("Example.Resource", rows("Id", "Name"), root)
        assert catalog_order_errors("Example.Resource", rows("Name", "Id"), root)
        assert len(selected) == 6 and all("Hidden" not in row[1] for row in selected)


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
            ("ScheduleExpression", "rate(5 minutes)"),
        ]

        def errors(selected):
            write(design, header + "".join(
                f"| {number} | {prop} | `{value}` | ルールの設定 |\n"
                for number, (prop, value) in enumerate(selected, 1)
            ))
            validator = MODULE.Validator(root)
            validator.schema_catalog = schema
            validator.check_design_tables({design: ("eventbridge", ("Events.Rule",))}, *catalog)
            return validator.errors

        assert not errors(rows), errors(rows)
        for selected in (rows[2:3] + rows[:2] + rows[3:], [rows[1], rows[0], *rows[2:]]):
            assert any("catalog file order" in error for error in errors(selected))
        for index in (0, 1):
            for selected in (rows[:index] + rows[index + 1:], rows + [rows[index]]):
                assert any("must appear exactly once" in error for error in errors(selected))
            for value in ("", "UNSET", "PENDING_DEPLOY"):
                selected = rows.copy()
                selected[index] = (rows[index][0], value)
                assert any("must have a confirmed value" in error for error in errors(selected))
        assert not errors([rows[0], ("State", "ENABLED"), *rows[2:]])

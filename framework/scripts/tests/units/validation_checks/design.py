"""Schema, required names, CIDR and catalog row order."""


from __future__ import annotations


import json


import shutil
from unittest.mock import patch
from utils.aws_schemas import Schemas
from utils.aws_catalogs import Catalogs


from support.validator import MODULE, SCRIPT, project, write, schema_validator, load


def check_catalog_inputs() -> None:
    from cloudformation_schema import manifest_text, material_files
    from design_catalog import design_material_files
    lock = load("update-catalog-lock")
    with project() as root:
        shutil.copytree(SCRIPT.parents[2] / "framework/materials", root / "framework/materials")
        scripts = root / "framework/scripts"
        scripts.mkdir()
        shutil.copy2(SCRIPT.with_name("update-catalog-lock.py"), scripts)

        def check(expected=None):
            # Refresh integrity locks so semantic failures cannot hide behind checksums.
            materials = root / "framework/materials"
            for name, files in (
                ("catalog", material_files(root)),
                ("api-catalog", sorted((materials / "api").glob("*"))),
                ("cloudformation-schema", sorted((materials / "cloudformation-schema/ap-northeast-1").glob("*.json"))),
            ):
                (materials / f"{name}.sha256").write_text(manifest_text(root, files), encoding="utf-8")
            markers = [line.partition("=")[2] for path in material_files(root)
                       for line in path.read_text(encoding="utf-8").splitlines()]
            metadata = materials / "catalog.properties"
            metadata.write_text(lock.replace_metadata(metadata.read_text(encoding="utf-8").splitlines(), {
                "catalog.fileCount": str(len(material_files(root))),
                "catalog.propertyCount": str(markers.count("")),
                "catalog.identifierOutputCount": str(markers.count("IDENTIFIER_OUTPUT")),
            }), encoding="utf-8")
            # Each corruption is a new definition lifetime, including snapshot checks.
            with patch('utils.aws_schemas.schemas_for', return_value=Schemas(root)), \
                 patch('utils.aws_catalogs.catalogs_for', return_value=Catalogs(root)):
                validator = MODULE.Validator(root)
                validator.check_catalog_inputs()
            if expected is None:
                assert not validator.errors, validator.errors
            else:
                assert any(expected in error for error in validator.errors), (expected, validator.errors)
            assert not any("checksum mismatch" in error or ".sha256 does not match" in error
                           for error in validator.errors), validator.errors

        check()
        aws = root / "framework/materials/aws/EC2_VPC.properties"
        apis = [path for path in design_material_files(root) if path not in material_files(root)]
        for path in [aws, *apis]:
            original = path.read_text(encoding="utf-8")
            first, *rest = original.splitlines()
            key = first.partition("=")[0]
            for line, expected in (
                (key, "invalid catalog line"),
                ("Unknown.Resource.Property=", "invalid catalog line"),
                (key + "Missing=", "absent from provider schema"),
                (key + "=INVALID", "invalid catalog line"),
                (key + "=IDENTIFIER_OUTPUT=INVALID", "invalid catalog line"),
            ):
                path.write_text("\n".join([line, *rest]) + "\n", encoding="utf-8")
                check(expected if path == aws else "selection list")
            path.write_text(original + first + "\n", encoding="utf-8")
            check("catalog properties must be unique" if path == aws else "selection list")
            path.write_text(original.rstrip("\n"), encoding="utf-8")
            check("catalog file lacks final newline")
            path.write_text(original, encoding="utf-8")

        for path, expected in ((apis[0], None), (root / "framework/materials/api/QuickSight_Group.properties", "display order")):
            original = path.read_text(encoding="utf-8")
            path.write_text("\n".join(reversed(original.splitlines())) + "\n", encoding="utf-8")
            check(expected)
            path.write_text(original, encoding="utf-8")

        original = aws.read_text(encoding="utf-8")
        aws.write_text(original.replace("EC2.VPC.CidrBlock=", "EC2.VPC.CidrBlock=IDENTIFIER_OUTPUT"), encoding="utf-8")
        check("invalid identifier output")
        aws.write_text(original, encoding="utf-8")
        schema_path = root / "framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpc.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["properties"]["CidrBlock"] = {"$ref": "#/definitions/Missing"}
        schema_path.write_text(json.dumps(schema) + "\n", encoding="utf-8")
        check("absent from provider schema")


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
        from validation import design_tables

        without_name = valid.replace("| 1 | Name | `vpc-app-stg` | VPCの名前 |\n", "").replace(
            "| 2 | VpcId", "| 1 | VpcId").replace("| 3 | CidrBlock", "| 2 | CidrBlock")
        for mode, text, expected in (
            ("CREATE", valid, None),
            ("CREATE", without_name, "required Name property"),
            ("IMPORT", without_name, None),
        ):
            with patch.object(design_tables, "expanded_design", wraps=design_tables.expanded_design) as expand, \
                 patch.object(design_tables, "expanded_display_rows", wraps=design_tables.expanded_display_rows) as display:
                diagnostics = errors(f"<!-- resource-mode: vpc-vpc-app-stg {mode} -->\n" + text)
                if expected is None:
                    assert not diagnostics, (mode, diagnostics)
                else:
                    assert any(expected in error for error in diagnostics), diagnostics
                assert expand.call_args.kwargs["modes"] == {"vpc-vpc-app-stg": mode}
                assert display.call_args.kwargs["modes"] == {"vpc-vpc-app-stg": mode}

        failed = path.with_name("network.md")
        write(failed, valid.replace("vpc-vpc-app-stg", "network-vpc-app-stg"))
        write(path, valid)
        for source, failure in (
            ("resource_logical_ids", ValueError("識別情報が曖昧")),
            ("design_model_values", OSError("Model読み込み失敗")),
        ):
            original = getattr(design_tables, source)
            for paths in ([failed], [failed, path]):
                validator = schema_validator(root)
                with patch.object(design_tables, source, side_effect=[failure, original(
                    design_tables.resource_heading_lines(valid.splitlines())) if source == "resource_logical_ids" else None]), \
                     patch.object(design_tables, "expanded_design", wraps=design_tables.expanded_design) as expand, \
                     patch.object(design_tables, "expanded_display_rows", wraps=design_tables.expanded_display_rows) as display, \
                     patch.object(design_tables, "check_required_name_tag", wraps=design_tables.check_required_name_tag) as names:
                    result = validator.findings.evaluate("design.tables", None, lambda:
                        validator.check_design_tables({path: ("vpc", ("EC2.VPC",))}, *catalog, paths=paths))
                diagnostic = f"invalid resource identity: {failed.relative_to(root).as_posix()}: {failure}"
                assert validator.errors == [diagnostic], validator.errors
                assert result.status == "FAIL" and result.errors == (diagnostic,), result
                assert expand.call_count == display.call_count == len(paths) - 1
                assert [call.args[0] for call in names.call_args_list] == paths[1:]
        failed.unlink()

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
        with patch('utils.aws_catalogs.catalogs_for', return_value=Catalogs(root)):
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


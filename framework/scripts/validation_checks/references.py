"""Design references, grouped resources and resource overviews."""

from __future__ import annotations
from test_support.validator import MODULE, SCRIPT, project, write, schema_validator, load


def errors_for(rows: list[list[str]]) -> list[str]:
    root = SCRIPT.parents[2]
    validator = MODULE.Validator(root)
    validator.check_markdown_iam_policy_artifacts(
        root / "docs" / "designs" / "stg" / "123456789012" / "iam.md",
        "VPCFLOWLOGROLE01",
        rows,
    )
    return validator.errors


def check_identifier_propagation() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(repository).catalog_design_properties()
    with project() as root:
        design = root / "docs" / "designs" / "dev" / "123456789012" / "vpc.md"
        design.parent.mkdir(parents=True)
        write(design,
            """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | vpc-app-dev | VPCを識別するNameタグの値 |
| 2 | VpcId | PENDING_DEPLOY | VPCを一意に識別するID |

<a id="vpc-sbnt-app-dev-private-01"></a>

### EC2.Subnet: sbnt-app-dev-private-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | sbnt-app-dev-private-01 | Subnetを識別するNameタグの値 |
| 2 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
| 3 | SubnetId | PENDING_DEPLOY | Subnetを一意に識別するID |
"""
        )
        metadata = {design: ("vpc", ("EC2.VPC", "EC2.Subnet"))}
        validator = schema_validator(root)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        validator.check_design_links(identifier_outputs)
        assert not validator.errors, validator.errors

        write(design,
            design.read_text(encoding="utf-8")
            .replace("VpcId | PENDING_DEPLOY", "VpcId | vpc-0123456789abcdef0")
            .replace("[PENDING_DEPLOY](#vpc-vpc-app-dev)", "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)")
            .replace("SubnetId | PENDING_DEPLOY", "SubnetId | subnet-0123456789abcdef0")
        )
        validator = schema_validator(root)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        validator.check_design_links(identifier_outputs)
        assert not validator.errors, validator.errors

        deployed = design.read_text(encoding="utf-8")
        write(design,
            deployed.replace("vpc-0123456789abcdef0", "vpc-app-dev")
        )
        validator = schema_validator(root)
        validator.check_design_tables(metadata, catalog_types, property_owners, identifier_outputs)
        assert any("must use a physical value" in error for error in validator.errors)

        write(design,
            deployed.replace(
                "[vpc-0123456789abcdef0](#vpc-vpc-app-dev)", "[vpc-wrong](#vpc-vpc-app-dev)"
            )
        )
        validator = MODULE.Validator(root)
        validator.check_design_links(identifier_outputs)
        assert any("identifier reference does not match observed target" in error for error in validator.errors)


def check_array_source_role_links() -> None:
    from array_display import indexed_rows

    with project() as root:
        path = root / "docs/designs/dev/123456789012/iam.md"
        path.parent.mkdir(parents=True)
        role = """<a id="iam-role"></a>
### IAM.Role: Role

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `app-role` | Role name |

<a id="iam-profile"></a>
### IAM.InstanceProfile: Profile

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
"""
        def errors(label):
            rows = indexed_rows([
                ["1", "InstanceProfileName", "`app-profile`", "Profile name"],
                ["2", "Roles", f"[{label}](#iam-role)", "Selected role"],
            ], "IAM.InstanceProfile")
            content = role + "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
            # Hidden links must not enter reference discovery or broken-link checks.
            content += "<!--\n[hidden](missing.md#missing)\n-->\n"
            assert "<!-- array-source:" in content
            write(path, content)
            validator = MODULE.Validator(root)
            validator.check_design_links({}, paths=[path])
            return validator.errors

        assert not errors("app-role"), errors("app-role")
        assert any("IAM Role link must display RoleName" in error for error in errors("wrong-role")), errors("wrong-role")


def check_s3_bucket_policy_grouping() -> None:
    repository = SCRIPT.parents[2]
    catalog_types, property_owners, identifier_outputs = MODULE.Validator(
        repository
    ).catalog_design_properties()
    with project() as root:
        design = root / "docs" / "designs" / "dev" / "123456789012" / "s3.md"
        artifact = design.parent / "s3" / "app-data-bucket-policy.json"
        artifact.parent.mkdir(parents=True)
        write(artifact, '{"Version":"2012-10-17","Statement":[]}\n')
        kms_design = design.with_name("kms.md")
        write(kms_design,
            """# AWS KMS 詳細設計

- Design service ID: `kms`
- Owned catalog resource types: `KMS.Key`, `KMS.Alias`

## リソース詳細

<a id="kms-appdatakey"></a>

### KMS.Key: AppDataKey

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `1234abcd-12ab-34cd-56ef-1234567890ab` | KMS keyを識別するID |
| 2 | KMS.Alias.AliasName | `alias/app-data` | <a id="kms-appdatakeyalias"></a><!-- logical-id: AppDataKeyAlias --> application data用keyを識別するalias |
"""
        )
        valid = """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`, `S3.BucketPolicy`

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |
| 2 | Region | `ap-northeast-1` | bucketを配置するAWS region |
| 3 | BucketEncryption[].KMSMasterKeyID | [alias/app-data](kms.md#kms-appdatakeyalias) | 新規objectのdefault暗号化に使用するKMS key alias |
| 4 | BucketEncryption[].SSEAlgorithm | `aws:kms` | 暗号化方式 |
| 5 | VersioningConfiguration.Status | `Enabled` | objectのversion保持状態 |
| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |
"""
        metadata = {
            design: ("s3", ("S3.Bucket", "S3.BucketPolicy")),
            kms_design: ("kms", ("KMS.Key", "KMS.Alias")),
        }

        def errors(markdown: str) -> list[str]:
            write(design, markdown)
            validator = schema_validator(root)
            validator.check_design_tables(
                metadata, catalog_types, property_owners, identifier_outputs
            )
            validator.check_design_links(identifier_outputs)
            return validator.errors

        assert not errors(valid)
        wrong_order = valid.replace(
            "| 1 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |\n"
            "| 2 | Region | `ap-northeast-1` | bucketを配置するAWS region |",
            "| 1 | Region | `ap-northeast-1` | bucketを配置するAWS region |\n"
            "| 2 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |",
        )
        assert any("BucketName must be the first row" in error for error in errors(wrong_order))
        other_region = valid.replace("`ap-northeast-1`", "`us-east-1`")
        assert not errors(other_region)
        unset_region = valid.replace("`ap-northeast-1`", "`UNSET`")
        assert any("must be a confirmed AWS region ID" in error for error in errors(unset_region))
        literal_alias = valid.replace(
            "[alias/app-data](kms.md#kms-appdatakeyalias)", "`alias/app-data`"
        )
        assert any("must link to a KMS.Alias" in error for error in errors(literal_alias))
        wrong_alias = valid.replace("[alias/app-data]", "[alias/other]")
        assert any("must display the referenced KMS alias" in error for error in errors(wrong_alias))
        wrong_heading = valid.replace(
            "### S3.Bucket: app-dev-data-123456789012",
            "### S3.Bucket: AppDataBucket",
        )
        assert any("heading identifier must match BucketName" in error for error in errors(wrong_heading))
        explicit_bucket = valid.replace(
            "| 6 | S3.BucketPolicy.PolicyDocument",
            "| 6 | S3.BucketPolicy.Bucket | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | bucket policyを適用するbucket |\n"
            "| 7 | S3.BucketPolicy.PolicyDocument",
        )
        assert any("S3.BucketPolicy.Bucket must be omitted" in error for error in errors(explicit_bucket))
        separate_heading = valid.replace(
            "| 6 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |",
            "\n<a id=\"s3-appdatabucketpolicy\"></a>\n\n"
            "### S3.BucketPolicy: AppDataBucketPolicy\n\n"
            "| No. | Property | Value | Source / Comment |\n"
            "| ---: | --- | --- | --- |\n"
            "| 1 | S3.BucketPolicy.PolicyDocument | [app-data-bucket-policy.json](s3/app-data-bucket-policy.json) | bucketへのaccessを制御するpolicy document |",
        )
        assert any("must not have an independent heading" in error for error in errors(separate_heading))


def check_subnet_association_overview() -> None:
    model = load("sync-model")
    association_type = "EC2.SubnetRouteTableAssociation"
    metadata = (
        "# VPC 詳細設計\n\n- Design service ID: `vpc`\n"
        f"- Owned catalog resource types: `EC2.Subnet`, `EC2.RouteTable`, `{association_type}`\n\n"
    )
    subnet_header = "| No. | ResourceName | Comment |"
    subnet_rows = [f"| {number} | [subnet-{number}](#vpc-subnet-{number}) | Subnetの用途 |" for number in range(1, 4)]
    overview = "\n".join([
        "## リソース一覧", "", "### EC2.Subnet", "", subnet_header,
        "| ---: | --- | --- |", *subnet_rows, "",
        "### EC2.RouteTable", "", subnet_header, "| ---: | --- | --- |",
        "| 1 | [route](#vpc-route) | Subnetの経路を管理するtable |", "", "",
    ])
    details = "## リソース詳細\n\n"
    for number in range(1, 4):
        route_table = (
            f"| 3 | EC2.RouteTableId | [rtb-00000001](#vpc-route) | 関連付けるRoute Table |\n"
            if number < 3 else ""
        )
        details += (
            f'<a id="vpc-subnet-{number}"></a>\n\n### EC2.Subnet: subnet-{number}\n\n'
            f"{MODULE.TABLE_HEADER}\n{MODULE.TABLE_ALIGNMENT}\n"
            f"| 1 | EC2.Subnet.SubnetId | `subnet-{number:08d}` | Subnetを識別するID |\n"
            f"| 2 | EC2.Subnet.Name | `subnet-{number}` | SubnetのNameタグ |\n"
            f"{route_table}\n"
        )
    details += (
        '<a id="vpc-route"></a>\n\n### EC2.RouteTable: route\n\n'
        f"{MODULE.TABLE_HEADER}\n{MODULE.TABLE_ALIGNMENT}\n"
        "| 1 | EC2.RouteTable.RouteTableId | `rtb-00000001` | Route Tableを識別するID |\n\n"
    )
    independent = (
        f'<a id="vpc-assoc-1"></a>\n\n### {association_type}: Assoc1\n\n'
        f"{MODULE.TABLE_HEADER}\n{MODULE.TABLE_ALIGNMENT}\n"
        f"| 1 | {association_type}.Id | `rtbassoc-00000001` | 関連付けを識別するID |\n"
        f"| 2 | {association_type}.RouteTableId | [rtb-00000001](#vpc-route) | 関連付けるRoute Table |\n"
        f"| 3 | {association_type}.SubnetId | [subnet-00000001](#vpc-subnet-1) | 関連付けるSubnet |\n\n"
    )
    valid = metadata + overview + details
    legacy_overview = overview.replace("| ResourceName | Comment |", "| ResourceName | RouteTableId | Comment |", 1).replace(
        "| ---: | --- | --- |", "| ---: | --- | --- | --- |", 1
    )
    for row in subnet_rows:
        legacy_overview = legacy_overview.replace(row, row.replace("| Subnetの用途 |", "| [rtb-00000001](#vpc-route) | Subnetの用途 |"), 1)
    with project() as root:
        design = root / "docs/designs/dev/123456789012/vpc.md"
        design.parent.mkdir(parents=True)

        def errors(markdown):
            write(design, markdown)
            validator = MODULE.Validator(root)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(valid), errors(valid)
        merged_model = model.model_for(design, SCRIPT.parents[2])
        # An overview edit must not change resources, references, or observed IDs.
        write(design, metadata + legacy_overview + details)
        assert model.model_for(design, SCRIPT.parents[2]) == merged_model
        assert "resourceType=EC2.SubnetRouteTableAssociation" not in merged_model
        assert "desired.row.001-003.property=EC2.SubnetRouteTableAssociation.RouteTableId" in merged_model
        assert "desired.row.001-003.value=[route](#vpc-route)" in merged_model
        assert "observed.row.001-003.value=rtb-00000001" in merged_model
        assert "desired.row.002-003.property=EC2.SubnetRouteTableAssociation.RouteTableId" in merged_model
        assert "EC2.SubnetRouteTableAssociation.Id" not in merged_model
        assert "EC2.SubnetRouteTableAssociation.SubnetId" not in merged_model

        write(design,
            valid.replace("EC2.RouteTableId", f"{association_type}.RouteTableId")
        )
        catalog_types, property_owners, identifier_outputs = MODULE.Validator(
            SCRIPT.parents[2]
        ).catalog_design_properties()
        validator = schema_validator(root)
        validator.check_design_tables(
            {design: ("vpc", ("EC2.Subnet", "EC2.RouteTable", association_type))},
            catalog_types,
            property_owners,
            identifier_outputs,
        )
        assert any(
        "must use its Markdown display alias" in error
            for error in validator.errors
        ), validator.errors

        pending = valid
        for identifier in ("rtb-00000001", *(f"subnet-{number:08d}" for number in range(1, 4))):
            pending = pending.replace(identifier, "PENDING_DEPLOY")
        assert not errors(pending), errors(pending)

        bad_designs = [
            (valid + independent, "types must match"),
            (metadata + legacy_overview + details, "resource overview must use No."),
            (valid.replace(subnet_rows[0] + "\n", ""), "must list every detail resource exactly once"),
        ]
        for markdown, message in bad_designs:
            failures = errors(markdown)
            assert any(message in failure for failure in failures), (message, failures)


def check_resource_overview() -> None:
    with project() as root:
        design = root / "docs" / "designs" / "dev" / "123456789012" / "s3.md"
        design.parent.mkdir(parents=True)
        valid = """# Amazon S3 詳細設計

- Design service ID: `s3`
- Owned catalog resource types: `S3.Bucket`

## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |

## リソース詳細

<a id="s3-app-dev-data-123456789012"></a>

### S3.Bucket: app-dev-data-123456789012

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | BucketName | `app-dev-data-123456789012` | application dataを格納するbucketの名前 |
"""

        def errors(markdown: str) -> list[str]:
            write(design, markdown)
            validator = MODULE.Validator(root)
            validator.check_design_overviews()
            return validator.errors

        assert not errors(valid)
        assert any("resource overview numbering error" in error for error in errors(valid.replace("| 1 | [app-dev-data", "| 2 | [app-dev-data", 1)))
        assert any("Comment must describe the resource in Japanese" in error for error in errors(valid.replace("アプリケーションのデータを保管するbucket |", "resource |", 1)))
        assert any("must state a distinct purpose or role" in error for error in errors(valid.replace("アプリケーションのデータを保管するbucket |", "バケット（app-dev-data-123456789012）の設定 |", 1)))
        sg = valid.replace("S3.Bucket", "EC2.SecurityGroup").replace("app-dev-data-123456789012", "VULNERABILITYSCANCDESECURITYGROUP01")
        sg = sg.replace("アプリケーションのデータを保管するbucket |", "セキュリティグループ（VULNERABILITYSCANCDESECURITYGROUP01）の設定 |", 1)
        assert any("must state a distinct purpose or role" in error for error in errors(sg))
        assert not errors(sg.replace("セキュリティグループ（VULNERABILITYSCANCDESECURITYGROUP01）の設定 |", "脆弱性スキャン用ホストから検査対象への通信を制御する |", 1))
        assert any("resource overview must use No." in error for error in errors(valid.replace("| No. | ResourceName |", "| ResourceName |", 1)))
        extra = valid.replace("| ResourceName | Comment |", "| ResourceName | SSEAlgorithm | Comment |", 1)
        assert any("resource overview must use No." in error for error in errors(extra))
        details_heading = "## リソース詳細\n\n"
        invalid_sections = [
            (valid.replace(details_heading, "", 1), "details heading must appear exactly once"),
            (valid.replace(details_heading, details_heading * 2, 1), "details heading must appear exactly once"),
            (valid.replace(details_heading, "", 1).replace("## リソース一覧", details_heading + "## リソース一覧", 1), "details must follow the overview"),
            (valid.replace(details_heading, "", 1) + "\n" + details_heading, "details must follow the overview"),
            (valid.replace("### S3.Bucket:", "## S3.Bucket:", 1), "detail heading must use H3"),
            (valid.replace("### S3.Bucket:", "#### S3.Bucket:", 1), "detail heading must use H3"),
            (valid.replace(details_heading, "", 1).replace("### S3.Bucket:", details_heading + "### S3.Bucket:", 1), "anchors must be inside resource details"),
            (valid + "\n### 実装注記\n", "details must follow the overview"),
        ]
        for markdown, message in invalid_sections:
            failures = errors(markdown)
            assert any(message in failure for failure in failures), (message, failures)
        assert any("resource overview must use No." in error for error in errors(valid.replace("| ResourceName |", "| BucketName |", 1)))
        missing_row = valid.replace(
            "| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |\n",
            "",
        )
        assert any("must list every detail resource exactly once" in error for error in errors(missing_row))


def check_artifact_naming() -> None:
    trust = ["1", "AssumeRolePolicyDocument", "[Trust](iam/vpcflowlogrole01-trust-policy.json)", "信頼ポリシー"]
    old_trust = ["1", "AssumeRolePolicyDocument", "[Trust](iam/vpcflowlogrole01-assume-role-policy-document.json)", "信頼ポリシー"]
    inline_name = ["1", "Policies[].PolicyName", "`VPCFlowLogsToCloudWatchLogs`", "ポリシー名"]
    inline = ["2", "Policies[].PolicyDocument", "[Policy](iam/vpcflowlogrole01-vpc-flow-logs-to-cloud-watch-logs.json)", "権限ポリシー"]
    old_inline = ["2", "Policies[].PolicyDocument", "[Policy](iam/vpcflowlogrole01-inline-policy-document.json)", "権限ポリシー"]
    assert not errors_for([trust])
    assert errors_for([old_trust])
    assert not errors_for([inline_name, inline])
    assert errors_for([inline_name, old_inline])
    assert MODULE.artifact_id("VPCFlowLogsToCloudWatchLogs") == "vpc-flow-logs-to-cloud-watch-logs"

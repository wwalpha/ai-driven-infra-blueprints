# 詳細設計Markdownサンプル

各例の適用条件と検証ルールは[詳細設計の共通ルール](detailed-design.md)を参照する。

<a id="cloudformation-stack"></a>

## CloudFormation stack詳細設計

```md
# CloudFormation stack 詳細設計

## Stack一覧
| StackName | Template | Parameters |
| --- | --- | --- |
| cfn-stack-app-dev-job-01 | job.yaml | job-01.json |
| cfn-stack-app-dev-job-02 | job.yaml | job-02.json |
```

<a id="service-metadata"></a>

## Service metadata

```md
- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`, `EC2.FlowLog`
```

<a id="resource-overview"></a>

## リソース一覧

```md
## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |
```

<a id="resource-detail-table"></a>

## Resource-detail table

```md
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
```

<a id="macie-bucket-mapping"></a>

## Macie bucket対応表

```md
#### 対象S3 bucket

| Job | AWS account ID | Bucket |
| --- | --- | --- |
| [CdeSadJob](#macie-cdesadjob) | `123456789012` | [example-bucket](s3.md#s3-example-bucket) |
```

<a id="kms-alias"></a>

## KMS Alias

```md
<a id="kms-s3filetransferkey01"></a>

### KMS.Key: S3FILETRANSFERKEY01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | EnableKeyRotation | `true` | key materialの自動rotationを有効にする設定 |
| 3 | KMS.Alias.AliasName | `alias/venus-dev-s3-file-transfer` | <a id="kms-s3filetransferkeyalias01"></a><!-- logical-id: S3FILETRANSFERKEYALIAS01 --> KMS keyを識別するalias |
```

<a id="iam-trust-policy"></a>

## IAM信頼ポリシー表

```md
<!-- iam-policy-tables:start -->

<a id="iam-vpcflowlogsrole-trust"></a>

#### 信頼ポリシー：FlowLogsTrust

| Version |
| --- |
| `2012-10-17` |

| No. | Effect | Principal.Service | Action | Condition |
| ---: | --- | --- | --- | --- |
| 1 | Allow | `vpc-flow-logs.amazonaws.com` | `sts:AssumeRole` | `ArnLike`：`aws:SourceArn` = `arn:aws:ec2:ap-northeast-1:123456789012:vpc-flow-log/*`<br>`StringEquals`：`aws:SourceAccount` = `123456789012` |

<!-- iam-policy-tables:end -->
```

<a id="pending-reference"></a>

## Deploy前の参照

```md
| 4 | EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
```

<a id="deployed-reference"></a>

## Deploy後の参照

```md
| 4 | EC2.Subnet.VpcId | [vpc-0123456789abcdef0](#vpc-vpc-app-dev) | Subnetが所属するVPC |
```

<a id="identifier-output"></a>

## Resource自身のidentifier output

```md
| 1 | EC2.VPC.VpcId | vpc-0123456789abcdef0 | 一意に識別するID |
```

# Detailed Design Markdown Samples

See [common detailed design rules](detailed-design.md) for each example's applicable conditions and validation rules.

<a id="cloudformation-stack"></a>

## CloudFormation stack detailed design

```md
# CloudFormation stack 詳細設計

<!-- max-concurrent-stacks: 2 -->

## Stack一覧

| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | cfn-stack-app-dev-job-daily | job.yaml | job-daily.json | 日次集計jobを配置するstack |
| 2 | 10 | cfn-stack-app-dev-job-monthly | job.yaml | job-monthly.json | 月次集計jobを配置するstack |
```

<a id="service-metadata"></a>

## Service metadata

```md
- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`, `EC2.FlowLog`
```

<a id="resource-overview"></a>

## Resource overview

```md
## リソース一覧

### S3.Bucket

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | アプリケーションのデータを保管するbucket |
```

<a id="resource-name-heading"></a>

## Resource name headings and internal IDs

IAM Role ResourceName and detail headings display RoleName; retain internal logical IDs in hidden metadata.

```md
### IAM.Role

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [app-dev-worker-role](#iam-app-dev-worker-role) | workerがデータを読み取るための実行権限 |

## リソース詳細

<!-- resource-logical-id: WorkerRole -->
<a id="iam-app-dev-worker-role"></a>

### IAM.Role: app-dev-worker-role

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | `app-dev-worker-role` | workerの実行権限を識別するロール名 |
| 2 | AssumeRolePolicyDocument | [WorkerTrust](iam/worker-role-trust-policy.json) | workerからの引受を許可する信頼ポリシー |
```

```md
<!-- resource-logical-id: CoreSystemNightlyProcessingCompletedDetect0200To0455Schedule -->
<a id="scheduler-ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455"></a>

### Scheduler.Schedule: ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455` | 夜間処理の完了を5分間隔で検知するschedule名 |
```

Overview/reference links use `[ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455](#scheduler-ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455)`. Internal ID markers are not displayed.

<a id="nameless-resource-heading"></a>

## Single resources of a type without name properties

Example with no name property, selected Name tag, or existing confirmed display label, and exactly 1 standalone resource of the same type in the same service. The logical ID is an example value; actual designs retain confirmed values.

```md
# AWS Security Hub 詳細設計

- Design service ID: `securityhub`
- Owned catalog resource types: `SecurityHub.Hub`

## リソース一覧

### SecurityHub.Hub

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [SecurityHub.Hub](#securityhub-securityhub.hub) | セキュリティ検出結果を集約するHub |

## リソース詳細

<!-- resource-logical-id: SecurityHub -->
<a id="securityhub-securityhub.hub"></a>

### SecurityHub.Hub

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EnableDefaultStandards | `true` | デフォルトの標準を有効にする設定 |
```

Ordinary reference links use `[SecurityHub.Hub](securityhub.md#securityhub-securityhub.hub)`. Do not save type names in `display.resource.*.label`. For multiple resources of the same type, use individually confirmed labels and retain existing confirmed labels.

<a id="vpc-endpoint-name-tag"></a>

## Mandatory VPC Endpoint Name tags

The name components below are example values; actual designs use human-confirmed values and existing patterns.

```md
## リソース一覧

### EC2.VPCEndpoint

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [vpce-app-dev-s3](#vpc-vpce-app-dev-s3) | VPCからS3へ接続するGateway Endpoint |

## リソース詳細

<!-- resource-logical-id: S3Endpoint -->
<a id="vpc-vpce-app-dev-s3"></a>

### EC2.VPCEndpoint: vpce-app-dev-s3

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | Endpointを識別するID |
| 2 | ServiceName | `com.amazonaws.ap-northeast-1.s3` | 接続先のS3 service |
| 3 | Tags[1].Key | `Name` | <!-- array-source: ["Tags[].Key", "`Name`", 1] --> 名前を識別するタグのキー |
| 4 | Tags[1].Value | `vpce-app-dev-s3` | <!-- array-source: ["Tags[].Value", "`vpce-app-dev-s3`", 1] --> Endpointを識別する名前 |
| 5 | VpcEndpointType | `Gateway` | Endpointの接続方式 |
| 6 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Endpointが所属するVPC |
```

Ordinary references display `[vpce-app-dev-s3](vpc.md#vpc-vpce-app-dev-s3)`. Id and Id references display current IDs / `PENDING_DEPLOY` according to existing rules; separate hidden internal ID logical references in model desired from current IDs in observed. Do not create Endpoint design-only .Name or substitute display labels for missing mandatory tags.

<a id="ec2-instance-name-tag"></a>

## Mandatory EC2 Instance Name tags

Name tag values are examples; actual designs use confirmed values. Retain internal logical IDs in hidden metadata.

```md
## リソース一覧

### EC2.Instance

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [dev-app-vulnerability-scan-01](#ec2-dev-app-vulnerability-scan-01) | 脆弱性スキャンを実行するInstance |

## リソース詳細

<!-- resource-logical-id: VULNERABILITYSCANINSTANCE01 -->
<a id="ec2-dev-app-vulnerability-scan-01"></a>

### EC2.Instance: dev-app-vulnerability-scan-01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | InstanceId | `PENDING_DEPLOY` | Instanceを識別するID |
| 2 | BlockDeviceMappings[1].DeviceName | `/dev/sda1` | 起動ディスクのデバイス名 |
| 3 | BlockDeviceMappings[1].Ebs.VolumeSize | `30` | 起動ディスクの容量 |
| 4 | BlockDeviceMappings[1].Ebs.VolumeType | `gp3` | 起動ディスクの種類 |
| 5 | ImageId | `ami-0123456789abcdef0` | 起動するAMI |
| 6 | InstanceType | `t3.micro` | Instanceの種類 |
| 7 | Name | `dev-app-vulnerability-scan-01` | <!-- ec2-name-tag: ["`Name`","名前を識別するタグのキー"] --> Instanceを識別する名前 |
```

Ordinary reference links also display Name tag values. InstanceId references display current IDs / `PENDING_DEPLOY`, retaining separation of model desired logical references/observed IDs. Do not substitute design-only .Name or display labels for Name tags.

Setting table `Name` combines formal Tags Key/Value for display; retain 2 model rows. For multiple BlockDeviceMappings, display the second DeviceName and each Ebs item as `BlockDeviceMappings[2].DeviceName`, `BlockDeviceMappings[2].Ebs.VolumeSize`, etc.

<a id="resource-detail-table"></a>

## Resource-detail table

```md
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
```

<a id="macie-bucket-mapping"></a>

## Macie bucket mapping tables

```md
#### 対象S3 bucket

| Job | AWS account ID | Bucket |
| --- | --- | --- |
| [macie-app-dev-cde-sad](#macie-macie-app-dev-cde-sad) | `123456789012` | [example-bucket](s3.md#s3-example-bucket) |
```

<a id="kms-alias"></a>

## KMS Alias

```md
<!-- resource-logical-id: S3FILETRANSFERKEY01 -->
<a id="kms-venus-dev-s3-file-transfer"></a>

### KMS.Key: venus-dev-s3-file-transfer

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | EnableKeyRotation | `true` | key materialの自動rotationを有効にする設定 |
| 3 | KMS.Alias.AliasName | `alias/venus-dev-s3-file-transfer` | <a id="kms-alias-venus-dev-s3-file-transfer"></a><!-- logical-id: S3FILETRANSFERKEYALIAS01 --> KMS keyを識別するalias |
```

<a id="iam-trust-policy"></a>

## IAM trust policy tables

```md
<!-- iam-policy-tables:start -->

<a id="iam-role-app-dev-vpc-flow-logs-trust"></a>

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

## References before Deploy

```md
| 4 | EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
```

<a id="deployed-reference"></a>

## References after Deploy

```md
| 4 | EC2.Subnet.VpcId | [vpc-0123456789abcdef0](#vpc-vpc-app-dev) | Subnetが所属するVPC |
```

<a id="identifier-output"></a>

## Resource's own identifier output

```md
| 1 | EC2.VPC.VpcId | vpc-0123456789abcdef0 | 一意に識別するID |
```

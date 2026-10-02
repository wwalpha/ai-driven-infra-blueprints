# 詳細設計Markdownサンプル

各例の適用条件と検証ルールは[詳細設計の共通ルール](detailed-design.md)を参照する。

<a id="cloudformation-stack"></a>

## CloudFormation stack詳細設計

```md
# CloudFormation stack 詳細設計

## Deployment設定

| Property | Value |
| --- | ---: |
| MaxConcurrentStacks | 2 |

## Stack一覧

| No. | DeployOrder | StackName | Template | Parameters | Comment |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 10 | cfn-stack-app-dev-job-01 | job.yaml | job-01.json | 日次集計jobを配置するstack |
| 2 | 10 | cfn-stack-app-dev-job-02 | job.yaml | job-02.json | 月次集計jobを配置するstack |
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

<a id="resource-name-heading"></a>

## Resource名のheadingと内部ID

```md
<!-- resource-logical-id: CoreSystemNightlyProcessingCompletedDetect0200To0455Schedule -->
<a id="scheduler-ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455"></a>

### Scheduler.Schedule: ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | `ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455` | 夜間処理の完了を5分間隔で検知するschedule名 |
```

一覧・参照linkは`[ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455](#scheduler-ebs-venus-dev-core-nightly-completed-detect-every-5m-0200-0455)`とする。内部IDのmarkerは表示されない。

<a id="nameless-resource-heading"></a>

## 名称propertyのない同型単一resource

名称property、選択済みName tag、既存の確定済み表示labelがなく、同じservice内に同型の独立resourceが1件だけある場合の例。logical IDは例示値であり、実設計では確定済み値を保持する。

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

通常の参照linkは`[SecurityHub.Hub](securityhub.md#securityhub-securityhub.hub)`とする。型名を`display.resource.*.label`へ保存しない。同型が複数ある場合は個別の確定済みlabelを使い、既存の確定済みlabelも維持する。

<a id="vpc-endpoint-name-tag"></a>

## VPC Endpointの必須Name tag

以下の名称componentは例示値であり、実設計ではhuman-confirmedな値と既存patternを使う。

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
| 3 | Tags[].Key | `Name` | 名前を識別するタグのキー |
| 4 | Tags[].Value | `vpce-app-dev-s3` | Endpointを識別する名前 |
| 5 | VpcEndpointType | `Gateway` | Endpointの接続方式 |
| 6 | VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Endpointが所属するVPC |
```

通常の参照は`[vpce-app-dev-s3](vpc.md#vpc-vpce-app-dev-s3)`を表示する。IdやId参照は既存規則どおりcurrent ID／`PENDING_DEPLOY`を表示し、modelのdesiredには非表示内部IDのlogical reference、observedにはcurrent IDを分離する。Endpointの設計専用.Nameは作らず、必須tag不足を表示labelで代替しない。

<a id="ec2-instance-name-tag"></a>

## EC2 Instanceの必須Name tag

Name tagの値は例示値であり、実設計では確定済みの値を使う。内部logical IDは非表示metadataへ保持する。

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
| 2 | ImageId | `ami-0123456789abcdef0` | 起動するAMI |
| 3 | InstanceType | `t3.micro` | Instanceの種類 |
| 4 | Tags[].Key | `Name` | 名前を識別するタグのキー |
| 5 | Tags[].Value | `dev-app-vulnerability-scan-01` | Instanceを識別する名前 |
```

通常の参照linkもName tagの値を表示する。InstanceIdの参照はcurrent ID／`PENDING_DEPLOY`を表示し、modelのdesired logical reference／observed IDの分離を維持する。設計専用.Nameや表示labelでName tagを代替しない。

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
| [macie-app-dev-cde-sad](#macie-macie-app-dev-cde-sad) | `123456789012` | [example-bucket](s3.md#s3-example-bucket) |
```

<a id="kms-alias"></a>

## KMS Alias

```md
<!-- resource-logical-id: S3FILETRANSFERKEY01 -->
<a id="kms-s3-file-transfer-key"></a>

### KMS.Key: s3-file-transfer-key

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KeyId | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | EnableKeyRotation | `true` | key materialの自動rotationを有効にする設定 |
| 3 | KMS.Alias.AliasName | `alias/venus-dev-s3-file-transfer` | <a id="kms-alias-venus-dev-s3-file-transfer"></a><!-- logical-id: S3FILETRANSFERKEYALIAS01 --> KMS keyを識別するalias |
```

<a id="iam-trust-policy"></a>

## IAM信頼ポリシー表

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

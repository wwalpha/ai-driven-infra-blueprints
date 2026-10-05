# Logs Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

`Logs.LogGroup.LogGroupName`は、AWSサービス標準ログには送信元サービスの既定・推奨形式を適用する。Glue Jobの組込みログには下記の4パターンを適用する。その他の独自アプリケーション・運用ログには`cwlogs-{{application}}-{{environment}}-{{purpose}}`を適用する。

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Lambda | Standard function log group | `Logs.LogGroup` | `LogGroupName` | `/aws/lambda/{{function_name}}` |
| AWS Step Functions | Execution log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vendedlogs/states/{{state_machine_name}}` |
| Amazon VPC | Flow Logs log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vpc/flow-logs[/{{suffix}}]` |
| AWS Glue | Job log group | `Logs.LogGroup` | `LogGroupName` | 下記「Glue Jobのロググループ名」の4パターン |
| Other AWS services | Standard service log group | `Logs.LogGroup` | `LogGroupName` | 対象サービスの公式な既定・推奨形式 |
| Amazon CloudWatch Logs | Custom application or operational log group | `Logs.LogGroup` | `LogGroupName` | `cwlogs-{{application}}-{{environment}}-{{purpose}}` |

## Glue Jobのロググループ名

Glue 5.0の組込みログでは、custom prefixとSecurityConfigurationのCloudWatch Logs暗号化設定に応じて、完全な`LogGroupName`を次の形式とする。

| 条件 | error log group | output log group |
| --- | --- | --- |
| custom prefixなし + SecurityConfigurationなし | `/aws-glue/jobs/error` | `/aws-glue/jobs/output` |
| custom prefixあり + SecurityConfigurationなし | `<prefix>/error` | `<prefix>/output` |
| custom prefixなし + SecurityConfiguration SSE-KMS | `/aws-glue/jobs/<SecurityConfig>-role/<Role>/error` | `/aws-glue/jobs/<SecurityConfig>-role/<Role>/output` |
| custom prefixあり + SecurityConfiguration SSE-KMS | `<prefix>/<SecurityConfig>-role/<Role>/error` | `<prefix>/<SecurityConfig>-role/<Role>/output` |

- `<prefix>`はJob引数`--custom-logGroup-prefix`の確定済み値とする。prefix自体を完全な`LogGroupName`として扱わない。
- SSE-KMSの分岐は`SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.CloudWatchEncryptionMode=SSE-KMS`の場合に適用する。SecurityConfigurationを指定していてもCloudWatch Logs暗号化が`DISABLED`の場合は、表の「SecurityConfigurationなし」と同じ形式を適用する。
- `<SecurityConfig>`はJobが参照するSecurityConfigurationの確定済み名称、`<Role>`はJob実行IAM Roleの確定済みRoleNameとする。Role ARNを名称componentに使用しない。

## Application rules

- VPC Flow Logsの`[/{{suffix}}]`は任意とする。`suffix`は共通規則の`project.json`の選択target設定を使用し、設定があれば`/aws/vpc/flow-logs/<suffix>`、未設定なら直前の`/`ごと省略して`/aws/vpc/flow-logs`とする。
- AWSサービスの既定・推奨形式には、`cwlogs-...`への適合や共通のlower-kebab-case形式を要求しない。サービス固有の区切り・大文字小文字を維持する。
- `function_name`、`state_machine_name`などは送信元resourceの確定済み名称を使用する。placeholderの値や送信元サービスを推測しない。
- その他のAWSサービスは、対象サービスの公式資料で既定・推奨形式を確認し、送信元resourceとの対応を確認する。未確認の形式は適合と判定しない。
- `/aws/`で始まることだけで適合とは判定せず、送信元サービスと名称形式の対応を確認する。
- IMPORTは実際の名称を維持し、命名convention不一致をerror／blockerにしない。
- 既存resourceと既存詳細設計の確定済み名称を自動変更しない。renameまたはreplacementは別の明示依頼がある場合だけ扱う。
- 名称の確定値、参照整合性、AWS provider schemaのtype・pattern・length制約は引き続き検証する。

## References

- Lambdaの既定形式: [Configuring CloudWatch log groups](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-loggroups.html)
- Glueの独自prefixと実際のLogGroupName: [Logging for AWS Glue jobs](https://docs.aws.amazon.com/glue/latest/dg/monitor-continuous-logging.html)
- Step Functionsの推奨prefix: [Avoiding CloudWatch Logs resource policy size limits](https://docs.aws.amazon.com/step-functions/latest/dg/sfn-best-practices.html#bp-cwl)

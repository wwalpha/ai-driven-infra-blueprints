# Logs Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

`Logs.LogGroup.LogGroupName`は、Glue Job用にhumanが明示した下表の独自形式を優先し、それ以外のAWSサービス標準ログには送信元サービスの既定・推奨形式を適用する。その他の独自アプリケーション・運用ログには`cwlogs-{{application}}-{{environment}}-{{purpose}}`を適用する。

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Lambda | Standard function log group | `Logs.LogGroup` | `LogGroupName` | `/aws/lambda/{{function_name}}` |
| AWS Step Functions | Execution log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vendedlogs/states/{{state_machine_name}}` |
| AWS Glue | Custom job log group | `Logs.LogGroup` | `LogGroupName` | `/aws/glue-jobs/{{application}}/{{environment}}/{{account_id}}` |
| Other AWS services | Standard service log group | `Logs.LogGroup` | `LogGroupName` | 対象サービスの公式な既定・推奨形式 |
| Amazon CloudWatch Logs | Custom application or operational log group | `Logs.LogGroup` | `LogGroupName` | `cwlogs-{{application}}-{{environment}}-{{purpose}}` |

## Application rules

- Glue Job用独自ロググループには上記のhuman指定形式を適用する。これはAWS公式の既定名ではない。`application`はhuman-confirmedな値、`environment`は選択targetのenvironment、`account_id`は選択targetの`awsAccountId`を使用する。
- Glue 5.0の組込みログで`--custom-logGroup-prefix`にこの形式を指定する場合、実際のLogGroupNameには`/error`または`/output`が付き、security configuration有効時は追加のcomponentも付く。prefixと完全なLogGroupNameを同一視せず、サービスが付加するcomponentを維持する。
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

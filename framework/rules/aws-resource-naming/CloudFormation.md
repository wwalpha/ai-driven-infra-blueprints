# CloudFormation Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CloudFormation | Stack | `CloudFormation.Stack` | `StackName` | `cfn-stack-{{application}}-{{environment}}-{{purpose}}[-{{number}}]-{{account_id}}` |
| AWS CloudFormation | StackSet | `CloudFormation.StackSet` | `StackSetName` | `cfn-{{application}}-{{environment}}-{{purpose}}-{{deployment_scope}}` |
| AWS CloudFormation | Change set | `CloudFormation.ChangeSet` | `ChangeSetName` | `cfn-cset-{{purpose}}-{{revision}}` |

## Service-specific constraints

- AWS CloudFormation StackNameの`number`はoptionalとし、通常は省略する。同じapplication・environment・purposeの複数stackを区別する場合だけ、`account_id`の前に`-01`からの2桁連番を付ける。例：通常は`cfn-stack-app-dev-network-123456789012`、同用途の複数stackは`cfn-stack-app-dev-job-01-123456789012`、`cfn-stack-app-dev-job-02-123456789012`。
- AWS CloudFormation stack、StackSet、change setは英字で開始し、英数字とhyphenだけを使い、128文字以内とする。Change setはdeployment operationの名前であり、詳細設計resourceとして追加しない。

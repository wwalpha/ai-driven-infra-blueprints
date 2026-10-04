# Glue Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Glue | Job | `Glue.Job` | `Name` | `glue-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Security configuration | `Glue.SecurityConfiguration` | `Name` | `glsc-{{account_id}}[-{{number}}]` |
| AWS Glue | Catalog | `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS Glue JobとSecurityConfigurationの`Name`はlower-kebab-case・1〜255文字とする。Jobの`purpose`は用途を識別するhuman-confirmedなtokenを使用する。
- SecurityConfigurationのprefixは`glsc`（Glue Security Configuration）とし、`account_id`は`project.json`の選択targetの`awsAccountId`を使用する。`number`はoptionalとし、同じaccount_idにconfigurationが単体の場合は省略する。同じaccount_idに複数configurationがある場合だけ、`-01`からの2桁連番を必須とする。例：単体は`glsc-123456789012`、複数は`glsc-123456789012-01`、`glsc-123456789012-02`。

# Glue Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Glue | Job | `Glue.Job` | `Name` | `glue-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Security configuration | `Glue.SecurityConfiguration` | `Name` | `glsc[-{{number}}][-{{suffix}}]` |
| AWS Glue | Catalog | `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS Glue JobとSecurityConfigurationの`Name`はlower-kebab-case・1〜255文字とする。Jobの`purpose`は用途を識別するhuman-confirmedなtokenを使用する。
- SecurityConfigurationのprefixは`glsc`（Glue Security Configuration）とする。`number`はoptionalとし、同じAWS accountにconfigurationが単体の場合は省略する。同じAWS accountに複数configurationがある場合だけ、`-01`からの2桁連番を必須とする。例：単体は`glsc`、複数は`glsc-01`、`glsc-02`。
- SecurityConfigurationの`suffix`はoptionalとし、選択targetに設定がある場合だけ末尾へ付ける。例：`suffix=blue`なら単体は`glsc-blue`、複数は`glsc-01-blue`、`glsc-02-blue`。

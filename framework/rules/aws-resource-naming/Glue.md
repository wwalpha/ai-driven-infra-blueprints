# Glue Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Glue | Job | `Glue.Job` | `Name` | `glue-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Security configuration | `Glue.SecurityConfiguration` | `Name` | `glsc-{{application}}-{{environment}}[-{{number}}]` |
| AWS Glue | Catalog | `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS Glue JobとSecurityConfigurationの`Name`はlower-kebab-case・1〜255文字とする。Jobの`purpose`は用途を識別するhuman-confirmedなtokenを使用する。
- SecurityConfigurationのprefixは`glsc`（Glue Security Configuration）とし、application・environmentの順とする。`number`はoptionalとし、省略時は`glsc-venusinf-dev`とする。同じapplication・environmentの複数configurationを区別する場合だけ、`-01`からの2桁連番を使用できる。例：`glsc-venusinf-dev-01`、`glsc-venusinf-dev-02`。

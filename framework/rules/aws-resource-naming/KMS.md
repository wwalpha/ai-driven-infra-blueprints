# KMS Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS KMS | Customer managed key alias | `KMS.Alias` | `AliasName` | `alias/{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]` |

## Service-specific constraints

- AWS KMS aliasは`alias/`で開始し、AWS reservedの`alias/aws/`を使用しない。

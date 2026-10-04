# MWAA Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon MWAA | Environment | `MWAA.Environment` | `Name` | `mwaa-{{application}}-{{environment}}[-{{purpose}}]` |

## Service-specific constraints

- Amazon MWAA Environmentの`purpose`は用途別にenvironmentを分ける場合だけ含める。`Name`は英字で開始し、英数字、hyphen、underscoreだけを使い、1〜80文字とする。この命名patternではlower-kebab-caseを使用する。

# Macie Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon Macie | Classification job | `Macie.ClassificationJob` | `name` | `macie-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- Amazon Macie ClassificationJobの`purpose`は検出内容を識別するhuman-confirmedな値とし、`name`はnon-emptyかつ500文字以内とする。

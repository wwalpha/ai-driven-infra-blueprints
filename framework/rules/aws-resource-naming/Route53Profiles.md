# Route53Profiles Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon Route 53 Profiles | Profile | `Route53Profiles.Profile` | `Name` | `rpf-{{application}}-{{environment}}-{{region}}` |

## Service-specific constraints

- AWS Lambda function、Amazon Data Firehose delivery stream、Amazon EventBridge rule／schedule、Route 53 Resolver endpoint／rule／profileは64文字以内とする。

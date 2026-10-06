# KMS Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS KMS | Customer managed key alias | `KMS.Alias` | `AliasName` | `alias/{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]` |

## Service-specific constraints

- AWS KMS aliases must start with `alias/` and must not use the AWS-reserved `alias/aws/`.

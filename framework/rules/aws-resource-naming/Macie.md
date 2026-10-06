# Macie Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon Macie | Classification job | `Macie.ClassificationJob` | `name` | `macie-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]` |

## Service-specific constraints

- Amazon Macie ClassificationJob's `purpose` must be a human-confirmed value identifying what is detected; `name` must be non-empty and at most 500 characters.

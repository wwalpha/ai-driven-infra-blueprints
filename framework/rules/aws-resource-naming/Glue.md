# Glue Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Glue | Job | `Glue.Job` | `Name` | `glue-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Security configuration | `Glue.SecurityConfiguration` | `Name` | `glsc[-{{number}}][-{{suffix}}]` |
| AWS Glue | Catalog | `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS Glue Job and SecurityConfiguration `Name` must use lower-kebab-case and be 1–255 characters. Job `purpose` must be a human-confirmed token identifying its use.
- The SecurityConfiguration prefix is `glsc` (Glue Security Configuration). `number` is optional and omitted when there is a single configuration in the same AWS account. Only when there are multiple configurations in the same AWS account, a two-digit sequence starting at `-01` is mandatory. Examples: single: `glsc`; multiple: `glsc-01`, `glsc-02`.
- SecurityConfiguration `suffix` is optional and appended only when configured for the selected target. Example: with `suffix=blue`, single: `glsc-blue`; multiple: `glsc-01-blue`, `glsc-02-blue`.

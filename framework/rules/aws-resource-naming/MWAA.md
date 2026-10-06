# MWAA Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon MWAA | Environment | `MWAA.Environment` | `Name` | `mwaa-{{application}}-{{environment}}[-{{purpose}}]` |

## Service-specific constraints

- Include Amazon MWAA Environment's `purpose` only when separating environments by use. `Name` must start with a letter, use only alphanumeric characters, hyphens, and underscores, and be 1–80 characters. This naming pattern uses lower-kebab-case.

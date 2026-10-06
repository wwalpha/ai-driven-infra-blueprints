# CodeCommit Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CodeCommit | Repository | `CodeCommit.Repository` | `RepositoryName` | `ccmt-{{application}}[-{{environment}}]-{{purpose}}[-{{suffix}}]` |

## Service-specific constraints

- Omit AWS CodeCommit repository's `environment` when the same repository is shared across environments; include it when separate repositories are used for each environment.

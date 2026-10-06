# CodePipeline Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CodePipeline | Pipeline | `CodePipeline.Pipeline` | `Name` | `cpln-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]` |

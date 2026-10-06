# CodeBuild Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CodeBuild | Project | `CodeBuild.Project` | `Name` | `cbld-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]` |

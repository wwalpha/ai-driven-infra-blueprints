# Athena Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon Athena | Workgroup | `Athena.WorkGroup` | `Name` | `athwg-{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]` |

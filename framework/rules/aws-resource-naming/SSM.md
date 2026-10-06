# SSM Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Systems Manager | Patch baseline | `SSM.PatchBaseline` | `Name` | `sspb-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Association | `SSM.Association` | `AssociationName` | `ssma-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window | `SSM.MaintenanceWindow` | `Name` | `ssmw-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window target | `SSM.MaintenanceWindowTarget` | `Name` | `mwtg-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window task | `SSM.MaintenanceWindowTask` | `Name` | `mwts-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- The name of AWS Systems Manager Association itself targets `AssociationName`. `Name` is the referenced SSM document name (example: `AWS-RunPatchBaseline`); do not change it with this naming pattern.

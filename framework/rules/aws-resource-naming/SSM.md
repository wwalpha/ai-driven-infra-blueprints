# SSM Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Systems Manager | Patch baseline | `SSM.PatchBaseline` | `Name` | `sspb-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Association | `SSM.Association` | `AssociationName` | `ssma-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window | `SSM.MaintenanceWindow` | `Name` | `ssmw-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window target | `SSM.MaintenanceWindowTarget` | `Name` | `mwtg-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window task | `SSM.MaintenanceWindowTask` | `Name` | `mwts-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS Systems Manager Association自身の名称は`AssociationName`を対象とする。`Name`は参照するSSM document名（例：`AWS-RunPatchBaseline`）であり、この命名patternで変更しない。

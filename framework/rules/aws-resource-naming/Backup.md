# Backup Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Backup | Backup vault | `Backup.BackupVault` | `BackupVaultName` | `backup-vault-{{application}}-{{environment}}-{{purpose}}` |
| AWS Backup | Backup plan | `Backup.BackupPlan` | `BackupPlanName` | `backup-plan-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

## Service-specific constraints

- AWS Backup vaults and backup plans created in the console must be at most 50 characters.

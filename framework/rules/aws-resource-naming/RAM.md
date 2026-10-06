# RAM Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS RAM | Resource share | `RAM.ResourceShare` | `Name` | `ram-{{service}}-{{application}}-{{environment}}-share-with-{{target_type}}-{{target_token}}` |

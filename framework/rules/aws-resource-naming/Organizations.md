# Organizations Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Organizations | Service control policy | `Organizations.Policy` | `Name` | `scp-{{application}}[-{{environment}}]-{{purpose}}` |

## Service-specific constraints

- AWS Organizations Policy's `scp` pattern is used for SCPs with `Type=SERVICE_CONTROL_POLICY`. Omit `environment` when the same SCP is shared across environments; include it when separating by environment. Do not automatically apply the `scp` prefix to other policy types.

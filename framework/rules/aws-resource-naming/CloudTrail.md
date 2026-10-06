# CloudTrail Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CloudTrail | Trail | `CloudTrail.Trail` | `TrailName` | `ctrail-{{application}}-{{environment}}[-{{suffix}}]` |

`suffix` uses the selected target's configured value according to the common rules. If unset, omit it together with the separator (examples: `ctrail-venusinf-dev`; with suffix `aaaaaa`, `ctrail-venusinf-dev-aaaaaa`).

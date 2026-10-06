# Events Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon EventBridge | Rule | `Events.Rule` | `Name` | `ebr-{{rule_type}}-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |

## Service-specific constraints

- AWS Lambda functions, Amazon Data Firehose delivery streams, Amazon EventBridge rules/schedules, and Route 53 Resolver endpoints/rules/profiles must be at most 64 characters.

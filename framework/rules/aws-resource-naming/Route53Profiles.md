# Route53Profiles Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon Route 53 Profiles | Profile | `Route53Profiles.Profile` | `Name` | `rpf-{{application}}-{{environment}}-{{region}}` |

## Service-specific constraints

- AWS Lambda functions, Amazon Data Firehose delivery streams, Amazon EventBridge rules/schedules, and Route 53 Resolver endpoints/rules/profiles must be at most 64 characters.

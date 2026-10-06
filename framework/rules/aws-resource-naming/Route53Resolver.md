# Route53Resolver Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon Route 53 Resolver | Resolver endpoint | `Route53Resolver.ResolverEndpoint` | `Name` | `rslv-{{endpoint_type}}-{{application}}-{{environment}}-{{purpose}}` |
| Amazon Route 53 Resolver | Resolver rule | `Route53Resolver.ResolverRule` | `Name` | `rslvr-{{application}}-{{environment}}-{{from}}-to-{{to}}-{{domain_token}}` |

## Service-specific constraints

- AWS Lambda functions, Amazon Data Firehose delivery streams, Amazon EventBridge rules/schedules, and Route 53 Resolver endpoints/rules/profiles must be at most 64 characters.

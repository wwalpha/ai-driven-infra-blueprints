# CloudWatch Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon CloudWatch | Alarm | `CloudWatch.Alarm` | `AlarmName` | `{{account_id}}:{{environment}}:{{resource_token}}:{{aws_service}}.{{metric_name}}[.{{statistic}}][.{{condition}}][.{{severity}}]` |

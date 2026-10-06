# ApiGatewayV2 Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon API Gateway | REST, HTTP, or WebSocket API | `ApiGateway.RestApi`, `ApiGatewayV2.Api` | `Name` | `apigw-{{protocol}}-{{application}}-{{environment}}-{{purpose}}` |

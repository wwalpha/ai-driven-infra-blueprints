# SQS Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon SQS | Queue | `SQS.Queue` | `QueueName` | `sqs-{{application}}-{{environment}}-{{purpose}}[.fifo]` |

## Service-specific constraints

- Amazon SQS queues must be at most 80 characters; FIFO queues must end with `.fifo`. Amazon SNS FIFO topics must also end with `.fifo`.

# SQS Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon SQS | Queue | `SQS.Queue` | `QueueName` | `sqs-{{application}}-{{environment}}-{{purpose}}[.fifo]` |

## Service-specific constraints

- Amazon SQS queueは80文字以内とし、FIFO queueは`.fifo`で終える。Amazon SNS FIFO topicも`.fifo`で終える。

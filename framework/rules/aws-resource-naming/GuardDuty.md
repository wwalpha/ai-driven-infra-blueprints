# GuardDuty Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon GuardDuty | Malware Protection plan | `GuardDuty.MalwareProtectionPlan` | Name tag | `gdmp-{{application}}-{{environment}}-{{purpose}}[-{{number}}]` |

## Service-specific constraints

- `gdmp`はGuardDuty Malware Protectionの固定prefixとする。`purpose`は保護対象S3バケットの用途を識別するhuman-confirmedな値とする。
- `number`はoptionalとし、同じ用途のplanが複数ある場合だけ`01`からの2桁連番を使用する。例：`gdmp-venus-dev-upload`、`gdmp-venus-dev-upload-01`。
- Name tagは任意とし、humanが明示的に使用するときだけpatternを適用する。`Tags[].Key=Name`と直後の対応する`Tags[].Value`で保持し、設計専用の`.Name`は追加しない。
- `MalwareProtectionPlanId`はAWS生成identifierのため命名対象外とする。`ProtectedResource.S3Bucket.BucketName`と`Role`は参照先の確定済み値を使用し、このpatternを適用しない。

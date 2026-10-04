# Organizations Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Organizations | Service control policy | `Organizations.Policy` | `Name` | `scp-{{application}}[-{{environment}}]-{{purpose}}` |

## Service-specific constraints

- AWS Organizations Policyの`scp` patternは`Type=SERVICE_CONTROL_POLICY`のSCPに使用する。環境間で同じSCPを共有する場合は`environment`を省略し、環境別に分ける場合は含める。他のpolicy typeへ`scp` prefixを自動適用しない。

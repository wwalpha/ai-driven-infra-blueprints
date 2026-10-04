# QuickSight Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon QuickSight | Data source | `QuickSight.DataSource` | `Name` | `qsds-{{application}}-{{environment}}-{{source_type}}-{{purpose}}` |
| Amazon QuickSight | VPC connection | `QuickSight.VPCConnection` | `Name` | `qsvc-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- Amazon QuickSight DataSourceの`source_type`は`athena`、`snowflake`などの接続種別をlowercaseで表し、`purpose`は部署・情報区分などデータソースの用途を識別するhuman-confirmedな値とする。DataSourceとVPCConnectionの`Name`は1〜128文字の表示名とし、`DataSourceId`／`VPCConnectionId`とは別に扱う。

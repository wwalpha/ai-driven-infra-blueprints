# QuickSight Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon QuickSight | Data source | `QuickSight.DataSource` | `Name` | `qsds-{{application}}-{{environment}}-{{source_type}}-{{purpose}}` |
| Amazon QuickSight | VPC connection | `QuickSight.VPCConnection` | `Name` | `qsvc-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- Amazon QuickSight DataSource's `source_type` expresses the connection type, such as `athena` or `snowflake`, in lowercase; `purpose` must be a human-confirmed value identifying the data source's use, such as a department or information category. DataSource and VPCConnection `Name` are display names of 1–128 characters, handled separately from `DataSourceId` / `VPCConnectionId`.

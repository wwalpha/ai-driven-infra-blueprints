# RDS Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon RDS | DB instance | `RDS.DBInstance` | `DBInstanceIdentifier` | `rds-{{application}}-{{environment}}-{{engine}}-{{number}}` |
| Amazon RDS | DB subnet group | `RDS.DBSubnetGroup` | `DBSubnetGroupName` | `rdbsg-{{application}}-{{environment}}-{{number}}` |
| Amazon RDS | DB parameter group | `RDS.DBParameterGroup` | `DBParameterGroupName` | `rdbpg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon RDS | DB cluster parameter group | `RDS.DBClusterParameterGroup` | `DBClusterParameterGroupName` | `rdbcpg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon RDS | Option group | `RDS.OptionGroup` | `OptionGroupName` | `rdbog-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

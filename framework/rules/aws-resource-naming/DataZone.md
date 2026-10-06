# Amazon DataZone Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern | Example |
| --- | --- | --- | --- | --- | --- |
| Amazon DataZone | Domain | `DataZone.Domain` | `Name` | `dzdm-{{application}}-{{environment}}[-{{purpose}}]` | `dzdm-venusinf-dev` |
| Amazon DataZone | Project | `DataZone.Project` | `Name` | `dzprj-{{application}}-{{environment}}-{{purpose}}[-{{number}}]` | `dzprj-venusinf-dev-analytics` |
| Amazon DataZone | Data source | `DataZone.DataSource` | `Name` | `dzds-{{application}}-{{environment}}-{{source_type}}-{{purpose}}[-{{number}}]` | `dzds-venusinf-dev-glue-inbound` |

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon DataZone | Connection | `DataZone.Connection` | `Name` | `dzcn-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]` |
| Amazon DataZone | Environment | `DataZone.Environment` | `Name` | `dzenv-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]` |
| Amazon DataZone | Environment profile | `DataZone.EnvironmentProfile` | `Name` | `dzep-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]` |
| Amazon DataZone | Project profile | `DataZone.ProjectProfile` | `Name` | `dzpp-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]` |

## Service-specific constraints

- Domain `purpose` is optional. Omit the entire component and its separator when it is unset.
- Project `number` is optional and starts at `01`; use it only when multiple projects share the same application, environment, and purpose.
- Connection, Environment, Environment profile, and Project profile `number` is optional and starts at `01`; use it only when multiple resources of the same type share the same application, environment, and purpose. Omit the entire component and its separator when it is unset.
- Data source `source_type` must be a human-confirmed lower-kebab-case token. Its `number` is optional and starts at `01`; use it only when multiple data sources share the same application, environment, source type, and purpose.
- Project names must be at most 64 characters; data source names must be at most 256 characters. Confirm complete names against the provider schema before saving.

- Connection, Environment, Environment profile, and Project profile `suffix` is optional and uses the selected target's `project.json` setting under the common rules. When unset, omit the entire `[-{{suffix}}]` component including its hyphen.

# IAM Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS IAM | Role | `IAM.Role` | `RoleName` | `{{application}}-{{environment}}-{{purpose}}Role[-{{suffix}}]` |

## Service-specific constraints

- RoleName's `purpose` must be a human-confirmed PascalCase purpose name (example: `DataManagement`), followed immediately by the fixed `Role`. This component is an exception to the common lower-kebab-case rule; `application`, `environment`, and `suffix` retain the common rules. Do not automatically insert `target_alias` (example: `cde`).
- `suffix` is optional; append `-<suffix>` only when configured in the selected target's `project.json`. If unset, omit the hyphen as well. Examples: `venusinf-dev-DataManagementRole` / `venusinf-dev-DataManagementRole-aaaaaa`.
- AWS IAM Roles must be at most 64 characters and customer managed policies at most 128 characters; do not create names differing only in case.

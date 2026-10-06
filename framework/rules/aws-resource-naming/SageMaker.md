# Amazon SageMaker Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon SageMaker | Domain | `SageMaker.Domain` | `DomainName` | `smdm-{{application}}-{{environment}}[-{{purpose}}][-{{suffix}}]` |
| Amazon SageMaker | User profile | `SageMaker.UserProfile` | `UserProfileName` | `smup-{{application}}-{{environment}}-{{user_token}}[-{{suffix}}]` |
| Amazon SageMaker | Space | `SageMaker.Space` | `SpaceName` | `smsp-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]` |

## Service-specific constraints

- Domain `purpose` is optional. Omit the entire component and its separator when it is unset.
- User profile `user_token` must be a human-confirmed stable lower-kebab-case token. Do not infer it or embed generated IDs or ARNs.
- Space `number` is optional and starts at `01`; use it only when multiple spaces share the same application, environment, and purpose. Omit the entire component and its separator when it is unset.

- Domain, User profile, and Space `suffix` is optional and uses the selected target's `project.json` setting under the common rules. When unset, omit the entire `[-{{suffix}}]` component including its hyphen.

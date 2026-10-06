# Secrets Manager Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Secrets Manager | Secret | `SecretsManager.Secret` | `Name` | `{{application}}/{{environment}}/{{purpose}}` |

## Service-specific constraints

- Use ASCII `/` between hierarchy levels and lower-kebab-case within each component; do not add leading or trailing `/`. Do not automatically append number or suffix.
- Use human-confirmed values for `application` and `purpose`, and the selected target's `project.json` value for `environment`.
- Names must be 1–512 characters. To avoid confusion in partial ARN references, do not use names ending in a hyphen followed by 6 characters. Do not include the random string AWS appends to ARNs in the name. Do not persist generated ARNs in the model or generated views.
- `Name` tags are optional; use the Secret's formal `Name` for identification. Do not automatically change existing resources or confirmed names; IMPORT retains actual/current names according to the common rules.

For name constraints, see [AWS CreateSecret API](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_CreateSecret.html); for hierarchy format, see [AWS naming guide](https://docs.aws.amazon.com/prescriptive-guidance/latest/secure-sensitive-data-secrets-manager-terraform/naming-convention.html).

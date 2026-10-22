# Secrets Manager Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Secrets Manager | Secret | `SecretsManager.Secret` | `Name` | `{{application}}/{{environment}}/{{purpose_path}}` |

## Service-specific constraints

- Keep `application` as the first level and `environment` as the second level. `purpose_path` is a purpose path of one or more levels separated by ASCII `/`, with no upper limit on the number of levels within AWS name constraints. Allow 3, 4, 5 or more total levels; do not force distinct purposes into the third level.
- Use lower-kebab-case within each component; empty components and leading or trailing `/` are prohibited. Do not automatically append number or suffix.
- Use human-confirmed values for `application` and each component of `purpose_path`, and the selected target's `project.json` value for `environment`.
- Valid examples: `app/dev/credentials`, `app/dev/snowflake/keypair`, `app/dev/snowflake/keypair/lambda`, `app/dev/snowflake/keypair/lambda/rotation`. Invalid examples: `app/dev//keypair`, `/app/dev/credentials`, `app/dev/credentials/`.
- Names must be 1–512 characters and contain only ASCII letters, numbers, and `/_+=.@-`; the framework component rules above still apply to CREATE. To avoid confusion in partial ARN references, do not use names ending in a hyphen followed by 6 characters. Do not include the random string AWS appends to ARNs in the name. Do not persist generated ARNs in the model or generated views.
- `Name` tags are optional; use the Secret's formal `Name` for identification. Do not automatically change existing resources or confirmed names; IMPORT retains actual/current names according to the common rules.

For name constraints, see [AWS CreateSecret API](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_CreateSecret.html); for hierarchy format, see [AWS naming guide](https://docs.aws.amazon.com/prescriptive-guidance/latest/secure-sensitive-data-secrets-manager-terraform/naming-convention.html).

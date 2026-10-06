# GuardDuty Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon GuardDuty | Malware Protection plan | `GuardDuty.MalwareProtectionPlan` | Name tag | `gdmp-{{application}}-{{environment}}-{{purpose}}[-{{number}}]` |

## Service-specific constraints

- `gdmp` is the fixed prefix for GuardDuty Malware Protection. `purpose` must be a human-confirmed value identifying the use of the protected S3 bucket.
- `number` is optional; use a two-digit sequence starting at `01` only when multiple plans have the same purpose. Examples: `gdmp-venus-dev-upload`, `gdmp-venus-dev-upload-01`.
- Name tags are optional; apply the pattern only when the human explicitly uses one. Retain it as `Tags[].Key=Name` followed immediately by the corresponding `Tags[].Value`; do not add a design-only `.Name`.
- `MalwareProtectionPlanId` is an AWS-generated identifier and excluded from naming. `ProtectedResource.S3Bucket.BucketName` and `Role` use confirmed values of their reference targets; do not apply this pattern to them.

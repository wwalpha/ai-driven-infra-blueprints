# Logs Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

For `Logs.LogGroup.LogGroupName`, apply the source service's default/recommended format to standard AWS service logs. Apply the 4 patterns below to built-in Glue Job logs. Apply `cwlogs-{{application}}-{{environment}}-{{purpose}}` to other custom application/operational logs.

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CodeBuild | Project log group | `Logs.LogGroup` | `LogGroupName` | `/aws/codebuild/{{project_name}}[/{{suffix}}]` |
| AWS Lambda | Standard function log group | `Logs.LogGroup` | `LogGroupName` | `/aws/lambda/{{function_name}}` |
| AWS Step Functions | Execution log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vendedlogs/states/{{state_machine_name}}` |
| Amazon VPC | Flow Logs log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vpc/flow-logs[/{{suffix}}]` |
| AWS Glue | Job log group | `Logs.LogGroup` | `LogGroupName` | The 4 patterns under “Glue Job log group names” below |
| Other AWS services | Standard service log group | `Logs.LogGroup` | `LogGroupName` | The target service's official default/recommended format |
| Amazon CloudWatch Logs | Custom application or operational log group | `Logs.LogGroup` | `LogGroupName` | `cwlogs-{{application}}-{{environment}}-{{purpose}}` |

## Glue Job log group names

For built-in Glue 5.0 logs, the complete `LogGroupName` must use the following formats according to the custom prefix and SecurityConfiguration's CloudWatch Logs encryption setting.

| Condition | error log group | output log group |
| --- | --- | --- |
| No custom prefix + no SecurityConfiguration | `/aws-glue/jobs/error` | `/aws-glue/jobs/output` |
| Custom prefix + no SecurityConfiguration | `<prefix>/error` | `<prefix>/output` |
| No custom prefix + SecurityConfiguration SSE-KMS | `/aws-glue/jobs/<SecurityConfig>-role/<Role>/error` | `/aws-glue/jobs/<SecurityConfig>-role/<Role>/output` |
| Custom prefix + SecurityConfiguration SSE-KMS | `<prefix>/<SecurityConfig>-role/<Role>/error` | `<prefix>/<SecurityConfig>-role/<Role>/output` |

- `<prefix>` is the confirmed value of Job argument `--custom-logGroup-prefix`. Do not treat the prefix itself as the complete `LogGroupName`.
- The SSE-KMS branch applies when `SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.CloudWatchEncryptionMode=SSE-KMS`. Even if SecurityConfiguration is specified, when CloudWatch Logs encryption is `DISABLED`, apply the same format as “no SecurityConfiguration” in the table.
- `<SecurityConfig>` is the confirmed name of the SecurityConfiguration referenced by the Job; `<Role>` is the confirmed RoleName of the Job execution IAM Role. Do not use a Role ARN as a name component.

## Application rules

- CodeBuild uses the confirmed source `CodeBuild.Project.Name` for `project_name`. Its `[/{{suffix}}]` is optional: use the selected target's `project.json` suffix under the common rules; when configured, use `/aws/codebuild/<projectName>/<suffix>`, otherwise omit the preceding `/` as well and use `/aws/codebuild/<projectName>`.
- VPC Flow Logs' `[/{{suffix}}]` is optional. `suffix` uses the selected target's `project.json` setting under the common rules; when configured, use `/aws/vpc/flow-logs/<suffix>`, otherwise omit the preceding `/` as well and use `/aws/vpc/flow-logs`.
- Do not require AWS service default/recommended formats to conform to `cwlogs-...` or the common lower-kebab-case format. Retain service-specific separators and case.
- Use confirmed source resource names for `function_name`, `state_machine_name`, etc. Do not infer placeholder values or the source service.
- For other AWS services, verify the default/recommended format in the target service's official documentation and confirm correspondence with the source resource. Do not classify unverified formats as conforming.
- Do not classify a name as conforming merely because it starts with `/aws/`; confirm correspondence between the source service and name format.
- IMPORT retains actual names; do not treat naming convention mismatches as errors/blockers.
- Do not automatically change existing resources or confirmed names in existing detailed designs. Handle rename/replacement only with a separate explicit request.
- Continue validating confirmed name values, reference consistency, and AWS provider schema type/pattern/length constraints.

## References

- Lambda default format: [Configuring CloudWatch log groups](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-loggroups.html)
- Glue custom prefix and actual LogGroupName: [Logging for AWS Glue jobs](https://docs.aws.amazon.com/glue/latest/dg/monitor-continuous-logging.html)
- Step Functions recommended prefix: [Avoiding CloudWatch Logs resource policy size limits](https://docs.aws.amazon.com/step-functions/latest/dg/sfn-best-practices.html#bp-cwl)

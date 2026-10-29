# Logs Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

For `Logs.LogGroup.LogGroupName`, the following are standard/recommended alternatives, not mandatory structures for every LogGroup. Custom application/operational names are permitted within Provider constraints. Retain `cwlogs-{{application}}-{{environment}}-{{purpose}}` as the basic recommended custom pattern. Never validate a standard AWS name against that unrelated custom pattern.

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern | Applicability |
| --- | --- | --- | --- | --- | --- |
| AWS CodeBuild | Project log group | `Logs.LogGroup` | `LogGroupName` | `/aws/codebuild/{{project_name}}` | alternative |
| AWS Lambda | Standard function log group | `Logs.LogGroup` | `LogGroupName` | `/aws/lambda/{{function_name}}` | alternative |
| AWS Step Functions | Execution log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vendedlogs/states/{{state_machine_name}}` | alternative |
| Amazon VPC | Flow Logs log group | `Logs.LogGroup` | `LogGroupName` | `/aws/vpc/flow-logs[/{{suffix}}]` | prefix |
| AWS Glue | Job log group | `Logs.LogGroup` | `LogGroupName` | The 4 patterns under “Glue Job log group names” below | alternative |
| Other AWS services | Standard service log group | `Logs.LogGroup` | `LogGroupName` | The target service's official default/recommended format | alternative |
| Amazon CloudWatch Logs | Custom application or operational log group | `Logs.LogGroup` | `LogGroupName` | `cwlogs-{{application}}-{{environment}}-{{purpose}}` | alternative |

## Glue Job log group names

Glue 5.0 uses the following standard forms according to its custom prefix and CloudWatch Logs encryption. These forms are Naming alternatives even when the Job version, source Role or encryption setting is unavailable. Naming acceptance does not prove the source configuration or reference correspondence.

| Condition | AWS resource | Catalog resource types | Naming target | Pattern | Applicability |
| --- | --- | --- | --- | --- | --- |
| No custom prefix + no encryption | Job logs | `Logs.LogGroup` | `LogGroupName` | `/aws-glue/jobs/error` <br> `/aws-glue/jobs/output` | alternative |
| Custom prefix + no encryption | Job logs | `Logs.LogGroup` | `LogGroupName` | `{{prefix}}/error` <br> `{{prefix}}/output` | alternative |
| No custom prefix + SSE-KMS | Job logs | `Logs.LogGroup` | `LogGroupName` | `/aws-glue/jobs/{{security_configuration}}-role/{{role_name}}/error` <br> `/aws-glue/jobs/{{security_configuration}}-role/{{role_name}}/output` | alternative |
| Custom prefix + SSE-KMS | Job logs | `Logs.LogGroup` | `LogGroupName` | `{{prefix}}/{{security_configuration}}-role/{{role_name}}/error` <br> `{{prefix}}/{{security_configuration}}-role/{{role_name}}/output` | alternative |

- `{{prefix}}` denotes Job argument `--custom-logGroup-prefix`. Do not treat the prefix itself as the complete `LogGroupName`.
- The SSE-KMS branch applies when `SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.CloudWatchEncryptionMode=SSE-KMS`. Even if SecurityConfiguration is specified, when CloudWatch Logs encryption is `DISABLED`, apply the same format as “no SecurityConfiguration” in the table.
- `{{security_configuration}}` denotes the SecurityConfiguration name and `{{role_name}}` denotes the execution RoleName. Do not use a Role ARN as a name component. Existing Model reference validation continues independently.

## Application rules

- CodeBuild uses the confirmed source `CodeBuild.Project.Name` for `project_name`. Use `/aws/codebuild/<projectName>` without appending a target suffix.
- VPC Flow Logs' `[/{{suffix}}]` is optional. `suffix` uses the selected target's `project.json` setting under the common rules; when configured, use `/aws/vpc/flow-logs/<suffix>`, otherwise omit the preceding `/` as well and use `/aws/vpc/flow-logs`.
- Do not require AWS service default/recommended formats to conform to `cwlogs-...` or the common lower-kebab-case format. Retain service-specific separators and case.
- Use confirmed source resource names for `function_name`, `state_machine_name`, etc. Do not infer placeholder values or the source service.
- Other AWS standard formats and custom names are permitted. Missing source-service/version/encryption evidence alone is neither a Naming violation nor a Review requirement. This does not bypass Provider constraints or independent source/reference validation.
- An `/aws/` prefix alone proves no source correspondence. Naming AUTO_PASS records only the applicable Naming checks; it does not certify source-service configuration.
- IMPORT retains actual names; do not treat naming convention mismatches as errors/blockers.
- Do not automatically change existing resources or confirmed names in existing detailed designs. Handle rename/replacement only with a separate explicit request.
- Continue validating confirmed name values, reference consistency, and AWS provider schema type/pattern/length constraints.

## References

- Lambda default format: [Configuring CloudWatch log groups](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-loggroups.html)
- Glue custom prefix and actual LogGroupName: [Logging for AWS Glue jobs](https://docs.aws.amazon.com/glue/latest/dg/monitor-continuous-logging.html)
- Step Functions recommended prefix: [Avoiding CloudWatch Logs resource policy size limits](https://docs.aws.amazon.com/step-functions/latest/dg/sfn-best-practices.html#bp-cwl)

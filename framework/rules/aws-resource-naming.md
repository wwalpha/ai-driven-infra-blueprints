# AWS Resource Naming Rules

## Scope

This rule's framework naming convention, coverage, and mandatory Name policy apply to CREATE (including unspecified resourceMode). IMPORT retains AWS actual/current names, settings, and presence/absence of Name tags; convention mismatches or absent Name tags are not errors/blockers. Rename, Name tag addition/change, and filling provisional values are prohibited. Retain validation of AWS constraints such as provider schemas, structure, confirmed values, and references in both modes. Distinguish display labels from AWS properties. Follow `model-information.md` for classification authority.

This rule is the default naming convention when determining human-selected AWS resource names, identifiers, or `Name` tags in detailed design.

- It does not apply to AWS-generated physical IDs, ARNs, DNS names, or IP addresses.
- `IAM.ManagedPolicy.ManagedPolicyName`, `IAM.User.UserName`, and `IAM.InstanceProfile.InstanceProfileName` are excluded from the naming convention and naming rule coverage check. Do not exclude validation of missing/unconfirmed name values or provider schema type, pattern, length, etc.
- `Config.ConfigurationRecorder.Name`, `Config.DeliveryChannel.Name`, `Glue.Connection.ConnectionInput.Name`, `GuardDuty.Detector.Name`, `Route53.HostedZone.Name`, and `Route53.RecordSet.Name` are excluded from the naming rule coverage check. Retain validation of missing/unconfirmed name values and provider schema type, pattern, length, etc. Excluding `GuardDuty.Detector.Name` does not authorize adding/using properties absent from the catalog. Do not extend exclusions to Name tags or other Name properties.
- `Glue.Database.DatabaseInput.Name` and `Glue.Table.TableInput.Name` are excluded from the naming convention and naming rule coverage check. Retain Glue Database's `{{application}}*{{environment}}*{{purpose}}` and Glue Table's `{{purpose}}` as name format references; retain business table names for Glue Tables. Do not check conformity to these formats. Retain validation of missing/unconfirmed name values and provider schema type, pattern, length, etc.; do not extend exclusions to Name tags or other Name properties.
- `CodeBuild.Project.Name` is mandatory in detailed design; retain 1 row per resource with a confirmed non-empty literal. Do not substitute a Name tag or display label; stop if unconfirmed.
- Root-level `Tags` or `HostedZoneTags` indicate tagging capability only, not that a `Name` tag is mandatory. `Name` tags are optional by default.
- Catalog resource types requiring `Name` tags are `EC2.VPC`, `EC2.Subnet`, `EC2.RouteTable`, `EC2.FlowLog`, and `EC2.VPCEndpoint`. Represent the first 4 in detailed design as 1 row each of `EC2.VPC.Name`, `EC2.Subnet.Name`, `EC2.RouteTable.Name`, and `EC2.FlowLog.Name`, respectively.
- `EC2.VPCEndpoint` retains the mandatory tag as formal `Tags[].Key=Name` followed immediately by the corresponding `Tags[].Value`. Do not add a design-only `.Name`; use this Value in overviews, headings, and ordinary reference links. Do not substitute a display label for a missing tag.
- For other resources, design a `Name` tag only when the human explicitly specifies it. Do not ask, add, or classify as a blocker merely because a resource is taggable.
- `.Name` for the 4 types above is a detailed-design-only property; convert it in IaC to a tag with the case-sensitive `Name` key. Do not represent it as 2 rows of `Tags[].Key` and `Tags[].Value`.
- When other resources use human-selected `Name` tags, represent them in array form as `Tags[].Key` followed immediately by `Tags[].Value`, or in object form as a `Tags` JSON object.
- Use exactly the case-sensitive `Name` as the `Name` tag key; do not leave its value empty.
- Resource heading identifiers for the 4 types above must exactly match `.Name` values; anchors join Service ID and that value in lowercase.
- Do not automatically change existing resources or confirmed names in existing detailed designs. Handle rename/replacement only with a separate explicit request.
- If an existing resource treated as CREATE lacks a mandatory `Name` tag, do not invent a value or proceed to design saving or IaC changes; report it as a blocker.
- Apply their respective existing rules to CloudFormation logical IDs, detailed design logical IDs, and JSON artifact filenames.

## Naming rule coverage check

- This is a mandatory gate before design start. Immediately after confirming target catalog resource types and CREATE/IMPORT, before design questions about names, parameters, policies, etc., run `python3 framework/scripts/check-design-naming.py --resource-type <Catalog.ResourceType> --mode <CREATE|IMPORT>` for each target resource. CREATE checks catalog name properties and mandatory Names even when values are unconfirmed; add `--name-tag` only for human-selected optional Name tags. IMPORT, explicit Scope exclusions, and types without names retain their existing scope.
- Do not start/continue design for unregistered rules, empty patterns, rule file read failures, unknown resource types, or unexecuted/failed preflight. Stop with the missing resource type/property and cause; do not infer name candidates/alternative patterns or save models or Markdown/JSON. Do not add naming rules within the same design task.
- Rerun on resume, resource type/mode addition/change, optional Name tag selection, before design contract registration, and before saving. Only confirmations necessary to select targets, management classification, and optional Name tags may precede the gate. Do not proceed to ordinary design questions until all targets pass.
- Except for properties excluded by Scope, before saving verify rows matching the catalog resource type and Naming target in the target service file for selected name properties of creation targets, mandatory `.Name`, and human-selected `Name` tags. If unregistered, identify the target type/property and stop; do not infer patterns.
- Resources with no selected name property and types without names (example: `SecurityHub.Hub` / Security Hub CSPM) are excluded. Do not require naming patterns for display labels, internal logical IDs, or AWS-generated identifiers. Do not add Name tags merely because a resource is taggable.
- Do not change confirmed names of existing resources. This check confirms rule existence; it does not automatically rename to patterns.

## General rules

- Names without service-specific requirements must use lower-kebab-case with ASCII `-` separators.
- Represent pattern placeholders as `{{lower_snake_case}}` and optional components as `[-{{component}}]`.
- Use only human-confirmed values for semantic components such as `application`, `purpose`, `service`, `subnet_type`, and `route_type`. Do not infer values; if unconfirmed, stop and confirm one item at a time.
- Use only values matching the selected target in `project.json` for `environment`, `target_alias`, `account_id`, and `region`. Do not invent an alias for a target without one.
- `account_id` uses the selected target's `awsAccountId`.
- `suffix` uses only the value configured for the selected target in `project.json` (example: target's `"suffix": "aaaaaa"`). It must be a human-confirmed non-empty lower-kebab-case string. Different values per environment/alias and configuration for only some targets are permitted. Do not fall back to another target's value, alias, or account ID.
- Use the configured value only where a pattern contains `{{suffix}}`. For `[-{{suffix}}]`, use `-<suffix>` when configured for the selected target; otherwise omit the entire component including its separator. If a required `{{suffix}}` is unset, identify the missing value and stop. Do not automatically append suffixes to patterns without them or replace `account_id`, `target_alias`, `number`, or fixed endings (example: `-sg`). Do not automatically change existing resources or confirmed names.
- `number` starts with the two-digit `01`. Use sequences only when multiple resources have the same role.
- Use human-confirmed stable tokens for `zone`, `requester_vpc`, `accepter_vpc`, `resource_token`, and `target_token`; do not embed generated IDs or ARNs.
- Use changeable components such as `source`, `destination`, and `condition` only when the human explicitly specifies fixing those values in names.
- Do not use organization-specific tokens `ISZPF`, `ISZ`, `PF`, `isuzu`, or `isuzucojp` in generic patterns or examples.
- Confirm final names satisfy the target property's provider schema type, pattern, length, and AWS uniqueness scope. If exceeded, do not automatically truncate, add hashes, or abbreviate; ask the human for shorter values.
- If changing an explicit name entails replacement, only confirm the rename in the design task; do not proceed to IaC changes or replacement execution.
- Rows whose `Naming target` is `.Name` or `Name tag` apply the pattern to mandatory or human-selected `Name` tag values.
- If the mandatory or human-selected `Name` tag pattern is absent from the target service file's table, ask the human one question without inferring the name.

## Name tag policy

| Policy | AWS resource | Rule |
| --- | --- | --- |
| Required | VPC (`EC2.VPC.Name`), Subnet (`EC2.Subnet.Name`), Route table (`EC2.RouteTable.Name`), Flow Log (`EC2.FlowLog.Name`), VPC endpoint (Name tag of `EC2.VPCEndpoint`), individually detailed-designed EC2 Instance (Name tag of `EC2.Instance`) | Mandatory because AWS-generated IDs alone make purpose hard to identify and these resources are continually selected in the VPC console |
| Conditional | VPC peering connection, NAT gateway, Transit gateway/attachment/route table, Customer gateway, Site-to-Site VPN connection | The human decides use when multiple resources of the same kind exist, in cross-account/central networking, or when frequently selected manually in the console |
| Optional by default | Internet gateway, Elastic IP address, Security group, resources with their own name/identifier properties | Do not automatically add: they can be identified by related resources or formal names/identifiers |

Resources individually detailed-designed as `EC2.Instance` use Name tags as display names. Do not require the same `Name` tag for temporary EC2 Instances created by Auto Scaling, etc. and not treated as individual detailed design resources. Security groups use mandatory `GroupName`; do not additionally require a `Name` tag.

## Service rule lookup

After reading the common rules, read only the file matching the catalog namespace before `.` in the target resource type. Examples: `S3.Bucket` uses `S3.md`; VPC, Subnet, EC2 Instance, and Security group use `EC2.md`. Even with multiple services, read only target namespaces, not the entire directory at once. If the target rule is missing, follow the coverage check; do not infer naming patterns.

| Catalog namespace | Rule file |
| --- | --- |
| `ApiGateway` | [ApiGateway](aws-resource-naming/ApiGateway.md) |
| `ApiGatewayV2` | [ApiGatewayV2](aws-resource-naming/ApiGatewayV2.md) |
| `Athena` | [Athena](aws-resource-naming/Athena.md) |
| `AutoScaling` | [AutoScaling](aws-resource-naming/AutoScaling.md) |
| `Backup` | [Backup](aws-resource-naming/Backup.md) |
| `CloudFormation` | [CloudFormation](aws-resource-naming/CloudFormation.md) |
| `CloudTrail` | [CloudTrail](aws-resource-naming/CloudTrail.md) |
| `CloudWatch` | [CloudWatch](aws-resource-naming/CloudWatch.md) |
| `CodeBuild` | [CodeBuild](aws-resource-naming/CodeBuild.md) |
| `CodeCommit` | [CodeCommit](aws-resource-naming/CodeCommit.md) |
| `CodePipeline` | [CodePipeline](aws-resource-naming/CodePipeline.md) |
| `Config` | [Config](aws-resource-naming/Config.md) |
| `EC2` | [EC2](aws-resource-naming/EC2.md) |
| `ElasticLoadBalancingV2` | [ElasticLoadBalancingV2](aws-resource-naming/ElasticLoadBalancingV2.md) |
| `Events` | [Events](aws-resource-naming/Events.md) |
| `FMS` | [FMS](aws-resource-naming/FMS.md) |
| `Glue` | [Glue](aws-resource-naming/Glue.md) |
| `GuardDuty` | [GuardDuty](aws-resource-naming/GuardDuty.md) |
| `IAM` | [IAM](aws-resource-naming/IAM.md) |
| `KMS` | [KMS](aws-resource-naming/KMS.md) |
| `Kinesis` | [Kinesis](aws-resource-naming/Kinesis.md) |
| `KinesisFirehose` | [KinesisFirehose](aws-resource-naming/KinesisFirehose.md) |
| `Lambda` | [Lambda](aws-resource-naming/Lambda.md) |
| `Logs` | [Logs](aws-resource-naming/Logs.md) |
| `MWAA` | [MWAA](aws-resource-naming/MWAA.md) |
| `Macie` | [Macie](aws-resource-naming/Macie.md) |
| `NetworkFirewall` | [NetworkFirewall](aws-resource-naming/NetworkFirewall.md) |
| `Organizations` | [Organizations](aws-resource-naming/Organizations.md) |
| `QuickSight` | [QuickSight](aws-resource-naming/QuickSight.md) |
| `RAM` | [RAM](aws-resource-naming/RAM.md) |
| `RDS` | [RDS](aws-resource-naming/RDS.md) |
| `Route53Profiles` | [Route53Profiles](aws-resource-naming/Route53Profiles.md) |
| `Route53Resolver` | [Route53Resolver](aws-resource-naming/Route53Resolver.md) |
| `S3` | [S3](aws-resource-naming/S3.md) |
| `SNS` | [SNS](aws-resource-naming/SNS.md) |
| `SQS` | [SQS](aws-resource-naming/SQS.md) |
| `SSM` | [SSM](aws-resource-naming/SSM.md) |
| `Scheduler` | [Scheduler](aws-resource-naming/Scheduler.md) |
| `SecretsManager` | [SecretsManager](aws-resource-naming/SecretsManager.md) |
| `WAFv2` | [WAFv2](aws-resource-naming/WAFv2.md) |

If provider schema or current AWS service constraints are stricter than the target service file's constraints, apply the stricter constraints. If they cannot be satisfied, do not correct names by guessing; ask the human and stop.

## Setting table display order

- Ordinary property display order follows materials properties line order. Retain Name tag requirements and design-only .Name single-row display, heading, and anchor contracts; follow `framework/rules/detailed-design.md` for display positions.

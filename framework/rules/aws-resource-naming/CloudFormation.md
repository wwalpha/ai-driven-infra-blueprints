# CloudFormation Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CloudFormation | Stack | `CloudFormation.Stack` | `StackName` | `cfn-stack-{{application}}-{{environment}}-{{purpose}}[-{{number}}][-{{suffix}}]` |
| AWS CloudFormation | StackSet | `CloudFormation.StackSet` | `StackSetName` | `cfn-{{application}}-{{environment}}-{{purpose}}-{{deployment_scope}}` |
| AWS CloudFormation | Change set | `CloudFormation.ChangeSet` | `ChangeSetName` | `cfn-cset-{{purpose}}-{{revision}}` |

## Service-specific constraints

- AWS CloudFormation StackName's `number` is optional and normally omitted. Only when distinguishing multiple stacks with the same application, environment, and purpose, append a two-digit sequence starting at `-01` after `purpose`. Examples: normally `cfn-stack-app-dev-network`; multiple stacks for the same purpose: `cfn-stack-app-dev-job-01`, `cfn-stack-app-dev-job-02`.
- StackName's `suffix` is optional and appended only when configured for the selected target. Example: with `suffix=blue`, `cfn-stack-app-dev-network-blue`.
- AWS CloudFormation stack, StackSet, and change set names must start with a letter, use only alphanumeric characters and hyphens, and be at most 128 characters. A change set is the name of a deployment operation and must not be added as a detailed design resource.

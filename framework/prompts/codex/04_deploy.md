# Infrastructure Deployment Phase Router

Use the [Deploy Skill](../../../.agents/skills/deploy/SKILL.md) for authority and managed Worktree entry. Read this router once; follow links before the applicable phase. Reuse unchanged readings in the same Task; this never replaces current AWS reads. If the condition is unclear, read the potentially applicable section and stop if safety cannot be established.

## Normal startup

Fix SDK or CLI before preparation; honor Human choice or report the chosen method. Preserve Task authority, fixed scope and inputs, account/Region, approval and request evidence across resume. SDK and CLI are independent; never switch methods to recover or publish. No AWS operation is authorized by this router alone.

## Read before changing files

Before registration read [Task transition](../../rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../rules/task-contract.md#task-boundary), [Acceptance contract](../../rules/task-contract.md#acceptance-contract), [Topology](../../rules/project-configuration.md#topology), and [Credentials and account](../../rules/project-configuration.md#credentials-and-account). Then read [Prepare](deploy/runbook.md#prepare).

Before CloudFormation AWS execution read [Common rules](../../rules/cloudformation.md#common-rules), [AWS execution context](../../rules/cloudformation.md#aws-execution-context), [Resource mode boundary](../../rules/cloudformation.md#resource-mode-boundary), [Deployment validation and execution](../../rules/cloudformation.md#deployment-validation-and-execution), [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy), and [Properties format](../../rules/model-information.md#properties-format). SDK additionally reads [SDK Stack](deploy/runbook.md#sdk-stack) and [Managed Deploy snapshot and Git publication](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication); CLI reads [CLI Stack](deploy/runbook.md#cli-stack) and its linked operation sections. No generated detailed-design prose is a normal Deploy prerequisite.

Before Observed or generation read [Identifier lifecycle](../../rules/observed-values.md#identifier-lifecycle), [Collection and propagation](../../rules/observed-values.md#collection-and-propagation), [Observation publication](../../rules/observed-values.md#observation-publication), and [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation). Before completion read [Validation policy](../../rules/loop-engineering.md#validation-policy), [Validation scope](../../rules/loop-engineering.md#validation-scope), [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion), and [Verify and finish](deploy/runbook.md#verify-and-finish).

When applicable read [Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation), [S3 deployment artifacts](../../rules/cloudformation.md#s3-deployment-artifacts), [Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair), and [Independent controller runs and execution timing](../../rules/cloudformation.md#independent-controller-runs-and-execution-timing). Terraform reads [Terraform Rules](../../rules/terraform.md), [Properties format](../../rules/model-information.md#properties-format), [Local loop](../../rules/loop-engineering.md#local-loop), common Task/Model/Observed/completion rules and [Terraform](deploy/runbook.md#terraform).

## Direct AWS CLI method

Read [CLI Stack](deploy/runbook.md#cli-stack) and its operation-specific Rules before acting.

## CLI entrypoints

For SDK preparation and commands read [Prepare](deploy/runbook.md#prepare) and [SDK Stack](deploy/runbook.md#sdk-stack); CLI uses its independent route above.

## LLM-controlled Stack checkpoints

Read [SDK Stack](deploy/runbook.md#sdk-stack) and [final save](deploy/runbook.md#最終保存).

## Correct this Task's preparation omissions

Read [contract correction](deploy/runbook.md#correct-this-tasks-preparation-omissions) only when applicable.

## Confirm unapproved delete/replacement

Read [approval procedure](deploy/runbook.md#confirm-unapproved-deletereplacement) before requesting or applying approval.

## Unfinished AWS operation recovery

Read [unfinished operation recovery](deploy/runbook.md#unfinished-aws-operation-recovery) and the method-specific recovery before resuming an uncertain operation.

## External IaC repair handoff

Read [repair handoff](deploy/runbook.md#external-iac-repair-handoff) only for the authorized SDK one-shot repair.

## Terraform

Read [Terraform](deploy/runbook.md#terraform) for that engine.

## Verify and finish

Read [Verify and finish](deploy/runbook.md#verify-and-finish); for SDK final saving also read [final save](deploy/runbook.md#最終保存), and for CLI read [observations and publication](../../rules/cloudformation.md#observations-validation-and-publication).

## 最終保存

Read [final save](deploy/runbook.md#最終保存) for SDK final sync.

## DeployOrder selection and synchronization scope

Read [DeployOrder selection](deploy/runbook.md#deployorder-selection-and-synchronization-scope) when selecting scope.

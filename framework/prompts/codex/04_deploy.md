# Infrastructure Deployment Phase Router

Use the [Deploy Skill](../../../.agents/skills/deploy/SKILL.md) for authority and managed Worktree entry. Read this router once; follow links before the applicable phase. Reuse unchanged readings in the same Task; this never replaces current AWS reads. If the condition is unclear, read the potentially applicable section and stop if safety cannot be established.

## Normal startup

For CloudFormation fix SDK or CLI before preparation; honor Human choice or report the chosen method. Preserve Task authority, fixed scope and inputs, account/Region, approval and request evidence across resume. SDK and CLI are independent; never switch methods to recover or publish. No AWS operation is authorized by this router alone.

## Read before changing files

Before registration read [Task transition](../../rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../rules/task-contract.md#task-boundary), [Acceptance contract](../../rules/task-contract.md#acceptance-contract), [Topology](../../rules/project-configuration.md#topology) and [Credentials and account](../../rules/project-configuration.md#credentials-and-account); [Prepare](deploy/runbook.md#prepare) supplies the remaining common authority/context reads. At completion [Validation policy](../../rules/loop-engineering.md#validation-policy) and the [finish procedure](deploy/runbook.md#verify-and-finish) determine required checks. Do not read later phases now merely because they are linked here.

| When | Required next read |
| --- | --- |
| Entry / first preparation | [Managed entry](deploy/runbook.md#managed-entry), then [Prepare](deploy/runbook.md#prepare) and only the selected method's preparation |
| SDK first or continuing Stack operation | [SDK Stack](deploy/runbook.md#sdk-stack); observation saves also require its Observation reads link |
| CLI current operation | [CLI Stack](deploy/runbook.md#cli-stack), then only delivery, ChangeSet, Execute or save section for the current operation |
| All needed operations settled | [Verify and finish](deploy/runbook.md#verify-and-finish), then only the fixed method's finish |
| Failure, uncertainty or resume | SDK: [recovery](deploy/runbook.md#unfinished-aws-operation-recovery); CLI: [recovery](deploy/runbook.md#cli-recovery); missing evidence stops |
| Unapproved destructive change | [Approval wait](deploy/runbook.md#confirm-unapproved-deletereplacement) before consent or execution |
| Proven Task declaration omission | [Contract correction](deploy/runbook.md#correct-this-tasks-preparation-omissions) |
| Authorized one-shot IaC repair | [Repair](deploy/runbook.md#external-iac-repair-handoff) |
| Pending/conflicted Git publication | [Git Recovery](deploy/runbook.md#git-recovery) for the selected method |
| Terraform target | [Terraform](deploy/runbook.md#terraform) and its required common reads; no CloudFormation procedure |

The [operation matrix](deploy/runbook.md#operation-routes) indexes first/continuing/multi-Stack/sync/final/retry paths. Reuse unchanged readings; current AWS and boundary rechecks are never skipped. SDK already reads current AWS in advance, so no unconditional status-before-advance call. Unknown applicability requires the relevant safety read and a stop when unresolved. Ordinary Deploy uses approved Model/Template/Parameters/Stack definitions, not generated detailed-design prose.

## Direct AWS CLI method

Read [CLI Stack](deploy/runbook.md#cli-stack) and its operation-specific Rules before acting.

## CLI entrypoints

For SDK preparation and commands read [Prepare](deploy/runbook.md#prepare) and [SDK Stack](deploy/runbook.md#sdk-stack); CLI uses its independent route above.

## LLM-controlled Stack checkpoints

For intermediate saves read [SDK Stack](deploy/runbook.md#sdk-stack); only when ending the Task read [final save](deploy/runbook.md#最終保存).

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

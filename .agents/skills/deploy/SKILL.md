---
name: deploy
description: Use for authorized infrastructure deployment through the existing SDK controller or independent LLM-direct AWS CLI procedures, unfinished operation recovery and the SDK one-shot Implement handoff.
---

Use only the Human-authorized Deploy scope. **SDK is the default; CLI requires an explicit Human choice.** Fix `Deploy execution method: sdk` or `cli` in the CloudFormation Task before preparation/AWS access (existing Tasks without the field remain SDK). Never switch methods on resume, failure, observation or publication. No method selection grants AWS authority.

During ordinary Deploy, **never search, inspect or read Framework Python source**, including startup, continuation, errors and recovery. Use published Skills, CLI `--help` and structured results. Executing a public Python command is permitted. If those cannot resolve the issue, report it to the Human and stop; source investigation requires an explicitly separate Framework development instruction. No Sub Agents, background writer, automatic IaC repair or unrequested Task.

## Common entry

Confirm Human environment/Target, Engine, account/Region/profile, Stack scope and permitted actions against `project.json`; never infer missing scope or substitute credentials. Stop on uncertain identity, conflicting operations, changed fixed inputs or missing evidence. Deploy cannot change IaC, intended design or scenarios.

Before registration read [Task transition](../../../framework/rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../../framework/rules/task-contract.md#task-boundary), [Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract), [Topology](../../../framework/rules/project-configuration.md#topology) and [Credentials and account](../../../framework/rules/project-configuration.md#credentials-and-account). Reuse unchanged readings in this Task, never current AWS facts.

Select only the fixed method: SDK follows the sections below directly, without a Phase Router or normal Runbook read. Human-selected CLI reads [CLI preparation](../../../framework/prompts/codex/deploy/runbook.md#cli-prepare) and its operation links, skipping SDK preparation/commands. Terraform reads [Terraform](../../../framework/prompts/codex/deploy/runbook.md#terraform). Both use [managed entry](#managed-entry).

## Managed entry

Resolve the Task ID and Target; follow the Worktree [permission inspection and continuation procedure](../worktree/SKILL.md#sandbox-permission-approval-and-continuation), then use the existing lifecycle entry from a surviving root:

```console
python3 -B framework/scripts/worktree_task.py deploy-start --task-id <task-id>
```

Adopt its returned `worktree` and `task_file` for registration/preparation/child commands. Inspect only the selected Task/current checkout and necessary shared metadata under the Worktree entry procedure; never investigate unrelated checkout contents or infer scope from another Task. Do not repeat the helper's Task/Git inventory after success. Reuse the same valid unfinished Task and preserve Snapshot/progress/current requests; ambiguous ownership stops, never create a replacement Task. Offline preparation/help/read-only diagnostics remain available outside managed Worktrees.

## SDK preparation

Use the registered Python wrapper in the returned root. The first repository change is registration of `tasks/<task-id>.md`. Model, Template, Parameters and Stack definitions are execution authority; generated detailed-design prose is not. Preparation is offline and does not authorize deployment.

Offline preparation produces an external contract and summary; inspect the original contract, exact StackNames, Resource owners, Validation scope and Model/View paths before registering:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> --task-file tasks/<task-id>.md
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --register <absolute-preparation.json>
```

Repeat `--stack`, or use inclusive `--order-from`/`--order-to` instead; never combine the selectors. Optional `--service` checks the discovered owners and grants no additional services. Use `--aws-account-id` instead of `--alias` when no alias exists and the configured `--profile` when set. Missing/invalid scope, changed inputs or ambiguous ownership stop registration. Preserve the registered Snapshot and all fixed StackNames on resume; do not rerun old preparation to replace evidence. External consumers are deferred without Model/View authority. On a valid unfinished Task, use its existing contract/Snapshot and go directly to SDK operations; do not prepare/register again or search other Tasks for inputs.

## SDK operations

Keep the same Task/Target and repeat `--stack` for **every fixed StackName** on all actions, including when saving only one Stack. Use `--aws-account-id` instead of `--alias` where applicable, configured `--profile` when set; `--sequential` can only lower concurrency.

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action advance
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action sync --sync-stack <StackName>
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action checkpoint --sync-stack <StackName>
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action status
```

| Current need/result | Next operation or stop |
| --- | --- |
| First or continuing ordinary turn | `advance` reads current AWS and advances one bounded turn; no unconditional status-before-advance call. |
| Multiple Stacks | Retain full scope and configured concurrency; independent same-Order peers may continue after one failure, later Orders require earlier success. |
| Independent inspection, interruption or uncertain request | `status` and [SDK Recovery](../../../framework/prompts/codex/deploy/runbook.md#unfinished-aws-operation-recovery); retain original identity/token. |
| Current observations must be saved, including failure/running/unknown facts | Read [Observation reads](../../../framework/prompts/codex/deploy/runbook.md#observation-reads), then `sync --sync-stack`; repeat `--sync-stack` for an indivisible candidate. Intermediate sync keeps running. |
| Already saved candidate requires validation/commit/publication | `checkpoint`, with saved scope; no new AWS execution or recollection. A separate checkpoint is normally unnecessary after sync. |
| Required destructive change is unapproved | [Approval wait](../../../framework/prompts/codex/deploy/runbook.md#confirm-unapproved-deletereplacement); after full consent add `--approve-change-set <actual-approved-ID>` to the same target/scope turn. |
| Final observations/checks are ready, all requests settled | [SDK finish](#sdk-finish). |
| Git publication pending/conflicted | [Git Recovery](../../../framework/prompts/codex/deploy/runbook.md#git-recovery); never redeploy because saving failed. |

Inspect `stage`, `cause`, `nextAction`/`nextActions` and actual result separately. A null or missing command means review; do not infer authority or a retry. Stop new starts on Task/context/input mismatch or unresolved dependencies, retaining accepted requests for observation. No Sub Agents, fixed-period sync or background Model writer.

Only CREATE resources with unique explicit cfn-logicalId, active Conditions and confirmed ownership are deployable; IMPORT resources and external owners remain untouched. The Controller validates current AWS context, fixed Snapshot, template/parameters/artifacts, full ChangeSets, dependencies, DeployOrder and MaxConcurrentStacks at execution boundaries. After authentication and reviewed registration, use `advance` directly: no manual duplicate AWS inventory, mechanical `status` or DeployOrder recomputation before it. These controller checks still run at every required boundary. Do not infer AWS absence from read errors or success from an old COMPLETE/Outputs/checkpoint. Retain original StackId/ChangeSetId/token for uncertain requests; never blindly resend Create/Execute, delete, rollback or redeploy successful Stacks.

## SDK finish

When ending the Task, use the final command below, retaining full Stack scope. Add only needed `--sync-stack` observations; omit when already saved. This privately validates completed with Model/Views and adopts only PASS. Failure retains running, saved Model and successful Views. `checkpoint` resumes the same saved final intent without another `--final` or recollection. No all-Stack SUCCESS or separate pre-final complete is required. After verified publication use finalize below; unresolved Git work selects [Git Recovery](../../../framework/prompts/codex/deploy/runbook.md#git-recovery).

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action sync --final
python3 -B framework/scripts/worktree_task.py finalize --task-id <task-id>
```

Retain every fixed `--stack` and configured profile/account selector on final sync; add only needed `--sync-stack` observations. Before ending read [Verify and finish](../../../framework/prompts/codex/deploy/runbook.md#verify-and-finish) for Validation/Acceptance and reporting. No finalization while requests are active/uncertain, approval is pending, saves/checks are incomplete or publication is pending. Intermediate sync/checkpoint retains the same Worktree; checkpoint resumes saved intent without fresh AWS execution/recollection. Worktree completion/permission guards remain authoritative.

## Conditional procedures

Read only the applicable procedure, using structured `stage`, `cause`, `nextAction`/`nextActions`. Failure or a null/missing command means stop and report; a documented recovery requires its stated evidence/authority. Never infer permission to retry from an error.

| Condition | Procedure |
| --- | --- |
| Unapproved Remove / Replacement True or Conditional | [Approval](../../../framework/prompts/codex/deploy/runbook.md#confirm-unapproved-deletereplacement); consent covers the complete current ChangeSet, never partial approval |
| Interrupted or uncertain AWS operation | [SDK recovery](../../../framework/prompts/codex/deploy/runbook.md#unfinished-aws-operation-recovery) or [CLI recovery](../../../framework/prompts/codex/deploy/runbook.md#cli-recovery), matching the fixed method |
| Proven Task preparation omission | [Contract correction](../../../framework/prompts/codex/deploy/runbook.md#correct-this-tasks-preparation-omissions) |
| Preauthorized one-shot IaC repair | [Repair](../../../framework/prompts/codex/deploy/runbook.md#external-iac-repair-handoff); never investigate Framework source to diagnose it |
| Pending/conflicted Git publication | [Git recovery](../../../framework/prompts/codex/deploy/runbook.md#git-recovery); retain candidate, no AWS replay |

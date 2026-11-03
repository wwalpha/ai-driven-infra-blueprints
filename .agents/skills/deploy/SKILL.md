---
name: deploy
description: Use for authorized infrastructure deployment through the existing SDK controller or independent LLM-direct AWS CLI procedures, unfinished operation recovery and the SDK one-shot Implement handoff.
---

Use only the Human-authorized Deploy scope. **SDK is the default; CLI requires an explicit Human choice.** Fix `Deploy execution method: sdk` or `cli` in the CloudFormation Task before preparation/AWS access (existing Tasks without the field remain SDK). Never switch methods on resume, failure, observation or publication. No method selection grants AWS authority.

During ordinary Deploy, **never search, inspect or read Framework Python source**, including startup, continuation, errors and recovery. Use published Skills, CLI `--help` and structured results. Executing a public Python command is permitted. If those cannot resolve the issue, report it to the Human and stop; source investigation requires an explicitly separate Framework development instruction. No Sub Agents, background writer, automatic IaC repair or unrequested Task.

## Common entry

Confirm Human environment/Target, Engine, account/Region/profile, Stack scope and permitted actions against `project.json`; never infer missing scope or substitute credentials. Stop on uncertain identity, conflicting operations, changed fixed inputs or missing evidence. Deploy cannot change IaC, intended design or scenarios.

Before registration read [Task transition](../../../framework/rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../../framework/rules/task-contract.md#task-boundary), [Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract), [Topology](../../../framework/rules/project-configuration.md#topology) and [Credentials and account](../../../framework/rules/project-configuration.md#credentials-and-account). Reuse unchanged readings in this Task, never current AWS facts.

Select only the fixed method: SDK follows the sections below directly. Read only Common entry, Managed entry, SDK preparation and SDK operations before the first `advance`; later procedures are conditional. Human-selected CLI reads [CLI preparation](../../../framework/prompts/codex/deploy/runbook.md#cli-prepare) and its operation links, skipping SDK preparation/commands. Terraform reads [Terraform](../../../framework/prompts/codex/deploy/runbook.md#terraform). Both use [managed entry](#managed-entry).

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
```

Use `advance` for the first or continuing ordinary turn; no unconditional status-before-advance call. Retain full scope and configured concurrency: independent same-Order peers may continue after one failure; later Orders require earlier success. Only the LLM chooses save timing, never fixed-period sync.

Inspect `stage`, `cause`, `nextAction`/`nextActions` and actual result separately. Stop new starts on Task/context/input mismatch or unresolved dependencies, retaining accepted requests for observation.

Only CREATE resources with unique explicit cfn-logicalId, active Conditions and confirmed ownership are deployable; IMPORT resources and external owners remain untouched. The Controller validates current AWS context, fixed Snapshot, template/parameters/artifacts, full ChangeSets, dependencies, DeployOrder and MaxConcurrentStacks at execution boundaries. Do not manually repeat its AWS inventory or DeployOrder calculation; these checks still run at every required boundary. Do not infer AWS absence from read errors or success from an old COMPLETE/Outputs/checkpoint. Retain original StackId/ChangeSetId/token for uncertain requests; never blindly resend Create/Execute, delete, rollback or redeploy successful Stacks.

## Conditional procedures

Read only the applicable procedure. Failure or a null/missing command means stop and report; a documented recovery requires its stated evidence/authority. Never infer permission to retry from an error.

| Condition | Procedure |
| --- | --- |
| Current observations must be saved, including failure/running/unknown facts, or a saved candidate needs publication | [SDK saves](../../../framework/prompts/codex/deploy/runbook.md#sdk-saves) |
| All requests settled and ending the Task | [SDK finish](../../../framework/prompts/codex/deploy/runbook.md#sdk-finish) |
| Unapproved Remove / Replacement True or Conditional | [Approval](../../../framework/prompts/codex/deploy/runbook.md#confirm-unapproved-deletereplacement); after full consent add `--approve-change-set <actual-approved-ID>` to the same Task/target/scope turn |
| Interrupted or uncertain AWS operation | [SDK recovery](../../../framework/prompts/codex/deploy/runbook.md#unfinished-aws-operation-recovery) or [CLI recovery](../../../framework/prompts/codex/deploy/runbook.md#cli-recovery), matching the fixed method |
| Proven Task preparation omission | [Contract correction](../../../framework/prompts/codex/deploy/runbook.md#correct-this-tasks-preparation-omissions) |
| Preauthorized one-shot IaC repair | [Repair](../../../framework/prompts/codex/deploy/runbook.md#external-iac-repair-handoff); never investigate Framework source to diagnose it |
| Pending/conflicted Git publication | [Git recovery](../../../framework/prompts/codex/deploy/runbook.md#git-recovery); retain candidate, no AWS replay |

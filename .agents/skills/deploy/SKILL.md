---
name: deploy
description: Use for authorized infrastructure deployment through the existing SDK controller or independent LLM-direct AWS CLI procedures, and unfinished operation recovery.
---

Use only the Human-authorized Deploy scope. **SDK is the default; CLI requires an explicit Human choice.** Fix `Deploy execution method: sdk` or `cli` in the CloudFormation Task before preparation/AWS access (existing Tasks without the field remain SDK). Never switch methods on resume, failure, observation or publication. No method selection grants AWS authority.

During ordinary Deploy, **never search, inspect or read Framework Python source**, including startup, continuation, errors and recovery. Use published Skills, CLI `--help` and structured results. Executing a public Python command is permitted. If those cannot resolve the issue, report it to the Human and stop; source investigation requires an explicitly separate Framework development instruction. No Sub Agents, background writer, automatic IaC repair or unrequested Task.

## Common entry

Confirm Human environment/Target, Engine, account/Region/profile, Stack scope and permitted actions against `project.json`; never infer missing scope or substitute credentials. Stop on uncertain identity, conflicting operations, changed fixed inputs or missing evidence. Deploy cannot change IaC, intended design or scenarios.

For CloudFormation, a Human-specified name is not necessarily a formal StackName. Once the Environment and Target Directory are fixed, inspect the design Model's `cloudformation-stacks.properties` and obtain the formal StackNames from `desired.stack.*.name`. Compare each Human-specified name with those names: use an exact match; otherwise use a formal name only when the design establishes a unique correspondence. If there are multiple candidates, ask the Human to identify the intended Stack. If there is no candidate or the correspondence is unclear, ask the Human and do not proceed until the scope is fixed. Never guess from an ambiguous name or add a Stack the Human did not authorize. For multiple names, resolve each one and preserve the Human-authorized scope.

Before registration read [Task transition](../../../framework/rules/task-contract.md#task-transition) (including its required common and conditional reads), [Task boundary](../../../framework/rules/task-contract.md#task-boundary), [Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract), [Topology](../../../framework/rules/project-configuration.md#topology) and [Credentials and account](../../../framework/rules/project-configuration.md#credentials-and-account). Reuse unchanged readings in this Task, never current AWS facts.

Select only the fixed method: SDK follows the sections below directly. Read only Common entry, Local entry, SDK preparation and SDK operations before the first `advance`; later procedures are conditional. Human-selected CLI reads [CLI preparation](../../../framework/prompts/codex/deploy/runbook.md#cli-prepare) and its operation links, skipping SDK preparation/commands. Terraform reads [Terraform](../../../framework/prompts/codex/deploy/runbook.md#terraform). Both use [local entry](#local-entry).

## Local entry

For every new Deploy, first invoke the [Worktree Skill](../worktree/SKILL.md) and run its ordinary `create --task-name <task-name>`. Proceed only when Create succeeds and `python_setup.status` is `ready`. Use the returned Worktree root and new Task ID for Deploy registration, Preparation, AWS operations, Observed / View synchronization, Validation and Task completion. Do not search for or reuse a past Task or Worktree. If Create or Setup fails, stop before Deploy and retain resources as directed by the Worktree Skill.

Run every Deploy-related Python command in that Worktree through `python3 -B framework/scripts/run-python.py`, including Preparation, Controller, observation, Validation and Task Contract commands. It uses the existing registered shared Python environment; missing, failed or stale setup blocks execution, with no system dependency fallback. Invoke AWS CLI directly. Worktree Skill owns Git integration and Cleanup; Deploy adds no Git lifecycle operations.

CloudFormation progress and recovery remain tied to this same Task. Retain its Worktree and execution evidence, including original StackId, ChangeSetId and token, while an AWS result is unknown; follow the fixed method's existing recovery without blind resubmission. Each new Deploy checks current AWS Account, Region, Stack and ChangeSets, without using another Task's local progress. If AWS is busy or its state is unknown, do not submit new AWS operations.

## SDK preparation

Use the returned Worktree root. The first repository change is registration of `tasks/<task-id>.md`. Model, Template, Parameters and Stack definitions are execution authority; generated detailed-design prose is not. Preparation is offline and does not authorize deployment.

Before running preparation, fix the entire Stack scope as described in Common entry. Pass only confirmed formal StackNames to `--stack`; never pass an unchecked Human string or treat a service name, abbreviation or internal identifier as a formal StackName. Do not run preparation while the scope is unresolved. Offline preparation produces an external contract and summary; inspect the original contract, exact StackNames, Resource owners, Validation scope and Model/View paths before registering:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> --task-file tasks/<task-id>.md
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --register <absolute-preparation.json>
```

Repeat `--stack`, or use inclusive `--order-from`/`--order-to` instead; never combine the selectors. Optional `--service` checks the discovered owners and grants no additional services. Use `--aws-account-id` instead of `--alias` when no alias exists and the configured `--profile` when set. Missing/invalid scope, changed inputs or ambiguous ownership stop registration. Preserve this invocation’s registered Snapshot and fixed StackNames for its operations. External consumers are deferred without Model/View authority.

## SDK operations

Keep the same Task/Target and repeat `--stack` for **every fixed StackName** on all actions, including when saving only one Stack. Use `--aws-account-id` instead of `--alias` where applicable, configured `--profile` when set; `--sequential` can only lower concurrency.

```console
env BLUEPRINT_TASK_FILE=tasks/<task-id>.md python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> --action advance
```

Use `advance` for the first or continuing ordinary turn; no unconditional status-before-advance call. Retain full scope and configured concurrency: independent same-Order peers may continue after one failure; later Orders require earlier success. Only the LLM chooses save timing, never fixed-period sync.

Inspect `stage`, `cause`, `nextAction`/`nextActions` and actual result separately. Stop new starts on Task/context/input mismatch or unresolved dependencies, retaining accepted requests for observation.

For each Stack, inspect `states[*].progress` for Stack status, phase, observed counts and active Resources. `available`, `partial`, `stale`, `countsAvailable` and `eventAsOf` qualify that observation; no total or percentage is inferred. For stops, read `states[*].diagnostic` including `code`, `message`, `resource`, `requiredAction` and available event evidence; report redaction or unavailable events. Approval waits and uncertain requests retain their existing Human and no-blind-retry boundaries.

Only CREATE resources with unique explicit cfn-logicalId, active Conditions and confirmed ownership are deployable; IMPORT resources and external owners remain untouched. The Controller validates current AWS context, fixed Snapshot, template/parameters/artifacts, full ChangeSets, dependencies, DeployOrder and MaxConcurrentStacks at execution boundaries. Do not manually repeat its AWS inventory or DeployOrder calculation; these checks still run at every required boundary. Do not infer AWS absence from read errors or success from an old COMPLETE/Outputs/checkpoint. Retain original StackId/ChangeSetId/token for uncertain requests; never blindly resend Create/Execute, delete, rollback or redeploy successful Stacks.

## Conditional procedures

Read only the applicable procedure. Failure or a null/missing command means stop and report; a documented recovery requires its stated evidence/authority. Never infer permission to retry from an error.

| Condition | Procedure |
| --- | --- |
| Current observations must be saved, including failure/running/unknown facts, or a saved local sync needs recovery | [SDK saves](../../../framework/prompts/codex/deploy/runbook.md#sdk-saves) |
| All requests settled and ending the Task | [SDK finish](../../../framework/prompts/codex/deploy/runbook.md#sdk-finish) |
| Unapproved Remove / Replacement True or Conditional | [Approval](../../../framework/prompts/codex/deploy/runbook.md#confirm-unapproved-deletereplacement); after full consent add `--approve-change-set <actual-approved-ID>` to the same Task/target/scope turn |
| Interrupted or uncertain AWS operation | [SDK recovery](../../../framework/prompts/codex/deploy/runbook.md#unfinished-aws-operation-recovery) or [CLI recovery](../../../framework/prompts/codex/deploy/runbook.md#cli-recovery), matching the fixed method |
| Proven Task preparation omission | [Contract correction](../../../framework/prompts/codex/deploy/runbook.md#correct-this-tasks-preparation-omissions) |
| Failed Deploy | Review the AWS state and failure evidence. Use a separate authorized Implement Task for IaC corrections. |

# Repository Initialization Prompt

Follow [task-contract](../../rules/task-contract.md) for contract registration, reservations, stopping/resuming.

Use this prompt for Codex to confirm necessary initialization values with the human and create `project.json` and target paths. Do not assume `docs/system-overview.md` has been created or filled in.

Do not ask the human to create/edit JSON. Complete questions, answers, normalization, and file creation within this initialization task.

## Unresolved issue gate

Apply [issue-gate](../../rules/issue-gate.md) for target service stop decisions and exceptions before start/resume/mutation.

## First response

In the first response after prompt execution, ask only Project name without changing files.

```text
repository初期化を始めます。

Step 1: Project
Project nameを入力してください。
```

## Read first

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. Existing `project.json` (if present)
4. [project-configuration](../../rules/project-configuration.md)
5. [issue-gate](../../rules/issue-gate.md)
6. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope), and [Other task completion](../../rules/loop-engineering.md#other-task-completion)

Follow AGENTS.md “必要な規則の読み方” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.

## Stop before reinitialization

If `project.json` already exists, treat the repository as initialized. Stop without changing files or existing paths and report that target addition requires a migration task using `framework/prompts/codex/02_add-target.md`.

## Collect required values

Ask only one question per response in the following order. Do not present multiple questions, question lists, or input tables at once.

1. Project name
2. Confirm one Environment ID and ask whether to add another environment. Repeat until no additions remain
3. For each environment, confirm whether it has one or multiple logical destinations. Only for multiple destinations, confirm aliases one at a time, repeating until no additions remain
4. Confirm each target's AWS account ID (`awsAccountId`) one at a time, for resource creation ID settings/names and target identity. The same AWS account ID may be assigned to different aliases
5. Confirm AWS region for each target one at a time
6. Confirm IaC engine for each target one at a time
7. Confirm optional AWS profiles for each target one at a time. They may be omitted if unnecessary; continue initialization even when unset
8. Confirm optional AWS execution account IDs (`awsExecutionAccountId`) for each target one at a time. When omitted, authenticate against `awsAccountId`
9. Confirm optional naming suffixes for each target one at a time. Omit for targets not needing them; when specified, use confirmed non-empty lower-kebab-case strings

Explain that Environment IDs and aliases use lower-kebab-case, AWS account IDs are 12 digits, and IaC engine is `cloudformation` or `terraform`. Use only aliases entered by the human; do not have fixed candidates such as `cde` or `non-cde`.

- Collect only targets whose Environment ID, AWS account ID, AWS region, and IaC engine are all currently confirmed.
- Exclude not-yet-created targets or targets with unconfirmed required values from this initialization; do not record placeholders or `UNSET`. Explain they may be added after confirmation with `framework/prompts/codex/02_add-target.md`.
- On each answer, check format and contradictions with previous answers before proceeding.
- For invalid/unclear answers, briefly explain the reason and ask only the same item again.
- If the human volunteers multiple confirmed values, accept them and ask only the next unresolved item.
- If the human requests corrections, update the corresponding values and return to dependent unresolved items.
- Omit optional `alias` when an environment has only one target. With multiple targets, aliases are mandatory for all; do not mix aliased/non-aliased targets.
- Aliases must be unique within the same environment; values consisting only of 12 digits are prohibited.
- Keep IaC engines consistent across multiple aliases with the same environment/AWS account ID.
- Do not create questionnaires, answer histories, or session state files; retain ongoing answers only in conversation context.
- Do not infer values.

Once all values are available, list the project and all targets and ask only one confirmation whether to initialize the repository. Do not change files until the human explicitly approves.

## Validate answers

Before file changes, confirm the following.

- Project name is non-empty
- Optional target suffixes are non-empty lower-kebab-case strings. Configuration for only some targets is permitted; do not save unconfirmed values
- At least 1 target exists
- Environment IDs are lower-kebab-case
- AWS account IDs are 12 digits
- Optional AWS execution account IDs are strings of 12 ASCII digits. Keep IaC engines consistent also across targets with the same environment/execution account. Do not automatically switch authentication or connect to AWS in this task
- AWS regions are non-empty
- IaC engine is `cloudformation` or `terraform`
- Environments with one target have no alias; all targets in environments with multiple targets have unique valid aliases
- Target-directory `alias` or `awsAccountId` is not duplicated within the same environment
- Targets with the same environment/AWS account ID use the same IaC engine
- Optional AWS profiles, if specified, are non-empty strings without leading/trailing whitespace, newlines, NUL, or `UNSET`. Do not verify profile existence or connect to AWS in this task

If missing/invalid values remain, stop without changes.

## Create active task contract

As the first repository change, newly register `tasks/<task-name>.md` under the following conditions.

```md
- Task type: `initialization`
```

- Limit the goal to initialization of confirmed project topology and target paths
- AWS mutation, AWS API, deploy, and apply are prohibited
- In `Required changes`, separately state `project.json` creation, target path creation, and IaC engine selection with unique Requirement IDs
- Map `Acceptance checks` to each Requirement ID using `changed:project.json`, `exists:` for paths to create, and `absent:` for unselected IaC roots
- Limit allowed paths to `project.json`, target `docs/designs/**` and `model/**` to create, selected IaC initialization paths, IaC engine roots unselected by all targets, and `tasks/<task-name>.md`
- Resource design, IaC implementation, and AWS connection checks are out of scope
- Do not change `tests/scenarios/**` or `tests/results/**`

## Create project topology

Create `project.json` at repository root from human-confirmed values. Use UTF-8, 2-space indentation, and a final newline; sort targets by environment, then target directory. Target directory is the alias if present, otherwise AWS account ID.

```json
{
  "projectName": "<confirmed-project-name>",
  "targets": [
    {
      "environment": "<confirmed-environment-id>",
      "alias": "<confirmed-optional-alias>",
      "awsAccountId": "<confirmed-12-digit-account-id>",
      "awsExecutionAccountId": "<confirmed-optional-12-digit-execution-account-id>",
      "awsRegion": "<confirmed-region>",
      "iacEngine": "<cloudformation-or-terraform>",
      "awsProfile": "<confirmed-optional-profile>",
      "suffix": "<confirmed-optional-suffix>"
    }
  ]
}
```

For targets without aliases, omit the `alias` key itself. Record only confirmed initialization values; do not include `UNSET`, background, purpose, account roles, or design decisions.
For targets without suffixes, omit the `suffix` key itself. Use suffixes only in patterns containing `{{suffix}}` according to `framework/rules/aws-resource-naming.md`.
For targets without AWS execution account IDs, omit the `awsExecutionAccountId` key itself. Retain `awsAccountId` for selectors and paths.
For targets without AWS profiles, omit the `awsProfile` key itself. Do not record credentials.

## Create target paths

For each target, create only absent paths and place `.gitkeep` in empty directories.

```text
docs/designs/<environment>/<target-directory>/.gitkeep
model/<environment>/<target-directory>/.gitkeep
```

If IaC engine is `cloudformation`:

```text
infra/cloudformation/parameters/<environment>/<target-directory>/.gitkeep
```

If IaC engine is `terraform`:

```text
infra/terraform/environments/<environment>/<target-directory>/.gitkeep
```

Check all targets' `iacEngine` and delete roots of IaC engines selected by no targets.

- If no target selects CloudFormation, delete `infra/cloudformation/`.
- If no target selects Terraform, delete `infra/terraform/`.
- Retain both roots only when both are selected.
- If deletion targets contain files other than `.gitkeep`, stop without deleting them as existing implementations.

## Do not create

- Empty detailed design Markdown
- Empty service model properties
- CloudFormation template
- Terraform modules, resources, providers, or state settings
- IaC engine directories unselected by all targets
- Questionnaires, answer histories, session state
- sample environment、sample AWS account
- scenario、scenario result、general task evidence

## Existing repository handling

- Do not overwrite existing designs, models, or IaC implementations.
- Reuse existing target paths; do not change contents solely for `.gitkeep`.
- Stop if confirmed topology contradicts existing target paths or IaC engines.

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode task`
2. `python -m py_compile framework/scripts/blueprint-loop.py framework/scripts/validate-blueprint.py`
3. `git diff --check`

Record validation results, created topology, created paths, existing paths left unchanged, and blockers only in Codex completion reports. Do not save verification results in the repository. After initialization, do not create or execute design, infrastructure, or scenario-test tasks.

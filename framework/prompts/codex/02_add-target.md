# Add Project Target Prompt

Follow [task-contract](../../rules/task-contract.md) for contract registration, reservations, stopping/resuming.

Use this prompt for migration adding 1 environment/logical target with confirmed required values to `project.json` in an initialized repository.

Do not ask the human to create/edit JSON. Do not infer values; complete questions, confirmations, and file changes within this migration task.

## Unresolved issue gate

Apply [issue-gate](../../rules/issue-gate.md) for target service stop decisions and exceptions before start/resume/mutation.

## First response

In the first response after prompt execution, ask only the Environment ID to add without changing files.

```text
project target追加を始めます。

Step 1: Environment
追加するEnvironment IDを入力してください。
```

## Read first

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `project.json`
4. [project-configuration](../../rules/project-configuration.md)
5. [issue-gate](../../rules/issue-gate.md)
6. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope), and [Other task completion](../../rules/loop-engineering.md#other-task-completion)

If `project.json` is absent, stop without changing files and report that initialization using `framework/prompts/codex/01_initialize.md` is required.

Follow AGENTS.md “How to read required rules” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.

## Collect required values

Ask only one question per response in the following order.

1. Environment ID
2. New alias, only when the existing environment has alias targets
3. AWS account ID (`awsAccountId`) for resource creation ID settings/names and target identity
4. AWS region
5. IaC engine
6. AWS profile (optional; omit if unnecessary and continue target addition)
7. AWS execution account ID (`awsExecutionAccountId`, optional; when omitted, authenticate against `awsAccountId`)
8. Naming suffix (optional; when specified, a confirmed non-empty lower-kebab-case string)

Explain that Environment IDs and aliases use lower-kebab-case, AWS account IDs are 12 digits, and IaC engine is `cloudformation` or `terraform`.

- Do not infer unknown/unconfirmed values or change files. Explain the same prompt may be rerun after required values are confirmed and stop.
- If the human volunteers multiple confirmed values, accept them and ask only the next unresolved item.
- On each answer, check format, duplication with existing targets, and contradictions with existing paths or IaC engines.
- Omit aliases when adding only one target to a new environment. A new unique alias may be added only when all existing environment targets have aliases.
- Adding a second target to an existing environment without aliases requires changing its existing target; stop without changing it in this prompt.
- Do not create questionnaires, answer histories, or session state files; retain ongoing answers only in conversation context.

Once all values are available, present the target to add and ask only one confirmation whether to add it. Do not change files until the human explicitly approves.

## Validate answers

Before file changes, confirm the following.

- `project.json` is valid under the current schema
- Environment ID is lower-kebab-case
- AWS account ID is 12 digits
- Optional AWS execution account ID is a string of 12 ASCII digits. Keep IaC engines consistent also across targets with the same environment/execution account. Do not automatically switch authentication or connect to AWS in this task
- Optional suffix is a non-empty lower-kebab-case string. Do not copy it from another target
- AWS region is non-empty
- IaC engine is `cloudformation` or `terraform`
- Optional AWS profile, if specified, is a non-empty string without leading/trailing whitespace, newlines, NUL, or `UNSET`. Do not verify profile existence or connect to AWS in this task
- The target-directory alias or AWS account ID does not exist in the same environment
- The alias is unique lower-kebab-case within the same environment and is not only 12 digits
- If an existing target has the same environment/AWS account ID, the IaC engine matches
- Target paths have no existing files other than `.gitkeep`

Stop without changes for missing, invalid, duplicate, or contradictory values.

## Create active task contract

As the first repository change, newly register `tasks/<task-name>.md` under the following conditions.

```md
- Task type: `migration`
```

- Limit the goal to addition of 1 confirmed target
- AWS mutation, AWS API, deploy, and apply are prohibited
- In `Required changes`, separately state `project.json` updates, target path creation, and selected IaC path creation with unique Requirement IDs
- Map `Acceptance checks` to each Requirement ID using `changed:project.json` and `exists:` or `changed:` for paths to create
- Limit Allowed paths to `project.json`, added target `docs/designs/**` and `model/**`, selected IaC target paths, and `tasks/<task-name>.md`
- Changes to existing targets, designs, models, IaC implementations, scenarios, or scenario results are prohibited

## Add project target

Add the confirmed target to `targets` in `project.json`, sorted by environment, then target directory. Target directory is the alias if present, otherwise AWS account ID. Do not change existing targets (including suffixes) or `projectName`. Use only the suffix confirmed by the human in this task for the added target; do not copy from another target. Retain UTF-8, 2-space indentation, and final newline.

```json
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
```

For targets without aliases, omit the `alias` key itself.
For targets without suffixes, omit the `suffix` key itself. Use this value only where naming patterns contain `{{suffix}}`.
For targets without AWS execution account IDs, omit the `awsExecutionAccountId` key itself. Retain `awsAccountId` for selectors and paths.
For targets without AWS profiles, omit the `awsProfile` key itself. Do not record credentials.

## Create target paths

Create only absent target paths and place `.gitkeep` in empty directories.

```text
docs/designs/<environment>/<target-directory>/.gitkeep
model/<environment>/<target-directory>/.gitkeep
```

If IaC engine is `cloudformation`:

```text
infra/cloudformation/parameters/<environment>/<target-directory>/.gitkeep
```

If IaC engine is `terraform`, follow [Terraform placement rules](../../rules/terraform.md):

```text
infra/<target-directory>/terraform/<environment>/.gitkeep
```

Resolve target-directory from the existing alias-or-Account-ID rule. Create only the absent Root; implementation later creates shared `infra/<target-directory>/terraform/modules/<module>/` as needed. Reuse that Module tree across environments; do not create per-environment copies, backend.tf, terraform.tfvars, or sample configuration during initialization/target addition.

Do not delete existing directories. Reuse existing target paths containing only `.gitkeep` without changing their contents.

## Do not change

- Existing target values or paths
- project name
- design、model、IaC implementation
- IaC engine root deletion
- scenario、scenario result
- Questionnaires, answer histories, session state

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode task`
2. `python -m py_compile framework/scripts/blueprint-loop.py framework/scripts/validate-blueprint.py`
3. `git diff --check`

Record validation results, added targets/paths, reused paths, and blockers only in Codex completion reports. Do not save verification results in the repository. After completion, do not create or execute design, infrastructure, or scenario-test tasks.

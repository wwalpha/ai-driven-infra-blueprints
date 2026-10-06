# Scenario Test

Follow [task-contract](../../rules/task-contract.md) for contract registration, reservations, stopping/resuming.

Use this prompt to validate application behavior and update current results as a `scenario-test` task independent of deploy. Do not create, repair, deploy, or redeploy infrastructure.

Follow [Credentials and account](../../rules/project-configuration.md#credentials-and-account) for common account/profile selection and apply [Policy account selection](../../rules/detailed-design.md#policy-account-selection) for policy-specific conditions.

## Unresolved issue gate

Apply [issue-gate](../../rules/issue-gate.md) for target service stop decisions and exceptions before start/resume/mutation.

## User input

- Scenario ID: `{{lower-kebab-case ID}}`
- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Expected behavior: `{{検証するapplication behavior}}`
- AWS mutation: `forbidden`
- Destructive operation: `forbidden`

## Resolve missing input

For placeholder, empty, or unknown required inputs, ask only one question per response in this order: Scenario ID, Target environment, Target alias (only when the selected environment has multiple targets), Target AWS account, Expected behavior. Present only environment/alias/account candidates belonging to the same target in `project.json`; do not automatically select. Do not ask aliases when an environment has only 1 target.

Do not execute scenarios requiring AWS mutation or destructive operations until target operations, resources, cleanup, and authorization scope are explicit in User input.

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `project.json`
4. [scenario-testing](../../rules/scenario-testing.md)
5. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope), and [Scenario-test task completion](../../rules/loop-engineering.md#scenario-test-task-completion)
6. Target `tests/scenarios/<scenario-id>/`
7. Target `tests/results/<scenario-id>/<environment>/<target-directory>/`
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. Read necessary `model/<environment>/<target-directory>/<service-id>.properties` as authoritative read-only design input
- [project-configuration](../../rules/project-configuration.md) and [issue-gate](../../rules/issue-gate.md).

Obtain design values from `desired.*` and necessary current identifiers from `observed.*`. Check entry indexes, locate needed properties/identifiers with existing `model_files.py --find`, and partially read only target resources and necessary referenced resources with `model_files.py --resource`. For split models, load only relevant portions of required parts into LLM context; do not preread generated `docs/designs/**` Markdown bodies as ordinary design input.

Retain Markdown/JSON artifact generation and authoritative properties consistency validation through existing scripts/local loops. Do not reduce Validation scope or checks because LLM prereading is omitted.

`<target-directory>` is the selected target's alias if present, otherwise AWS account ID. Record the actual AWS account ID from `project.json` in result metadata AWS account, not the directory name.

Follow AGENTS.md “必要な規則の読み方” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.

## Create active task contract

As the first repository change, newly register `tasks/<task-name>.md` under the following conditions.

- Task type is `scenario-test`.
- State scenario ID, environment, alias when present, AWS account, and expected behavior in the goal.
- In `Required changes`, separately state scenario definitions/implementations and current result updates for the same target with unique Requirement IDs.
- Map `Acceptance checks` to each Requirement ID using `changed:` for target scenario files and result files.
- Record AWS mutation and destructive operation values exactly as confirmed in User input.
- Limit Allowed paths to target `tests/scenarios/<scenario-id>/**`, `tests/results/<scenario-id>/<environment>/<target-directory>/**`, and `tasks/<task-name>.md` only.
- Changes to `docs/**`, `model/**`, and `infra/**` are prohibited.

## Define and execute

Before AWS execution, pass `--alias <alias>` or `--aws-account-id <account-id>` and `--read-only` to `check-deploy-context.py --environment <environment>` and confirm target, caller account, and region. Preflight automatically uses target `awsProfile` if present. Use the same profile for all scenario AWS CLI/SDK and child processes and follow `scenario-testing.md` execution rules. Retain existing authentication methods when unset.

1. Follow `framework/rules/scenario-testing.md` to create/update scenario definitions and minimum necessary test implementations.
2. Use procedures that actually observe expected behavior; deploy completion status or static settings alone are not PASS evidence.
3. Missing prerequisites or credentials/permissions are `BLOCKED`; executed tests failing pass criteria are `FAIL`.
4. Execute only authorized cleanup and record results.
5. Update only stable current results and evidence in the same result directory.

Even on failure, do not change designs, repair IaC, redeploy, or create other tasks. Briefly report root causes and observed facts and finish the scenario-test task.

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode task`
2. `git diff --check`

State scenario ID, targets, execution procedures, status, expected/actual behavior, evidence, cleanup, and blockers in the completion report.

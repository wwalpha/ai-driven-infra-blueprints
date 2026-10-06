# CloudFormation Stack Destroy Prompt

Execute only explicit CloudFormation Stack destroy as an `infrastructure` task with phase `destroy`. Input following `/destroy` supplies one or more exact StackNames, for example `/destroy venusinf-dev-vpc`. This invocation approves those StackNames once target/account/dependency checks pass; do not add a second deletion confirmation. Never broaden scope to parents, retained resources, force delete, resource removal updates, Terraform, or scenarios.

## User input

Resolve environment and alias (or 12-digit awsAccountId) from human input and `project.json`. Ask for a missing or ambiguous target; never infer account/region/profile/ownership from StackName. Use configured awsProfile, explicit matching profile, or default credential chain. Do not ask for a profile when omitted. Keep all StackNames in one controller invocation/session. Use a Python 3 launcher throughout.

## Read before changing files

1. `AGENTS.md` and this prompt in full.
2. [Task transition](../../rules/task-contract.md#task-transition), [Task boundary](../../rules/task-contract.md#task-boundary), [Acceptance contract](../../rules/task-contract.md#acceptance-contract), [Retry and stop](../../rules/task-contract.md#retry-and-stop).
3. The selected `tasks/<task-name>.md` when present.
4. Selected target in `project.json`, and `model/<environment>/<target-directory>/cloudformation-stacks.properties` (delegate indexed parts/StackName/DeployOrder resolution to local-plan).
5. [Topology](../../rules/project-configuration.md#topology), [Credentials and account](../../rules/project-configuration.md#credentials-and-account).
6. [Explicit Stack destroy](../../rules/cloudformation.md#explicit-stack-destroy).
7. [Destroy synchronization](../../rules/observed-values.md#destroy-synchronization).
8. [Unresolved issue gate](../../rules/issue-gate.md#unresolved-issue-gate), [Check timing](../../rules/issue-gate.md#check-timing).
9. [Infrastructure destroy completion](../../rules/loop-engineering.md#infrastructure-destroy-completion), [Validation scope](../../rules/loop-engineering.md#validation-scope).

Read specified sections including child sections through the next equal/higher heading. Do not read target template/parameter bodies, generated detailed-design/service Markdown bodies, deploy preparation documents, ZIPs, scenarios, or unrelated service model bodies. The controller/helper resolves ownership, identifiers and incoming references mechanically; AI does not sequentially read service models. Local loop/model generation remain machine checks. Only an explicitly requested defect investigation may read necessary affected portions.

## Local plan and contract

Before AWS APIs or repository writes, run local-plan once:

```text
python framework/scripts/cloudformation-destroy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName>] --local-plan
```

Use `--aws-account-id <12 digits>` instead of `--alias` for an unaliased target. No AWS calls occur in local-plan. Read its small machine JSON: target, units, MaxConcurrentStacks, owners, services, updates, exact paths. Stop for undeclared names, ambiguous ownership, legacy IDs without explicit cfn-logicalId, model repartition, or out-of-target incoming references. Do not repair models or widen scope in this task.

Register a contract through `task_contract.py --task-file tasks/<task-name>.md --source <external-candidate>` before any repository change. Reserve every local-plan observed path and this active contract as exact Modified files and Allowed paths; do not reserve IaC. Validation scope must explicitly include all planned owner/reference services in the same target. If no service has identifiers, include the explicit owner services (or `cloudformation-stacks` for an empty stack). Preserve other contracts and dirty work. Follow issue start/resume timing using these services.

Contract Task contract fields:

```text
- Task type: `infrastructure`
- Task status: `running`
- Infrastructure phase: `destroy`
- AWS API execution: `allowed`
- Destroy: `allowed`
- Target environment: `<environment>`
- Target alias: `<alias>`
- Target AWS account: `<project awsAccountId>`
- Destroy scope: `<StackName>` `<other StackName>`
```

Omit Target alias only for an unaliased target. Record exact stacks/account/region and external session path in Goal. Use Requirement IDs for deletion/observed consistency and map Acceptance checks to existing controller and planned model/view paths with `exists:`; do not require a diff when observed is already pending. Repository existence alone never proves AWS completion.

## Execute and resume

```text
python framework/scripts/cloudformation-destroy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName>] --state <external-session.json> [--profile <profile>] [--sequential] [--timing-log <external.jsonl>]
```

Use one new unused state path; add `--resume` to continue that same session. Resume retains exact target/profile/scope/ownership/order/limit and StackIds. For a suspended task, explicitly resume its contract with task_contract.py first. Do not launch remaining stacks in an outer loop after failure. No per-stack STS, issue scans or confirmation.

The controller owns one read-only AWS context/STS check, identity/protection/nested preflight, export/import checks, issue check immediately before first mutation, lightweight guards, standard DeleteStack by pinned StackId, terminal polling, failure drain and one batch observed sync. Do not invoke cloudformation-deploy.py or check-deploy-context.py separately. Termination protection requires a Human action in a separate scope; no automatic disable. External importers or actual dependencies conflicting with DeployOrder block all new deletes. DELETE_FAILED records reasons/events, stops new deletes, drains running peers and leaves lower orders unstarted; no repairs/force delete.

Fresh absence is ALREADY_ABSENT, with no observed reset. Saved StackId plus DELETE_IN_PROGRESS/accepted deletion evidence permits DELETE_COMPLETE when that ID disappears on resume. DELETE_INTENT alone is insufficient. Report DELETE_SKIPPED/retained resources and diagnostic read errors explicitly.

## Completion

Confirm session DELETE_COMPLETE for proven deletions and observedSynced for them; report ALREADY_ABSENT separately. The controller updates only those stacks' identifiers/incoming observed references to PENDING_DEPLOY after success and generates affected views once per batch, including partial failure batches. Desired inputs remain immutable. On generation failure, preserve models and resume synchronization in the same session.

Run exactly one final scoped loop:

```text
python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md
```

Do not run cfn-lint, validate-template, change sets, deploy_preparation.py, template/parameter/artifact validation/upload, clean IaC revision checks, deploy repair or full repository/validation digest guards. No additional full regression from this workflow. After PASS and successful terminal/sync evidence, complete only this contract. On failure apply task-contract stop rules and report proven deleted, failed, already absent, retained and unexecuted stacks. Finish without scenario tests or next tasks.

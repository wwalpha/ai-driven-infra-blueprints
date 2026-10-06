# Infrastructure Deployment Prompt

Follow [task-contract](../../rules/task-contract.md) for contract registration, reservations, stopping/resuming.

Use this prompt for an `infrastructure` task deploying/applying CloudFormation or Terraform created/validated from approved detailed designs, confirming deploy completion, and updating necessary observed values. Only controlled repair of CloudFormation failures is permitted within the same task. Do not change intended design or execute application behavior validation.

Follow [Credentials and account](../../rules/project-configuration.md#credentials-and-account) for common account/profile selection and apply [Policy account selection](../../rules/detailed-design.md#policy-account-selection) for policy-specific conditions.

## Unresolved issue gate

Apply [issue-gate](../../rules/issue-gate.md) for target service stop decisions and exceptions before start/resume/mutation. For CloudFormation, delegate checks to controllers; do not duplicate the same preflight outside them.

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Deployment scope: `{{対象のStackNameまたはTerraform root/resource。複数可}}`
- Authorized delete/replacement: `none`
- AWS profile: `{{任意。省略時はtargetのawsProfile、未設定ならdefault credential chain}}`

## Resolve missing input

Confirm User input before AWS APIs. Treat placeholder, empty, and unknown values as missing; ask only one question per response in the following order.

1. Target environment
2. Target alias (only when the selected environment has multiple targets)
3. Target AWS account
4. Deployment scope

Present only environment, alias, and AWS account candidates belonging to the same target in `project.json`; do not automatically select. Do not ask aliases when an environment has only 1 target. Treat delete/replacement as preapproved only when target resources and reasons are explicit in User input. Without preapproval, retain `none` and create change sets/plans; ask the human after creation only if unapproved delete/replacement is detected. Placeholder/empty AWS profiles use target `awsProfile`, or default credential chain when unset. Do not ask profile names. Reject explicit profiles differing from settings before execution.

If `project.json`, target approved authoritative service models, corresponding generated Markdown/JSON, or target IaC are absent, stop without guessing values. Generated artifact existence verification does not require AI body reading.

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `tasks/<task-name>.md` if present. Otherwise treat as idle and create it first under Create active task contract.
4. `project.json`
5. Authoritative `model/<environment>/<target-directory>/<service-id>.properties` entries/required parts for services owned/referenced by deployment scope, and referenced models needed for reference resolution
6. For CloudFormation, same-target `cloudformation-stacks.properties`. Delegate StackName mappings/generated stack Markdown matching to existing controller `load_units()`; AI must not manually compare the same values twice
7. [Policy account selection](../../rules/detailed-design.md#policy-account-selection). For CloudFormation, add [CloudFormation stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design); add related display sections only when changing/investigating design display.
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. [cloudformation](../../rules/cloudformation.md) or [terraform](../../rules/terraform.md) for the selected engine
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope). [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. Target IaC files, stack-specific parameters, and declared execution inputs

- [project-configuration](../../rules/project-configuration.md) and [issue-gate](../../rules/issue-gate.md).

Read mandatory documents per file/specified section. If tool output limits are exceeded, split the same file by line ranges or 6,000-character chunks described below, reviewing the specified range without omissions. Do not concatenate multiple large files into one output. Only necessary ranges actually reviewed during the same preparation need not be reread if content hashes match. Do not treat unread sections as reviewed merely from matching hashes. On changes/additions/deletions, review changes and necessary input ranges and prepare again. Do not require full rereads due to generated artifact changes.

At preparation start, fix the Python launcher to one existing available environment; use the same absolute path and PATH/PYTHONPATH for subsequent preparation, contract registration, controllers, and local loops. List missing dependencies together and resolve in the same environment; do not try different Pythons sequentially or duplicate authentication checks. Do not save credential values in logs.

Ordinary deploy AI design inputs are authoritative model properties. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, resource identity/references from existing metadata such as `desired.resource.*`, current non-ARN identifiers from `observed.*`, and stack settings from `cloudformation-stacks.properties`. Exclude generated service Markdown, `cloudformation-stacks.md`, service-owned generated JSON, and built ZIPs from ordinary body inputs.

`.md#anchor` references are not instructions to open Markdown bodies. Map path/file stem to referenced properties and confirm needed resources with existing `model_files.py --resource <resource-selector>` and metadata such as anchors. Stop for unknown/unmatched/ambiguous mappings; do not use generated Markdown body fallback.

Retain generated artifact existence verification, hash monitoring, reservations, machine generated artifact validation, and stop conditions. Only for explicit display defect/mismatch investigation, necessary artifact portions may be read. Classify model/generated artifact/IaC mismatches and deployment failures under [Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair). Repair only AUTO_REPAIRABLE and continue the same controller after validation.

`<target-directory>` is the selected target's alias if present, otherwise AWS account ID.

Follow AGENTS.md “必要な規則の読み方” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.

## CloudFormation offline preparation

Confirm and explicitly state all target StackNames and owned/referenced service IDs with existing properties readers. Do not infer service/resource/parameter/reference selections. For CloudFormation, do not generate contracts/reservations with ad hoc scripts; execute the following preparation once. Terraform uses existing contract creation procedures.

```console
<fixed-python> framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --service <service-id> [--service <service-id> ...] --task-file tasks/<task-name>.md [--profile <profile>] [--sequential] [--log-dir <external-directory>]
# aliasなしでは --aws-account-id <aws-account-id>
```

This procedure starts no AWS APIs, account authentication, mapping validation, lint, or controllers and does not change the repository. Check dependencies together; use existing `load_target` / `load_units` / `read_model` / `model_parts` to resolve target/authoritative StackNames and generated stack design equality, and existing reservation checks for conflicts. Reserve exact paths for explicit services including `cloudformation-stacks`: model entries, parts, splitting candidates for observed additions, and generated Markdown/JSON. If out-of-scope references are needed, controller safety checks stop; do not implicitly expand scope.

In external output `preparation.json`, save all input paths/content hashes in `inputs`, mandatory AI-read rule sections and per-file chunks of at most 6,000 characters in `documents`, sorted/deduplicated generated artifact paths without bodies in `generatedViews`, contract candidates, fixed Python/tool paths, and one controller argv/session containing all StackNames. Review `documents` chunks per file without omissions; do not reread files whose specified ranges have already been reviewed with the same hashes. This supports document review and does not replace model-generated design consistency validation. Retain generated Markdown/JSON and binary ZIP hashes/reservations in `inputs`, without creating `documents` entries or body chunk files. `generatedViews` is explanatory metadata, not proof of validation/PASS or grounds for omitting input guards. Validate ordinary service generated artifact equality at existing sync-model/local loop execution points; do not treat preparation/controllers as validating everything before deploy.

Once all mandatory documents/candidates match this human request, run the following. Do not add human review gates.

```console
<fixed-python> framework/scripts/deploy_preparation.py --register <external-preparation.json>
```

At registration, recheck input hashes, runtime, latest issues, and conflicts; use existing `task_contract.py --task-file ... --source ...` once with the same Python. Stop without registration for candidate changes, input changes, or conflicts. Review only changes/necessary inputs and recreate preparation; on existing task/session resume, use existing resume procedures without new preparation/contracts. Reprepare unregistered candidates needing new body output formats. Retain guards for all `inputs` even for legacy formats without `generatedViews`. Do not newly reregister already registered tasks. Generated contracts/output alone are not deploy completion.

`timing.jsonl` separately records environment checks, contract preparation, document I/O, elapsed time from document snapshot creation to registration, and registration. Post-snapshot elapsed time includes Agent review/tool waits. Target ordinary preparation within 60 seconds; if `within60Seconds=false`, report measured slow phases. Exceeding 60 seconds alone must not cause termination, PASS, or omitted checks. Measure authentication/communication as separate controller phases. Distinguish fixture measurements without AWS changes from actual deploy durations.

## Create active task contract

As the first repository change, newly register `tasks/<task-name>.md` authorizing only this task's targets. CloudFormation creates this contract with `--register` above; do not manually register it twice.

- Task type is `infrastructure`.
- Infrastructure phase is `deploy`.
- State target environment, alias when present, AWS account, deployment scope, and selected IaC engine in the goal.
- Set AWS API execution and deploy/apply to `allowed` only within this deployment scope.
- Record confirmed User input Authorized delete/replacement, or `none` if no input. If the human approves after change set/plan creation, update to target resources, actions, and confirmed reasons within the same task.
- In `Required changes`, state deployment and observed value updates after success only when necessary, with unique Requirement IDs.
- Map `Acceptance checks` using `exists:` for deployment units and `changed:` for target detailed designs/models only if observed value updates are needed. Do not treat unexecuted/failed deploy as complete based on repository files.
- Limit Allowed paths to observed synchronization target models/generated artifacts, this task's contract, and controlled repair files below. For CloudFormation, reserve exact deployment scope templates/parameters/declared artifacts and record `Controlled repair: allowed` and external `Deploy repair session`. Reservations are exclusively for controlled repair, not arbitrary IaC changes. Changes to Terraform IaC and `tests/**` are prohibited.

## Preflight

Initially confirm target IaC is clean. On resume, permit only specific AUTO_REPAIRABLE file bytes/digests recorded in the same session as uncommitted changes; stop for anything else. Do not overwrite/roll back unrelated worktree changes.

`cloudformation-deploy.py` is responsible for CloudFormation final preflight. Controllers confirm project targets, profiles, accounts, regions, engines, active task scope, issue gates, and immutable inputs. Do not separately run the same STS/context check from prompts. Match explicit account/region to the same project target and pass explicit profiles to controller `--profile`. Stop for mismatches.

For Terraform, do not decide credentials, deploy accounts, AWS regions, IaC engines, or necessary commands by LLM inference; run the following from repository root. `--profile` may be omitted without additional input. The script automatically uses target `awsProfile`.

Run the following for aliased targets.

```text
python framework/scripts/check-deploy-context.py --environment <environment> --alias <alias> [--profile <profile>]
```

Run the following for targets without aliases.

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

Continue only if the script returns exit code 0, using output region, profile (when configured), and IaC engine. Pass the same `--profile` to direct AWS CLI and explicitly specify the same profile for SDK. Pass the same `AWS_PROFILE` per process to Terraform providers/AWS backends according to `terraform.md`. On failure, stop without guessing, switching credentials, changing accounts, or bypassing checks. Do not display/save secrets or credential values.

After preflight success, check target stacks or Terraform state and existing resources read-only. For CloudFormation cross-stack references, inspect producer Outputs with `describe-stacks` and deployed exports in the same account/region with `list-exports`, matching export names, values, and `ExportingStackId`. Stop for engine switching, unknown state/backends, or mismatches between target IaC and approved design.

For CloudFormation, controllers run `describe-stacks` for known scoped StackNames and match templates, parameters, owned resources, and terminal statuses with `get-template` / `list-stack-resources` only for necessary targets. Do not discover all stacks with `list-stacks` in ordinary deploy. Retain existing rules when existing external import owners need confirmation. Distinguish designed but uncreated, designed and existing, undesigned, and same-named but mismatched stacks. Do not automatically adopt/change/delete undesigned/mismatched stacks; stop on scope conflicts. Do not save StackId/ARN or status snapshots in the repository.

## Resolve deployment units

For CloudFormation, existing `load_units()` confirms authoritative stack properties/generated Markdown equality; AI resolves Template, stack-specific Parameters, DeployOrder, and MaxConcurrentStacks from authoritative properties with StackName as deployment identity. Retain all StackNames sharing a template as individual units. Confirm resource ownership, parameters, and existing stack mappings from existing designs/IaC; stop if ambiguous. Do not automatically expand Deployment scope. Controllers enforce order/concurrency; LLMs must not recalculate dependency order.

Read optional TemplateBucket/TemplateKeyPrefix and artifact mappings in the same stack model according to S3 deployment artifacts in `cloudformation.md`. Resolve destinations from confirmed BucketName in the same target's S3 model. Sources are prebuilt local files; do not change builds, mappings, or original IaC during deploy. Declared artifact placement within this scope is included in AWS execution authorization. Stop if required buckets are uncreated; do not automatically create buckets or expand scope.

For Terraform, identify target roots, workspaces, backends, and variable inputs from existing IaC. Stop for missing/mismatched inputs.

CloudFormation uses check-deploy-context once within controller startup and rechecks AWS context on resume. Do not omit task/issue/input guards immediately before mutation.

## Validate and deploy

For CloudFormation:

1. Controllers perform final preflight with `check-deploy-context.py` helpers and per-StackName AWS existence/parameter/resource ownership matching. Explicitly state scope, target, and authorization in the active task in the following format.

```md
- Deployment scope: `stack-a`, `stack-b`
- AWS API execution: `allowed`
- Deploy/apply: `allowed`
- Target environment: `<environment>`
- Target AWS account: `<account>`
```

If an alias exists, also add a Target alias row with its value in backticks.

2. Launch controllers from the same Python environment as cfn-lint. First confirm whole-scope input reads and resource/identifier mappings. Collectively report mapping mismatches for all stacks/resources and stop before cfn-lint/change set creation. Only for unique mappings, confirm whole-scope cfn-lint and source/input hashes, then in each unit's turn confirm actual ImportValue Exports, place declared S3 artifacts, validate execution templates, run validate-template, create individual change sets, classify add/change/delete/replacement, reconfirm the same change sets, execute, and confirm terminal states. Send templates at most 51,200 bytes directly; above that through 1 MiB, place in specified buckets and pass the same S3 URL to validate-template/change sets. Do not create change sets for size limit excess, missing necessary settings, or upload failure. Do not execute these CLIs through other prompt methods for duplicate management.

```console
<fixed-python> framework/scripts/deploy_preparation.py --run-controller <external-preparation.json>
# 全StackName、固定Python、同task専用sessionとtiming-logを一回のcontroller起動へ渡す
```

Launch prepared argv only once; do not duplicate separate STS/context, mappings, or lint. On resume, add existing `--resume` and, only when approved, `--approve-change-set` to the same controller argv/session in `preparation.json`; retain the same task selector/runtime.

3. Controllers normally execute all DeployOrders in one launch. Sequential execution uses `--sequential` to limit execution to 1 without changing designed MaxConcurrentStacks. Pass all targets by repeating `--stack`; do not split per stack into separate controllers/sessions merely for sequential specification/failure collection. Normally run up to MaxConcurrentStacks only within the same group, starting the next stack in freed slots. Do not create consumer change sets before producer success. After stop conditions, do not launch other stacks from outer loops; report unstarted stacks including dependent consumers as NOT_STARTED. Collect all mapping diagnostics in preexecution checks. Missing required Exports in list-exports or unsuccessful in-scope producers are BLOCKED; report contradictions between designed order and Import/Export relationships. Do not automatically add out-of-scope producers.
4. On unapproved delete/replacement, controllers become BLOCKED, retain the same change set ID/change fingerprints in external sessions, and confirm other RUNNING stacks through terminal states. Explain impacts and seek human confirmation under `Confirm unapproved delete/replacement` next. Pass `--approve-change-set` only if the human approves the entire change set. Also match preapproval against all actual destructive changes before resuming the same way.
5. After approval, add `--resume --approve-change-set <保存されたchange-set-id>` to the same task/session. Controllers retrieve/match the same ID, CREATE_COMPLETE/AVAILABLE, and change fingerprints before execution. Do not execute changed/expired change sets with previous approval. Do not rerun successful stacks.
6. After each group succeeds, controller `cloudformation_observed.py` matches execution template LogicalIds, formal CFn types, catalog IDENTIFIER_OUTPUT, Outputs, and PhysicalResourceId and updates necessary non-ARN identifiers/observed rows of all references. Proceed to the next DeployOrder within the same process only after existing service-scoped sync-model generation/validation succeeds. Synchronize the final group too before COMPLETE; ordinary success requires no additional resume. Stop for ambiguous mappings with `AMBIGUOUS_OBSERVED_MAPPING`; LLMs must not supplement them. On failure/blockers, stop new launches and synchronize successful observed values; proceed to subsequent groups only after AUTO_REPAIRABLE repair/revalidation succeeds.

7. Session v2 retains inputDigest, validationDigest, validationStatus, validated input digests, and measurements. Do not rerun whole-scope cfn-lint if the same inputs/framework previously passed. Confirm actual AWS context, Exports, change sets, and immutable artifacts before execute every time. For v1 sessions, match old input hashes and revalidate/synchronize observed values on first resume, migrating to v2. Sessions retain target/design/scope, per-stack template/parameter/source digests, placement bucket/key/version/checksum, and execution template hashes. Save execution copies without original IaC changes in `.files` directories beside external sessions. Recheck placed objects/copies on resume and before execution; do not execute changed artifacts with previous approval. Deploy phase permits no IaC changes; update phase accepts only IaC changes within approved design for unstarted NOT_STARTED stacks after revalidation. Reject resume for prepared/executed stack IaC changes or target/design/scope changes. Do not save status/StackId/ARN/history in models/Git. Sessions continue the same task; do not automatically rollback/delete/redeploy successful stacks. On RUNNING retrieval errors, stop new launches and continue terminal checks. After controller interruption, resume only the same session; do not concurrently execute different sessions. Target locks reject duplicate controllers. If abnormal exit leaves a lock, confirm no running controller before removing only the lock and resuming the same session.

For Terraform:

1. Run `terraform fmt -check`, `terraform validate`, and `terraform plan -out=<repository外の一時path>`.
2. Confirm plan add, change, destroy, replacement, and sensitive output.
3. For unapproved destroy/replacement, follow `Confirm unapproved delete/replacement` below and wait for human confirmation without applying saved plans.
4. Run `terraform apply` only for the same plan binary preapproved or approved by the human after plan creation.
5. After success, obtain necessary non-sensitive identifiers from Terraform output; read state resource attributes read-only only when target outputs are absent. Confirm equality if both exist and update formal identifier output rows and all references.

## Confirm unapproved delete/replacement

If only unapproved delete/replacement is detected, do not treat it as deployment failure/task completion; wait for human confirmation in the same task. Do not uniformly hold all deployment for confirmation.

In the following order, display explanations humans can decide from, not just technical summaries.

1. Detected changes: Show stack names or Terraform roots/workspaces and add, change, delete/destroy, and replacement counts.
2. Direct stop reason: Show which delete/replacement does not match preapproval.
3. Target resources: For CloudFormation, show logical IDs, physical IDs, resource types, Remove/Replace, `Replacement`, `PolicyAction`, `DeletionPolicy` / `UpdateReplacePolicy`, and known change reasons. For Terraform, show resource addresses, resource types, destroy/replacement actions, and known change reasons without sensitive values.
4. Execution impacts: Explain known impacts on physical resources, stored data, settings, access, and availability plainly. Do not guess; explicitly mark unconfirmed impacts as `未確認`.
5. Current execution state: Explicitly state that target change sets/saved plans are unexecuted; distinguish other successful, failed, or unexecuted units in the same task, accurately stating whether AWS resources changed.
6. Available responses: Present options to approve all targets and continue the same deployment, perform additional read-only confirmation needed for decisions, decline and stop execution, or change IaC in a separate task for resource retention/releasing management. Do not imply that only part of the current change set/plan can be executed.
7. Human confirmation question: In one question, ask whether to approve all listed delete/replacement in the same change set/saved plan for the stated reasons.

If the human requests more information, execute only list/get/describe-equivalent read-only operations within the same task's deployment scope to supplement explanations, then present the same question again. Do not delete data, change resources, or repair IaC.

If the human approves all targets/reasons, update Authorized delete/replacement in `tasks/<task-name>.md` to approved resources, actions, and reasons, confirm the following, and resume the same task.

- For CloudFormation, retrieve the same change set ID again and execute only if status is `CREATE_COMPLETE`, execution status is `AVAILABLE`, and approved logical IDs, actions, replacements, and `PolicyAction` match.
- For Terraform, reconfirm the same saved plan and apply that plan binary only if approved resource addresses, resource types, and actions match.
- If change sets/plans expired, were recreated, or changed, do not use previous approval; explain new contents and reconfirm.

If the human does not approve or approves only a subset, stop without executing change sets/plans. Even if resource retention, removal from CloudFormation management, or configuration changes are needed, do not change IaC/intended design in this deploy phase.

CloudFormation failures proceed to controller Controlled deploy repair classification; AUTO_REPAIRABLE automatically continues remaining units after repair, validation, new change sets, and retries. Consult Human only for HUMAN_REQUIRED such as scope excess, account/region mismatch, unknown delete/replacement actions, unconfirmed designs, or missing external permissions. Terraform validation/plan/apply failures continue to stop as before. Only unapproved delete/replacement waits for human confirmation above rather than ending as failure. Do not change intended design or perform IaC changes without repair history or retries with unconfirmed causes. On CloudFormation stop conditions, do not start new units; confirm running stack terminal states and distinguish successful, failed, and unexecuted units. Do not automatically rollback/delete/redeploy successful stacks. Terraform apply failure may mean partial apply; check state and actual AWS resources read-only and stop.

CloudFormation observed collection/generation completes inside controllers. Manual collection below applies to Terraform.

If deploy/apply succeeds:

1. Confirm terminal success and resource existence.
2. Under `framework/rules/observed-values.md`, uniquely map retrieved values to formal catalog `IDENTIFIER_OUTPUT` properties. First update only model properties identifier output rows and observed values of all properties referencing the same anchor to the same physical ID; do not change link target paths, anchors, `Source / Comment`, or other intended design.
3. Run `framework/scripts/sync-model.py --write --environment <environment> --alias <alias>` for aliased targets, or `framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>` for targets without aliases.

Stop without guessing/IaC repair if required outputs are absent from IaC, catalog property mappings are nonunique, or reference source/target values differ. Update to new IDs after replacement; after destroy, return identifier output rows and all references to `PENDING_DEPLOY`. Do not save generated ARNs.

Do not treat deploy completion status, resource existence, or observed value collection as application behavior validation or scenario PASS.

## Verify and finish

1. Confirm target IaC diffs match authorized repair history in the same session and no out-of-scope changes exist.
2. Run `python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md` once. It includes task scope, Acceptance checks, and Git diff checks. Retain existing framework regression conditions (full/--all/framework changes); do not mix framework development and deploy tasks.

State targets, accounts, regions, engines, preflight results, deployment units/dependency order, plan/change set summaries, human confirmation waits/approval results, deploy completion status, observed value updates, and blockers in completion reports. Do not save verification output in the repository.

Do not change, create, or execute IaC outside controlled repair, intended design, scenarios, scenario results, other targets, or next tasks. For application behavior validation, the human uses `framework/prompts/codex/06_scenario-test.md` as a separate task.

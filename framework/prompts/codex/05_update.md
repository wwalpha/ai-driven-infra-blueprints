# Manual Design Update and Deployment Prompt

## Common update authority

Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.

[Service Model sources](../../rules/model-templates.md) define environment-specific
properties as authority. Read with `model.sources.load_model`; use
`model/cli.py trace <service.properties> <key>` to locate exact source bytes.
Design edits change desired/display/reference keys; authorized observation saves
change only selected `observed.row.<id>.value` keys in the same Model. Record the
entry, actual parts, required incoming consumers and generated paths in the Task.
Read dependencies grant no write paths. Read with the shared Model loader before
matching IaC/issues/diff. Generation across environments grants no Deployment scope
or AWS permission.

Follow [Task transition](../../rules/task-contract.md#task-transition), [Task boundary](../../rules/task-contract.md#task-boundary), [Acceptance contract](../../rules/task-contract.md#acceptance-contract), and [Retry and stop](../../rules/task-contract.md#retry-and-stop) for Task selection, registration, authority, acceptance, stopping and resuming.

Model-only branches require an explicit request and forbid AWS API execution and deploy/apply. Infrastructure update requires explicit authority to reflect the requested Model change into IaC and AWS; an ambiguous request or an Issue does not grant it. Read only the selected branch and its required references.

Model 更新時は **Change Validation のみ**実行する。Full Validation は Issue Scan や独立した明示的全量検証で使用し、更新の停止判定へ混入させない。変更した Resource / Property / Link と、それらが使用・破壊する参照契約を検証し、無関係な既存エラーを更新の停止理由にしない。読み取り依存先、検証対象、生成対象、Task の書き込み権限を区別する。

## Ordinary Model correction

For an explicit Human request to correct Model settings only, use a design/update Task
with forbidden AWS API execution and deploy/apply. IMPORT and CREATE Resources are both
eligible, including settings previously approved or imported in another Task. Enumerate
exact Modified files, Allowed paths, service Validation scope and affected consumers.
Do not acquire AWS values in this branch. Keep the infrastructure branch separate.

For complete external candidates use `model.sources.edit_base(path, context.snapshot)`
and `candidate_sources`, then the existing `edit_write_context`, `prepare_edit(path,
candidate, context)` and `publish_edit`. The old baseline records bytes and file sets,
without `load_model` or fixed-field/layout validation. The candidate must pass structure,
ID and reference checks. Never manually persist generated views; generate and validate
through the existing APIs. Complete and integrate only the verified final candidate.
Dedicated merge/delete/retarget operations below retain their limited declarations and
raw-value preservation checks; none requires the whole old Model to pass `load_model`.

## Dependency analysis and value-preserving refactoring

Load the producer snapshot through `model.sources.load_model`, then inspect
`model.references.incoming(snapshot, fixed_id, read_context)` and
`model.references.usages(consumer_snapshot, read_context)`. The CLI uses the same
read-only reference analysis:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py incoming model/<environment>/<target>/<service>.properties <fixed-ID>
```

Read usages, `model.references.diagnose` warnings, raw sources, fixed producer/consumer
IDs, consumerKey/pointer/occurrence, format/property/label policy and source positions.
Retain a before snapshot for removed resources and their anchors. Semantic warnings
never become an empty successful dependency result; structural/I/O/scope errors stop.

Follow [Reference diagnostics](../../rules/model-information.md#reference-diagnostics).
Incoming analysis and intermediate deletion leaves retain warnings. The parent final candidate
must resolve surviving Resource references and pass its scoped candidate guard before integration.
Do not impose deletion ordering, a separate detach Task or reference repair as a prerequisite.
Do not delete another resource or change surviving resources without authority.

For an independently requested dependency refactor, reuse the existing
[Value-preserving Model refactor](../../rules/task-contract.md#value-preserving-model-refactor)
contract, input editing and guarded publication. Preserve explicit environment-specific properties;
retain fixed identities and non-reference settings/types/JSON siblings/observations. Report
reference-derived differences as warnings. The LLM chooses repairs within scope or asks
about undetermined changes; Python does not invent them. This branch grants no AWS/IaC
permission and does not enter infrastructure execution below. For repairs associated
with registered deletions, use the same model-delete parent and intermediate writer
under the next Model-only branch, not an independently finalized refactor.

## Standalone Model reference retarget

Use this independent branch only for an explicit Human reference-only request under
[Standalone Model reference retarget](../../rules/task-contract.md#standalone-model-reference-retarget).
Read that section, Task transition/boundary/Acceptance, Model sources and
IMPORT authority before execution. Include every producer and consumer in Validation scope;
register a running design/update `import-retarget` parent with forbidden AWS/deploy,
exact reference records, source/view paths and service Validation scope. Inspect
`model.references` and raw authoritative sources; never infer identities from names
or physical/display equality. Call only [model-retarget](../../../.agents/skills/model-retarget/SKILL.md)
with the exact records. Batch all declared source changes in one guarded save, then
use existing generation APIs and worktree finalize on the running parent for latest-base
candidate verification/completion/ff-only integration. Do not invoke transfer/delete,
edit generated views, relax other operations, or enter infrastructure execution below.
Preserve both producers, settings, fixed identities, observations, all undeclared
references/consumers/environments, types/order and reference format/output/label policy.
Reference ambiguity, target mismatch and unused semantic declarations are warnings.
Malformed/overlapping operation positions, unauthorized non-reference changes and input
conflicts remain errors; retain the candidate on actual failure. No IT requirement is added.

## Model-only IMPORT merge or deletion

Use this branch for an explicit human Model-only request. Register one running design
Task with Workflow update, Model operation import-merge/model-delete, forbidden AWS
and deploy/apply. Apply the common Task sections already read; read
[Model sources](../../rules/model-templates.md)
and [IMPORT authority](../../rules/model-information.md#import-configuration-authority).
The [Model-only contract](../../rules/task-contract.md#model-only-import-operation-contract)
defines exact pair/reference syntax and compatibility. Do not infer IDs or require pre-edits.

The selected managed worktree is the transaction boundary. Keep the same parent Task
selector through every operation; include all planned source/view paths and required
direct consumers in its scope. The parent owns sequencing and
stopping; the following leaves own their exact editing procedures:

1. For an overall merge request, call [model-transfer](../../../.agents/skills/model-transfer/SKILL.md)
   with the registered pairs, then [model-retarget](../../../.agents/skills/model-retarget/SKILL.md)
   with registered references, then [model-delete](../../../.agents/skills/model-delete/SKILL.md)
   with the normalized sources one Resource at a time. For deletion, register every
   source and related reference/detach repair in one parent. The parent LLM chooses the
   next Resource, calls model-delete for its investigation/registered repairs/removal/raw
   save, and reads the result before deciding the next action. An explicitly
   requested single leaf returns after that operation. No per-step reapproval for an
   already requested overall integration.
2. Each successful leaf may save raw sources in the worktree, leaving an unfinished
   intermediate Model. Stop on failure and retain prior successful saves; the parent
   may use the existing suspend transition. Never auto-rollback the whole workflow.
3. Only after all leaves complete, use existing prepare_generation/validate_generation/publish_generation to prepare,
   validate and save the required views. Generation does not decide merge completeness.
4. Use worktree finalize: prepare the private commit and rebase onto latest local base,
   run one read-only final local loop on that actual candidate, consume its successful
   result for completion and ff-only merge, then let the surviving launcher cleanup.
   Incomplete deletions reject finalize before commit preparation. Final differences
   must prove complete transfer/removal across every source service, declared retargets,
   stable identities and preserved non-reference consumers. Remaining source links and
   reference-derived differences are reported as warnings.

Standalone validation/complete retain their own final checking responsibility. Ordinary
non-managed completed-candidate publication retains its previous IMPORT guard. A failed
final check retains the private commit/worktree without merge, automatic regeneration,
amend or loop retry by default. For model-delete, explicitly resume/repair in the same
parent and call finalization again after the correction; retain the earlier candidate
commit and revalidate the new candidate. Never merge a failed candidate. This repair
retry is distinct from forbidden per-Resource final validation. Report leaf saves and
final validation/integration separately.

"One Resource at a time" means sequential investigation, repair, deletion and raw save.
It never means independent Tasks/Worktrees/Commits/Merges. One parent owns permissions,
source set, scope, leaf results, final generation, validation, merge and cleanup.
Python supplies atomic APIs and rejects incomplete/invalid candidates; it never loops
over sources to perform edits or chooses repair methods. No new execution engine exists.
Do not enter the infrastructure branch below. /import separately permits acquired add/refresh/replace after its own Human selection; it does not authorize these Model-only operations.

## Check applicability and finish point first

This infrastructure branch receives uncommitted diffs manually edited by the Human in existing authoritative service Model inputs as confirmed design, then generates Markdown, reflects them into selected IaC, deploys/applies and confirms completion in one `infrastructure` Task. Do not use it to create new detailed designs.

First determine the requested environment/target/services and properties. Model/view
corrections use a design/update contract with exact source/view paths, service Validation
scope and forbidden AWS API execution/deploy/apply. Run scoped generation and classified
validation, then finish. Reflecting approved design into IaC or AWS requires the separately
requested implement or infrastructure update scope. Do not infer that scope from an Issue.
For Model/IaC differences, present both values and their impact; obtain the Human's
correction direction before changing either authority. Do not create another Task automatically.

Follow [Credentials and account](../../rules/project-configuration.md#credentials-and-account) for common account/profile selection and apply [Policy account selection](../../rules/detailed-design.md#policy-account-selection) for policy-specific conditions.

## Optional user input

- Authorized delete/replacement: `none` when omitted
- AWS profile: Optional. When omitted, target `awsProfile`, or default credential chain if unset. Reject explicit profiles differing from settings

Normally neither input is required. Treat delete/replacement as preapproved only when target resources and reasons are explicit. Create change sets/plans even without preapproval; proceed to waiting for human confirmation below only if unapproved delete/replacement is detected.

## Resolve target and scope from repository state

Before file changes, determine targets and scope in the following order.

1. Check `git status --short` and `git diff --name-only HEAD -- model/`.
2. Obtain environment, target and service from changed real format-2 entrances/parts, using `model.sources.source_scope` and common discovery. Use `model.impact.affected` to identify required incoming consumers. Alias wins over account ID; execution account IDs never identify paths. Do not create Models merely because targets are registered.
3. Confirm exactly 1 environment/target directory combination matching a `project.json` target; obtain the alias if present and always the actual AWS account ID. Stop without file changes if no human-edited authoritative design inputs exist, the requested deployment target is ambiguous, or targets are unregistered. For common edits, generate/validate every consumer in a separate design task, then explicitly hand off exactly one deployment target; never infer permission for other consumers.
4. Design scope is all existing model properties edited by the human in the same target. Use model row documents as input for policy/setting JSON bodies; do not adopt manual Markdown/JSON artifact diffs as design values.
5. Match corresponding authoritative service properties against existing IaC/parameters; implement only differing properties. Resolve CloudFormation stack scope only from authoritative `cloudformation-stacks.properties` in the same target. Use `desired.stack.*.name`, `.template`, `.parameters`, `.deployOrder`, and `desired.deployment.maxConcurrentStacks`; effective MaxConcurrentStacks is 1 when omitted. Confirm resource ownership and each shared-template stack instance/parameter mapping from service properties and existing IaC; stop if ambiguous. If changed design references resources owned by other stacks in the same account/region, also consider those producer stacks for necessary Output/Export additions.
6. Deployment scope is the above StackNames, templates/parameters, or Terraform roots/resources and dependencies. For CloudFormation, stop without guessing/migration if DeployOrder is unset; the controller enforces order and parallel limits. Do not convert DeployOrder to template DependsOn. For Terraform, resolve roots, workspaces, backends, variable inputs, modules/resources, and dependencies from existing IaC; stop for missing/mismatched inputs. Different StackNames using the same template are separate units; include only stacks owning changed design resources in scope. If handling producers and consumers requiring cross-stack exports in the same task, include both stacks in scope.

Stop without incorporating out-of-scope uncommitted changes. Only if repository information cannot uniquely identify deployment units, ask one missing item such as stack name per response. Do not require the user to reenter targets, paths, or entire scope identifiable from the repository; do not infer values.
Do not automatically interpret existing StackName deletions/renames in stack design diffs as stack deletion. If ending management/deleting target stacks is necessary, report targets/impacts and stop without execution in the current update phase.

## Read before changing files

1. `AGENTS.md`
2. Apply the [common Task sections](../../rules/task-contract.md#task-transition) already read. Add applicable infrastructure-specific Task contracts and recovery rules only when needed.
3. `tasks/<task-name>.md` if present. Otherwise treat as idle and create it first under Create active task contract.
4. `project.json`
5. `git status --short` and Design scope diffs identified from repository changes
6. Authoritative Design scope properties entrances and actual registered parts, read through the shared snapshot. For CloudFormation, same-target `cloudformation-stacks.properties` needed for stack scope resolution
7. [Policy account selection](../../rules/detailed-design.md#policy-account-selection). For CloudFormation, add [CloudFormation stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design); add related display sections only when changing/investigating design display.
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. [cloudformation](../../rules/cloudformation.md) or [terraform](../../rules/terraform.md) for the selected engine
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope). [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. `framework/materials/aws/*.properties`, `framework/materials/api/*.properties`, and same-named API design schemas relevant to target resources
13. For CloudFormation, target resource provider schemas
- [project-configuration](../../rules/project-configuration.md). For naming checks, [aws-resource-naming](../../rules/aws-resource-naming.md).

For naming rules, additionally read only service files corresponding to target resource type catalog namespaces from the common entry's Service rule lookup. Even for multiple services, read only target namespaces, not the whole naming rule directory at once. Match Catalog resource types/Naming target and patterns in selected service files.

Update design inputs are only authoritative model properties. Do not read generated Markdown bodies or generated JSON artifacts as input at start, IaC generation, or reference resolution. `cloudformation-stacks.md` is also a display generated artifact; the Agent must not retrieve/compare the same stack scope information twice. Use `desired.row.*.document` for JSON bodies. Full 03/04 prompt reads are unnecessary; follow this prompt for Update procedures and existing rules above for common contracts. Retain Markdown/JSON generation/saving and consistency validation by controllers/local loops.

For limited resources, use existing partial reading for both single files and split entry indexes. Selectors require exact resource number or logicalId matches; stop if unmatched/ambiguous.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py resource model/<environment>/<target-directory>/<service-id>.properties <resource-selector>
```

Load only target resources, parents/children/siblings in the same group, and service metadata/notes into context. Service-wide changes may read entire target service properties, without unconditional expansion to all services/models. Resolve saved Markdown Resource links and parentReference with the common resolver; retrieve only selected groups. No generated Markdown fallback. Unknown targets remain reference warnings for ordinary Model saves; missing configuration or deployment decisions still stop dependent infrastructure actions.

Limit reads to Design scope resources/properties and portions needed for reference resolution. For split models, read only required parts from entry indexes. Do not reread material already confirmed in the same task unless content changes, validation fails, or unresolved dependencies exist.

`<target-directory>` is the selected target's alias if present, otherwise AWS account ID.

Follow AGENTS.md “How to read required rules” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.

## Validate human design diff

- Identified Design scope is only existing model properties edited by the human under the target environment/target directory.
- Stop if Design scope model properties contain no human-created uncommitted diff.
- Stop without incorporating uncommitted changes outside identified Design scope into this task.
- Stop if IaC or generated Markdown/JSON artifacts have uncommitted changes predating task start. Human diffs in authoritative model properties are permitted.
- Do not repair, supplement, or roll back human-edited intended design in this task.
- Stop for detailed design deficiencies, contradictions, placeholders, schema violations, or unconfirmed human decisions.
- Apply schema validation such as existing `model.validations.schema.validate_required_properties` and `DesignSchemaCatalog.literal_errors` to target properties to confirm CREATE/IMPORT, formal types, required properties, types/constraints, and necessary dependencies. Do not automatically supplement scope or intended design.
- For CloudFormation, resolve target types with `design_catalog.py --cloudformation-type <catalog-resource-type>`. Do not silently exclude CFn-unsupported types such as `Macie.ClassificationJob` and `QuickSight.Group` and call update complete; report unapplied items and stop. Do not incorrectly convert to CFn, run APIs, add Custom Resources, or mutate API-only resources. Retain engine rule resourceMode boundaries.

Retain Design scope diffs at task start and confirm they remain identical through completion except for generated current value updates after deploy success.

## Create active task contract

As Codex's first repository change, newly register `tasks/<task-name>.md` authorizing only this task's targets.

- Task type is `infrastructure`.
- Infrastructure phase is `update`.
- State target environment, alias when present, AWS account, automatically identified Design scope and Deployment scope, and selected IaC engine in the goal.
- Explicitly state Design scope and implementation/deployment-related services in `Validation scope` as `<environment>/<target-directory>/<service-id>`. Do not expand to the entire target.
- Set AWS API execution and deploy/apply to `allowed` only within automatically identified Deployment scope.
- Record explicit Authorized delete/replacement values, or `none` if no input. If the human approves after change set/plan creation, update to target resources, actions, and confirmed reasons within the same task.
- In `Required changes`, separately state human design diff validation, Markdown generation, IaC implementation, deployment, and necessary observed value updates with unique Requirement IDs.
- Map `Acceptance checks` using `changed:` for Design scope, corresponding models, and target IaC, and `exists:` for deployment units. Do not treat unexecuted/failed deploy as complete based on repository files.
- Limit Allowed paths to Design scope model properties, destination Markdown/JSON artifacts, target IaC, and `tasks/<task-name>.md` only. Changes to other targets and `tests/**` are prohibited.

## Generate Markdown and implement IaC

1. Run `framework/scripts/sync-model.py --write --environment <environment> --alias <alias> --service <service-id>` for aliased targets, or `framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id> --service <service-id>` for targets without aliases, to generate Markdown/JSON artifacts from human design diffs. Specify multiple target services in the same target once by repeating `--service`; do not change model intended design.
2. Stop without repairing design on Markdown/JSON generation or validation failure.
3. From properties above and existing engine rules, minimally change only IaC needed for automatically identified Deployment scope. Reflect tags, Names, policy documents, and logical references from desired rows; do not hardcode physical IDs. For CloudFormation cross-stack references, defer producer Output/Export and consumer `!ImportValue` changes until deployed exports are investigated with the read-only check below.
4. For CloudFormation, retain independent Model/provider-schema/mapping checks and shared template decoding. For Terraform, run `terraform fmt -check`, `terraform init -backend=false` with fresh `TF_DATA_DIR`, and `terraform validate`. Repair IaC implementation errors for at most 3 iterations only if correctable within confirmed design. Stop if the same error repeats twice without material progress or human decisions/design changes are needed. Do not proceed to deploy with validation failures remaining.

## Preflight and deploy

Only target IaC uncommitted diffs generated from Design scope in this task are permitted for deploy. IaC diffs predating task start or diffs outside Deployment scope are not permitted. Stop for engine switching, unknown state/backends, design mismatches, or required input missing.

### CloudFormation read-only dependency check

Only for cross-stack references requiring live AWS state to decide IaC changes, existing `check-deploy-context.py` with `--read-only` may confirm identity/account/region/profile before necessary `describe-stacks` / `list-exports`. Add `--read-only` to the same target selector as Terraform examples below. This exception is read-only confirmation for implementation decisions; do not run it in ordinary CloudFormation update. It neither authorizes mutation nor replaces controller final preflight. Stop on mismatch/authentication failure; do not fall back to another profile.

Match actual Export names, values, and ExportingStackId in the same account/region against producer Outputs. If exports exist, change consumer template references and corresponding string portions to `!ImportValue` and proceed from static validation to controller. If no exports exist, add only necessary Output/Export to producer templates and first perform static validation, controller producer deploy, terminal success, and actual Export confirmation. Only afterward change NOT_STARTED consumer templates to `!ImportValue` and explicitly start an independent controller run from current inputs after GROUP_COMPLETE with `--pause-after-group`. If both stacks are not in Deployment scope, stop without expanding scope by guessing.

### CloudFormation controller

`cloudformation-deploy.py` is responsible for final preflight. The controller uses `deploy/context.py` SDK checks to confirm AWS identity, project targets, profiles, accounts, regions, engines, and necessary commands, enforcing task scope and immutable inputs. The Agent must not first run the same final deploy-context check standalone. Match explicit account/region against the same project target and pass explicit profiles to controller `--profile`. Stop for mismatches or missing credentials/permissions. Launch the controller from the registered Python environment.

```console
python framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] [--profile <profile>]
# aliasなしでは --alias の代わりに --aws-account-id <aws-account-id>
```

Normally one controller launch completes all DeployOrders. The controller owns input hashes, per-StackName existence/parameters/resource ownership, actual Export confirmation for ImportValue, validate-template, change set creation/classification/reconfirmation/execution, and terminal confirmation. Do not distribute change set creation/execution outside the controller. Retain existing `cloudformation.md` contracts for declared S3 artifact placement, template-size-based delivery, group barriers, MaxConcurrentStacks queues, current-run input/Task/target checks, immutable guards, failure stops, and draining RUNNING stacks. Do not create consumer change sets before producer success or adopt/change/delete stacks outside design.

On ordinary success, complete observed updates and service-scoped sync-model inside the controller before proceeding to the next group; synchronize the final group too before COMPLETE. Use `--pause-after-group` only for explicit producer/consumer IaC changes. GROUP_COMPLETE is not overall COMPLETE. After synchronization and authorized IaC changes, explicitly start an independent run with current target/Stack arguments. Inputs remain frozen within each run; subsequent runs evaluate previously successful stacks as ordinary UPDATE candidates using latest IaC and actual AWS Outputs/Exports, without inheriting old completion or approval. For scope excess, account/region mismatch, validation failure, or deployment failure, do not start new units; confirm RUNNING stack terminal states and stop. Do not automatically rollback/delete/redeploy successful stacks.

### Terraform preflight and apply

Do not decide credentials, deploy accounts, AWS regions, IaC engines, or necessary commands by LLM inference; run the following from repository root. `--profile` may be omitted without additional input. The script automatically uses target `awsProfile`.

Run the following for aliased targets.

```text
python framework/scripts/check-deploy-context.py --environment <environment> --alias <alias> [--profile <profile>]
```

Run the following for targets without aliases.

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

Continue only if the script returns exit code 0, using the output profile (when configured) for all subsequent AWS execution. Specify profiles explicitly for CLI/SDK; pass the same `AWS_PROFILE` per process for Terraform providers/AWS backends according to `terraform.md`. On failure, stop without switching credentials, changing accounts, or bypassing checks. Do not display/save secrets or credential values.

After preflight success, match state and existing resources in the same root/workspace/backend read-only. Run `terraform fmt -check`, `terraform validate`, and `terraform plan -out=<repository外の一時path>`; confirm scope, add, change, destroy, replacement, and sensitive output. `terraform apply` only the same saved plan binary preapproved or approved by the human below. Stop for plan failure, wrong workspace/account/region, sensitive output, or missing/mismatched inputs. Apply failure may mean partial apply; check state and actual AWS resources read-only and stop. Do not commit state/plan binaries.

## Confirm unapproved delete/replacement

For unapproved delete/replacement only, do not treat as failure/task completion; leave change sets/plans unexecuted and wait for human confirmation. Apply engine rule Delete and replacement confirmation/Validation and execution; only in this case consult `04_deploy.md`'s `Confirm unapproved delete/replacement` section. Explain targets, actions, reasons, known impacts on data/access/availability, unconfirmed matters, and current states of successful/running/unexecuted units; ask whether to approve all destructive changes in the same change set/saved plan. Do not execute with only partial approval. Do not add review uniformly stopping all deployment.

After approval, record target resources, actions, and reasons in the same task's Authorized delete/replacement. For CloudFormation, start an independent invocation with the same current Task/target/Stack arguments and `--approve-change-set <current-change-set-id>`; retain controller checks of the same ID, CREATE_COMPLETE/AVAILABLE, and change fingerprints. For Terraform, reconfirm the same plan's resource addresses/types/actions. Do not reuse prior approval for expired/recreated/changed change sets/plans. Stop if actions are unknown. Without approval, do not execute or mix IaC/design changes for resource retention/releasing management into this confirmation step.

## Post-deployment model sync

### CloudFormation

Observed collection, model updates, and generated artifact synchronization are owned by the controller. `model.adapters.observed` matches actual template LogicalIds, formal types, catalog IDENTIFIER_OUTPUT, and Outputs/PhysicalResourceId; updates necessary non-ARN identifiers and observed rows of all references, then runs service-scoped sync-model generation/validation. Confirm COMPLETE and synchronization results; the Agent must not rerun the same AWS value retrieval or `sync-model.py --write`. Stop for ambiguous mappings with AMBIGUOUS_OBSERVED_MAPPING; the LLM must not supplement them. Synchronization failure is not completion. Resolve the reported blocker, then use the existing `--recover-operations` entry with current Task/target/Stack arguments to settle the original unfinished operation/Observed/publication only; never resend Execute or start a new Deploy through Recovery. Generation must also succeed. Unknown AWS submission remains stopped with its original Token. After settled recovery, review current inputs before a separate independent Deploy. See `cloudformation-deploy.py --help`; no persistent Deploy Session participates.

### Terraform

After apply succeeds, the Agent performs existing post-apply procedures.

1. Confirm terminal success and resource existence; obtain necessary non-sensitive identifiers from Terraform output. Read state resource attributes read-only only when target outputs are absent; confirm equality if both exist.
2. Under `observed-values.md`, uniquely map to formal catalog IDENTIFIER_OUTPUT and first update identifier output rows and observed values of all references. Reflect new IDs after replacement and PENDING_DEPLOY after destroy. Do not change human-edited intended design, link target paths/anchors, or Source / Comment. Stop without guessing for missing necessary outputs, ambiguous mappings, or reference mismatches; do not save generated ARNs/secrets.
3. Run the above service-scoped `sync-model.py --write` only for services with updated observed values.

Do not treat deploy completion status, resource existence, or observed value collection as application behavior validation or scenario PASS.

## Verify and finish

1. Compare against human design diffs at task start and confirm Codex has not changed intended design other than generated current values.
2. Confirm selected IaC syntax/static validation results. Do not rerun if target IaC, parameters, and dependency inputs remain unchanged after success. Retain mandatory deploy-phase validation and AWS safety checks.
3. Run `python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md` once. Retain Validation scope, task-specific checks, Acceptance checks, diff checks, and properties/generated Markdown/JSON equality via read-only `sync-model.py`; mismatches are FAIL. Use existing validation cache/service parallelism; do not omit/weaken validation due to reduced Agent initial reading. Retain existing `loop-engineering.md` framework regression execution conditions; do not add all framework regression to ordinary Update.

Do not add overall validation after successful scoped validation. Rerun generation/validation only for input changes, new failures, or unresolved concerns; track the same execution on tool wait timeout.

State targets, Design scope, display generation, IaC changes, deployment units/dependency order, plan/change set summaries, human confirmation waits/approval results, deploy completion status, observed value updates, and blockers in completion reports. Do not save verification output in the repository.

Do not change, create, or execute scenarios, scenario results, other targets, or next tasks. If application behavior validation is needed, the human uses `framework/prompts/codex/06_scenario-test.md` as a separate task.

Persist observations only as `observed.row.<id>.value` beside the corresponding
desired Row. Absent keys, empty strings and PENDING_DEPLOY remain distinct. Derive
observed Property/comment and artifact hashes at read time. Preserve fixed IDs,
reference meanings and Stack placementName; ordinary observation updates never
rewrite desired/display/reference values or unrelated source bytes.

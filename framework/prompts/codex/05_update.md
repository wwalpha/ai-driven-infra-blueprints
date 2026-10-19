# Manual Design Update and Deployment Prompt
IMPORT acquisition and user-selected add/refresh/replace are exclusive to `/import`; explicit Model-only merge/delete uses `/update` under the narrow operation guard. Follow [IMPORT configuration authority](../../rules/model-information.md#import-configuration-authority). Read/compare remains allowed. Value-preserving source refactors are allowed; CREATE workflow is unchanged. Other substantive IMPORT updates remain forbidden; read/compare and value-preserving refactors never bypass the mechanical guards.


[Service Model sources](../../rules/model-templates.md) define the YAML-only input
contract for this prompt. Read runtime Models through model_files and use
`model_files.py <service.properties> --trace <key>` for the exact source. Design edits
use the common template, parameters.yaml and fixed bindings.json; authorized observed
updates use observed.json. Record template entry/parts, parameters.yaml, bindings.json,
observed.json and generated Markdown/JSON paths in the task contract. Common template
edits require all registered consumers in Validation scope. Read with the shared Model loader before
matching IaC/issues/diff. Generation across environments grants no Deployment scope
or AWS permission.


Follow [task-contract](../../rules/task-contract.md) for contract registration, stopping/resuming.

Use this prompt to receive diffs manually edited by the human in existing authoritative service Model inputs and not yet committed as confirmed design, then perform Markdown generation, reflection into selected IaC, deploy/apply, and completion confirmation in one `infrastructure` task. Do not use it to create new detailed designs.

## Dependency analysis and value-preserving refactoring

Before single deletion use `model_reference_usage.incoming_references(root, address)`
and `outgoing_references(root, address)`. A read-only CLI wraps the same API:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model_reference_usage.py <environment/target/service/fixed-ID> --direction incoming
```

Inspect raw sources and returned fixed producer/consumer IDs, expanded key, formal
Property, JSON pointer, syntax kind/format, effective value and source/provenance.
`role` distinguishes configuration, structure and display; a display link is not an
AWS setting, but surviving links still block deletion. Self usages vanish with the
resource; service-level links without a Resource owner must also be considered.
Unknown/ambiguous/cyclic/unexpandable inputs are failures, never an empty dependency
list. Do not infer Resource IDs, values, dependency meaning or an edit from names.

The LLM decides in this order; Python reports facts and verifies safety:

1. If A refers to B in one direction only, delete the explicitly authorized A first,
   integrate that single-delete Task, then independently delete B. Report any needed
   deletion outside Human authorization instead of executing it. Do not refactor when
   ordering suffices, and never implement multiple deletions in one import-delete Task.
2. For a resource cycle, inspect name/Property-derived dependencies that might be
   detached while preserving every effective setting. `format: name` alone is not
   proof. Preserve structural/AWS-setting/identifier constraints; stop with concrete
   required design changes if preservation cannot be proved.
3. Reuse existing independent parameters and Definitions. If changing a shared
   Definition would alter other consumers, isolate only the intended Instance using
   the existing Definition/binding structure, retaining fixed maps. Do not hardcode an
   environment-specific value into a shared template or alter another environment.
4. When necessary, execute a separate design /update Task under
   [Value-preserving Model refactor](../../rules/task-contract.md#value-preserving-model-refactor).
   Declare exact dependencies, ordinary paths/scope and forbidden AWS/deploy. Edit raw
   inputs as the LLM, publish through the ordinary design guard, generate views, and
   finalize the running worktree Task. Python verifies values, types, structure,
   declared removals and preserved consumers; it never chooses/fixes the edit.
5. Only after successful final validation/integration begin the next explicitly
   authorized single-delete Task against that integrated base. The refactor Task and
   each deletion have independent final validation and integration. Never change a
   surviving Resource while executing its neighbor's deletion Task.

CREATE dependency changes require ordinary design review even if values match; they
cannot succeed as this value-preserving IMPORT detach. A failed guard retains work
and detailed before/after diagnostics. Do not disable it or auto-approve failure.
This branch does not enter infrastructure execution below.


## Model-only IMPORT merge or deletion

Use this branch for an explicit human Model-only request. Register one running design
Task with Workflow update, Model operation import-merge/import-delete, forbidden AWS
and deploy/apply. Read [Task transition, boundary and Acceptance](../../rules/task-contract.md),
[issue gate](../../rules/issue-gate.md), [Model sources](../../rules/model-templates.md)
and [IMPORT authority](../../rules/model-information.md#import-configuration-authority).
The [Model-only contract](../../rules/task-contract.md#model-only-import-operation-contract)
defines exact pair/reference syntax and compatibility. Do not infer IDs or require pre-edits.

For an explicit Human deletion request, skip the ordinary pre-contract Issue Gate stop
and first register and validate the `import-delete` contract. After registration use
the common task-aware Issue Gate (`require_no_issues` or `issue_gate.py --task` with the
same selector), including on resume and before saves/final validation. Only existing
issue stops within its explicit Validation scope are waived; do not require remediation
or edit issues.md. All reference/Model safety checks and newly detected errors still
stop unsafe deletion. Merge and all other operations retain the ordinary pre-task gate.

The selected managed worktree is the transaction boundary. Keep the same parent Task
selector through every operation; include all planned source/view paths and required
direct consumers in its scope. Apply the common task-aware issue decision. The parent owns sequencing and
stopping; the following leaves own their exact editing procedures:

1. For an overall merge request, call [model-transfer](../../../.agents/skills/model-transfer/SKILL.md)
   with the registered pairs, then [model-retarget](../../../.agents/skills/model-retarget/SKILL.md)
   with registered references, then [model-delete](../../../.agents/skills/model-delete/SKILL.md)
   with the normalized sources. For deletion call only model-delete. An explicitly
   requested single leaf returns after that operation. No per-step reapproval for an
   already requested overall integration.
2. Each successful leaf may save raw sources in the worktree, leaving an unfinished
   intermediate Model. Stop on failure and retain prior successful saves; the parent
   may use the existing suspend transition. Never auto-rollback the whole workflow.
3. Use existing prepare_generation/validate_generation/publish_generation to prepare,
   validate and save the required views. Generation does not decide merge completeness.
4. Use worktree finalize: prepare the private commit and rebase onto latest local base,
   run one read-only final local loop on that actual candidate, consume its successful
   result for completion and ff-only merge, then let the surviving launcher cleanup.
   Final differences must prove complete transfer/removal, exact declared retargets,
   stable identities, all preserved consumers and absence of remaining source links.

Standalone validation/complete retain their own final checking responsibility. Ordinary
non-managed completed-candidate publication retains its previous IMPORT guard. A failed
final check retains the private commit/worktree without merge, automatic regeneration,
amend or loop retry. Report leaf saves and final validation/integration separately.
Do not enter the infrastructure branch below. /import separately permits acquired add/refresh/replace after its own Human selection; it does not authorize these Model-only operations.

## Check applicability and finish point first

First determine requested environment/target/services, properties, issues to repair, and endpoint (through model repair, IaC, or AWS reflection). Do not ask again about explicitly requested scope; confirm only missing decisions.

- Use the ordinary update procedure below only for requests to reflect human manual model diffs into AWS. Do not add preflight, change sets/plans, or deploy/apply to requests ending at IaC.
- Distinguish human-explicit issue repairs from update requiring manual model diffs. Before changes, match repair values against target models and existing IaC/parameters; treat matching existing IaC as confirmation targets. If only model repair, generated designs, and corresponding issue resolution are needed, record target service Validation scope and Issue remediation in a design-boundary repair contract. Do not stop repair due to absent manual model diffs or require same-value IaC rewrites.
- If IaC changes are actually needed, follow existing infrastructure boundaries. Do not mix model repair with IaC changes to lift update immutable input constraints; do not automatically create/execute another task.

Limit contract Required changes and Allowed paths to necessary changes and distinguish existing IaC confirmation targets. Do not reuse ordinary update contracts/AWS authorization for requests not meeting its applicability conditions below. Explicit issue repairs run target service generation, static validation of requested target IaC, and local loops once each, then finish at the specified endpoint. Do not omit task-type-specific checks or issue gates.

Follow [Credentials and account](../../rules/project-configuration.md#credentials-and-account) for common account/profile selection and apply [Policy account selection](../../rules/detailed-design.md#policy-account-selection) for policy-specific conditions.

## Unresolved issue gate

Apply [issue-gate](../../rules/issue-gate.md) and check every related service in one process.

```console
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id> [--service <service-id> ...]
```

Issue-gate is authoritative for stops/repair exceptions. Immediately before AWS mutation, also recheck the same services with `--task`; retain controller task/issue guards.

## Optional user input

- Authorized delete/replacement: `none` when omitted
- AWS profile: Optional. When omitted, target `awsProfile`, or default credential chain if unset. Reject explicit profiles differing from settings

Normally neither input is required. Treat delete/replacement as preapproved only when target resources and reasons are explicit. Create change sets/plans even without preapproval; proceed to waiting for human confirmation below only if unapproved delete/replacement is detected.

## Resolve target and scope from repository state

Before file changes, determine targets and scope in the following order.

1. Check `git status --short` and `git diff --name-only HEAD -- model/templates/ model/parameters/`.
2. Obtain environment and target directory from human-edited authoritative parameters.yaml and bindings.json, or the mechanically enumerated consumers of a common template. Resolve registered source impact with model_templates.py --alias <alias> --service <service> --affected. Enumerate service source directories through model_templates.model_paths; logical model/<environment>/<target-directory>/<service-id>.properties selectors do not require files.
3. Confirm exactly 1 environment/target directory combination matching a `project.json` target; obtain the alias if present and always the actual AWS account ID. Stop without file changes if no human-edited authoritative design inputs exist, the requested deployment target is ambiguous, or targets are unregistered. For common edits, generate/validate every consumer in a separate design task, then explicitly hand off exactly one deployment target; never infer permission for other consumers.
4. Design scope is all existing model properties edited by the human in the same target. Use model row documents as input for policy/setting JSON bodies; do not adopt manual Markdown/JSON artifact diffs as design values.
5. Match corresponding authoritative service properties against existing IaC/parameters; implement only differing properties. Resolve CloudFormation stack scope only from authoritative `cloudformation-stacks.properties` in the same target. Use `desired.stack.*.name`, `.template`, `.parameters`, `.deployOrder`, and `desired.deployment.maxConcurrentStacks`; effective MaxConcurrentStacks is 1 when omitted. Confirm resource ownership and each shared-template stack instance/parameter mapping from service properties and existing IaC; stop if ambiguous. If changed design references resources owned by other stacks in the same account/region, also consider those producer stacks for necessary Output/Export additions.
6. Deployment scope is the above StackNames, templates/parameters, or Terraform roots/resources and dependencies. For CloudFormation, stop without guessing/migration if DeployOrder is unset; the controller enforces order and parallel limits. Do not convert DeployOrder to template DependsOn. For Terraform, resolve roots, workspaces, backends, variable inputs, modules/resources, and dependencies from existing IaC; stop for missing/mismatched inputs. Different StackNames using the same template are separate units; include only stacks owning changed design resources in scope. If handling producers and consumers requiring cross-stack exports in the same task, include both stacks in scope.

Stop without incorporating out-of-scope uncommitted changes. Only if repository information cannot uniquely identify deployment units, ask one missing item such as stack name per response. Do not require the user to reenter targets, paths, or entire scope identifiable from the repository; do not infer values.
Do not automatically interpret existing StackName deletions/renames in stack design diffs as stack deletion. If ending management/deleting target stacks is necessary, report targets/impacts and stop without execution in the current update phase.

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `tasks/<task-name>.md` if present. Otherwise treat as idle and create it first under Create active task contract.
4. `project.json`
5. `git status --short` and Design scope diffs identified from repository changes
6. Authoritative Design scope templates and model/parameters/<environment>/<target-directory>/<service-id>/ inputs, read via the logical Model selector. For CloudFormation, same-target `cloudformation-stacks.properties` needed for stack scope resolution
7. [Policy account selection](../../rules/detailed-design.md#policy-account-selection). For CloudFormation, add [CloudFormation stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design); add related display sections only when changing/investigating design display.
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. [cloudformation](../../rules/cloudformation.md) or [terraform](../../rules/terraform.md) for the selected engine
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope). [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. `framework/materials/aws/*.properties`, `framework/materials/api/*.properties`, and same-named API design schemas relevant to target resources
13. For CloudFormation, target resource provider schemas
- [project-configuration](../../rules/project-configuration.md) and [issue-gate](../../rules/issue-gate.md). For naming checks, [aws-resource-naming](../../rules/aws-resource-naming.md).

For naming rules, additionally read only service files corresponding to target resource type catalog namespaces from the common entry's Service rule lookup. Even for multiple services, read only target namespaces, not the whole naming rule directory at once. Match Catalog resource types/Naming target and patterns in selected service files.

Update design inputs are only authoritative model properties. Do not read generated Markdown bodies or generated JSON artifacts as input at start, IaC generation, or reference resolution. `cloudformation-stacks.md` is also a display generated artifact; the Agent must not retrieve/compare the same stack scope information twice. Use `desired.row.*.document` for JSON bodies. Full 03/04 prompt reads are unnecessary; follow this prompt for Update procedures and existing rules above for common contracts. Retain Markdown/JSON generation/saving and consistency validation by controllers/local loops.

For limited resources, use existing partial reading for both single files and split entry indexes. Selectors require exact resource number, logical ID, or anchor matches; stop if unmatched/ambiguous.

```console
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --resource <resource-selector>
```

Load only target resources, parents/children/siblings in the same group, and service metadata/notes into context. Service-wide changes may read entire target service properties, without unconditional expansion to all services/models. Resolve properties logical references from `desired.resource.*.anchor` / `.logicalId` and `parentReference`. Map other services' `.md#anchor` links from path/file stem to producer properties; additionally retrieve only necessary resources with the same `model_files.py --resource`. Do not read generated Markdown bodies as fallback. Stop without guessing for unknown reference targets or missing required desired values, stack assignments, or human decisions.

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
- Apply schema validation such as existing `model_design.validate_required_properties` and `DesignSchemaCatalog.literal_errors` to target properties to confirm CREATE/IMPORT, formal types, required properties, types/constraints, and necessary dependencies. Do not automatically supplement scope or intended design.
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
4. For CloudFormation, run `cfn-lint --regions <project.jsonのawsRegion> <template...>` for all target templates. For Terraform, run `terraform fmt -check`, `terraform init -backend=false` with fresh `TF_DATA_DIR`, and `terraform validate`. Repair IaC implementation errors for at most 3 iterations only if correctable within confirmed design. Stop if the same error repeats twice without material progress or human decisions/design changes are needed. Do not proceed to deploy with validation failures remaining.

## Preflight and deploy

Only target IaC uncommitted diffs generated from Design scope in this task are permitted for deploy. IaC diffs predating task start or diffs outside Deployment scope are not permitted. Stop for engine switching, unknown state/backends, design mismatches, or required input missing.

### CloudFormation read-only dependency check

Only for cross-stack references requiring live AWS state to decide IaC changes, existing `check-deploy-context.py` with `--read-only` may confirm identity/account/region/profile before necessary `describe-stacks` / `list-exports`. Add `--read-only` to the same target selector as Terraform examples below. This exception is read-only confirmation for implementation decisions; do not run it in ordinary CloudFormation update. It neither authorizes mutation nor replaces controller final preflight. Stop on mismatch/authentication failure; do not fall back to another profile.

Match actual Export names, values, and ExportingStackId in the same account/region against producer Outputs. If exports exist, change consumer template references and corresponding string portions to `!ImportValue` and proceed from static validation to controller. If no exports exist, add only necessary Output/Export to producer templates and first perform static validation, controller producer deploy, terminal success, and actual Export confirmation. Only afterward change NOT_STARTED consumer templates to `!ImportValue` and resume the same controller session stopped with `--pause-after-group`. If both stacks are not in Deployment scope, stop without expanding scope by guessing.

### CloudFormation controller

`cloudformation-deploy.py` is responsible for final preflight. The controller uses existing `check-deploy-context.py` helpers to confirm AWS identity, project targets, profiles, accounts, regions, engines, and necessary commands, enforcing task scope, issue gates, and immutable inputs. The Agent must not first run the same final deploy-context check standalone. Match explicit account/region against the same project target and pass explicit profiles to controller `--profile`. Stop for mismatches or missing credentials/permissions. Launch the controller from the same Python environment as cfn-lint.

```console
python framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --state <repository外の同task専用session.json> [--profile <profile>]
# aliasなしでは --alias の代わりに --aws-account-id <aws-account-id>
```

Normally one controller launch completes all DeployOrders. The controller owns whole-scope cfn-lint, input hashes, per-StackName existence/parameters/resource ownership, actual Export confirmation for ImportValue, validate-template, change set creation/classification/reconfirmation/execution, and terminal confirmation. Do not distribute change set creation/execution outside the controller. Retain existing `cloudformation.md` contracts for declared S3 artifact placement, template-size-based delivery, group barriers, MaxConcurrentStacks queues, session validation reuse, immutable guards, failure stops, and draining RUNNING stacks. Do not create consumer change sets before producer success or adopt/change/delete stacks outside design.

On ordinary success, complete observed updates and service-scoped sync-model inside the controller before proceeding to the next group; synchronize the final group too before COMPLETE. Use `--pause-after-group` only for explicit producer/consumer IaC changes; `--resume` the same session from GROUP_COMPLETE after synchronization. Reject IaC changes to prepared/executed units; do not rerun successful stacks. For scope excess, account/region mismatch, validation failure, or deployment failure, do not start new units; confirm RUNNING stack terminal states and stop. Do not automatically rollback/delete/redeploy successful stacks.

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

After approval, record target resources, actions, and reasons in the same task's Authorized delete/replacement. For CloudFormation, pass `--resume --approve-change-set <保存されたchange-set-id>` to the same session; retain controller checks of the same ID, CREATE_COMPLETE/AVAILABLE, and change fingerprints. For Terraform, reconfirm the same plan's resource addresses/types/actions. Do not reuse prior approval for expired/recreated/changed change sets/plans. Stop if actions are unknown. Without approval, do not execute or mix IaC/design changes for resource retention/releasing management into this confirmation step.

## Post-deployment model sync

### CloudFormation

Observed collection, model updates, and generated artifact synchronization are owned by the controller. `cloudformation_observed.py` matches actual template LogicalIds, formal types, catalog IDENTIFIER_OUTPUT, and Outputs/PhysicalResourceId; updates necessary non-ARN identifiers and observed rows of all references, then runs service-scoped sync-model generation/validation. Confirm COMPLETE and synchronization results; the Agent must not rerun the same AWS value retrieval or `sync-model.py --write`. Stop for ambiguous mappings with AMBIGUOUS_OBSERVED_MAPPING; the LLM must not supplement them. Synchronization failure is not completion; retry in the same controller session after resolving blockers.

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

Model source persistence uses optional `observed.json` with actual row values only;
runtime property/comment come from desired metadata. File absence means unobserved,
never observation success. Omit empty observed files and empty binding labels; preserve
nonempty labels, fixed IDs, internal parameters, references and CFn placement.

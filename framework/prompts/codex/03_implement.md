# Infrastructure Implementation Prompt

Follow [task-contract](../../rules/task-contract.md) for contract registration, reservations, stopping/resuming.

Use this prompt for an `infrastructure` task converting authoritative model properties, the authority for approved detailed designs, into CloudFormation or Terraform selected in `project.json`, through local static validation. Do not execute AWS APIs, change sets, plans, or deploy/apply. For deploy/apply, use `framework/prompts/codex/04_deploy.md` in a separate task.

Follow [Credentials and account](../../rules/project-configuration.md#credentials-and-account) for common account/profile selection and apply [Policy account selection](../../rules/detailed-design.md#policy-account-selection) for policy-specific conditions.

## Unresolved issue gate

Apply [issue-gate](../../rules/issue-gate.md) for target service stop decisions and exceptions before start/resume/mutation.

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target alias: `{{project.jsonのalias。aliasなしの場合は省略}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Implementation scope: `{{対象の詳細設計fileまたはresource group。複数可。「対象accountの承認済み設計すべて」も可}}`

## Resolve missing input

Confirm User input before file changes. Treat placeholder, empty, and unknown values as missing; ask only one question per response in the following order.

1. Target environment
2. Target alias (only when the selected environment has multiple targets)
3. Target AWS account
4. Implementation scope

Present only environment, alias, and AWS account candidates belonging to the same target in `project.json`; do not automatically select. Do not ask aliases when an environment has only 1 target. If `project.json` or target approved detailed design authoritative model properties are absent, stop without guessing values.

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `tasks/<task-name>.md` if present. Otherwise treat as idle and create it first under Create active task contract.
4. `project.json`
5. Authoritative `model/<environment>/<target-directory>/<service>.properties` corresponding to implementation scope (read ranges follow below)
6. [Policy account selection](../../rules/detailed-design.md#policy-account-selection). For CloudFormation, add [CloudFormation stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design); add related display sections only when changing/investigating design display.
7. `framework/rules/aws-resource-naming.md`
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. [cloudformation](../../rules/cloudformation.md) or [terraform](../../rules/terraform.md) for the selected engine
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope). [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. `framework/materials/aws/*.properties`, `framework/materials/api/*.properties`, and same-named API design schemas relevant to target resources
13. For CloudFormation, `framework/materials/cloudformation-schema/ap-northeast-1/index.json` and target resource provider schemas
- [project-configuration](../../rules/project-configuration.md) and [issue-gate](../../rules/issue-gate.md). For naming checks, [aws-resource-naming](../../rules/aws-resource-naming.md).

For naming rules, additionally read only service files corresponding to target resource type catalog namespaces from the common entry's Service rule lookup. Even for multiple services, read only target namespaces, not the whole naming rule directory at once. Match Catalog resource types/Naming target and patterns in selected service files.

Implement design inputs are only authoritative model properties. Do not read generated `docs/designs/<environment>/<target-directory>/*.md` bodies (including `cloudformation-stacks.md`) at Implement start, IaC generation, or reference resolution, or retrieve values again. Do not require the Agent to compare properties and generated Markdown twice in advance. If properties lack necessary desired values, resources, references, stack assignments, or human decisions, include them in the pre-implementation deficiency list below and stop because a design task is required. Retain Markdown/JSON generation/saving and local loop consistency validation as before.

If Implementation scope specifies detailed design `.md` files, treat them as scope selectors. Without reading bodies, map `docs/designs/<environment>/<target-directory>/<service>.md` path/file stem to `model/<environment>/<target-directory>/<service>.properties` in the same environment/target/service and confirm equality with the selected project target. If corresponding models cannot be uniquely identified, stop without guessing.

For resource-limited scope, partially read authority with the following existing command. Selectors require exact matches for resource number (such as `001`), cfn-logicalId, legacy logical ID, or anchor; stop on unmatched/ambiguous selections.

```console
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service>.properties --resource <resource-selector>
```

Retrieve only target resources and parents, children, and siblings in the same group required by existing specifications, and service metadata/notes; do not add custom extraction. Use the same command for single files and split entry indexes; do not load unrelated resources or all parts into context. Service-wide scope may use entire service properties; “対象accountの承認済み設計すべて” may use target service model sets. Split models follow existing `model_files.py` entry indexes and part structure; read only required parts.

Limit reads to implementation scope resources/properties and producer properties needed for reference resolution. Use producer `model_files.py --resource` for additional retrieval too, without expanding change scope. Reading all target Markdown as fallback is prohibited. Do not reread material already confirmed in the same task unless content changes, validation fails, or unresolved dependencies exist.

`<target-directory>` is the selected target's alias if present, otherwise AWS account ID.

Follow AGENTS.md “How to read required rules” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.

## Read-only implementation preflight

After User input and issue gate confirmation, before active contract creation or IaC generation, perform all Check implementation support, Resolve implementation units, and existing IaC matching below read-only. Do not execute AWS APIs, IaC generation, or deploy. Reuse existing schema validation and dependency checks; do not add new validation engines or approval steps.

1. From target resource authoritative properties, confirm CREATE/IMPORT, formal CFn types, required properties, and unconfirmed values. Reuse schema validation applicable to properties such as existing `model_design.validate_required_properties` and `DesignSchemaCatalog.literal_errors` to check type, enum, pattern, length, range, and supplemented AWS character constraints. Do not reuse previous task Validation scope; validate explicit target services and necessary references. Distinguish Japanese display Comments from formal property values; do not automatically translate/replace invalid values.
2. Follow resource/property references in properties, confirm necessary dependency properties, anchors, logical/current identifiers, and handoff values; apply the same schema validation to used properties. Use properties-based reference resolution below and dependency checks in Resolve implementation units; read only necessary resources/properties at reference targets. Do not automatically expand change scope or all-service validation during dependency investigation.
3. For CloudFormation, confirm target resource owning stacks, template/parameter mappings, DeployOrder, and each shared-template stack instance from authoritative stack registration properties. Check correspondence between existing template Resources/Parameters/Outputs/Export/ImportValue and properties desired rows, missing parameter values/defaults, unknown reference targets, and dependency cycles. Absence of not-yet-created new IaC files alone is not a deficiency; unconfirmed placement/input design is. For Terraform, check existing module/environment input/output mappings.
For stacks with existing CloudFormation templates, run common local read-only validation before implementation. Directly match each resource's `desired.resource.*.cfn-logicalId=<StackName>-<Resources key>`. Do not use separate mapping tables or fill missing/invalid mappings with legacy matching when direct IDs exist in the same stack. Retain unique type + legacy logicalId matching only for old models without direct IDs. Evaluate Conditions with stack-specific parameters/defaults and collectively report active resource CREATE classification, formal type, mapping, duplicate ownership, identifier rows, and missing required Outputs. Do not process false resources; stop for unresolved Conditions. At this stage, absent new templates are not deficiencies; confirm model identifier rows and placement destinations.

```console
python framework/scripts/cloudformation_observed.py --environment <environment> --target-directory <target-directory> --stack <StackName> --stack <another-StackName>
```

4. Aggregate diagnostics for all verifiable targets/dependencies and present the deficiency list `対象file | resource（logical ID）/stack | property/parameter | 不足・違反理由` together in one response. State reasons for unreadable targets and continue other checks; do not end the report at the first deficiency. For 0 deficiencies, report that result and implementation target diffs, then proceed to contract creation/implementation without requiring additional approval. If deficiencies exist, do not implement; identify that a separate design task is required and unconfirmed matters, then stop. Do not repair designs/models/IaC here or automatically create/execute another task.

## Compare existing IaC before creating the contract

Before file changes, check implementation support and resolve implementation units below, then match confirmed target property design values against existing templates/modules and parameters. Matching portions are confirmation targets requiring no changes; only differences are implementation targets. If existing IaC is correct, do not create same-value rewrites or naming-only changes.

If all portions match, perform target IaC static validation once, report no changes needed and results, then finish. Read-only confirmation without repository changes does not create a new active contract or count as completion of an implement task requiring IaC changes. If explicit issue repair requires model changes, handle only repair scope under existing task boundaries; do not change models here.

## Create active task contract

As the first repository change, newly register `tasks/<task-name>.md` authorizing only this task's targets.

- Task type is `infrastructure`.
- Infrastructure phase is `implement`.
- State target environment, alias when present, AWS account, implementation scope, and selected IaC engine in the goal.
- Set AWS mutation, AWS API execution, and deploy/apply to `forbidden`.
- In `Required changes`, state only IaC implementation differing in prematching and target static validation with unique Requirement IDs. State unchanged existing IaC as confirmation targets.
- Map `Acceptance checks` to each Requirement ID using `changed:` for IaC files to change and `exists:` for unchanged confirmation targets. Do not omit task-type-specific checks.
- Limit Allowed paths to target IaC files and `tasks/<task-name>.md` only. Changes to detailed designs, models, and scenarios are prohibited.

## Check implementation support

Separately check resources listed in authoritative properties and resources implementable by the selected engine. For CloudFormation, run `python framework/scripts/design_catalog.py --cloudformation-type <catalog-resource-type>` for each type in implementation scope and use only successful formal types. `Macie.ClassificationJob` and `QuickSight.Group` are unsupported by CFn; do not convert them to templates, Outputs, or `!Ref`.

If Jobs are in requested scope, explicitly state them as unimplemented; implementing only supported resources is not completion of the whole request. Tasks already limited to CFn-supported scope may finish within that scope. Do not add Custom Resources, other engines, or API mutation because of unsupported resources.

## Resolve implementation units

Identify necessary templates/modules, parameters, and dependencies from target scope. Reuse existing boundaries/common components; do not create unused resources, future modules, or compatibility layers.

For CloudFormation, follow `1 template = 1 deploy responsibility` in `framework/rules/cloudformation.md`. Do not mechanically split by AWS service. For dependency cycles, missing parameters, or unknown reference targets, report missing information and stop.
For CloudFormation, read only the target's authoritative `model/<environment>/<target-directory>/cloudformation-stacks.properties`. Obtain StackName from existing `desired.stack.*.name`, template filenames from `.template`, individual parameter filenames from `.parameters`, DeployOrder from `.deployOrder`, and MaxConcurrentStacks from `desired.deployment.maxConcurrentStacks`. When omitted, effective MaxConcurrentStacks remains 1 under the existing contract; do not infer DeployOrder. `cloudformation-stacks.md` is a display generated artifact; do not read it as Implement input. Do not convert DeployOrder into IaC resource dependencies or add DependsOn to templates for this feature. Confirm scope resource template placement from approved service properties and existing IaC; if ambiguous, do not create by guessing and report that a design task is required. Even when multiple stacks share a template, confirm per-stack parameters and generated resource/Export name uniqueness.
Include CloudWatch Logs resources and Security Groups in the templates of resources using them; do not create templates containing only them. Include IAM Roles in the template of directly using resources in the same target when present. When no design resource in the same target directly references a Role and purpose/AssumeRole source are confirmed in service properties, place only the Role and associated IAM Policy/ManagedPolicy in a dedicated template and declare `RolePlacement: standalone` directly under `Metadata`. If consumer resources or Role-only stack design are unknown, stop without guessing.

Check `!Ref`, `!GetAtt`, `!Sub`, and resource references in policy/setting strings to target resources. For resources outside the template, identify actual owning stacks, necessary values, and producer Output/Export from properties logical references and existing IaC. If producer exports are not yet deployed, add only necessary Output/Export to producer templates within scope and leave consumer `!ImportValue` changes to tasks after producer deploy. Do not execute AWS APIs/deploy in implement; report prerequisites if deployed export confirmation is needed. If producers are out of scope or ownership is unknown, stop without expanding changes.

## Implement and validate

Use only authoritative model properties as machine-readable input of approved designs to implement the selected engine's minimum configuration. Obtain resource settings, tags, Names, policy documents, and identifier references from properties `desired.row.*` (JSON bodies from `.document`); do not retrieve values again from generated Markdown/JSON artifacts.

Reflect tags in properties desired rows into CloudFormation/Terraform unchanged. Do not output `EC2.VPC.Name`, `EC2.Subnet.Name`, `EC2.RouteTable.Name`, or `EC2.FlowLog.Name` as provider properties; convert them to tags with case-sensitive `Name` keys and the same values. Only when the corresponding target resource `.Name` and non-empty value are missing, report that a separate `design` task is required and stop without guessing values.

Resolve `[表示値](#anchor)` logical references saved in properties desired rows/reference values uniquely from the same model's `desired.resource.*.anchor` and `desired.resource.*.logicalId`. For `[表示値](<service>.md#anchor)` cross-service references, also map path/file stem to corresponding producer model properties, retrieve only necessary resources, and resolve from the same metadata. Resolve grouped resource `parentReference` from properties anchors too. Stop without guessing for unknown/ambiguous reference targets; do not read generated Markdown bodies. Do not hardcode link display text `PENDING_DEPLOY` or physical IDs into IaC. Add only catalog `IDENTIFIER_OUTPUT` needed by subsequent resources to CloudFormation Outputs or Terraform output, retaining logical resource/resource attribute references. Do not make generated ARNs observed-value outputs.

For CloudFormation:

1. Use `infra/cloudformation/templates/<alias>/` for aliased targets, or common `infra/cloudformation/templates/` for targets without aliases. Place parameter filenames listed in stack properties in `infra/cloudformation/parameters/<environment>/<target-directory>/` and change only individual files. Match template `Resources` logical IDs to service properties resources from each resource's `cfn-logicalId=<StackName>-<Resources key>` across all stack instances. Terraform requires neither this field nor generic logicalId. After generation/changes as well, always run the above `cloudformation_observed.py` common validation also used for deploy. Do not automatically fill missing identifier rows; distinguish model deficiencies from missing IaC Outputs in reports.
2. Use PascalCase from `framework/rules/cloudformation.md` for new `Resources` logical IDs and target-specific final `Outputs.*.Export.Name` values; confirm resource cfn-logicalId mappings, template references, export/import equality, and uniqueness. Insert at least 1 blank line between resources under `Resources`. For consumers with confirmed deployed producer exports, replace entire reference values and reference portions within strings with `!ImportValue`. Do not change existing IDs merely for naming format.
3. Run `cfn-lint --regions <project.jsonのawsRegion> <template...>` for all target templates.
4. Do not run `aws cloudformation validate-template`, change set creation, or AWS APIs.

For Terraform:

1. Use `infra/terraform/modules/<alias>/` for aliased targets, or common `infra/terraform/modules/` for targets without aliases; change only target `infra/terraform/environments/<environment>/<target-directory>/`.
2. Run `terraform fmt -check`, `terraform init -backend=false` with fresh `TF_DATA_DIR`, and `terraform validate`.
3. Do not run `terraform plan`, `terraform apply`, or AWS APIs. Do not create/save state files or plan binaries.

If static validation fails, investigate root causes. Minimally repair only IaC implementation errors correctable within confirmed design and rerun for at most 3 iterations. Stop if the same error repeats twice without material progress or human decisions/design changes are needed.

## Verify and finish

1. Confirm selected IaC local static validation results. Do not rerun if target IaC, parameters, and dependency inputs have not changed after success.
2. Run `python framework/scripts/blueprint-loop.py --mode task` once. This existing local loop confirms properties/generated Markdown/JSON artifact equality with `validate-blueprint.py` and read-only `sync-model.py`; mismatches are FAIL. Retain display/reference/stack validation through existing `check_design_tables`, `check_design_links`, and `check_stack_designs`. Even without Agent Markdown prereading/comparison, do not omit/weaken these validations or complete while ignoring mismatches. Diff checks are also included in this loop.

Do not add overall validation after successful scoped validation. Rerun only for repairs, new failures, or unresolved concerns; track the same execution on tool wait timeout.

State targets, accounts, regions, engines, changed files, implementation units/dependencies, validation results, retries, and blockers in completion reports. Do not save verification output in the repository.

Do not create or execute AWS APIs, change sets, plans, deploy/apply, observed value updates, scenarios, other targets, or next tasks. Perform deploy/apply only when the human explicitly uses `framework/prompts/codex/04_deploy.md` as a separate task.

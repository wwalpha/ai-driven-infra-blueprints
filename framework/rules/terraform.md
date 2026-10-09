# Terraform Rules

- Follow [Credentials and account](project-configuration.md#credentials-and-account) for account/profile/target selection.

Follow [issue-gate](issue-gate.md) for target service stops and exceptions.

- Create, change, and execute Terraform only in `infrastructure` tasks.
- Infrastructure task design inputs are approved authoritative model properties entries and required parts/referenced models. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, identity/references from metadata such as `desired.resource.*`, and current non-ARN identifiers from `observed.*`. In ordinary deploy, do not additionally read generated service Markdown/service-owned JSON bodies. Map `.md#anchor` using existing model readers and metadata; stop for unknown, unmatched, or ambiguous mappings, without generated Markdown body fallback.
- Retain generated artifact existence verification, existing hash monitoring/reservations, generated artifact validation by sync-model/local loop, and stop conditions. For explicit display defect/mismatch investigation, only necessary corresponding portions may be read. Do not continue deploy after mismatch or automatically repair IaC/intended design.
- If intended design changes are needed, stop without filling values and report that a separate `design` task is required.
- Use only when the active project and target environment/target directory select Terraform.
- Manage 1 environment/AWS account with only 1 IaC engine, consistent across aliases sharing an AWS account ID. Also keep engines consistent across targets sharing environment/execution account.
- This rule is the authority for Terraform placement. Resolve target-directory using [Topology](project-configuration.md#topology): alias when present, otherwise AWS Account ID. Framework validators reuse the resolved project target keys and common Terraform path helpers; do not parse Markdown to determine paths.
- Place shared Modules in `infra/<target-directory>/terraform/modules/<module>/` and environment Roots in `infra/<target-directory>/terraform/<environment>/`. Share the same target-directory's Modules across all its environments; separate different aliases and, without aliases, different Account IDs. Environment names come from project.json.
- Legacy `infra/terraform/environments/<environment>/<target-directory>/` and `infra/terraform/modules/<alias>/` are forbidden. No fallback, duplicate management, or empty legacy-directory workaround is permitted. Report existing violations; do not migrate managed resources/state without separate authorization.
- Do not generate unused infrastructure in advance.
- Adding API design catalogs does not establish Terraform implementation support or authorize adoption. Do not switch engines because CFn is unsupported; retain the selected engine and active task's explicit scope. Do not silently exclude resources with unverified implementation support and call the task complete.
- Terraform models require neither `logicalId` nor `cfn-logicalId`. Use service entry numbers and anchors as internal identities; do not save CFn metadata. Retain existing logicalIds only for read compatibility.
- For detailed design identifier references to CREATE, resolve model resources from Markdown link anchors and generate corresponding Terraform resource attribute references. Do not hardcode link display text `PENDING_DEPLOY` or physical IDs into configuration.
- Even when detailed design tables are integrated, retain CREATE KMS Keys and Aliases as separate resources. Do not generate IMPORT. Resolve target Keys from grouped Alias model `parentReference` and set Key attribute references in `target_key_id` corresponding to `parentProperty`. References from S3 to Aliases use the corresponding Alias name. Do not change existing resource addresses solely because display changes.
- Expose CREATE catalog `IDENTIFIER_OUTPUT` needed by subsequent resources or root modules as non-sensitive `output` from resource attributes. Generated ARNs are excluded from output collection and observed value persistence.

## Module and environment inputs

- Gather AWS `resource` definitions in the target Module. Roots contain Module calls, variable declarations/values, Provider, Backend and State configuration and other valid Terraform Root constructs (such as data, locals, outputs and non-AWS resources), but no direct AWS `resource` blocks. Keep existing service-specific file splits and Provider settings.
- Every Root calls Modules under its own `infra/<target-directory>/terraform/modules/<module>/` with local literal sources, for example `source = "../modules/iam"` from both dev and stg. Resolve local sources relative to the calling file's directory and normalize them, including symlinks, before testing directory containment and existence. Reject other targets, Root directories, per-environment Module copies, missing directories and external sources for Root calls. Local child Module calls stay in the same target's Module tree; remote child Modules retain Terraform's own semantics.
- The same Root Module call name within a target-directory must resolve to the same Module source across environments. Compare normalized paths, preserve existing call names, and do not equate unrelated Module instances by resource contents.
- Roots without aliases use `infra/<accountId>/terraform/<environment>/` and their own `infra/<accountId>/terraform/modules/<module>/`; do not introduce sharing between different Account IDs.
- Root configuration files sit directly in the environment directory; Module implementation files sit below modules/<module>. The name `modules` is reserved for the shared Module tree and cannot also identify a Terraform environment directory. Do not require particular filenames: backend.tf and terraform.tfvars follow approved backend/input settings.
- Declare Module inputs in its `variables.tf` or existing service files. Put environment-specific values in the corresponding Root's `terraform.tfvars`, `.auto.tfvars`, or existing approved Terraform input mechanism. Do not hardcode environment-specific values/defaults in Modules or read another environment's tfvars.
- Environment inputs may compose resource Names/Tags, but must not select resource structure or behavior through conditionals, count, for_each, lookup, or workspace/environment-name comparisons. Pass actual differing values as variables instead.
- Keep Backend/State identities distinct for every environment/target; confirm the approved backend key/path and workspace instead of guessing. Do not save passwords/API keys or other secrets as plaintext tfvars; use the existing approved secret input mechanism. Stop on unconfirmed required inputs.
- Reuse existing Module call names and resource addresses. Moving existing managed resources into Modules or changing addresses requires a separate explicitly authorized migration; this rule does not authorize State migration.
- Validate only generated files. Missing not-yet-generated Module/Root files alone are not implementation-preflight errors; an existing Module call to a missing directory is an error. Module-only changes also validate references from the same target-directory’s Roots, including all environments sharing those Modules. Full validation detects misplaced and legacy IaC even outside task scope. Framework checks placement and references; Terraform CLI retains syntax and semantic validation. Configuration findings use existing Validation scope and current-task changed-file grants, with whole-IaC gating only when explicitly requested by the existing full/regression workflow.

## Resource mode boundary

- Only authoritative model resourceMode=CREATE (including unspecified mode) is generated for Terraform. Retain IMPORT in detailed designs/properties, outside IaC generation, without AWS resource changes. Do not generate IMPORT as Terraform `resource`. Do not create/execute Terraform import commands/import blocks or import into state.
- IMPORT is a framework design management classification, not Terraform import functionality. Do not correct values to framework naming or add/change Name tags.
- Resource implementation, logical ID mappings, identifier references, and Outputs/output generation in this rule apply only to CREATE. Grouped children with independent identities are classified by their own resourceMode. Inline settings follow the containing resource's classification.
- For CREATE references to IMPORT, do not generate fictitious resource references. Without an existing approved handoff design, report what is missing and stop; do not design new external input mechanisms. Do not change external stacks/states owning IMPORT.
- Do not interpret switching already IaC-managed resources to IMPORT as authorization to automatically delete them from templates/configurations or release management. Report impacts and stop when detected.

## Validation and execution

- If the target has `awsProfile`, use the same profile for Terraform init/plan/apply and AWS value retrieval. Pass `AWS_PROFILE` only to target processes and children; do not rewrite global shells or AWS configuration files. Retain profiles for both AWS providers and AWS backends; stop before execution on conflicting settings overriding selection such as explicit profiles/direct credentials. Specify the same `--profile` for AWS CLI and profile for SDK. When unset, retain existing explicit profiles/default credential chains without omitting account/region validation.
- Match provider and AWS backend account restrictions/connection validation against their approved settings and execution account. Pass `awsAccountId` for explicit account ID values such as resource names; do not replace it with the execution account obtained from caller identity.
- The `implement` phase runs `terraform fmt -check`, `terraform init -backend=false` with fresh `TF_DATA_DIR`, and `terraform validate`; do not run plan, apply, or AWS APIs.
- The `deploy` phase leaves IaC unchanged and runs `terraform fmt -check`, `terraform validate`, and `terraform plan` saved outside the repository.
- The `update` phase generates Markdown without changing model properties manually edited by the human before task start; after implement-phase local validation, confirm plans saved outside the repository and apply. Permit only target IaC uncommitted diffs generated in this phase as apply targets.
- If IaC repair is needed in the deploy phase, stop without changing it.
- Do not introduce human review uniformly stopping all plans. Wait for human confirmation with an explanation according to `framework/prompts/codex/04_deploy.md` only when saved plans contain unapproved destroy/replacement.
- Execute saved plans for apply only when explicitly authorized by deploy/update phase active prompts and plan scope matches the prompt.
- When the active prompt limits targets, the implement phase may change only specified environments/modules/resources, and the deploy/update phase may apply only specified targets and finish.
- Saved plan resource change actions containing delete are subject to destroy/replacement confirmation. If unapproved, do not treat as deployment failure or task completion; wait for human confirmation without applying.
- After human approval, reconfirm the same saved plan in the same task and apply that plan binary only when approved resource addresses, resource types, and actions match. If the plan binary is lost, recreated, or changed, reconfirm without using prior approval.
- Do not apply saved plans when only a subset of changes is approved. If configuration repair or resource retention is needed, stop without changing IaC in the current deploy/update phase.
- Stop for wrong workspace/account/region, missing input, sensitive output, plan failure, deficient intended design, or inability to determine destroy/replacement actions.
- Do not commit state files or plan binaries.
- Record remote state in project design as a configuration with access control, locking, encryption, and backup.
- Do not output secrets or save generated ARNs as observed values.
- Switching existing environments between CloudFormation/Terraform is a dedicated migration/import task, not normal update.

Follow [observed-values](observed-values.md) for identifier collection/synchronization after success, and [task-contract](task-contract.md) and [loop-engineering](loop-engineering.md) for task finish.

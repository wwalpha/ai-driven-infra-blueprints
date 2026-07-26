# Codex Task: AI-driven infrastructure blueprint governance migration

## Task contract

- Task ID: `task-20260726-blueprint-governance-migration`
- Task type: repository governance and document-structure migration
- Target repository: the current `ai-driven-infra-blueprints` repository root
- Execution client: **macOS Codex app**, with the repository folder opened as the active local project/workspace
- Codex CLI invocation by the user: **not required and not assumed**
- IaC engine for this task: `none`
- AWS resource mutation: **forbidden**
- CloudFormation deploy/update/delete: **forbidden**
- Terraform apply/destroy/import: **forbidden**
- Network access: not required
- Goal: reflect the agreed ChatGPT + human + Codex workflow in the repository without changing the existing AWS implementation behavior

Do not ask for a design decision that is already specified below. Inspect the repository first, then implement and verify the migration in the same task.

This task will be started from a Codex thread in the macOS app after the user opens/selects the repository folder. Any shell, Python, Git, AWS CLI, or Terraform commands written below are commands that Codex may run through the app’s local execution environment; they are not instructions for the user to launch or operate Codex through the Codex CLI.

---

## 1. Goal

Migrate this repository from the old Copilot / `.github` / CloudFormation-only / manual-review structure to a Codex-oriented blueprint with the following model:

```text
AGENTS.md                    # short rules that apply to every task

rules/
├── detailed-design.md       # detailed-design file grouping, tables, and links
├── llm-design-information.md
├── cloudformation.md
├── terraform.md
├── post-deploy-actuals.md
└── loop-engineering.md

tasks/
└── <task-id>/
    └── prompt.md            # prompt created by ChatGPT for each change
```

The repository is a blueprint. A project created from it is expected to customize `AGENTS.md` for its project, environment, and selected IaC engine.

---

## 2. Agreed operating model

Encode all of the following as active repository rules and README guidance.

1. ChatGPT-like AI and a human decide which AWS resources will be created, such as VPC, Subnet, EC2, and S3.
2. ChatGPT reads the relevant files under `materials/aws/`, presents only the parameters that need a decision, and the human supplies or approves the inputs.
3. ChatGPT creates a task-specific Codex prompt from the agreed resources and inputs.
4. Codex may not change CloudFormation, Terraform, or detailed-design documents unless an active `tasks/<task-id>/prompt.md` exists.
5. Codex first updates the human-readable detailed design, then the separate LLM-readable design information, then the selected IaC implementation.
6. The user selects exactly one IaC engine for an environment: CloudFormation or Terraform. Do not manage the same environment with both engines.
7. `materials/aws/` is an immutable reference catalog of configurable fields. It is not a project-value store and is not a requirement to print every field in a detailed design.
8. A detailed design contains only the fields needed for that project/resource. Do not dump every field from `materials/aws/` into the design.
9. Values known only after deployment, such as generated IDs and DNS names, must be visibly represented before deployment and updated after deployment.
10. Generated ARNs are not collected or persisted as post-deploy actual values.
11. ARNs may still be used where technically required as an IaC/API reference or as a human-provided design value, for example an AWS managed-policy ARN or a Target Group ARN used transiently by a test. Do not confuse this with post-deploy actual-value collection.
12. There is no repository-level human review gate between `validate / plan` and `deploy / apply`.
13. `validate / plan` remains mandatory. If the active ChatGPT task prompt explicitly permits deployment and the machine checks pass, Codex continues to `deploy / apply` without `REVIEW_PENDING`.
14. If the task prompt does not permit deployment, Codex must not deploy. This migration task explicitly forbids all AWS mutations.
15. After deploy/apply, Codex retrieves only the necessary generated IDs, DNS names, IPs, endpoints, or similar values, updates the detailed design and LLM actual information, runs scenario tests, and records evidence.
16. Loop engineering is mandatory. Run a local deterministic loop after each logical change set, and a full task loop before completion. “Each change” means each coherent logical change, not every editor save.
17. Missing human input must not be guessed. Stop with an explicit missing-input report.
18. `materials/aws/` must never be changed by a normal project task.

---

## 3. Mandatory preflight

Before editing:

1. Read at least:
   - `AGENTS.md`
   - `README.md`
   - `CMD.md`
   - all files under `.github/`
   - all files under `docs/designs/`
   - all files under `docs/designs/_llm/`
   - `infra/cloudformation/templates/*`
   - `infra/cloudformation/parameters/*`
   - `tests/scenarios/*`
   - `tests/results/*`
   - the filenames and representative contents under `materials/aws/`
2. Inventory the current files and identify old rules that must be preserved, replaced, or removed.
3. Capture a baseline checksum for every file under `materials/aws/`. Use a deterministic sorted SHA-256 manifest. Save the baseline outside `materials/aws/`, under this task’s result directory.
4. Capture baseline checksums for:
   - `infra/cloudformation/templates/*`
   - `infra/cloudformation/parameters/*`
   - `tests/scenarios/*`
5. Confirm from the existing result evidence that the sample web-nginx stacks were deleted on 2026-03-27. Do not treat the IDs currently written in design documents as current deployed resources.
6. Save the complete received task instructions as:

```text
tasks/task-20260726-blueprint-governance-migration/prompt.md
```

Create this task prompt file before making the substantive migration edits.

Do not modify `materials/aws/` at any point.

---

## 4. Root `AGENTS.md`

Replace the current Copilot-oriented `AGENTS.md` with a concise Codex-oriented file. Keep it short and put detailed procedures in `rules/*.md`.

It must define at least:

- This repository is operated by Codex from the repository root.
- An active ChatGPT-created `tasks/<task-id>/prompt.md` is required before changing:
  - `docs/designs/**`
  - `llm/**`
  - `infra/cloudformation/**`
  - `infra/terraform/**`
- The active prompt is the task/change contract, not the long-term design source of truth.
- Human-readable current design is under `docs/designs/`.
- LLM-readable design information is under `llm/designs/`.
- Current post-deploy actual information is under `llm/actuals/<environment>/`.
- `materials/aws/` is read-only and immutable.
- Codex must read the task-relevant files in `rules/` before changing anything.
- Codex must not infer missing resource choices or parameter values.
- Design is updated before IaC.
- Only the IaC engine selected by the task/project is changed.
- No repository-level `REVIEW_PENDING` or manual review stop exists after validate/plan.
- Deploy/apply is allowed only when the active task prompt explicitly permits it.
- Generated ARN values are not persisted as actual values.
- The loop required by the task must run before completion.
- Scenario tests must verify behavior, not only static configuration.
- Evidence is saved under `tests/results/<task-id>/`.
- `AGENTS.md` has a clearly marked project-specific section that projects created from this blueprint must customize, including project name, environments, AWS account/region constraints, and selected IaC engine.

Do not create nested `AGENTS.md` files for this migration.

---

## 5. Create the six rule files

Create exactly these active rule files:

```text
rules/detailed-design.md
rules/llm-design-information.md
rules/cloudformation.md
rules/terraform.md
rules/post-deploy-actuals.md
rules/loop-engineering.md
```

Preserve useful, non-conflicting rules from the old `.github` instructions, but remove Copilot-specific wording, `_llm` paths, manual review gates, and obsolete result paths.

### 5.1 `rules/detailed-design.md`

Define all of the following.

#### File grouping principle

The grouping unit is the human design resource group, not the CloudFormation resource type and not the AWS service namespace.

- Multiple instances of the same resource group are written in the same Markdown file.
- Related child resources may be in the same Markdown file but may use separate headings and separate tables.
- Being in the same file never requires being in the same table.

Use these rules:

| Detailed-design file | Content grouping |
|---|---|
| `vpc.md` | VPC only |
| `internet-gateway.md` | Internet Gateway only |
| `elastic-ip.md` | Elastic IP only |
| `nat-gateway.md` | NAT Gateway only |
| `subnet.md` | Subnet only |
| `route-table.md` | Route Table, Route, and Subnet Route Table Association |
| `security-group.md` | Security Group plus its ingress/egress rules |
| `iam-role.md` | IAM Role and its policies/attachments |
| `instance-profile.md` | IAM Instance Profile |
| `ec2.md` | EC2 Instance, its UserData, and instance-local settings |
| `load-balancer.md` | Load Balancer, Target Group, and Listener; use separate sections/tables as appropriate |
| `s3-bucket.md` | S3 Bucket and Bucket Policy; use separate sections/tables as appropriate |

Do not create empty design files for resource groups not used by the current sample.

#### Table format

Every resource-detail table must use exactly:

```md
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
```

Rules:

- Number rows sequentially from 1 within each table.
- One file may contain multiple resource headings and tables.
- A child component such as a Listener, Route, association, UserData block, or Bucket Policy may have its own table.
- `Property` should use the corresponding `materials/aws` property spelling when it is a configurable AWS property and the mapping is unambiguous.
- Generated values and derived documentation fields may use clear human-readable names even if they do not exist in `materials/aws`.
- Do not include every material field; include only selected and necessary design fields.
- Do not use the IaC template path as if it were an AWS resource property. Put implementation notes in a separate prose section when needed.

#### Links

- Related resources must be Markdown links in the `Value` column.
- Use relative links.
- Use explicit, stable anchors rather than relying only on renderer-generated heading anchors.
- For a resource in another file, use a link such as `[WEBNGINXVPC](vpc.md#vpc-webnginxvpc)`.
- For a resource in the same file, use a link such as `[TG01](#target-group-tg01)`.
- Define a deterministic anchor naming rule and validate all links.

#### Generated values

- Before deployment, a generated current value is shown as `PENDING_DEPLOY`.
- If the desired resource exists but the current environment has been torn down, also show a clear current deployment-state row such as `NOT_DEPLOYED`; do not retain a historical ID as the current ID.
- After deploy/apply, replace `PENDING_DEPLOY` with the current value and cite the task ID in `Source / Comment`.
- After destroy, remove current physical values from the current design, return generated fields to `PENDING_DEPLOY`, and retain old values only in historical evidence.
- Do not create a mandatory separate “Post-Deploy Actual Values” table containing every possible field. Actual values belong in the relevant resource/component table only when needed.

`docs/designs/naming-rules.md` is a project-wide design support document and is not required to use the resource-detail four-column table for all of its reference tables.

### 5.2 `rules/llm-design-information.md`

Define:

- Human-readable design: `docs/designs/`.
- Machine-readable design mirror: `llm/designs/`.
- Machine-readable current actual values: `llm/actuals/<environment>/`.
- `docs/designs/_llm/` is obsolete and forbidden.
- The Markdown design is the human-readable current-design source of truth.
- `llm/designs` is a synchronized machine-readable mirror and must not independently invent or override design values.
- A conflict between Markdown and LLM information is an error; do not silently choose one.
- Use UTF-8 `.properties` files with the basic form:

```properties
<resourceGroup>.<logicalId>.<property>=<value>
```

- Resource references use stable logical references, not physical AWS IDs before deployment, for example:

```properties
natGateway.NATA01.subnetRef=subnet.PUBLICAZ1
routeTable.PUBLICRT01.defaultRouteTargetRef=internetGateway.WEBNGINXIGW
```

- Group LLM files consistently with their detailed-design file:
  - Load Balancer, Target Group, and Listener in `load-balancer.properties`.
  - Route Table, Route, and association in `route-table.properties`.
  - S3 Bucket and Bucket Policy in `s3-bucket.properties`.
- Keep intended design and current actual values separated.
- Do not store generated ARNs in `llm/actuals`.
- Existing/human-provided ARN design inputs may remain in `llm/designs` when needed, such as an AWS managed-policy ARN.
- Update Markdown and the related LLM design information in the same logical change.

### 5.3 `rules/cloudformation.md`

Retain valid current conventions and replace the old review flow. Define:

- CloudFormation is used only when selected by the active task/project.
- Detailed design first, then LLM design information, then CloudFormation.
- No nested stacks.
- Stack/template boundaries are based on change unit, rollback unit, dependency direction, and deploy responsibility, not “one AWS service per template.”
- `1 template = 1 deploy responsibility` remains the default.
- Cross-stack references should expose stable values needed by downstream stacks and avoid unnecessary coupling.
- Use AWS CLI for CloudFormation operations when execution is authorized.
- Run syntax/static checks and `aws cloudformation validate-template`.
- Create and inspect a change set or equivalent change summary before execution.
- There is no `REVIEW_PENDING` state and no mandatory human stop after validation.
- If the active task prompt has `deploy/update` authorized and the change set matches the prompt scope, continue automatically.
- Stop when validation fails, required input is missing, the account/region is wrong, or the change set contains a delete/replacement not authorized by the task prompt.
- After deploy/update, collect only required non-ARN actuals, update design and LLM actuals, run scenario tests, and record evidence.
- A design-only or governance task must not call AWS merely because CloudFormation files exist.

### 5.4 `rules/terraform.md`

Define the Terraform counterpart:

- Terraform is used only when selected by the active task/project.
- One environment is managed by one IaC engine.
- Design first, then LLM information, then Terraform.
- Define locations under `infra/terraform/` for modules and environment composition without generating unused infrastructure in this task.
- Require `terraform fmt -check`, `terraform validate`, and `terraform plan`.
- There is no mandatory human review stop after plan.
- Apply only if the active ChatGPT task prompt explicitly authorizes apply and plan scope matches.
- Stop on unauthorized delete/replacement, wrong workspace/account/region, missing input, sensitive output, or plan failure.
- State files and plan binaries must not be committed. Document remote-state and encryption expectations.
- Do not expose secrets or persist generated ARNs as post-deploy actuals.
- Switching an existing environment between CloudFormation and Terraform is a dedicated migration/import task, not a normal update.
- After apply, update necessary non-ARN actuals, run scenario tests, and record evidence.

### 5.5 `rules/post-deploy-actuals.md`

Replace the old “collect everything” catalog with a selective rule:

- Collect only values needed for follow-up configuration, links, connection, operation, scenario tests, or future task inputs.
- Typical valid examples: VPC ID, Subnet ID, Route Table ID, Security Group ID, EC2 Instance ID, private IP, public IP, DNS name, endpoint address, hosted zone ID when actually required.
- Generated ARN values are excluded from persistent actual-value records.
- ARN values may be retrieved transiently when an AWS API requires them, but do not write them to the detailed design or `llm/actuals`.
- A human-provided/design ARN is not a post-deploy actual and may remain when required.
- Use `PENDING_DEPLOY` before a current value exists.
- Use current physical values only while the resource currently exists.
- On destroy, mark the environment/resource as `NOT_DEPLOYED`, reset generated design fields to `PENDING_DEPLOY`, and leave historical values in task result evidence only.
- Update actuals after every successful create/update/destroy operation, not only initial creation.
- Record task ID, environment, region, collection method, and observation time/date in LLM actual information or its accompanying metadata.
- Never assume old IDs are current based only on an old result file.

### 5.6 `rules/loop-engineering.md`

Define two loops.

#### Local loop

Run after each coherent logical change:

- active task prompt exists
- changed paths are within prompt scope
- `materials/aws/` unchanged from task baseline
- required directory/file structure exists
- `.github/` absent
- `docs/designs/_llm/` absent
- resource design table schema valid
- row numbering valid
- resource grouping valid
- relative links and explicit anchors valid
- design/LLM grouping and references consistent
- no generated ARN persisted in `llm/actuals`
- formatting/static checks pass

#### Full task loop

At task completion:

- run local loop
- run selected IaC validation/plan only if relevant
- perform deploy/apply only if explicitly authorized by the active task prompt
- collect actuals only if a deployment occurred
- update detailed design and LLM actuals
- rerun the local loop
- run scenario tests if infrastructure behavior changed
- save evidence under `tests/results/<task-id>/`
- rerun until success, bounded by the retry rules

Retry/stop rules:

- maximum 3 automatic correction iterations for the same logical failure class
- stop if the same error repeats twice without material progress
- never “fix” a missing human input by inventing a value
- stop on out-of-scope file changes
- stop on unauthorized delete/replacement
- stop if `materials/aws/` differs from the task baseline
- never suppress a failing check to obtain a pass

Explicitly state that the repository’s “no human review after validate/plan” rule is separate from Codex sandbox/OS permission controls.

---

## 6. Remove the old `.github` workflow

After extracting any still-valid rules into the new root `AGENTS.md` and `rules/*.md`, delete the entire `.github/` directory.

Active repository files must no longer depend on:

- `.github/copilot-instructions.md`
- `.github/instructions/*`
- `.github/prompts/*`
- Copilot-specific workflow wording
- `REVIEW_PENDING`, `REVIEW APPROVED`, or `REVIEW REJECTED` as an active workflow
- `docs/test-results/`

Historical result evidence may mention the old workflow if clearly retained as historical evidence. Do not rewrite historical facts merely to hide the old process.

---

## 7. Migrate the existing task prompt

The root `CMD.md` is the historical ChatGPT prompt for the existing web-nginx sample.

- Move it to:

```text
tasks/task-20260327-web-nginx/prompt.md
```

- Preserve its historical body. Add only a short clearly separated metadata note stating that it is a completed historical task created under the superseded workflow.
- Remove `CMD.md` from the repository root after the move.
- Do not use that historical task as authorization for new AWS changes.

---

## 8. Restructure the existing detailed-design documents

Preserve the semantic design of the current web-nginx sample. Do not change its AWS architecture or CloudFormation behavior.

Perform this migration:

### From `docs/designs/vpc.md`

Split into:

- `docs/designs/vpc.md` — VPC only
- `docs/designs/internet-gateway.md` — Internet Gateway only
- `docs/designs/elastic-ip.md` — both EIPs
- `docs/designs/nat-gateway.md` — both NAT Gateways

### From `docs/designs/subnet.md`

Split into:

- `docs/designs/subnet.md` — all Subnets only
- `docs/designs/route-table.md` — Route Tables, Routes, and associations

### From `docs/designs/ec2.md`

Split into:

- `docs/designs/iam-role.md` — IAM Role and its policy attachment
- `docs/designs/instance-profile.md` — Instance Profile
- `docs/designs/ec2.md` — EC2 instances and UserData/bootstrap details

### From `docs/designs/alb.md`

Rename/restructure to:

- `docs/designs/load-balancer.md` — Load Balancer, Target Group, and Listener in the same file, with independent sections/tables

Delete `docs/designs/alb.md` after migration.

### Keep and update

- Keep `docs/designs/security-group.md`; Security Groups and their ingress/egress rules stay in the same file, with separate tables where clearer.
- Keep `docs/designs/naming-rules.md`; update obsolete paths and Copilot references.
- Remove `docs/designs/post-deploy-actual-values.md` after its valid policy is rewritten into `rules/post-deploy-actuals.md`.

### Current-state correction

Existing result evidence says all three sample stacks reached `DELETE_COMPLETE` on 2026-03-27.

Therefore:

- Remove old physical IDs, IPs, DNS names, state values, and generated ARNs from the current detailed-design state.
- Do not present those historical values as current.
- Retain historical values only in the existing result evidence.
- In the current detailed design, add necessary generated fields as `PENDING_DEPLOY` and record the deployment state as `NOT_DEPLOYED` where useful.
- Do not add generated ARN fields.

### Links and tables

- Convert every resource-detail table to the required four-column format.
- Add stable explicit anchors.
- Replace plain logical-ID references with Markdown links.
- Fix all existing broken relative links.
- Preserve prose sections such as purpose, dependencies, implementation responsibility, test viewpoints, and change history where still useful, updating paths and terminology.

Do not add unused material properties merely to make tables longer.

---

## 9. Separate and migrate LLM information

Delete the obsolete `docs/designs/_llm/` directory after migration.

Create:

```text
llm/designs/
llm/actuals/dev/
```

Migrate/split the existing design information into at least:

```text
llm/designs/naming-rules.properties
llm/designs/vpc.properties
llm/designs/internet-gateway.properties
llm/designs/elastic-ip.properties
llm/designs/nat-gateway.properties
llm/designs/subnet.properties
llm/designs/route-table.properties
llm/designs/security-group.properties
llm/designs/iam-role.properties
llm/designs/instance-profile.properties
llm/designs/ec2.properties
llm/designs/load-balancer.properties
```

Rules:

- Preserve intended design values.
- Split resource groups consistently with the Markdown files.
- Use logical references for related resources.
- Do not include stale physical IDs from the deleted deployment in `llm/designs`.
- Do not migrate the old global `post-deploy-actual-values.properties` catalog; its replacement is `rules/post-deploy-actuals.md`.

For the current deleted sample state, create minimal current-state information under `llm/actuals/dev/` that indicates `NOT_DEPLOYED` and the observation/evidence date, without retaining old IDs or generated ARNs. Do not fabricate a timestamp that is not present in the repository evidence; a date is sufficient if only the date is known.

---

## 10. README and repository structure

Rewrite `README.md` to describe the new blueprint accurately.

It must explain:

- ChatGPT + human decide resources.
- ChatGPT uses `materials/aws` to ask only required questions.
- ChatGPT creates `tasks/<task-id>/prompt.md`.
- Codex executes the task.
- Human-readable and LLM-readable design information are separate.
- Detailed design is grouped by the rules above.
- CloudFormation or Terraform is selected per environment.
- `validate / plan` has no repository-level human review stop.
- Deploy/apply occurs only when the active task prompt authorizes it.
- Post-deploy actuals exclude generated ARNs.
- Loop engineering and result evidence are mandatory.
- `materials/aws` is immutable and not exhaustively copied into designs.
- The current web-nginx content is a sample and was torn down; old results are historical evidence.

Show the new directory tree, including `infra/cloudformation/` and `infra/terraform/`.

Create a minimal `infra/terraform/README.md` describing the intended location and rules. Do not generate Terraform resources for the current CloudFormation sample.

---

## 11. Minimal executable loop support

Documentation alone is insufficient. Add a minimal deterministic local validator without third-party dependencies.

Create:

```text
scripts/blueprint-loop.sh
scripts/validate-blueprint.py
```

The exact internal implementation is up to you, but it must be small, readable, and use only the shell plus the Python standard library.

For this migration, support at least:

```bash
bash scripts/blueprint-loop.sh \
  --task-id task-20260726-blueprint-governance-migration \
  --mode local
```

The local validator must check at least:

- active task prompt exists
- required six rule files exist
- `.github/` does not exist
- `docs/designs/_llm/` does not exist
- `materials/aws` matches the saved task baseline manifest
- all resource-detail design tables use the exact four-column header
- `No.` values are sequential within each resource-detail table
- local Markdown links resolve to existing files and anchors
- expected detailed-design/LLM grouping pairs exist
- forbidden stale paths are absent from active files
- no generated ARN is stored under `llm/actuals`

Exclude `docs/designs/naming-rules.md` and historical task/result evidence from table-schema and obsolete-wording checks where appropriate.

Do not create an automatic AWS deploy engine in this migration. `rules/loop-engineering.md`, `rules/cloudformation.md`, `rules/terraform.md`, and future task prompts define full execution commands. The migration validator is the deterministic local foundation.

---

## 12. Preserve existing implementation behavior

The following must remain functionally unchanged in this governance migration:

- `infra/cloudformation/templates/*`
- `infra/cloudformation/parameters/*`
- `tests/scenarios/*`

Do not alter the current CloudFormation resource graph, parameters, outputs, stack boundaries, UserData, security rules, or scenario behavior.

A Target Group ARN may remain as a CloudFormation output or be retrieved transiently by the scenario tests because the ELB API requires it. This does not violate the prohibition on persisting generated ARN as a detailed-design/LLM actual value.

At the end, compare these files to the preflight baseline checksums and fail the task if any functional implementation file changed unexpectedly.

---

## 13. Result evidence

Create:

```text
tests/results/task-20260726-blueprint-governance-migration/result.md
```

Record:

- objective
- files read
- files created
- files moved/renamed
- files deleted
- old rules retained
- old rules intentionally removed
- design grouping migration summary
- LLM migration summary
- loop commands executed
- check results
- materials baseline/final manifest comparison
- implementation baseline/final comparison
- confirmation that no AWS mutation command was run
- known catalog gaps, including any current sample resource that lacks a corresponding `materials/aws` file, without modifying `materials/aws`
- unresolved items, if any

Do not claim success for a check that was not run.

---

## 14. Required verification

Run all applicable checks and include their outputs or summaries in the result file.

At minimum:

```bash
git diff --check
bash -n scripts/blueprint-loop.sh
python3 -m py_compile scripts/validate-blueprint.py
bash scripts/blueprint-loop.sh \
  --task-id task-20260726-blueprint-governance-migration \
  --mode local
```

Also run targeted searches, excluding historical task/result evidence where appropriate, to prove that active files contain no obsolete dependencies:

- no active reference to `.github/`
- no active reference to `docs/designs/_llm/`
- no active reference to `docs/test-results/`
- no active `REVIEW_PENDING` workflow
- no active Copilot execution model

Verify final checksums:

- every `materials/aws/*` file exactly matches the baseline
- CloudFormation templates/parameters exactly match the baseline
- scenario scripts exactly match the baseline

Do not run:

- `aws cloudformation deploy`
- `aws cloudformation update-stack`
- `aws cloudformation execute-change-set`
- `aws cloudformation delete-stack`
- `terraform apply`
- `terraform destroy`
- any other AWS mutation command

---

## 15. Acceptance criteria

The task is complete only when all of the following are true:

1. Root `AGENTS.md` is Codex-oriented, concise, and points to the six rule files.
2. Exactly the agreed six active `rules/*.md` files exist.
3. This prompt exists at `tasks/task-20260726-blueprint-governance-migration/prompt.md`.
4. Historical `CMD.md` is migrated to `tasks/task-20260327-web-nginx/prompt.md` and removed from root.
5. `.github/` is deleted.
6. `docs/designs/_llm/` is deleted.
7. LLM design information is under `llm/designs/` and current actual state under `llm/actuals/dev/`.
8. Resource design files are split/grouped exactly as specified.
9. Load Balancer, Target Group, and Listener are in the same `load-balancer.md`, but may use separate tables.
10. S3 Bucket and Bucket Policy are defined by rule as the same `s3-bucket.md`, but no unused S3 design file is created.
11. Route Table, Route, and association are in `route-table.md`, with separate tables allowed.
12. Every resource-detail table uses `No. | Property | Value | Source / Comment`.
13. Related resources are valid Markdown links with stable anchors.
14. Current design does not present the deleted sample’s old IDs, IPs, DNS names, states, or generated ARNs as current.
15. Generated ARNs are absent from persistent current actual information, while necessary design/API ARN use remains allowed.
16. Active workflow has no human review stop after validate/plan.
17. `materials/aws/` is byte-for-byte unchanged.
18. Existing CloudFormation templates/parameters and scenario scripts are functionally and byte-for-byte unchanged.
19. The local loop validator passes.
20. No AWS mutation was executed.
21. Result evidence is written truthfully.

---

## 16. Final Codex response

Return a concise but complete summary in this order:

1. What changed
2. New repository structure
3. Detailed-design grouping changes
4. LLM information migration
5. Loop implementation and checks run
6. Files deliberately left unchanged
7. Materials checksum result
8. Confirmation that no AWS mutation ran
9. Remaining risks or unresolved items

Do not stop at a proposal. Make the repository changes, run the local checks, and report the actual result.

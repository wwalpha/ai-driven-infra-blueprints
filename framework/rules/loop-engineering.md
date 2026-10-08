# Loop Engineering Rules

Loop engineering is mandatory. “Each change” means each coherent logical change set within the active task, not each editor save.

## Task boundary

[task-contract](task-contract.md) is the authority for contracts, change reservations, stopping, and resuming.

## Unresolved issue gate

Follow [issue-gate](issue-gate.md) for stop decisions, investigation/repair/save-only task exceptions, and rechecks.

## Local loop

The OS-independent entrypoint is `framework/scripts/blueprint-loop.py`. In command examples, `python` means an available Python 3 launcher; use `py -3` on Windows when only Python Launcher is available, or `python3` on Unix-like OSes when only `python3` is available.

Ordinary local loops use `blueprint-loop.py --mode task` to run common checks over the actual repository, design/model checks for services in Validation scope, task type checks, active task Acceptance checks, required framework regression, and both unstaged/staged `git diff --check`. Changes require an active task and valid Task type; do not run task-specific checks when this task's reserved files have no changes. Blocking failure at any layer is FAIL. Common CloudFormation template/parameter file findings retain their existing scan scope; in ordinary task/local validation, only current-task files block completion. Report findings in unrelated files as non-blocking. Global checks (contracts, reservations, Validation scope, required inputs, project/catalog/framework integrity, cross-stack ownership, Acceptance, and failed commands) always block. `--all`, scope `all`, and `--repository-wide-iac` (including full/framework regression dispatch) gate every file finding.

File gating reuses current-worktree Active grants from the selected contract. Managed worktrees additionally reuse their existing pinned lifecycle start-to-HEAD diff plus unstaged/staged/untracked paths, intersected with those grants; commits do not erase task scope, and planned but unchanged files do not enter the gate. For legacy/non-managed contracts without pinned lifecycle metadata, acquired exact Modified files are the stable contract authority, including committed files; Deferred and foreign-worktree grants do not count. Missing/invalid authority remains blocking. Classification occurs when a finding is emitted, without another repository/content scan.

Validate contract Requirement IDs/Acceptance checks on every run according to [Acceptance contract](task-contract.md#acceptance-contract). A partial run with Deferred files reports Active validation and pending path-based Acceptance checks; it retains `running` and cannot authorize final completion. Finish Active work, automatically retry Deferred reservations every 30 seconds for up to 20 attempts, and continue acquired work before the final successful loop and `--complete`. On exhaustion, end cleanly with unfinished Deferred work retained; do not mark failed/completed. Do not repeat validation at every reservation poll. Do not suspend a task solely because a requested file is Deferred; real check failures retain normal suspension behavior.

After each coherent logical change, deterministically confirm the following.

- When changes exist, an active task prompt and valid Task type exist. An unchanged idle state may lack this task's `tasks/<task-name>.md`
- Changed paths are within the Task type boundary and Allowed paths
- `tasks/` contains only contracts in `<task-name>.md` format. Current-worktree running tasks have exclusive Active file reservations, including `issues/**`; overlapping requests remain Deferred and non-conflicting work continues. Foreign-worktree tasks do not affect selection/ownership. In idle state, `tasks/` itself may be omitted
- `framework/materials/aws/` matches `framework/materials/catalog.sha256`
- The Tokyo region CloudFormation provider schema snapshot matches its lock and resolves every property path in `framework/materials/aws/`
- API design catalog/schema fixed snapshots and checksums, selection lists, and CFn-unsupported definitions are consistent. Validate Macie Job types, nested values, conditional requirements, and authoritative models, and reject them in CFn type resolution
- Markdown mapping tables for `bucketDefinitions` Macie Jobs match account, bucket, and order in the same Job's JSON artifact; reject missing/duplicate entries or ownership by a different Job. Do not place fixed bucket mapping tables on `bucketCriteria` types
- `framework/rules/resource-layout.json` holds display policies for all CFn/API catalog resources without omissions or extras, and integrated parents, properties, counts, and identification methods are valid. Reject undecided new resources
- Validate grouped child identification, parent membership, schemas, and references; do not lose multiple KMS Aliases or Alias references from S3
- Required directory/file structure exists
- `project.json` matches environment/target directory paths
- The minimum Markdown structure, resource tables, row numbering, and service-based explicit anchors defined by `framework/rules/detailed-design.md` are valid
- Service ownership, Markdown/model service metadata, and catalog resource type ownership are consistent; resources from different AWS services are not mixed
- Prohibited topology/state file metadata and design decisions, out-of-scope, and generated-values sections are absent
- Resource table `Source / Comment` is written in Japanese
- Resource tables contain no settings outside the properties selection list, and literals satisfy the corresponding CFn provider schema or API design schema type, enum, pattern, length, and range
- Policy properties requiring JSON reference valid JSON artifacts under their owning service and match service model artifact paths
- Each service's policy anchors, owning resources, and all Statement elements or all setting elements match linked JSON, without duplicate persistence of derived displays in models. Omit independent Property, JSON, Version, and Id metadata rows for all policies including IAM. Display trust policy Version in a one-column table only when it exists in JSON, and match it against JSON. Retain formal properties and JSON links in original setting rows, Version/Id in JSON bodies, same-named keys in setting tables, and three-column overviews for all services. Reject missing markers, invalid ownership, and table-only corrections. Registered policy display methods match formal catalog properties and provider schemas
- If Sid exists in IAM inline policy Statements, it is a string of at most 16 characters; excess length has not been automatically corrected
- IAM Role trust policy and inline policy artifacts use semantic filenames based on the Role logical ID and explicit `PolicyName`
- Exactly 1 `IAM.Role.RoleName` row exists with a confirmed non-empty literal. Overview ResourceName, detail headings, anchors, and reference links use RoleName, not substitutes such as Name tags, display labels, role paths, or internal logical IDs
- Property order in resource setting tables matches materials properties line order. Ignore unselected/hidden items and retain array elements and grouped child membership. Retain special display positions for design-only .Name/S3.Region and horizontal SG display; do not use a separate priority order for names/generated IDs
- CREATE `EC2.VPC`, `EC2.Subnet`, `EC2.RouteTable`, and `EC2.FlowLog` have 1 `.Name` row with a non-empty value matching the resource heading identifier
- CREATE `EC2.VPCEndpoint` / `EC2.Instance` have case-sensitive `Tags[].Key=Name` followed immediately by the corresponding confirmed non-empty `Tags[].Value`, matching overview/heading/ordinary reference link display names. Design validation/generation use the common helper to determine requirements and reject display label substitution
- Single standalone resources of a type without a name property generate type-only detail headings and type-derived anchors when no selected Name tag or existing label exists. Distinguish overview headings from detail headings; retain hidden logical IDs and desired/observed separation. Do not save derived type names in labels; reject type-name display for multiple resources of the same type, omitted name properties, or missing mandatory CREATE Name tags
- resourceMode is only CREATE/IMPORT; validate unspecified mode as CREATE. Exempt only IMPORT from framework naming coverage, lower-kebab, and mandatory Name policy; do not fill missing Name tags. Obtain classification and resource numbers from model anchor mappings, without duplicate Markdown comments; retain schema, catalog, reference, row structure, and generated display equality validation
- Cross-service relative links and explicit anchors resolve, and the same references are generated from authoritative models
- Each resource has exactly 1 `CodeBuild.Project.Name` row with a confirmed non-empty literal. Common name validation for design validation/model generation rejects missing, empty, unconfirmed, and duplicate values; Name tags/display labels are not substitutes
- If CloudFormation stack detailed designs exist, validate stack names, template filenames, and parameter filenames, and confirm equality with generated stack models
- No generated ARNs exist in `model/`
- Model service entry indexes and each part are at most 600 lines, without missing parts, invalid references, unregistered parts, or duplicate keys. Validate scope, task boundaries, generation equality, and observed values across all parts as the same service
- Scenario/result structure and metadata are valid
- Formatting/static checks succeed

Task-type-specific checks cannot be omitted from the active task; confirm at least the following.

- `initialization`: `project.json` changes, and target paths and IaC selection are valid
- `design`: Target authoritative model properties change first, and Markdown/JSON artifacts match their deterministic generation results
- `infrastructure`: IaC changes in the `implement` phase; in the `deploy` phase, IaC is unchanged or only reserved files matching controlled repair evidence in the same session change. In the `update` phase, human-changed model properties, generated Markdown, and IaC are in the same diff. In `destroy`, only post-success observed models/generated views/active contract may change; no IaC validation. Scenarios are unchanged in all phases
- `scenario-test`: The scenario and current results for the same target change
- `governance`: Framework files other than the active task change
- `catalog-maintenance`: Catalog files and `framework/materials/catalog.sha256` change
- `migration`: Required outputs other than the active task change

## Validation scope

Place `## Validation scope` in the active task with entries of ``- `<environment>/<target-directory>/<service-id>` ``. Use the alias as target directory when present, otherwise the AWS account ID. Specify services by model file stem (`ec2` for EC2). Stop for environment-only, account-only, or service-only specifications, unknown targets, or missing model/Markdown. Do not infer validation targets from Allowed paths or changed files. Also reject design changes outside scope.

```md
## Validation scope

- `dev/cde/ec2`
- `dev/non-cde/ec2`
- `stg/cde/ec2`
- `stg/non-cde/ec2`
```

`sync-model.py --write` and `--mode task` / `--mode local` / `--mode full` use the same Validation scope. Retain target services from validator through model matching; do not implicitly expand to `--all`. Validate target service models, generated Markdown/JSON equality, catalog/schema, naming, policies, and reference links. Read only anchors, names, and logical/current identifier information needed to resolve reference target links. Do not validate entire reference-target services' schemas, naming, or generated artifacts or count existing out-of-scope design errors such as prod as task failures. Retain task contracts, Requirement/Acceptance, change scope, project topology, catalog/schema snapshot integrity, and framework structure as common checks. Do not fully validate IaC contents or scenarios/results in ordinary design tasks.

Validate multiple targets and multiple services within the same target with at most 4 parallel workers; wait for all workers and aggregate diagnostics in scope order. Parallelize read-only matching after generation candidates are ready; do not multiply target and service worker counts. `--validation-jobs 1` permits serial comparison. `sync-model.py --write` also uses active task scope to avoid generating other services. For an explicit single target/service, `--environment <env> --alias <alias> --service <service-id>` may be used (`--aws-account-id` without an alias).

Framework-only governance/catalog-maintenance/migration may explicitly specify ``- `framework` ``. Validate actual designs for all services only with explicit `--all` or a sole ``- `all` `` Validation scope entry. If scope is missing, stop even in `full`; do not fall back to overall validation. Daily overall validation runs on a separately configured schedule. Do not add overall validation “just in case” after scoped validation.


`framework/scripts/validate-blueprint.py` remains the CLI, ordered runner, cache/worker
coordinator and compatibility entrypoint for selective callers. Its internal `validation/`
modules separate Task/Acceptance state (`task.py`), framework contracts, Project topology/scope,
Model/Design ownership/naming, table/schema checks, overview/link/artifact checks,
CloudFormation/IaC inputs, and Scenario/Result records. Domains receive explicit inputs and
the small `findings.py` collector, never the whole runner. The collector keeps ordered
blocking/global and file-gated findings separate and reads the gate established by Task parsing.
Scenario checks validate records without executing scenarios; a recorded FAIL remains valid.
Shared internal modules conservatively select full regression under `--affected`.

## Validation cache

Ordinary task/local runs save only successful catalog/service results in the OS temporary directory `blueprint-validation-cache` outside the repository and reuse them when content hashes match. `BLUEPRINT_VALIDATION_CACHE_DIR` may specify a destination outside the repository. Include filenames, file sets, SHA-256, Python/OS, all framework inputs (including validator/generator/rule/catalog/schema), project and AGENTS, target model entries/parts, Markdown/JSON, and referenced models/displays in the key. Read reference-target content only for invalidation decisions; do not add out-of-scope service schema validation. Do not decide by mtime alone.

For new inputs, changed contents, added/deleted files, missing/corrupt caches, unknown dependencies, or symlinks, do not reuse successful results; revalidate within explicit scope. Input changes during validation are FAIL; do not save that service's result. Run task contracts, Requirement/Acceptance, issue gates, change scope, project topology, model part structure, scope-wide resource ownership/stack duplication, IaC/deploy safety checks, and Git diff checks every time. Do not infer scope from changed paths or fall back to out-of-scope overall validation. Caches do not replace current AWS values, change sets, plans, or account/region confirmation.

`--fresh` disables successful-result reuse. `--mode full` and `--all` also validate fresh. Within-run-only catalog lists/model rows/path reuse is used even in fresh runs and does not carry over to the next execution. Display reused/executed service counts and include reused validation counts in successful counts. Do not terminate validation exceeding 60 seconds and call it PASS.

## Framework regression

### Windows full regression input guard

- Windows full regression requires human password input before starting validation processes for explicit `full` / `--all`, automatic addition due to framework changes, or `--affected` selections covering all checks. Scoped validation and regression narrowed to a subset by explicit mappings require no input. In staged validation, the snapshot runner uses the same guard. On Windows, stage the current runner/guard and reject dispatch through old entrypoints differing from workspace content.
- The human runs `python -I -B framework/scripts/regression_guard.py --install` at repository root to register a salted PBKDF2-HMAC-SHA256 hash only in the single `.lock` at repo root. Do not use administrator privileges, ProgramData, separate helper installation, or ACL settings. Do not overwrite existing `.lock`.
- Before each full regression, match input against that repository's `.lock`. For absent registration, invalid format, redirect, noninteractive input, mismatch, or canceled input, do not start validation processes or report PASS. Do not pass passwords through chat, arguments, environment variables, or logs or save unlock flags/tokens/authenticated state. Agents must not register/retrieve actual passwords or bypass guards.
- `.lock` is local configuration, not a task artifact; exclude only repo-root `.lock` from validator changed task paths. Carry the same registration into staged snapshots; source `.lock` changes also make final results stale. Do not display actual password/hash registration values in completion reports or logs.
- Copying legacy ProgramData `.lock` to repo root permits use of the same password. The corrected version does not consult ProgramData or delete existing external files. Do not separate it from permissions to change repository files or enable the guard outside Windows.

- Ordinary design, implement, deploy, update, destroy, scenario/evidence, initialization, and target migration use `python framework/scripts/blueprint-loop.py --mode task`. Retain `validate-blueprint.py` inheriting Validation scope, properties/generated Markdown/JSON equality via its service-scoped `sync-model.py`, active task contracts, task-specific checks, and `git diff --check`.
- Tasks changing framework scripts, rules, validators/generators, or common processing use `python framework/scripts/blueprint-loop.py --mode full`. In addition to specified-scope validation, run every `framework/scripts/*.checks.py` with at most 2 parallel workers and aggregate diagnostics/failure lists in name order. Separate only framework-internal regression using fixtures, mocks, and fixed catalog inputs from ordinary tasks.
- Even in `task` / `local`, automatically add all regression when unstaged, staged, or untracked changed paths include `framework/**`, `.agents/**`, `AGENTS.md`, or `README.md`. Include rules, materials (catalog/schema snapshots), future schema/catalog directories, prompts, and distributed skills as well as scripts. Detect deletion/rename sources too. If Git cannot determine changes, stop without omitting regression. Use explicit `full` to revalidate committed changes.
- `--mode local` is also valid as the same scoped validation as `task`. If a skill specifies `local`, that execution suffices; do not require additional `task` / `full`. Explicit `--all` means overall validation plus all regression; `local` scope `all` likewise remains overall validation plus all regression. `full` alone or regression addition due to framework changes does not expand actual design scope.
- Continue regression and diff checks even if the validator fails. Prevent Python optimization from disabling assertions. Failed/unexecuted selected checks are FAIL.
- Retain existing mandatory CloudFormation `cfn-lint`, deploy context, `aws cloudformation validate-template`, change set/change summary, delete/replacement checks, AWS account/region checks, and Terraform fmt/init/validate/plan/apply procedures according to each phase's rules/prompts. The loop does not replace actual IaC/deployment procedures or combine implement and deploy.

## Conflict resolution and reproducible validation

- Launch with `python -X utf8 framework/scripts/blueprint-loop.py --mode task` is recommended. Even under ordinary launch, the runner restarts in UTF-8 mode and passes `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` to child processes. Before validation, confirm Japanese file reads/writes and child process output; do not start regression if this fails. Explicitly specify UTF-8 for text I/O.
- After conflict resolution, stage files to validate and this task's `tasks/<task-name>.md`, then specify `--staged --base <比較元commit>`. Explicitly specify a base commit matching the human's change scope and include incoming changes in the diff against it. Stop on unresolved index conflicts. Ordinary mode continues to validate unstaged/staged/untracked changes.
- Staged mode fixes the base commit, HEAD, and index tree and expands them into an independent Git repository outside the repository to validate that snapshot's runner, contract, and inputs. Do not include original workspace unstaged/untracked files or rewrite the original index. Setting snapshot HEAD to the base makes contracts, changed paths, and diff checks use the same basis. If original HEAD/index tree changes by completion, exit nonzero as stale; do not treat the old tree's result as a PASS for the latest state. This does not lock subsequent edits.
- Explicitly select validation with `--mode task --affected` (`local` is also permitted). This is an exception to ordinary automatic full regression addition; select checks only using the runner's explicit mapping. The mapping covers regression entries, the standalone runner, exact validator test modules, shared test support consumers, and dynamic reference/layout fixture consumers. Unknown files (including siblings in these directories), missing mapped files, and unresolved deletion/rename sources fall back to full regression. Common validators/generators, rules, catalogs and prompts remain full regression. Do not omit merely because changes are incoming.
- `--affected` cannot be combined with `full` / `--all`. Do not omit common validation, task-specific checks, Acceptance checks, or diff checks. Display selection reasons, selected checks, and unexecuted checks. Framework development task completion continues to use `--mode full`.
- Regression fixtures contain only necessary framework inputs and project/task/model generated within tests; do not copy actual consumer issues, projects, models, designs, or active tasks. Compare filesystem paths with `Path`; use `as_posix()` only for contract values requiring POSIX notation such as Markdown links.
- Only independent regression scripts run with at most 2 parallel workers; validators and Git diff checks run serially. `--jobs 1` permits serial comparison. Each check owns its temporary fixture and must not write shared workspaces. Run remaining checks after failure; on interruption, stop running child processes.

## Timing and long-running execution

- Each local loop run creates a `blueprint-loop-*` directory in the OS temporary directory outside the repository and displays its absolute path at start. `--log-dir <repository外のdirectory>` may specify the destination parent. Do not overwrite existing logs on concurrent runs/reruns. OS cleanup applies to temporary directories; specify a destination outside the repository when continued retention is needed.
- With `--profile`, measure `validate-blueprint.py` and its `sync-model.py` child, `model_design.checks.py`, and `design_catalog.checks.py` using stdlib cProfile; save `.prof` and the top 25 cumulative-time entries in check logs in the same run directory. Also specify `--fresh` for cold validation measurement. Examine per-function breakdowns for fixture copying, catalog reading, generation, and validation. Measurement overhead prevents direct comparison with ordinary execution time. Since thread worker internals are absent from main-thread cProfile measurement, use `--validation-jobs 1` for detailed comparisons.
- Incrementally record UTC time, repository, Python launcher, loop/check PIDs, start/end, per-check/overall elapsed seconds, exit codes, and success/failure in `timing.jsonl`. Use monotonic clocks for durations; run all checks after failure. Save check stdout/stderr directly in per-check `.log` and display it in the terminal when the check finishes.
- If a check runs for 30 seconds or longer, display/save its name, elapsed time, and PID in the terminal and `timing.jsonl` every 30 seconds. This is a liveness indication that the child process has not exited, not a progress percentage or guarantee of extending the Copilot session.
- Agents start the local loop only once and track existing run logs/PIDs. Do not restart merely because tool waiting/tracking times out. Do not change repository inputs until checks finish or launch duplicate loops for the same repository. Do not add focused checks/full loops to unchanged unfinished runs.
- On session disconnection, reread the same active task and confirm the log path shown at start. Confirm `loop_end` success/failure, check exit codes, execution of all checks, and unchanged inputs during validation. Missing `loop_end` means incomplete; heartbeats alone are not PASS. Because PIDs may be reused, also match commands and process start times. Rerun the entire loop only if actual processes have exited without completion records. Do not reuse previous PASS if inputs changed.
- If VS Code Copilot command tracking cannot keep up with long execution, the human runs the same local loop in an ordinary terminal and the agent checks saved logs. Follow README procedures to distinguish settings, session errors, and terminal tracking; do not bypass by omitting validation.
- These timing logs are explicitly permitted local diagnostic output for non-scenario tasks; do not save/commit them under `tasks/` or `tests/results/`.

## Design task completion

Before design questions, on resume, target changes, before design contract registration, and before saving, run `check-design-naming.py` for all targets as the start gate in `aws-resource-naming.md`. Do not start/continue design for unregistered rules, empty patterns, read failures, or unexecuted/failed checks; identify missing resource types/properties and stop before model updates. Follow common naming rules for CREATE/IMPORT and explicit exclusion scope.

1. Update authoritative properties in `model/**` specified by the active prompt. Only when existing-resource retrieval is specified, validate read-only AWS context before repository changes and directly reflect differences in selected properties of human-selected resources to current values.
2. For existing-resource retrieval, reflect only necessary non-ARN current identifiers in model observed rows. Do not save secrets, generated ARNs, or resource provenance.
3. Save confirmed design values in the corresponding `model/**` first. Before generation, `framework/scripts/sync-model.py --write` validates schema/catalog mandatory root properties in authoritative properties per service; for deficient services, generate no Markdown/JSON artifacts or policy tables, even temporary files. Retain properties as inputs and report missing resources/properties. Temporarily generate/validate only services with complete required items; save successful services in the same coherent change. Also generate `bucketDefinitions` Macie Job mapping tables from model documents. Retain saved Markdown/JSON for failing services and continue processing other services. If failures remain, do not treat as complete; correct authoritative properties and rerun.
4. Run the local loop.
5. Finish the task without changing IaC, AWS mutation, scenarios, or results.

## Infrastructure task completion

Infrastructure task Task contracts must contain exactly 1 `Infrastructure phase`; only `implement`, `deploy`, `update`, or `destroy` are permitted.

`implement` phase:

1. Using approved design and service models as input, create/change only IaC specified by the active prompt.
2. Perform local static validation with target-region `cfn-lint` for CloudFormation, or `terraform fmt -check`, `terraform init -backend=false`, and `terraform validate` for Terraform.
3. Do not execute AWS APIs, CloudFormation change sets, Terraform plans, deploy/apply, or observed value updates.
4. Run the local loop and finish.

`deploy` phase:

1. Run deterministic preflight with created/validated IaC. Classify failures under [Controlled deploy repair](cloudformation.md#controlled-deploy-repair); minimally repair/revalidate affected units only for AUTO_REPAIRABLE.
2. Confirm scope with `cfn-lint`, `aws cloudformation validate-template`, and change sets for CloudFormation; validation and saved plans for Terraform.
3. If no unapproved delete/replacement exists, deploy/apply only targets authorized by the active prompt. If any exists, explain targets, reasons, impacts, and current execution state and wait for human confirmation; after approval, resume in the same task with the same change set or saved plan.
4. Update model observed values and regenerate Markdown only when successful AWS mutation exists.
5. Run the local loop and finish without proceeding to scenario tests.

`update` phase:

1. Confirm only uncommitted model properties manually edited by the human before task start as immutable intended-design input.
2. Generate Markdown from properties, create/change target IaC, and perform local static validation.
3. Run deterministic preflight and confirm change set/plan scope. For unapproved delete/replacement, wait for human confirmation with an explanation; after approval, resume authorized deploy/apply in the same task with the same change set or saved plan.
4. Update model observed values and regenerate Markdown only after successful AWS mutation.
5. Confirm Codex has not changed the human's intended-design diff; after the local loop, finish without proceeding to scenario tests.

## Infrastructure destroy completion

Infrastructure phase `destroy` is an independent CloudFormation Stack workflow:

1. Resolve local ownership/write paths, reserve them and confirm exact target/account/region/profile/pinned StackIds, protection and nested identity.
2. Validate actual export/import dependencies for the whole scope before any delete.
3. Delete standard stacks in reverse DeployOrder with bounded same-order concurrency; stop starts on failure and drain running stacks.
4. Confirm DELETE_COMPLETE using pinned session evidence; fresh ALREADY_ABSENT is reported separately.
5. Reset only proven deleted stacks' observed identifiers and incoming references to PENDING_DEPLOY, preserving desired inputs.
6. Regenerate affected Markdown/JSON in one batch (partial success permitted, failed/unexecuted unchanged).
7. Run `python framework/scripts/blueprint-loop.py --mode task --task-file <task>` once, then complete only after terminal/sync evidence and PASS.
8. Finish without scenario tests or another task.

Do not require deploy/implement IaC validation in destroy: no cfn-lint, validate-template, change sets, template/parameter/artifact checks, deploy preparation, clean revision check, deploy repair or full infra/framework digest guards. The scoped loop retains model/generated equality, task boundary/reservations, issue, catalog/schema and common checks; it skips IaC validation. Framework implementation changes still require normal full regression.

## Scenario-test task completion

1. Create/update scenario definitions and test implementations specified by the active prompt.
2. Run tests against the AWS account corresponding to the specified environment/target directory.
3. Update the same scenario-scoped current results and stable evidence files.
4. Update results not rerun after scenario changes to `STALE` or `NOT_EXECUTED`.
5. Run the local loop and finish without proceeding to failure remediation or another task.

## Other task completion

- `initialization`, `governance`, `catalog-maintenance`, and `migration` validate only active prompt scope and finish.
- Non-scenario tasks must not save verification output under `tests/scenarios/**` or `tests/results/**`.
- By default, non-scenario task verification results belong only in Codex completion reports.

## Retry and stop

Follow [task-contract](task-contract.md#retry-and-stop) for stopping/retry and authorization scope.

Local loop PASS displays executed Requirement IDs, Acceptance check count, task type, and framework regression script count. Do not treat generic validation results unable to display these as proof of task completion.

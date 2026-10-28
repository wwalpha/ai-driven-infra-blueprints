# Loop Engineering Rules

Validation follows the change classification below. “Each change” means each coherent logical change set within the active task, not each editor save.

## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.

## Task boundary

[task-contract](task-contract.md) is the authority for contracts, stopping, and resuming.

## Local loop

The OS-independent entrypoint is `framework/scripts/blueprint-loop.py`. In command examples, `python` means an available Python 3 launcher; use `py -3` on Windows when only Python Launcher is available, or `python3` on Unix-like OSes when only `python3` is available.

In managed worktrees, replace the launcher in Python examples with
`python3 -B framework/scripts/run-python.py` (use an available Python 3 launcher on Windows).
The wrapper runs the task's registered ready shared Python Interpreter
and sets its CLI PATH for this process
and all children; fresh shells need no activation. Use the same wrapper for standalone
checks/pytest. Failed/stale setup must be recovered
with `worktree_task.py setup --task-id <task-id>` before task execution. Lifecycle helpers
use the ordinary launcher from a surviving checkout.

### Validation policy

This section is the single authority for development checks and final validation across
AGENTS, Skills, Prompts and task completion sections. Their local-loop instructions apply
when the classification requires a loop. Choose from actual dependencies and behavior,
not directory names alone; inspect callers, imports, shared fixtures, registered template
consumers and affected outputs before narrowing. Use the broadest applicable row for a
mixed change. Task contracts, Acceptance requirements, and
phase-specific schema, generation, IaC, AWS and approval checks remain mandatory where
applicable; a lightweight documentation check is not evidence that these runtime checks ran.
Generated design Markdown/JSON is validated with its authoritative Model inputs, not
classified as an independent documentation edit.

| Change | Required final validation |
| --- | --- |
| Markdown, Skill or Prompt text only | `git diff --check`, diff review and necessary reference/description checks; no local loop or regression |
| Isolated test fixture only | Tests consuming that fixture |
| Individual service properties or parts | Target service validation and affected saved-reference consumers |
| Individual module with proven bounded impact | Related tests and validation of the affected scope |
| Shared Framework logic | Dependency-selected UTs and necessary related IT cases; scoped validator |
| Validation infrastructure or execution control | Related selection/runner tests plus scoped validator |
| Unknown impact | Stop for missing dependency evidence; identify related feature tests before validation |

Normal changes use proven callers, imports and fixtures to identify related local tests; sharing a module never by itself requires all IT. Explicit release validation may separately request all UT/IT. During development, run directly related tests first. After a failure and a material fix,
rerun the failed test or affected service; for a fixture fix, run its consuming tests.
Do not run Full after each correction, repeat unchanged results, or retry Full with known
failures left unfixed. If dependencies need investigation, directly invoke the relevant existing UT
`framework/scripts/tests/units/<name>.checks.py` entrypoints or installed pytest test nodes during
repair. CI always runs all UT/IT; local narrowing does not replace a required final Full or prove unknown impact safe.
For bounded final validation, run these tests and the existing Project scoped loop or
standalone scoped validator:

```console
python3 -B framework/scripts/tests/units/<name>.checks.py
python3 -m pytest -q framework/scripts/tests/units/<suite>.checks.py::<test-node>
python3 framework/scripts/validate-blueprint.py --repository-root . --task-file tasks/<task-name>.md
```

Use pytest only for existing pytest suites and an already available dependency; retain
script entrypoints for other suites. The standalone validator uses the contract's explicit
Validation scope; do not add `--all` or `--repository-wide-iac` for bounded checks.
Local regression discovers all UTs; caches, worker counts and validation scope are retained.
Ordinary Project Tasks treat Framework code and definitions as immutable. Deploy does
not scan/hash Framework definitions or compare them at start, mutation, Observed
synchronization, handoff or resume. Task, Model, IaC, ChangeSet, execution evidence and signed journal checks remain required. Task/local
loops do not select UT/IT from Framework Git differences; they validate the Project's
Validation scope and Task Contract. Framework development uses dedicated UT entrypoints,
`run_it.py`, Framework IT CI, or explicit Full. CI changed-file selection and its dependency mapping are removed. Explicit Full uses
`blueprint-loop.py --mode full --task-file tasks/<task-name>.md` once after repairs stabilize;
Full does not expand service scope to `all`.

If final Full fails, identify its direct causes, repair within the active task scope,
and rerun failed tests/affected services first. Re-run Full only after those fixes stabilize;
this is an allowed additional final attempt, subject to existing suspension/resume and
retry/stop rules. A failed, interrupted or stale run is never PASS. If inputs change after
successful validation, reassess the affected dependencies and classification before
integration; do not reuse stale success or repeat Full on unchanged inputs.

For human-authorized multi-phase work, each phase completes changes, targeted checks,
its classified final validation, commit, local-main merge and worktree cleanup before
starting the next authorized phase. Full is normally once per phase when required;
text-only phases use lightweight checks. Do not start an unrequested phase or create
another task merely because validation succeeds. Report executed checks, omitted checks
and classification reasons in the completion response; add no permanent reports/logs.

### Change Validation and Full Model Validation

Model 更新時は **Change Validation のみ**実行する。Full Validation は Issue Scan や独立した明示的全量検証で使用し、更新の停止判定へ混入させない。変更した Resource / Property / Link と、それらが使用・破壊する参照契約を検証し、無関係な既存エラーを更新の停止理由にしない。読み取り依存先、検証対象、生成対象、Task の書き込み権限を区別する。

`validation.change` is the update/save/Task/final-candidate entrypoint. The transient
`model.change_plan` compares only changed service snapshots by logicalId and formal
Property/occurrence. It records changed fields, read dependencies, affected reference
contracts and required Views. Unreadable old authorities retain raw comparison fields;
old Model validity is not a save prerequisite. A missing before snapshot for an existing
persisted Model is an explicit comparison error, never a Full-validation fallback.

`model.validations.full_inputs.check_model_inputs` remains the independent full-quality entrypoint;
Issue Scan explicitly selects `model_validation="full"` and inspects every current
Resource, Property and Link in its requested scope without Task/Git differences or
previous PASS results. The two entries reuse naming, schema, required-property, policy
and reference rules, selecting inputs before execution instead of filtering Full results.

Task/local loops and Task completion use Change Validation. Read-only explicit `full`
loops retain scoped Full Model checks and all UT regression. An independent validator
can select `--model-validation full`; `--all` retains its explicit repository scope.
Full Model validation with `--write` is rejected. Final candidates always use Change
Validation, including when their caller requests regression.

Reference discovery reuses verified, current entries from the signed dependency index.
Missing or stale entries are discovered structurally into invocation-local metadata using
shared raw Model snapshots, without Full quality validation or persistent index writes.
Incomplete reference metadata retains its source, reason and identifiable target/attribute;
stop only when its relationship to a changed producer cannot be ruled out. Unrelated
existing reference quality errors do not block saves. Deploy retains its
sealed-index and Snapshot checks; missing metadata needs no manual update preparation.
Producer reads validate
only the required attributes/context. Read-only producers need no additional write rights
or quality scope. Consumers join generation only when their reference inputs change;
actual changed output paths still require Modified files, Allowed paths and publication
scope. Generation projects the Model without revalidating Model/View quality or requiring
resolved physical values. Unresolved references retain their existing declarations;
Task/path/JSON ownership, Snapshot and publication integrity remain mandatory.
Model save and partial View synchronization have separate
results; incomplete generation does not complete a Task. Snapshot, publication-lock,
input-comparison, atomic-save/rollback and Import/Deploy authority boundaries remain.

### Local loop execution

For ordinary Model edits use one command:

```console
python -X utf8 framework/scripts/blueprint-loop.py --mode task --write --task-file tasks/<task-name>.md
```

Explicit `--write` is passed to the leading validator. It evaluates common preconditions
once, prepares all selected targets in one stage, projects each candidate once using
retained expanded Models, compares consumed input bytes/file sets/the
selected contract once under the publication lock, and saves only changed projected bytes.
Unresolved Issues do not block this generation/publication. Preserve each successful
service's outputs alongside failed services' saved artifacts. Report only technical
generation failures; pending/unresolved Model references do not fail ordinary View
projection. Deploy independently retains strict readiness checks. Common integrity
failures still stop all saves; Model/IaC checks remain required.
It then refreshes Git changed paths once for output-dependent Task conditions and
`changed`/`exists`/`absent` Acceptance. Explicit content Acceptance checks run
independently after successful publication
and never roll back successful Views for quality findings. Unknown check IDs
or undefined execution stages fail before saving. Ordinary generation performs no
post-save quality readback or regeneration. An I/O
failure rolls back only that service; a retained recovery journal safely stops publication.

`--staged --write` and framework-only `--write` are rejected before Model discovery.
`--mode full` does not expand generation scope. On a nonzero integrated validator exit,
start no subsequent UT or Git checks; retain diagnostics and suspend the selected Task.
Read-only loops retain diagnostic aggregation. Without `--write`, the loop and standalone
validator remain read-only; `sync-model.py --write` remains the generation-only
entrypoint. IMPORT's dedicated flow, AWS post-operation verification and independently
invoked validation remain separate purposes. Follow
[Selection and publication](task-contract.md#selection-and-publication) for concurrent editing.

Ordinary local loops use `blueprint-loop.py --mode task` to run common checks over the actual repository, Change Validation for changed inputs and required Views within Validation scope, task type checks, task Acceptance checks, and both unstaged/staged `git diff --check`. Changes require an active task and valid Task type. Blocking failure at any layer is FAIL. Existing checks retain their scan scope and record discovered failures as ordinary errors. `--all`, scope `all`, and `--repository-wide-iac` retain their existing scan-scope behavior.

Validate contract Requirement IDs/Acceptance checks on every run according to [Acceptance contract](task-contract.md#acceptance-contract). Before successful final validation under [Validation policy](#validation-policy) and `--complete`, finish all requested work under [Task transition](task-contract.md#task-transition).

For a selected report-only issues Task, `--mode local` without `--write`, `--all`
or `--staged` uses the existing `issues_save_only()` predicate and explicitly selects
contract-only validation through `run_validation()` and `Validator`. Validate the
Task requirements/Allowed paths/Modified files, running status, explicit service scope,
actual report destinations and file access with the existing Task and save authority
checks. Both `issues.md` and `iac-issues.md` must exist and have exact `exists:`
Acceptance checks. This post-save path does not run generic `check_validation_scope`,
Model/design/display/IaC/AWS checks, Scan, cfn-lint or Git change/diff checks. Missing
Model/design inputs may themselves be the recorded issues. It does not replace or
rerun Snapshot, Review, publication authority or atomic save/rollback checks.
Other Tasks and modes retain ordinary validation; the default Validator is unchanged.

When running a local loop, retain the following checks in its applicable scope. During development and at completion, choose the checks under [Validation policy](#validation-policy).

- When changes exist, an active task prompt and valid Task type exist. An unchanged idle state may lack this task's `tasks/<task-name>.md`
- Changed paths are within the Task type boundary and Allowed paths
- For the explicit service-scoped issues report-only `migration` described in [Snapshot and publication](issues-investigation.md#snapshot-and-publication), use `issues_save_only()` without Git change discovery or diff checks. HEAD/commit, worktree/index/untracked and input changes never stop Issue scan, publication or completion. Retain contract/service scope/Acceptance, whole-target Snapshot coverage and actual output Allowed paths (issues.md and iac-issues.md only; Human confirmations are read-only); never attribute another Task's edits to the Issue Task. Other Tasks retain baseline/commit/input checks.
- `tasks/` contains only contracts in `<task-name>.md` format. In idle state, `tasks/` itself may be omitted.
- `framework/materials/aws/` matches `framework/materials/catalog.sha256`
- The Tokyo region CloudFormation provider schema snapshot matches its lock and resolves every property path in `framework/materials/aws/`
- API design catalog/schema fixed snapshots and checksums, selection lists, and CFn-unsupported definitions are consistent. Validate Macie Job types, nested values, conditional requirements, and authoritative models, and reject them in CFn type resolution
- Markdown mapping tables for `bucketDefinitions` Macie Jobs match account, bucket, and order in the same Job's JSON artifact; reject missing/duplicate entries or ownership by a different Job. Do not place fixed bucket mapping tables on `bucketCriteria` types
- `framework/rules/resource-layout.json` holds display policies for all CFn/API catalog resources without omissions or extras, and integrated parents, properties, counts, and identification methods are valid. Reject undecided new resources
- Validate grouped child identification, parent membership, schemas, and references; do not lose multiple KMS Aliases or Alias references from S3
- Required directory/file structure exists
- `project.json` matches environment/target directory paths
- The minimum Markdown structure, resource tables, row numbering, and saved explicit anchors defined by `framework/rules/detailed-design.md` are valid
- Service ownership, Markdown/model service metadata, and catalog resource type ownership are consistent; resources from different AWS services are not mixed
- Prohibited topology/state file metadata and design decisions, out-of-scope, and generated-values sections are absent
- Resource table `Source / Comment` is written in Japanese
- Resource tables contain no settings outside the properties selection list, and literals satisfy the corresponding CFn provider schema or API design schema type, enum, pattern, length, and range
- Policy properties requiring JSON reference valid JSON artifacts under their owning service and match service model artifact paths
- Each service's policy anchors, owning resources, and all Statement elements or all setting elements match linked JSON, without duplicate persistence of derived displays in models. Omit independent Property, JSON, Version, and Id metadata rows for all policies including IAM. Display trust policy Version in a one-column table only when it exists in JSON, and match it against JSON. Retain formal properties and JSON links in original setting rows, Version/Id in JSON bodies, same-named keys in setting tables, and three-column overviews for all services. Reject missing markers, invalid ownership, and table-only corrections. Registered policy display methods match formal catalog properties and provider schemas
- If Sid exists in IAM inline policy Statements, it is a string of at most 16 characters; excess length has not been automatically corrected
- IAM Role trust policy and inline policy artifacts use semantic filenames based on the Role logical ID and explicit `PolicyName`
- Exactly 1 `IAM.Role.RoleName` row exists with a confirmed non-empty literal. Overview ResourceName, detail headings and reference-link labels use RoleName; anchors retain their saved values, not substitutes such as Name tags, display labels, role paths, or internal logical IDs
- Property order in resource setting tables matches materials properties line order. Ignore unselected/hidden items and retain array elements and grouped child membership. Retain special display positions for design-only .Name/S3.Region and horizontal SG display; do not use a separate priority order for names/generated IDs
- CREATE `EC2.VPC`, `EC2.Subnet`, `EC2.RouteTable`, and `EC2.FlowLog` have 1 `.Name` row with a non-empty value matching the resource heading identifier
- CREATE `EC2.VPCEndpoint` / `EC2.Instance` have case-sensitive `Tags[].Key=Name` followed immediately by the corresponding confirmed non-empty `Tags[].Value`, matching overview/heading/ordinary reference link display names. Design validation/generation use the common helper to determine requirements and reject display label substitution
- Single standalone resources of a type without a name property generate type-only detail headings and saved anchors when no selected Name tag or existing label exists. Distinguish overview headings from detail headings; retain hidden logical IDs and desired/observed separation. Do not save derived type names in labels; reject type-name display for multiple resources of the same type, omitted name properties, or missing mandatory CREATE Name tags
- resourceMode is only CREATE/IMPORT; validate unspecified mode as CREATE. Exempt only IMPORT from framework naming coverage, lower-kebab, and mandatory Name policy; do not fill missing Name tags. Obtain classification and resource numbers from Model logicalId indexes, without duplicate Markdown comments; retain schema, catalog, reference, row structure, and generated display equality validation
- Read-only reference analysis and intermediate leaves report warnings and retain unavailable Views with their generation state; applicable reference-dependent checks that cannot finish are reasoned FAILs. The common final candidate guard rejects missing/ambiguous Resource targets and invalid types/Properties; pending observations and saved-text differences remain warnings. Validate corrected fields and affected reference contracts using only changed-service before/after comparison snapshots in ordinary saves, Task checks/completion and worktree guards. Framework-only changes perform no Model load.
- Each resource has exactly 1 `CodeBuild.Project.Name` row with a confirmed non-empty literal. Common name validation for design validation/model generation rejects missing, empty, unconfirmed, and duplicate values; Name tags/display labels are not substitutes
- If CloudFormation stack detailed designs exist, validate stack names, template filenames, and parameter filenames, and confirm equality with generated stack models
- No generated ARNs exist in `model/`
- Service template entry indexes and each part are at most 600 lines, without missing parts, invalid references, unregistered parts, or duplicate keys. Validate scope, task boundaries, generation equality, and observed values across all parts as the same service
- Scenario/result structure and metadata are valid
- Formatting/static checks succeed

For tasks affecting runtime inputs or behavior, task-type-specific checks cannot be omitted; confirm at least the following. Text-only tasks use the documentation row of [Validation policy](#validation-policy), with contract scope and Required changes reviewed before completion.

- `initialization`: `project.json` changes, and target paths and IaC selection are valid
- `design`: Target authoritative service Model inputs change first, and Markdown/JSON artifacts match their deterministic generation results
- `infrastructure`: IaC changes in the `implement` phase; in the `deploy` phase, deploy does not edit IaC; only exact one-shot verified child commit transitions owned by the current Task may be attributed. In the `update` phase, human-changed authoritative service Model inputs, generated Markdown, and IaC are in the same diff. In `destroy`, only post-success observed models/generated views/active contract may change; no IaC validation. Scenarios are unchanged in all phases
- `scenario-test`: The scenario and current results for the same target change
- `governance`: Framework files other than the active task change
- `catalog-maintenance`: Catalog files and `framework/materials/catalog.sha256` change
- `migration`: Required outputs other than the active task change

## Validation scope

Existing service entrances follow [Model sources](model-templates.md). Source and
observation changes are environment/target/service scoped. Use common properties discovery
and the Change Plan for affected incoming reference contracts. Missing comparison or
dependency inputs are explicit errors; never fall back to target-wide quality checks. Read-only producer discovery never
expands Deployment scope, Allowed paths or AWS permission.

Assemble full properties authority before Model/catalog/schema/view checks. Input guards
retain original bytes, comment-only changes, observation absence, parts sets, project and
actual producer dependencies. Broken authorities stop; stale generated views fail
in generation/synchronization validation and the default shared Validator.
[Issues diagnostics](issues-investigation.md#scope-and-responsibilities) skip Model/saved
Markdown display synchronization and generation equality, retaining saved Markdown
internal consistency and independent Model, reference and design-integrity checks.
Observation writers patch only authorized observed.value in the same properties and
preserve desired/display/reference/placementName. This grants no multi-environment deploy.

Import pins one environment/target/service. Its producer/incoming inputs are read-only;
acquisition/source/display completion runs no design validation or local loop. The LLM
owns service iteration and conversational consent. This exception does not apply to
Framework implementation or ordinary design.

## Validation cache

Do not save warning-bearing or incomplete results as count-only PASS cache records.
Keep their warnings/unverified scope visible on rerun. Reuse normal complete caches
only within the existing invocation input context (or an explicitly caller-owned PassCache
outside that context). Cache instances inside the context share successful results; leaving
it discards them, including when the same instance is used in a later invocation.

Successful catalog/service results are held in memory, never loaded from or saved to
persistent PASS files. There is no trusted complete Framework release identity; restricting
reuse to one invocation prevents a Framework update between executions from reusing an old
PASS without another Framework scan, Git/mtime check or substitute digest. The existing
external cache-directory option remains an in-memory namespace and retains its path guard.
Framework code and distributed definitions are immutable during ordinary Project execution;
Framework development still uses its required checks and fresh providers for definition edits.
Common inputs cover the mutable Project's `project.json`, `AGENTS.md`, `README.md` and
`.agents/` file set. Distribution copies under a separate definitions/runtime root are not
Project inputs. Generation records actual mutable Project bytes, kinds and file sets; it
does not register/re-read immutable Framework files for change detection.
Include filenames, file sets, SHA-256, Python/OS, target model entries/parts, Markdown/JSON,
and referenced models/displays in the key. Read reference-target content only for
invalidation decisions; do not add out-of-scope service schema validation. Do not decide
by mtime alone. Issue scans and report-only Issue validation execute diagnostics without PASS-cache reuse or input-change guards; artifacts retain execution time and confirmed/unverified scope, with no input fingerprint.

For new inputs, changed contents, added/deleted files, missing cache entries, unknown dependencies, or symlinks, do not reuse successful results; revalidate within explicit scope. For ordinary Tasks, input changes during validation are FAIL; do not save that service's result. Issue scans do not stop for input changes and publish no PASS cache records. Run task contracts, Requirement/Acceptance, change scope, project topology, model part structure, scope-wide resource ownership/stack duplication, IaC/deploy safety checks, and Git diff checks every time. Do not infer scope from changed paths or fall back to out-of-scope overall validation. Caches do not replace current AWS values, change sets, plans, or account/region confirmation.

`--fresh` disables successful-result reuse. `--mode full` and `--all` also validate fresh. Invocation-local Model rows and input/path reuse is used even in fresh runs and does not carry over to the next execution.

Process-local AWS Mapping, SDK, Schema and Catalog utilities separately retain static
definitions and full Mapping validation by exact provider/service and SDK, Schema,
Catalog and validation lifetime. They are lazy and single-flight, independent of
`input_scope`, Model inputs, diagnostics and PassCache. Explicit stage aliases use the
surviving source root. Definition edits require a new process or fresh relevant providers;
SDK factories and data-path configuration are fixed when constructing an SDK provider.
Validation/adapter code changes require a new Mapping validation lifetime. Arbitrary
documents passed to `catalog_properties` are always validated. Schema public catalogs
isolate mutable per-resource views from the shared definitions.

Display reused/executed service counts and include reused validation counts in successful counts.
Do not terminate validation exceeding 60 seconds and call it PASS.

Integrated write reuses current-run candidate results rather than service PassCache:
never regenerate or read saved outputs to create a service cache. Catalog uses its
Project key from retained common input bytes; retain a new Catalog PASS only
after the single input comparison succeeds. `--fresh` disables retained PASS reuse, while
current-run deduplication remains active.

## Framework regression

Ordinary `task` / `local` loops, including staged snapshots, do not
automatically run Framework regression for changed files or missing Validation scope.
Explicit `full` / `--all` runs all UTs and no IT, retaining validator scope and safety
checks. Framework development runs related dedicated UTs and necessary
IT cases under Validation policy. CI always runs all tests.

All UT and IT run in [Framework IT](../../.github/workflows/framework-it.yml) on every pull request,
push to `main`/`master`, and manual dispatch, using Python 3.14 and the existing requirements.
Its sole entrypoint is `framework/scripts/tests/run_it.py`. CI has no changed-file or case selection
and no path filters. The existing loop scheduler runs every UT with at most 2 workers,
then the IT runner executes every registered suite; either failure fails the job, and UT
failures do not skip IT.
Existing pytest/direct entrypoints run in independent processes. It continues after suite failures, records PASS/FAIL and duration,
and reconciles runtime verification receipts with `tests/CASES.md`. Missing execution,
skipped pytest bodies, stale registrations and parameter-count mismatches fail the job.
Full IT owns one immutable authored fixture bundle and its cleanup; modifying cases
use independent copies. Git/worktree integration tests validate that
functionality; other tests must not initialize Git/worktree environments unnecessarily. Generation events and before/after content/permission fingerprints
verify initialization counts and shared-fixture integrity. No real consumer Model inputs,
AWS credentials or live AWS resources are required. Do not add an extra Full loop.
Optional manual `baseline_ref` measures before/after once under identical dependencies
and separate fresh caches; normal CI executes only the current revision.
Confirm IT PASS for the current PR revision before merging. Pending, canceled,
unexecuted or failed CI is not completed IT validation. Configure the `Framework IT`
job as a required status check in GitHub branch protection/rulesets; repository files
alone do not enable that setting.

### Windows full regression input guard

- Windows full regression requires human password input before starting validation processes for explicit `full` / `--all` (including `test_*.py`). Scoped validation and regression narrowed to a subset by explicit mappings require no input. In staged validation, the snapshot runner uses the same guard. On Windows, stage the current runner/guard and reject dispatch through old entrypoints differing from workspace content.
- The human runs `python -I -B framework/scripts/regression_guard.py --install` at repository root to register a salted PBKDF2-HMAC-SHA256 hash only in the single `.lock` at repo root. Do not use administrator privileges, ProgramData, separate helper installation, or ACL settings. Do not overwrite existing `.lock`.
- Before each full regression, match input against that repository's `.lock`. For absent registration, invalid format, redirect, noninteractive input, mismatch, or canceled input, do not start validation processes or report PASS. Do not pass passwords through chat, arguments, environment variables, or logs or save unlock flags/tokens/authenticated state. Agents must not register/retrieve actual passwords or bypass guards.
- `.lock` is local configuration, not a task artifact; exclude only repo-root `.lock` from validator changed task paths. Carry the same registration into staged snapshots; source `.lock` changes also make final results stale. Do not display actual password/hash registration values in completion reports or logs.

- When [Validation policy](#validation-policy) requires a scoped loop for design, implement, deploy, update, destroy, scenario/evidence, initialization or target migration, use `python framework/scripts/blueprint-loop.py --mode task`. Retain `validate-blueprint.py` inheriting Validation scope, properties/generated Markdown/JSON equality via its service-scoped `sync-model.py`, active task contracts, task-specific checks, and `git diff --check`.
- Select final regression under [Validation policy](#validation-policy). A required Full runs specified-scope validation and every `framework/scripts/tests/units/**/*.checks.py` and `units/**/test_*.py` through their existing Python script entrypoints with at most 2 parallel workers, aggregating diagnostics/failure lists in name order. Keep regression fixtures, mocks and fixed catalog inputs separate from ordinary tasks. Service parameter and typed service integration contracts run in CI; their split unit cases remain local. Reject an empty regression discovery or empty required service case selection; script counts are not coverage.
- Task/local loops retain Git change discovery for Task boundaries and diff checks, but never use those paths to select Framework UT/IT. Framework changes remain subject to Task Contract and Allowed paths restrictions.
- `--mode local` is also valid as the same scoped validation as `task`, except for the report-only issues post-save contract validation described above. Do not add a redundant task run. Explicit `--all` means overall validation plus all regression; scope `all` alone means overall Project validation without automatic Framework regression. `full` alone does not expand actual design scope. Repository-wide IaC checks remain enabled for explicit `full` / `--all`, not because Framework files changed.
- Continue regression and diff checks even if the validator fails. Prevent Python optimization from disabling assertions. Failed/unexecuted selected checks are FAIL.
- Retain existing mandatory CloudFormation deploy context, `aws cloudformation validate-template`, change set/change summary, delete/replacement checks, AWS account/region checks, and Terraform fmt/init/validate/plan/apply procedures according to each phase's rules/prompts. The loop does not replace actual IaC/deployment procedures or combine implement and deploy.

## Conflict resolution and reproducible validation

- Launch with `python -X utf8 framework/scripts/blueprint-loop.py --mode task` is recommended. Even under ordinary launch, the runner restarts in UTF-8 mode and passes `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` to child processes. Before validation, confirm Japanese file reads/writes and child process output; do not start regression if this fails. Explicitly specify UTF-8 for text I/O.
- After conflict resolution, stage files to validate and this task's `tasks/<task-name>.md`, then specify `--staged --base <比較元commit>`. Explicitly specify a base commit matching the human's change scope and include incoming changes in the diff against it. Stop on unresolved index conflicts. Ordinary mode continues to validate unstaged/staged/untracked changes.
- Staged mode fixes the base commit, HEAD, and index tree and expands them into an independent Git repository outside the repository to validate that snapshot's runner, contract, and inputs. Do not include original workspace unstaged/untracked files or rewrite the original index. Setting snapshot HEAD to the base makes contracts, changed paths, and diff checks use the same basis. For ordinary Tasks, if original HEAD/index tree changes by completion, exit nonzero as stale; do not treat the old tree's result as a PASS for the latest state. Report-only Issue Tasks retain the saved snapshot result without this final Git/input comparison. This does not lock subsequent edits.
- Every regression test uses explicit synthetic project/Model inputs generated in temporary directories within tests, regardless of repository type or active Validation scope. Do not inspect the executing repository's `project.json` or `model/`, including existence checks, test-case discovery and cache inputs. Necessary framework inputs may be used; do not copy actual consumer issues, projects, models, designs or active tasks into fixtures. This rule does not restrict the selected service validation or ordinary import/issues workflows from reading their authorized inputs. Compare filesystem paths with `Path`; use `as_posix()` only for contract values requiring POSIX notation such as Markdown links.
- Only independent regression scripts run with at most 2 parallel workers; validators and Git diff checks run serially. `--jobs 1` permits serial comparison. Each check owns its temporary fixture and must not write shared workspaces. Run remaining checks after failure; on interruption, stop running child processes.

## Timing and long-running execution

- Each local loop run creates a `blueprint-loop-*` directory in the OS temporary directory outside the repository and displays its absolute path at start. `--log-dir <repository外のdirectory>` may specify the destination parent. Do not overwrite existing logs on concurrent runs/reruns. OS cleanup applies to temporary directories; specify a destination outside the repository when continued retention is needed.
- With `--profile`, measure `validate-blueprint.py` and its `sync-model.py` child using stdlib cProfile; save `.prof` and the top 25 cumulative-time entries in check logs in the same run directory. Also specify `--fresh` for cold validation measurement. Examine per-function breakdowns for fixture copying, catalog reading, generation, and validation. Measurement overhead prevents direct comparison with ordinary execution time. Since thread worker internals are absent from main-thread cProfile measurement, use `--validation-jobs 1` for detailed comparisons.
- Incrementally record UTC time, repository, Python launcher, loop/check PIDs, start/end, per-check/overall elapsed seconds, exit codes, and success/failure in `timing.jsonl`. Use monotonic clocks for durations; run all checks after failure. Save check stdout/stderr directly in per-check `.log` and display it in the terminal when the check finishes.
- If a check runs for 30 seconds or longer, display/save its name, elapsed time, and PID in the terminal and `timing.jsonl` every 30 seconds. This is a liveness indication that the child process has not exited, not a progress percentage or guarantee of extending the Copilot session.
- Agents start the local loop only once and track existing run logs/PIDs. Do not restart merely because tool waiting/tracking times out. Do not change repository inputs until checks finish or launch duplicate loops for the same repository. Do not add focused checks/full loops to unchanged unfinished runs.
- On session disconnection, reread the same active task and confirm the log path shown at start. Confirm `loop_end` success/failure, check exit codes, execution of all checks, and unchanged inputs during validation. Missing `loop_end` means incomplete; heartbeats alone are not PASS. Because PIDs may be reused, also match commands and process start times. Rerun the entire loop only if actual processes have exited without completion records. Do not reuse previous PASS if inputs changed.
- If VS Code Copilot command tracking cannot keep up with long execution, the human runs the same local loop in an ordinary terminal and the agent checks saved logs. Follow README procedures to distinguish settings, session errors, and terminal tracking; do not bypass by omitting validation.
- These timing logs are explicitly permitted local diagnostic output for non-scenario tasks; do not save/commit them under `tasks/` or `tests/results/`.

## Design task completion

Before design questions, on resume, target changes, before design contract registration, and before saving, run `check-design-naming.py` for all targets as the start gate in `aws-resource-naming.md`, except for the dedicated `/import` workflow (including `--dry-run`). That workflow uses source/acquisition safety checks and separate display generation; design validation is deferred to explicit issues. Do not start/continue ordinary design for unregistered rules, empty patterns, read failures, or unexecuted/failed checks; identify missing resource types/properties and stop before model updates. Follow common naming rules for CREATE/IMPORT and explicit exclusion scope.

1. Update authoritative environment-specific properties inputs specified by the active prompt. Only when existing-resource retrieval is specified, validate read-only AWS context before repository changes and directly reflect differences in selected properties of human-selected resources to current values.
2. For existing-resource retrieval, reflect only necessary non-ARN current identifiers in observed.row.*.value. Do not save secrets, generated ARNs, or resource provenance.
3. Save confirmed design values in the corresponding properties through Change Validation. New Resources require mandatory root properties; existing Resources select only rules related to changed fields and affected reference contracts. The integrated task loop with `--write` projects the required Views without View quality gates or physical-value readiness requirements. Also generate `bucketDefinitions` Macie Job mapping tables from model documents. Retain saved Markdown/JSON for services whose generation fails and save successful services in the same coherent change. Report Model save and View synchronization separately; unresolved required Views prevent Task completion.
4. Run `python -X utf8 framework/scripts/blueprint-loop.py --mode task --write --task-file tasks/<task-name>.md` once to generate and perform final validation.
5. Finish the task without changing IaC, AWS mutation, scenarios, or results.

## Infrastructure task completion

Infrastructure task Task contracts must contain exactly 1 `Infrastructure phase`; only `implement`, `deploy`, `update`, or `destroy` are permitted.

`implement` phase:

1. Using approved design and service models as input, create/change only IaC specified by the active prompt.
2. Perform the existing local Model/provider-schema and mapping checks with shared CloudFormation decoding, or `terraform fmt -check`, `terraform init -backend=false`, and `terraform validate` for Terraform.
3. Do not execute AWS APIs, CloudFormation change sets, Terraform plans, deploy/apply, or observed value updates.
4. Run the local loop and finish. A deploy-request child uses `worktree_task.py repair-validate` to execute this same scoped task loop, sealing the actual result/dependent-input snapshot for exact parent integration. Keep at most 3 same-child static correction cycles. Handwritten PASS, changed validation inputs and failure-approval integration do not qualify; static PASS alone is not AWS resolution.

`deploy` phase:

1. Run deterministic preflight with validated IaC. Preserve failure and AWS execution state under [Controlled deploy repair](cloudformation.md#controlled-deploy-repair). The supervising LLM hands proven IaC causes to a separate authorized implement Task; deploy never edits IaC. Runtime recovery is independent.
2. Confirm scope with AWS ValidateTemplate and change sets for CloudFormation; validation and saved plans for Terraform.
3. If no unapproved delete/replacement exists, deploy/apply only targets authorized by the active prompt. If any exists, explain targets, reasons, impacts, and current execution state and wait for human confirmation; after approval, resume in the same task with the same change set or saved plan.
4. Update model observed values and regenerate Markdown only when successful AWS mutation exists.
5. Run the local loop and finish without proceeding to scenario tests.

`update` phase:

1. Confirm only uncommitted authoritative service Model inputs manually edited by the human before task start as immutable intended-design input.
2. Generate Markdown from runtime Models, create/change target IaC, and perform local static validation.
3. Run deterministic preflight and confirm change set/plan scope. For unapproved delete/replacement, wait for human confirmation with an explanation; after approval, resume authorized deploy/apply in the same task with the same change set or saved plan.
4. Update model observed values and regenerate Markdown only after successful AWS mutation.
5. Confirm Codex has not changed the human's intended-design diff; after the local loop, finish without proceeding to scenario tests.

## Infrastructure destroy completion

Infrastructure phase `destroy` is an independent CloudFormation Stack workflow:

1. Resolve local ownership/write paths and confirm exact target/account/region/profile/pinned StackIds, protection and nested identity.
2. Validate actual export/import dependencies for the whole scope before any delete.
3. Delete standard stacks in reverse DeployOrder with bounded same-order concurrency; stop starts on failure and drain running stacks.
4. Confirm DELETE_COMPLETE using pinned session evidence; fresh ALREADY_ABSENT is reported separately.
5. Reset only proven deleted stacks' observed identifiers and incoming references to PENDING_DEPLOY, preserving desired inputs.
6. Regenerate affected Markdown/JSON in one batch (partial success permitted, failed/unexecuted unchanged).
7. Run `python framework/scripts/blueprint-loop.py --mode task --task-file <task>` once, then complete only after terminal/sync evidence and PASS.
8. Finish without scenario tests or another task.

Do not require deploy/implement IaC validation in destroy: no cfn-lint, validate-template, change sets, template/parameter/artifact checks, deploy preparation, clean revision check, deploy repair or deployment input guards. The scoped loop retains model/generated equality, task boundary, issue, catalog/schema and common checks; it skips IaC validation. Framework implementation changes follow [Validation policy](#validation-policy).

## Scenario-test task completion

1. Create/update scenario definitions and test implementations specified by the active prompt.
2. Run tests against the AWS account corresponding to the specified environment/target directory.
3. Update the same scenario-scoped current results and stable evidence files.
4. Update results not rerun after scenario changes to `STALE` or `NOT_EXECUTED`.
5. Run the local loop and finish without proceeding to failure remediation or another task.

## Other task completion

- `initialization`, `governance`, `catalog-maintenance`, and `migration` select final validation under [Validation policy](#validation-policy), validate only active prompt scope and finish.
- Non-scenario tasks must not save verification output under `tests/scenarios/**` or `tests/results/**`. Human-run `/model-test` audit logs follow the separate [Task boundary](task-contract.md#task-boundary) exception; offline mock verification still uses temporary directories outside the repository.
- By default, non-scenario task verification results belong only in Codex completion reports.

## Retry and stop

Follow [task-contract](task-contract.md#retry-and-stop) for stopping/retry and authorization scope.

When a local loop is required, its PASS displays executed Requirement IDs, Acceptance check count, task type, and framework regression script count. Do not substitute generic validation for that required evidence. For classifications completed without a loop, confirm their required checks and Acceptance requirements; report that no local loop ran.

## Model-only final integration

Follow [Reference diagnostics](model-information.md#reference-diagnostics). Keep Model
validation and View generation states separate. PENDING_DEPLOY has its own deployment meaning: a valid
logical reference may pass Model validation before its physical value is deployed. Run
all mandatory Change Validation checks, including candidate target, type and attribute
checks; an interrupted or unexecuted mandatory check blocks completion. Preserve pending
warnings and finish required View generation/comparison using the existing PENDING_DEPLOY
projection. Retained or not-generated Views do not prove completion. Invalid references,
unresolved mandatory checks and actual failures block integration. Do not add Full
Validation to Model updates.

The running /update Model-only parent prepares source and generated views, then finalize
creates its private candidate commit and rebases onto latest local base. Run the existing
classified read-only final loop once on that candidate. Pass its immutable in-call
FinalCandidate explicitly through run_loop/run_validation/TaskValidation/import checks;
UT selection, Full guard, Acceptance and whitespace checks all use base→candidate.
The final meaning check runs once in TaskValidation, not again through source/view sync.
Standalone complete retains its own check; integration consumes the successful result
for status and merge without another loop. The validation interval holds no lifecycle
lock. Recheck base, HEAD, clean state and exact permitted status transition before merge.
On FAIL retain candidate/worktree; no auto-regeneration/amend/retry by default.
For model-delete, the explicitly resumed parent may repair and invoke finalization
again, retaining the earlier candidate commit and validating the corrected candidate.
No successful deletion leaf invokes final validation. Require every registered deletion
before commit preparation; merge only after the single parent final check succeeds. Cleanup runs in the
surviving ordinary-Python parent after the registered-runtime child exits.

The same final-candidate composition also applies to an explicit
[Value-preserving Model refactor](task-contract.md#value-preserving-model-refactor).
Its ordinary design save guard verifies source candidates; TaskValidation invokes the
refactor meaning check through require_import_changes on the actual latest-base
candidate. Generation remains the existing path, and independent complete retains its
own check. No second pre-finalize final loop or completion is required. Ordinary Model-only design/update changes also use this final-candidate composition when
the contract forbids AWS and deploy/apply and the declared and actual changes are Model
and generated design files only. Other design tasks retain ordinary integration.

The same Model-only final-candidate composition applies to
[Standalone Model reference retarget](task-contract.md#standalone-model-reference-retarget).
Source saves already prove the complete declared retarget and preservation; final
TaskValidation independently proves latest base→candidate after rebase, without transfer
or deletion requirements. Generation uses existing APIs and does not decide meaning.
Retain classified final validation, exact-HEAD merge checks. Do not add
IT as a requirement of this operation, or automatically regenerate/retry on failure.

## Validation results and Task Acceptance

Final Validation status is exactly PASS or FAIL. PASS requires completion of every
applicable mandatory check and valid logical reference contracts. Invalid input,
exceptions, interruptions, missing dependencies and unexecuted mandatory checks are
FAIL with check_id, scope, concrete reason, known source/Resource/Property, underlying
diagnostics and existing diagnostic IDs. Empty or unspecified reasons are invalid.
An internal not-started check is execution bookkeeping, never a public third status.
Record `metadata.complete` when a handler finishes or exact required child results
prove completion. `started`, PASS alone and execution-suppression flags are not
completion evidence. A complete FAIL remains FAIL. Reuse requires the same candidate
and scope; in-flight reentry is an incomplete FAIL. Aggregate the required children,
including pre-registered, replaced and imported results, without overwriting same-key
failures or inheriting unrelated failures. Do not cache failed or incomplete results.
Register the Task-specific required plan before execution, run its missing checks, and
refuse completion when any required check cannot finish. Inapplicable checks are not
planned; never reclassify a required check merely to avoid failure. Child failures,
interruptions and scopes survive aggregation and candidate changes without overwriting
same-ID results. Duplicate diagnostics do not erase failed check outcomes.

Normal pending_deploy is separate reference information after logical target/type/
attribute validation. Continue required generation, comparison and Policy checks using
the existing PENDING_DEPLOY projection for unavailable physical values. Normal pending
does not defer Views or remove checks/results from the validation plan. Fix a leaked
normal-pending exception at its resolution boundary; an exception that still aborts a
required handler is FAIL, including when pending diagnostics are present. Retained or
unavailable Views are not evidence of completed generation. Required View checks that
cannot execute are FAIL; never discard a failure because it contains pending diagnostics.
Keep service-level partial generation, publication locks and rollback unchanged.

Raw Validation and Task Acceptance are separate. Required corrections and regressions
must be repaired and revalidated to PASS; Human approval cannot bypass them. Only an
unrelated pre-existing Model input FAIL may be excluded from this Task Acceptance after
LLM investigation and the exact Human approval described in
[Task Acceptance exclusions](task-contract.md#task-acceptance-exclusions).
The raw FAIL, reason and ID remain visible. Report raw Validation, required checks,
Task Acceptance, approved out-of-task FAILs and any unapproved FAILs independently.
No global failure allowance, arbitrary skip or automatic path-only exemption exists.

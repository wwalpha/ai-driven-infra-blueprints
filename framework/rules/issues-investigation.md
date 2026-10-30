# Local issues investigation

Model 更新時は **Change Validation のみ**実行する。Full Validation は Issue Scan や独立した明示的全量検証で使用し、更新の停止判定へ混入させない。変更した Resource / Property / Link と、それらが使用・破壊する参照契約を検証し、無関係な既存エラーを更新の停止理由にしない。読み取り依存先、検証対象、生成対象、Task の書き込み権限を区別する。

## Scope and responsibilities

Use `framework/scripts/issues_scan.py` for local diagnostics. Models, designs, IaC,
comparison semantics and AWS resources are read-only. Retain mechanical diagnosis,
all-name review, Model/View validation, current IaC comparison, offline cfn-lint,
masking. Issues uses `check_display=False` without generation equality or PASS-cache reuse.
Do not compare Model/saved Markdown display synchronization or register display-only
differences as Issues, including string/link, link-label and JSON/policy presentation.
Retain saved Markdown internal consistency, valid reference destinations and Resource
identity checks independently of display synchronization. Preserve every actual
diagnostic and its ID in the artifact; ordinary Markdown retains every Issue and its formal ID. Dependent checks that cannot execute
retain their concrete reason and scope as FAIL. Proven pending deployment has its own View generation state. Validate Model inputs and typed references
independently; retain existing Markdown link destination/anchor,
resource identity/ownership/naming, schema, CodeBuild PLAINTEXT policy and Model/IaC
checks. Markdown generation/synchronization and the shared Validator's default
`check_display=True` retain strict equality. Never repair Model/IaC, call AWS, deploy or
start another phase from issues execution.

Reports belong to an environment/target, not an individual service. Discover target
membership from its top-level Model entrances and saved service designs without
loading other service bodies. Scan only Human-authorized services, once. The artifact
records `target_services`, selected `services` and exactly one `service_results`
entry per selected service. Publication requires the selected set to equal target
membership. An explicit `unverified` service result requires a reason; failures stay
visible as processing errors and unverified coverage. Missing services refuse the
entire publication without reading the old reports or expanding investigation.

The report-only `migration` runs in the selected checkout without a worktree.
`issues_save_only()` retains explicit service scope, Allowed paths, Modified files,
Acceptance and Task status checks. After saving, run `blueprint-loop.py --mode local`
with the selected Task and without `--write`, `--all` or `--staged`. This uses the
existing Task and save-authority checks only: require both report files, exact
`exists:` Acceptance checks for both, explicit services, running status, allowed
report destinations and readable files. Do not run generic scope/input-presence,
Model/design/display/IaC checks, AWS, Scan, cfn-lint or Git diff collection/comparison.
Recorded violations and missing Model/design inputs do not fail a valid save contract.
Snapshot/Review and atomic publication guards remain mandatory at save time.
It does not inspect Git changes or watch inputs.
Framework maintenance uses its independent governance/worktree workflow.

## Independent Human confirmations

Before switching a target, the Human must explicitly register required confirmed
facts in `issues/<environment>/<target>/human-confirmations.yaml`. This file is
required even when the list is empty. There is no automatic Markdown migration,
extraction or fallback. Never infer Human facts from naming strings or LLM guesses.
Use the common strict YAML reader; JSON syntax is also valid YAML.

```yaml
version: 2
environment: dev
target: cde
confirmations:
  - id: human-name-1
    service: s3
    fact: Human confirmed the existing bucket name
    scope:
      resource: '001'
      property: S3.Bucket.BucketName
    exceptions:
      - rule: design.service
        diagnostic_id: current-diagnostic-id
        condition: Existing name is allowed for this Resource and Property
    evidence: Explicit Human instruction and its context
```

Every listed field is mandatory; an empty exceptions list is permitted.
IDs are unique, service/environment/target are explicit, scope contains resource and
property as concrete exact identities; `*`, missing and blank identities are rejected.
Each exception has exactly `rule`, `diagnostic_id` and nonempty `condition`: the
Human explicitly permits that condition for that existing diagnostic ID and Rule/Check.
Evidence is nonempty. Unknown fields, duplicate YAML keys and wrong target/version
fail closed. The file contains confirmed facts, scope, exceptions and evidence only;
it never stores Issue history, generated runtime values or a report cache.
Only schema v2 is supported. Report missing or invalid fields and refuse unsupported
data without fallback, automatic migration or deletion of existing Human facts.
Any necessary data switch requires a separate explicitly authorized Task.

Read all confirmations at Scan and review them against current diagnostics. An
exception excludes only a diagnostic whose structured service/resource/property and
Rule/Check match, whose existing ID matches that exception's `diagnostic_id`, and
whose condition was explicitly allowed by the Human. Current reason/evidence must
be nonempty but cannot override identity mismatch or supply missing diagnostic fields.
Identity comparison uses exact existing values, with no guessed aliases or wildcard
expansion. Environment/target come from the validated Scan/Human file. A fact without
an applicable exception cannot suppress a diagnostic. Keep diagnostics with unknown
identities as Issues (or explicitly report a conflict/unverified scope).
Contradiction keeps the diagnostic and records a Human conflict as unverified;
never silently call it resolved. Do not modify or delete a confirmed fact without
Human authorization. New facts require actual Human confirmation and an explicitly
authorized Task file change, not a Review suggestion.

The issues skill reads Human confirmations only. It never rewrites the Human file,
records Issue history, removes related records or writes Review results back to it.
Human fact creation/edit/deletion requires a separately Human-authorized independent
Task with ordinary Task permissions. This workflow adds no Human-file editing API.
Current structured reference diagnostics retain their existing code as Rule, fixed
Resource number from `modelKey` and formal Property only when the Model position
belongs to the diagnosed owner. Cross-Model positions and missing fields stay unknown.

## Diagnostic cause and ownership

Diagnostic.cause_kind is independent of ownership: input_invalid becomes an ordinary
candidate only with a proven selected owner; check_failure remains processing_errors
and unverified; dependency_wait and unclassified remain unverified. Only explicit
InputValidationError and successful rule comparisons prove input violations. Generic
ValueError does not. Model read failures never prove invalid Model contents.
Reference categories retain MODEL_NEEDS_FIX → input_invalid,
FRAMEWORK_UNSUPPORTED → check_failure and unresolved/pending validation → dependency_wait;
validated IMPORT pending_deploy comparison exclusions are unchanged.

Reuse validation.diagnostics.service_scope for canonical single Model/Markdown sources.
Explicit owner/source conflicts, shared or multiple sources and insufficient evidence
require Review; target_path and words in prose never establish ownership. Proven
outside-scope diagnostics remain information and cannot be assigned into selected scope.
Python-proven owners are not submitted for LLM reassignment. cfn-lint retains its
resource-path/Stack-origin ownership proof. Keep ownership evidence and diagnostic IDs
across channels. cause_kind is excluded from Diagnostic.identity; established structured
IDs stay stable. Former string diagnostics gain structured source/check context and new
IDs; old Human exceptions cannot match them by message, guessed Rule or missing identity.

## Commands and complete Review

Apply AGENTS section-reading rules and the issues skill's mandatory naming/display
rules. The following example assumes both named services are the entire target and
Human authorized both. For a smaller requested scope, scan it and report publication
refusal with missing services; do not broaden it automatically.

```console
python3 framework/scripts/issues_scan.py scan --environment dev --target-directory cde --service s3 --service iam --artifact /tmp/issues-scan.json
python3 framework/scripts/issues_scan.py review init --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json
python3 framework/scripts/issues_scan.py review next --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json --limit 20
# Explicit LLM judgment of every returned ID, then write /tmp/issues-batch.json.
python3 framework/scripts/issues_scan.py review submit --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json --submission /tmp/issues-batch.json
python3 framework/scripts/issues_scan.py review status --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json
# Repeat Next / LLM Review / Submit / Status until complete, then:
python3 framework/scripts/issues_scan.py review export --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json --review /tmp/issues-review.json
python3 framework/scripts/issues_scan.py --task-file tasks/save-local-issues.md save --artifact /tmp/issues-scan.json --review /tmp/issues-review.json
```

Register the migration contract before any repository write. Declare all authorized
services and exact report paths, its own Task, Requirement IDs and `exists:` Acceptance.
Keep the read-only Human file out of both path declarations. Complete
final validation under [Validation policy](loop-engineering.md#validation-policy).
Actual validation errors are FAIL, even when diagnostic reports were saved.

Only artifact v6 is supported. Temporary Scan/Review files remain outside the
repository. No old artifact conversion, aliases or alternative partial-result save
API exists. External evidence belongs in the whole Scan's Review `issues`, within
its authorized services; never append partial evidence directly to a target report.

The Review has exactly these keys:

```json
{
  "scan_id": "this Scan ID",
  "reviewed_naming_context_id": "this Scan naming context ID",
  "reviewed_names": ["all Naming IDs other than AUTO_PASS"],
  "reviewed_judgments": ["all judgment IDs"],
  "reviewed_confirmations": ["all Human confirmation IDs"],
  "diagnostic_assignments": {
    "ambiguous diagnostic ID": {"status": "assigned", "service": "service-id", "evidence": "Verified source and Resource"},
    "unresolved diagnostic ID": {"status": "unresolved", "reason": "Shared source has no proven owner"}
  },
  "diagnostic_decisions": [
    {"id": "diagnostic ID", "outcome": "issue", "reason": "Current problem confirmed"}
  ],
  "issues": [],
  "unverified": []
}
```

Scan retains every Naming ID, Provider result, applicable rules and deterministic decision: `AUTO_PASS` (mandatory checks proven), `VIOLATION_CANDIDATE` (evidenced mandatory violation), or `REVIEW_REQUIRED` (evidence missing for an applicable mandatory check). Recommended Pattern differences, optional additions/omissions, unknown optional components and missing source-service guesses alone never require Review. An unresolved mandatory constraint cannot AUTO_PASS.

Review every non-AUTO_PASS naming ID and every judgment/confirmation ID, with no duplicates or sampling. Snapshot and Controller recompute automatic decisions from Scan evidence, reject forged decisions/duplicate IDs and require the exact remaining IDs in `reviewed_names`. Snapshot retains `automatically_reviewed_names` separately; their union with reviewed IDs covers every Scan name. Every Naming entry requires its Scan-generated decision and matching target context; reject incomplete artifacts and require an explicit rescan and Review. Existing machine diagnostics and all Human confirmations remain mandatory even for AUTO_PASS names. Submit
one decision for each current ordinary input violation or owner-assigned input violation.
Assignments cover exactly the owner-ambiguous diagnostic IDs. Python-proven owners require no assignment. Assigned decisions require a selected service and nonempty evidence; unresolved decisions require a nonempty reason and retain their diagnostic ID in unverified. Only input_invalid diagnostics with a proven owner can become ordinary Issues. check_failure remains in processing_errors and unverified; dependency_wait and unclassified remain unverified even after owner assignment. Every ID still requires review. Decisions cover only ordinary input violations and owner-assigned input violations; unresolved diagnostics never become Issues.
`issue` decisions require ID/outcome/reason. `excluded` and `conflict` additionally
require `confirmation_id`, `target: {resource, property}` and current `evidence`.
An exclusion requires the confirmed exception's Rule/diagnostic ID/condition and exact
applicable structured diagnostic scope; Review `target` never supplies missing
diagnostic identity. `issues`
contains additional current LLM findings with service/message and optional relative
source path/positive line, resource/property/rule. Additional Naming Issues use
`rule: "review.naming"`, the exact `naming_item_id`, matching service/resource/property,
`applied_rule`, `violation` and concrete `evidence`. Violation is one of
`required_missing`, `format`, `confirmed_mismatch`, `rule_missing`, or
`provider_constraint`; confirmed mismatches also require `expected` and `actual`.
`format` requires an evidenced applicable mandatory structure or explicit mandatory rule, not recommended Pattern mismatch alone. Confirmed mismatches require a unique, provable component binding; reject invented expected/actual values. Existing diagnostics cannot be duplicated by changing Rule or Source spelling. Inspect required naming IDs and only components present in the applicable pattern. Unknown
semantic components are neither violations nor unverified; never infer their values.
Still report independently verifiable violations and retain CREATE/IMPORT scope.
`unverified` normally contains exactly service/check/reason. For `check: "naming"`,
add `failure_kind` as `input_unavailable`, `read_failure`, or `execution_failure`
and describe the actual incomplete check in reason. Do not claim unexecuted checks succeeded.

## Review Controller

`issues/review_progress.py` manages only Review execution. Scan artifact v6, bounded
`detail --offset --limit`, diagnostic/naming/Human semantics, whole-target Task
checks and report publication remain unchanged. `review init` validates the saved
artifact and indexes all required IDs, excluding recomputed AUTO_PASS names; its bounded response reports section counts and the automatic count. AUTO_PASS names remain in paged Scan detail and never enter individual Naming batches or checkpoint acknowledgements.
Naming Context is partitioned into its target/policy and complete individual rule
materials, without slicing text. The existing `reviewed_naming_context_id` is emitted
only after every such ID has been explicitly reviewed.

All Review commands require external `--artifact` and `--state` files. A schema-1
checkpoint records Scan ID, SHA-256 of the exact Scan artifact bytes, Naming Context
ID, environment/target/services, per-section ID results, one issued Batch and
completion. It is distinct from the final Review JSON. Repeated init reuses only a
valid matching checkpoint. Digest mismatch rejects a different or modified Scan;
it does not inspect live inputs, require freshness, trigger rescan or discard Review.
State reads validate schema/checksum, ID coverage, dependency ordering and recorded judgments.
Dependent final findings may remain as an unconfirmed draft during re-review.

`next --limit 20 --max-bytes 32768` returns `scan_id`, `section`, `batch_id`,
`expected_ids` and complete `items`. It records issuance, never confirmation.
Items carry original masked Scan material, explicit matching Human facts and reference access to other
previously reviewed Human facts. Judgments retain diagnostic ownership evidence and
selected services. No machine IaC record set is added to LLM work.
Naming batches carry shared `naming_context`: complete target/policy plus `rules`
indexed by namespace. Each item's `naming_rule_refs` selects its common/service
namespaces in that same batch. Common rules appear once, and each required service's
rules appear once, even across mixed Resource Types; unrelated rules are omitted.
Check applicability per item within every batch; prior context Review, retrieval or
session memory never substitutes for item Review. Rule text is never summarized.
The full serialized JSON, including shared context and all items, must fit the UTF-8
byte budget. The controller shrinks by whole items, with no text truncation.
If one item cannot fit, it returns `blocked`, ID, reason and required bytes (exit 2),
without advancing that ID. A smaller subsequent next invalidates the previous pending
Batch ID. Retrieve a complete supported batch before judging/submitting it.

The LLM writes a submission with exactly `batch_id`, `section`, `results`:

```json
{
  "batch_id": "Batch ID returned by next",
  "section": "naming",
  "results": [
    {
      "id": "exact returned naming ID",
      "reviewed": true,
      "reason": "Applicable pattern and confirmed fixed components checked",
      "evidence": "Current naming item source/key and applicable rule",
      "issues": [],
      "unverified": []
    }
  ]
}
```

Every expected ID needs an explicit result with all six fields above; reason/evidence
must be nonempty. An ambiguous diagnostic Judgment also needs `assignment` in the
existing `diagnostic_assignments` value format. A Diagnostic result needs `decision`
in the existing `diagnostic_decisions` entry format, including the same diagnostic ID.
Do not add assignment for Python-proven owners. Only assigned input_invalid
Judgments create new Diagnostic Decision IDs; check_failure/dependency_wait/unclassified
and unresolved owners retain existing unverified/processing behavior.
`issues` and `unverified` use the existing Review contracts and may be recorded in
any batch, with final additional-finding confirmation after all decisions. Existing
Review validation functions check assignments, decisions, Naming evidence, Human
exceptions, additions and unverified scope, without a second implementation.

Submit checks the issued Batch/complete ID set, every explicit result and cumulative
Issue consistency before one atomic checkpoint replacement. Invalid batches persist
nothing; identical resubmission is idempotent even after later progress. Different
accepted judgments or stale/partial submissions raise errors, without implicit overwrite.
Each operation reuses the existing thread/process OS publication mutex with the
checkpoint path as an isolated namespace, then reloads the current checkpoint under
that lock. Atomic replacement alone is not concurrency protection. Conflicting
writers are checked against the reloaded pending/result state. The existing OS lock
releases on process exit; no custom persistent lock/history/sidecar is added.

Use explicit correction when a confirmed judgment is wrong or new evidence changes
it. First inspect the exact section/ID, then prepare a replacement from that result:

```console
python3 framework/scripts/issues_scan.py review inspect --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json --section judgments --id diagnostic-id
python3 framework/scripts/issues_scan.py review revise --artifact /tmp/issues-scan.json --state /tmp/issues-progress.json --revision /tmp/issues-revision.json
```

The revision file has exactly these fields:

```json
{
  "scan_id": "original Scan ID",
  "section": "judgments",
  "id": "diagnostic-id",
  "expected_digest": "result_digest returned by inspect",
  "reason": "New source evidence corrects the earlier owner assignment",
  "result": {
    "id": "diagnostic-id",
    "reviewed": true,
    "reason": "Evidence now establishes the assigned service",
    "evidence": "Specific source and Resource ownership evidence",
    "issues": [],
    "unverified": [],
    "assignment": {"status": "assigned", "service": "s3", "evidence": "Verified source ownership"}
  }
}
```

Inspect returns the current full `result` and its `result_digest` without changing
state. Revise requires an accepted Section/ID, matching Scan, nonempty correction
reason and complete result validated by the existing Review validators. Under the
checkpoint mutex it reloads and compares the expected digest before replacing a
different result. Conflicts or invalid input change nothing. An already-identical
result is a no-op for safe retries, even after subsequent progress. The correction
reason is required by the operation; no persistent revision history is added.

After an Owner Assignment correction, recalculate the Diagnostic Decision inventory:
discard only removed diagnostics or decisions whose diagnostic scope changed,
revalidate retained decisions, and leave newly required IDs pending. An evidence-only
assignment change that leaves diagnostic scope unchanged retains its valid decision.
Revalidate all retained results and cumulative Issues/Unverified for every correction,
including Naming and Human Review. These operations correct Review results only;
they cannot modify the Scan's rules, names, Human facts or diagnostics.
Any changed non-final result returns final additional-finding confirmation to pending;
its existing findings remain in the checkpoint as `reviewed: false` and are presented
as `previous_result` by the final Next batch. Re-review and explicitly retain/correct/
remove them in a normal complete Submit. Unrelated confirmed IDs remain accepted.
Revise clears outstanding batch issuance; retrieve the next required batch again.
Export is forbidden while any required ID or final confirmation is pending.

After every correction, continue Next → Review → Submit → Status for the pending
range, then Export again and use only the new Export for Save and post-save Local
Loop. Even a final-section correction that remains complete requires re-export.
An older exported file is not updated by a checkpoint correction and must never be
reused. Do not stop because there are many items; reduce `--limit` when output hits
its cap and continue complete, explicitly judged batches.

`status` reports Scan/scope, each section's total/reviewed/remaining counts, next
section, `complete` and `exportable`. Diagnostic totals are determined from completed
Owner judgments; `pending_dependency` explicitly marks the still-open decision set.
Completion requires all sections, including final additions, plus full validation.
`export --review /tmp/issues-review.json` refuses pending IDs and always calls
`review_snapshot()` before atomically writing exactly the nine-field Review above.
Errors identify the invalid batch/result ID and reason; status/next locate remaining
IDs. Export never writes reports or grants save authority.

Scan diagnostic exit 1/2 is not artifact creation failure: continue Review when a
valid artifact exists, retaining failures and incomplete scope. Output omission calls
for smaller complete batches, never skipped IDs or fabricated acknowledgements.
Persist each judged batch, inspect status on resume and continue pending IDs through
Export, existing Save and post-save Local Loop. Large volume alone is not a stop
condition. For a real blocker report concrete cause, completed counts and pending
scope; preserve checkpoint and Scan. This guarantees retained progress/resumption,
not automatic restart of a platform-terminated agent. Temporary OS files must remain
available; no repository checkpoint, persistent sidecar or history file is permitted.

## Snapshot and publication

Scan → complete LLM Review → validated immutable Snapshot → deterministic Markdown
rendering → atomic replacement. The frozen Snapshot stores serialized values; caller
mutations cannot alter it. Its execution time comes from Scan, never the save clock.
Ordinary Issue IDs are
deterministic from the current service/diagnostic; service headings and numbered
lists retain explicit service ownership and deterministic Issue IDs.

Neither report is read as an input, merged or used for state decisions. All ordinary Issues, unverified scope, processing errors and warnings come from this
Scan/Review only. Keep information in the artifact rather than expanding it in Markdown.
Render notices as concise target/check/reason text with necessary evidence; do not dump
internal JSON or IDs. A processing failure also recorded as unverified appears once under
processing errors, retaining incomplete status. Warnings remain non-numbered. A zero Issue count with incomplete coverage says検証未完了. Warning
sections remain separate from ordinary numbered Issues.
The generated reports hold no confirmed Human facts as authority and no old IDs,
resolved history, service blocks or verification-target restoration metadata.

Reuse `iac_report()` and the one existing aggregation/index. No second scan,
comparison, lint or regrouping occurs during publication. The same Snapshot renders
the same bytes. Under the shared publication lock, validate running Task and actual
destination paths, then use the common atomic-files transaction for only issues.md
and iac-issues.md. Old bytes are held only for rollback. Any failed
replacement restores all outputs, including a replacement that failed after rename.

Do not fingerprint inputs, compare Git/bytes/file sets, reject input changes or
trigger automatic rescan/review. Keep execution time and confirmed/unverified scope.
Concurrent edits during generation/validation/publication remain prohibited by the
repository operating rule. An explicit future Scan requires its own full Review.

## Input reuse and report detail

Keep invocation-local Model parsing, actual parts/keys/source lines, shared catalog,
schema and expression evaluator. Scan executes read-only service checks without PASS
cache reuse and retains independent diagnostics when Views/services fail. No persistent
snapshot cache, nested parallelism or service subagents. Evidence paths and positive
lines remain Scan-time data; publication does not reread Model/IaC/design sources.
Keep 4-worker maximum and cfn-lint's isolated workers.

The v6 artifact retains complete compact Issue IDs/category/cause/action/repair target/member
counts and its existing bounded overview (16 groups / 10 examples / 10 fields / 160 characters).
Ordinary Markdown retains all Issues, formal Issue IDs, Service H3 headings and evidence;
there is no count limit or display-synchronization-specific diagnostic expansion.
IaC Markdown retains Scan time/scope/status, every nonzero Issue classification count,
record category counts and the dedicated PENDING_DEPLOY exclusion count. Omit zero
categories and empty sections/tables. Show at most 20 compact Issues in existing
report_order, with ID/classification/target/problem only, and omission counts only when
needed (表示20件／全1194件／省略1174件). Do not present repair direction, actions,
field/Condition/value details, deferred examples or CLI instructions in normal Markdown.
Omitted Issues remain unresolved; display limits never change counts or repair scope.
Retrieve all Issues with `detail --section iac_issues --offset 0 --limit 50`, then fetch
members with `detail --section iac --issue-id ISSUE-<id> --offset 0 --limit 50`; page
until total is covered. If the temporary artifact is unavailable, a separately authorized
new Scan and complete Review may be needed. Add no persistent sidecar.
Do not reaggregate or paste the entire report into chat.

## Comparison coverage

Desired properties are authoritative. Do not use observed/generated Markdown bodies for IaC comparison. Use CloudFormation formal catalog types, `cfn-logicalId`, stack models, per-stack parameters, and target context. Only explicit `cfn-logicalId` and declared Stack mappings establish CREATE correspondence; do not infer unconfirmed mappings. Read only reference-target model information for external services; do not expand investigation scope.

Supported scope: literals, values with confirmed schema types, nested objects/ordered arrays, JSON documents/policies, Ref/GetAtt resource identities and attributes, parameters/defaults, Condition/If/Equals/And/Or/Not, parameter/pseudo-only Sub/Join, Select/Split/FindInMap, formal independent children, and inline children with unique parent Refs. Retain formal conversion of model `.Name` to Name tags and exclusions such as S3.Region/identifier outputs. Unselected settings present only in IaC are not violations. Tag arrays use formal key matching. IAM policy Statement arrays and ManagedPolicy role attachments compare without order while retaining duplicates; other arrays retain order and duplicates. ManagedPolicy Roles includes proven attachments through same-stack Role.ManagedPolicyArns. CodeBuild environment references require the explicit variable Type and a supported producer contract; secret selectors and KMS aliases retain their identity. Compare the whole object/document when specified as a whole.

The repaired local KMS comparison contracts are limited to Athena WorkGroup result encryption
(`KeyArn`, `KeyId`, or `AliasName`), Logs LogGroup `KmsKeyId`, Glue SecurityConfiguration S3/CloudWatch
`KmsKeyArn`, and CodePipeline ArtifactStore encryption key ID (the latter three accept
`AliasArn` only). Check both Model and IaC forms before comparing values. A prohibited
form is a difference even on both sides; different forms are never equivalent. Keep
same-form physical values unconfirmed when local inputs cannot prove them. Alias ARN
derivation uses the explicitly mapped alias name and its owning stack context, not a
fictional CloudFormation Alias GetAtt attribute. This does not apply new KMS rules to
other services, IAM permission resources, or arbitrary CodeBuild environment strings.
Local ARN comparison also supports explicitly named Logs LogGroups, CodeBuild Projects,
and default-bus EventBridge Rules, including concrete Sub/Split/Select expressions.
SQS QueuePolicy Model GetAtt resolves only through its current stack's validated resource
mapping and supported attributes; missing/inactive resources and cross-stack guesses
remain uncompared. These local contracts do not enable AWS or deployment evaluation.

Uncompared: Terraform (no existing reliable local mapping/evaluator), Transform, ImportValue whose approved handoff cannot be proved locally, unknown attributes/nonunique mappings, unsupported expressions, and unconfirmed values/types. This is not a configuration marking all resources unsupported. IMPORT itself is not generated; absent IaC is not missing. Explicit missing CREATE templates/resources/properties are non-blocking differences. Input syntax/read/save failures are errors, not success.

Keep the comparison categories distinct: `deferred` means reference comparison is on hold; `excluded` means outside the current comparison; `uncompared` means reference resolution/comparison could not complete; `error` means a processing/evaluation failure. Retain existing supported local IMPORT resolution paths. Where validated producer/receiving contracts reach the IMPORT handoff check, select the phase from authoritative observations (not rendered labels):

| Authoritative observation | phase | category |
| --- | --- | --- |
| Identifier observation absent | `unobserved` | `deferred` |
| Identifier observation is `PENDING_DEPLOY` | `pending_deploy` | `excluded` |
| Identifier observation exists and passes identifier validation, but approved handoff is still required | `awaiting_handoff` | `deferred` |

Invalid identifiers/contracts retain their existing uncompared/error classification; they are not normal waits. All six record categories (`matched`, `difference`, `deferred`, `uncompared`, `error`, `excluded`) remain in the v6 artifact and record counts. Only difference/uncompared/error records enter `iac_issues` and Issue category counts; deferred/excluded records have no Issue ID. `iac_status` priority is error → partial (uncompared or deferred) → differences → complete match → no compared records. Deferred is partial, never matched or complete. `pending_deploy` requires no comparison at present: it contributes neither uncompared/deferred nor partial/repair-required status; excluded-only scope is no compared records, not equality.

Normal Markdown shows `PENDING_DEPLOY（比較対象外）` as a dedicated count, separate from the Issue category `CFn非対応・比較対象外`; it omits these excluded records' causes and details. Deduplicate parent/child propagation by consumer service/resource and structured cause for this count; raw excluded record counts remain separate. Retrieve retained causes through `detail --section iac --record-category excluded`; use `--record-category deferred` for deferred records. These record filters cannot be combined with Issue category/ID filters. Deferred/excluded alone do not create ordinary issues or fail scan validation; retain independent ordinary diagnostics, unverified scope and processing errors.

## IaC report grouping and publication

Aggregation runs once over finished comparison records, using dictionaries and deterministic keys. A missing file groups by environment/target, structured cause kind, missing path, and action. Direct missing-template diagnostics and propagated `export-search-incomplete` metadata share that action; these prove comparison search interruption, not direct producer/consumer dependency. Different missing inputs remain separate. Selected direct setting differences group by template, Stack, service/resource/property, difference kind, and response; uncertainty is never merged by prose similarity. Proven missing-template/parameter input actions retain 要対応 / 入力修正; missing inputs that only interrupt reference search remain 比較未完了, without confirming a setting difference. A shared missing-input group retains the direct proven action when it also has unresolved dependent members. Condition-disabled CREATE with unconfirmed design intent remains 要判断. Unresolved Export/Import remains 比較未完了, processing failures remain 処理エラー and unknown difference causes remain 原因未確定; do not promote every difference record to 要修正. CFn非対応・比較対象外 remains unchanged. Investigation statuses and unresolved members do not establish equality or completion.

All comparison records (including matched/excluded), unchanged `iac_key` identities, masked field-display information and deterministic Issue-to-record membership belong to the execution's temporary artifact outside the repository. `iac_issues[].members` indexes the original `iac` list. `detail` retrieves category/Issue filters before offset/limit pagination without source reads or comparison. No persistent sidecar, embedded JSON, record restoration, old-result merge, or Markdown digest check.

`iac-issues.md` is replaced from the current valid artifact only. Never restore old results, human annotations, embedded JSON or out-of-scope Services. Existing `iac-issues.state.json` is ignored even if stale, malformed or inconsistent; do not read, write, migrate or automatically delete it. Do not replace state with another persistent file/cache. Only the two Markdown reports belong to the indivisible save batch; the Human file is read-only. Preserve destination authority, atomic writes and rollback of all outputs on failure. Saving performs no comparison, lint, full regrouping or input freshness checks. Ordinary CREATE/IMPORT logic remain unchanged.

## Offline cfn-lint and coverage

`issues.cfn_lint` plans independently of comparison success and decoded documents. CREATE/default Resources with explicit logical ID and declared Stack contribute raw templates; explicitly selected cloudformation-stacks contributes declared templates. IMPORT/API-only/Terraform are not_applicable. Missing or ambiguous mappings remain unverified without guessed files. Missing explicit templates are input_missing; malformed templates retain raw lint; missing, invalid or unsafe Stack parameter files leave that Stack unverified without stopping other Stacks. Reference-discovered outside templates do not expand the plan. Pass the Stack Model parameter JSON to cfn-lint and retain the parameter-applied run, excluding the additional raw default-value run. Deduplicate by canonical template and parameter paths, requested target region and lint policy, retaining every origin.

`utils.cfn_lint` confines cfn-lint private APIs to its adapter. A single imported helper forks a fresh child per deduplicated template; Windows uses a new Python process. Always reap helper/child, distinguish timeout/abnormal exit/protocol failure, continue independent jobs, and mark remaining jobs not_run when common schema/runtime is unavailable.

Use ConfigMixIn with explicit region/template/Stack parameter file/JSON format, validate conflicts, check effective template selection before Runner.run, and consume its iterator incrementally. Honor HOME/cwd rc precedence, Metadata, merge/rule configuration, parameters and suppression. Record requested/effective regions and effective config fingerprint. Do not invoke Runner.cli, stdin fallback, configured output_file, graph/update/output modes or lint_all batch assumptions. A missing runtime or unavailable required API is a processing error. Record the installed version without rejecting it solely by version number. Do not silently change requirements or deploy policy.

Keep requested/effective regions, configuration provenance and job coverage. Issue scans
do not aggregate lint dependency hashes/file sets or compare them between jobs, at scan
completion or before saving. Provider prerequisites are checked before access; child-only
offline replacements prohibit provider update/download and network access without editing
the installed package. Never persist config/parameter/secret bodies.

A known provider mapping whose schema cannot be read/parsed/constructed is a processing error even when the library absorbs its chained loader exception and yields no matches. Keep acquired matches and incomplete coverage; unknown types and intentional override exclusions retain their ordinary diagnostic provenance.

Normal Error is an ordinary candidate only when ownership is proven. E0000 is ordinary only with concrete parser/scanner/CfnParse/JSON/Unicode/root-type provenance from observing existing YAML/JSON loader calls; keep fallback and Match construction unchanged. I/O/internal/unproven decode failures are processing errors, including suppressed failures. E0001 defaults to processing (transform cause unproven); E0002/E0003, unknown severity and protocol/launch/timeout failures are processing. Iterator completion does not prove downstream rules ran; retain suppressed decode and transform coverage as unverified without promoting suppressed input diagnostics to exit 1/2. Warning/Informational remain separate non-numbered channels and remain outside ordinary numbered issues.

Use diagnostic Resources/logical-ID paths plus explicit origins to prove one selected owner. Common/multiple/unknown owner Errors require judgment and explicit diagnostic_assignments; selected cloudformation-stacks may own common errors. Proven outside-resource findings remain scope-external diagnostics. Never assign to the first service by convenience or confuse a scope-wide failure with an outside resource finding. Retain Rule ID, severity, path, position and provenance. Merge NoEcho defaults/effective parameters and known comparison/Model secrets into redaction before final artifact construction; malformed decode text is withheld. Mask before shortening; reports/detail never restore secret text.

## Status, output and measurements

validation_status priority is ERROR (processing, including IaC category=error), FAIL (selected ordinary or unassigned Error), INCOMPLETE (required mechanical/lint checks unexecuted), CHECKED. Keep review_required, iac_status and lint coverage separate. Differences/uncompared only affect iac_status; not_applicable is never lint PASS. Error plus downstream-unexecuted coverage remains FAIL plus incomplete coverage; independent processing errors take ERROR precedence. Separate stage-error counts from affected IaC record counts.

scan exit: processing/input failure 2; ordinary/unassigned Error 1; otherwise 0. Coverage-only/Warning/Info/IaC differences alone do not raise the code. Save errors in authority/review/I/O return 2; successful publication returns 2 when the artifact has processing errors, otherwise 0 even with ordinary issues. stdout includes publication_status=SAVED and validation_status. The save API reports
post_save_validation_execution=NOT_STARTED and post_save_validation_command; it never claims Local
Loop PASS before execution. Record the actual subsequent Local Loop PASS/FAIL separately.
SAVED with Scan FAIL and post-save contract PASS is valid; SAVED with processing errors
still exits 2. Save/CHECKED/exit 0 never means AWS equality or all-range PASS.

warnings/information/unverified/processing_errors summaries expose total, at most five masked/brief previews, omitted counts and paged detail; code lists are bounded. Retain artifact overview limits and external all-Issue/all-member retrieval; normal IaC Markdown lists at most 20 Issues, while ordinary Markdown lists all Issues. Metrics separate mechanical, IaC comparison, aggregation and lint. runner wall_seconds ends after aggregation and excludes CLI JSON/output and LLM time; outer process wall time is a separate measurement. No unmeasured project speedup or worker/default changes.

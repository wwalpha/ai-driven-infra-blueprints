# Local issues investigation

## Scope and responsibilities

Use `framework/scripts/issues_scan.py` for local diagnostics. Models, designs, IaC,
comparison semantics and AWS resources are read-only. Retain mechanical diagnosis,
all-name review, Model/View validation, current IaC comparison, offline cfn-lint,
masking. Never repair Model/IaC, call AWS, deploy or
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
Acceptance and Task status checks. It does not inspect Git changes or watch inputs.
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

## Commands and complete Review

Apply AGENTS section-reading rules and the issues skill's mandatory naming/display
rules. The following example assumes both named services are the entire target and
Human authorized both. For a smaller requested scope, scan it and report publication
refusal with missing services; do not broaden it automatically.

```console
python3 framework/scripts/issues_scan.py scan --environment dev --target-directory cde --service s3 --service iam --artifact /tmp/issues-scan.json
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section naming_context
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section naming --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section judgments --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section human_confirmations --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section ordinary --offset 0 --limit 50
python3 framework/scripts/issues_scan.py --task-file tasks/save-local-issues.md save --artifact /tmp/issues-scan.json --review /tmp/issues-review.json
```

Register the migration contract before any repository write. Declare all authorized
services and exact report paths, its own Task, Requirement IDs and `exists:` Acceptance.
Keep the read-only Human file out of both path declarations. Complete
final validation under [Validation policy](loop-engineering.md#validation-policy).
Actual validation errors are FAIL, even when diagnostic reports were saved.

Only artifact v5 is supported. Temporary Scan/Review files remain outside the
repository. No old artifact conversion, aliases or alternative partial-result save
API exists. External evidence belongs in the whole Scan's Review `issues`, within
its authorized services; never append partial evidence directly to a target report.

The Review has exactly these keys:

```json
{
  "scan_id": "this Scan ID",
  "reviewed_naming_context_id": "this Scan naming context ID",
  "reviewed_names": ["all naming IDs"],
  "reviewed_judgments": ["all judgment IDs"],
  "reviewed_confirmations": ["all Human confirmation IDs"],
  "diagnostic_assignments": {"ambiguous diagnostic ID": "service-id"},
  "diagnostic_decisions": [
    {"id": "diagnostic ID", "outcome": "issue", "reason": "Current problem confirmed"}
  ],
  "issues": [],
  "unverified": []
}
```

Review every naming/judgment/confirmation ID, with no duplicates or sampling. Submit
one decision for each current ordinary or service-ambiguous Error diagnostic.
Assignments cover exactly those ambiguous Error IDs, with a selected service.
`issue` decisions require ID/outcome/reason. `excluded` and `conflict` additionally
require `confirmation_id`, `target: {resource, property}` and current `evidence`.
An exclusion requires the confirmed exception's Rule/diagnostic ID/condition and exact
applicable structured diagnostic scope; Review `target` never supplies missing
diagnostic identity. `issues`
contains additional current LLM findings with service/message and optional relative
source path/positive line, resource/property/rule. `unverified` contains current
LLM limitations with exactly service/check/reason. Report missing knowledge as
unverified coverage; do not invent a defect or claim unexecuted AWS checks succeeded.

## Snapshot and publication

Scan → complete LLM Review → validated immutable Snapshot → deterministic Markdown
rendering → atomic replacement. The frozen Snapshot stores serialized values; caller
mutations cannot alter it. Its execution time comes from Scan, never the save clock.
Ordinary Issue IDs are
deterministic from the current service/diagnostic; service headings and numbered
lists retain explicit service ownership and deterministic Issue IDs.

Neither report is read as an input, merged or used for state decisions. All ordinary
Issues, information, unverified scope, processing errors and warnings come from this
Scan/Review only. A zero Issue count with incomplete coverage says検証未完了. Warning
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

IaC retains complete compact Issue IDs/category/cause/action/repair target/member
counts and the existing 16 detail groups / 10 examples / 10 fields / 160 characters
limits. Fetch every member from the same external artifact with `detail --section
iac --issue-id ISSUE-<id> --offset 0 --limit 50`; page until total is covered. These
limits constrain display, never classification, counts or subsequent repair scope.
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

Invalid identifiers/contracts retain their existing uncompared/error classification; they are not normal waits. All six record categories (`matched`, `difference`, `deferred`, `uncompared`, `error`, `excluded`) remain in the v4 artifact and record counts. Only difference/uncompared/error records enter `iac_issues` and Issue category counts; deferred/excluded records have no Issue ID. `iac_status` priority is error → partial (uncompared or deferred) → differences → complete match → no compared records. Deferred is partial, never matched or complete. `pending_deploy` requires no comparison at present: it contributes neither uncompared/deferred nor partial/repair-required status; excluded-only scope is no compared records, not equality.

Normal Markdown shows `PENDING_DEPLOY（比較対象外）` as a dedicated count, separate from the Issue category `CFn非対応・比較対象外`; it omits these excluded records' causes and details. Deduplicate parent/child propagation by consumer service/resource and structured cause for this count; raw excluded record counts remain separate. Retrieve retained causes through `detail --section iac --record-category excluded`; use `--record-category deferred` for deferred records. These record filters cannot be combined with Issue category/ID filters. Deferred/excluded alone do not create ordinary issues or fail scan validation; retain independent ordinary diagnostics, unverified scope and processing errors.

## IaC report grouping and publication

Aggregation runs once over finished comparison records, using dictionaries and deterministic keys. A missing file groups by environment/target, structured cause kind, missing path, and action. Direct missing-template diagnostics and propagated `export-search-incomplete` metadata share that action; these prove comparison search interruption, not direct producer/consumer dependency. Different missing inputs remain separate. Selected direct setting differences group by template, Stack, service/resource/property, difference kind, and response; uncertainty is never merged by prose similarity. Proven missing-template/parameter input actions retain 要対応 / 入力修正; missing inputs that only interrupt reference search remain 比較未完了, without confirming a setting difference. A shared missing-input group retains the direct proven action when it also has unresolved dependent members. Condition-disabled CREATE with unconfirmed design intent remains 要判断. Unresolved Export/Import remains 比較未完了, processing failures remain 処理エラー and unknown difference causes remain 原因未確定; do not promote every difference record to 要修正. CFn非対応・比較対象外 remains unchanged. Investigation statuses and unresolved members do not establish equality or completion.

All comparison records (including matched/excluded), unchanged `iac_key` identities, masked field-display information and deterministic Issue-to-record membership belong to the execution's temporary artifact outside the repository. `iac_issues[].members` indexes the original `iac` list. `detail` retrieves category/Issue filters before offset/limit pagination without source reads or comparison. No persistent sidecar, embedded JSON, record restoration, old-result merge, or Markdown digest check.

`iac-issues.md` is replaced from the current valid artifact only. Never restore old results, human annotations, embedded JSON or out-of-scope Services. Existing `iac-issues.state.json` is ignored even if stale, malformed or inconsistent; do not read, write, migrate or automatically delete it. Do not replace state with another persistent file/cache. Only the two Markdown reports belong to the indivisible save batch; the Human file is read-only. Preserve destination authority, atomic writes and rollback of all outputs on failure. Saving performs no comparison, lint, full regrouping or input freshness checks. Ordinary CREATE/IMPORT logic remain unchanged.


## Offline cfn-lint and coverage

`issues.cfn_lint` plans independently of comparison success and decoded documents. CREATE/default Resources with explicit logical ID and declared Stack contribute raw templates; explicitly selected cloudformation-stacks contributes declared templates. IMPORT/API-only/Terraform are not_applicable. Missing or ambiguous mappings remain unverified without guessed files. Missing explicit templates are input_missing; malformed templates and invalid/missing Stack parameters do not suppress raw lint. Reference-discovered outside templates do not expand the plan. Deduplicate by canonical template path, requested target region and lint policy, retaining every origin. Stack parameters are never automatically injected.

`utils.cfn_lint` confines private APIs to fixed cfn-lint 1.57.2. A single imported helper forks a fresh child per deduplicated template; Windows uses a new Python process. Always reap helper/child, distinguish timeout/abnormal exit/protocol failure, continue independent jobs, and mark remaining jobs not_run when common schema/runtime is unavailable.

Use ConfigMixIn with explicit region/template/JSON format, validate conflicts, check effective template selection before Runner.run, and consume its iterator incrementally. Honor HOME/cwd rc precedence, Metadata, merge/rule configuration, parameters and suppression. Record requested/effective regions and effective config fingerprint. Do not invoke Runner.cli, stdin fallback, configured output_file, graph/update/output modes or lint_all batch assumptions. Missing/different runtime versions are processing errors, never unverified private-API execution. The current checkout removed the dependency under a separate deploy task; do not silently restore/change requirements or deploy policy.

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

scan exit: processing/input failure 2; ordinary/unassigned Error 1; otherwise 0. Coverage-only/Warning/Info/IaC differences alone do not raise the code. Save errors in authority/review/I/O return 2; successful publication returns 2 when the artifact has processing errors, otherwise 0 even with ordinary issues. stdout includes publication_status=SAVED and validation_status. Save/CHECKED/exit 0 never means AWS equality or all-range PASS.

warnings/information/unverified/processing_errors summaries expose total, at most five masked/brief previews, omitted counts and paged detail; code lists are bounded. Retain IaC 16 groups/10 examples/10 fields/160-character limits, the Markdown complete compact Issue list and external all-member retrieval. Metrics separate mechanical, IaC comparison, aggregation and lint. runner wall_seconds ends after aggregation and excludes CLI JSON/output and LLM time; outer process wall time is a separate measurement. No unmeasured project speedup or worker/default changes.

# Local issues investigation

## Scope and responsibilities

The local issues-only entrypoint is `framework/scripts/issues_scan.py`. Process multiple services in the same environment/target in one process. Actual project models, generated designs, and IaC are read-only. There is no fallback to AWS API/SDK, change sets, Terraform init/plan/provider retrieval, deploy, or scenarios. Do not add new comparisons to implement/deploy/update or the post-save loop.

Ordinary issues use `issues/<environment>/<target-directory>/issues.md`, model desired → IaC differences use `iac-issues.md` with full data only in the temporary external scan artifact, and environment comparisons retain `diff.md`. Ordinary gate implementation, service ownership format, and stop decisions remain unchanged. IaC differences alone must not cause failure exit, ordinary issue registration, suspension, or Issue remediation requirements. Retain existing validator diagnostics for schema, model/Markdown equality, references, policies, account/region, etc., and post-save validation under [Validation policy](loop-engineering.md#validation-policy).

The scoped report-only `migration` Task runs without a worktree. Identify it with
`issues_save_only()`; do not collect or compare HEAD/commit, worktree/index or untracked
changes for investigation, saving, validation or completion. Other Tasks' edits are not
Issue Task changes. Do not compare the Task catalog between start and completion. Retain contract/service scope/Acceptance and Allowed paths checks on
actual report destinations. Other Tasks retain their input/Git safety checks.

## Read and review

Apply AGENTS.md section-reading rules. Apply common rules, target namespace rules, Model authority/Properties format, Markdown structure, and target resource display/reference rules specified by the issues skill's naming check. This scan does not permit omitting mandatory rules.

| Machine checks | Decisions and inputs remaining for the LLM |
| --- | --- |
| Project topology, scope, model/index/part syntax and line counts | Scope is explicit. Confirm only service ownership of ambiguous diagnostics |
| Existing service validators, generated Markdown/JSON equality, catalog/schema, references, policies, observed persistence prohibitions | Existing issues whose concrete diagnostic meaning/mapping is unclear. Retrieve diagnostic details/resources only when needed |
| Naming coverage, mandatory Name, existing name value checks | Name patterns for all resources, human-confirmed components, human exceptions and their scope. Do not check only error names/representative examples |
| Formal IaC type/ID/stack mappings and comparison of confirmed values and supported expressions | Do not regenerate machine differences as prose. Do not send uncompared items to full-text comparison or AWS |
| Scoped report formatting, exclusion, saving, report destination authority | Evidence-backed additional ordinary issues and complete continuing/resolved/unverified decisions for every scoped existing Issue |

`scan` stdout contains execution/Scope, per-category counts, bounded cause/action summaries and representatives, artifact path and detail/review instructions. Never expand all uncompared/errors/names/judgments in initial output. Retrieve all naming/judgment pages through `detail`; the complete-review requirement and exit/save decisions remain unchanged. Diagnostics, full records, rules and masked field differences stay in the same run's external artifact.

Review every `naming.names[].id`, distinguishing missing/unknown components, pattern mismatches, and explicit exceptions. Service-common `desired.note.*`, row comments, existing human confirmations, and design prose not mechanized remain decision material. For insufficient information, additionally retrieve only the corresponding model's `model/cli.py resource` or relevant rule/section. Do not classify as conforming/problem-free or resolve existing issues with insufficient material.

## Commands

The following `python3` uses the registered Python runtime, the shared comparison decoder and the isolated cfn-lint adapter. Comparison parse failures remain separate from lint input defects. Do not add a full loop before scan.

```console
python3 framework/scripts/issues_scan.py scan --environment dev --target-directory cde --service s3 --service iam --artifact /tmp/issues-scan.json
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section naming_context
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section naming --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section judgments --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section iac_issues --category 要修正 --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section iac_issues --category 比較未完了 --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section iac --issue-id ISSUE-<id> --offset 0 --limit 50
python3 framework/scripts/issues_scan.py --task-file tasks/save-local-issues.md save --artifact /tmp/issues-scan.json --review /tmp/issues-review.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/save-local-issues.md
```

Replace example scope/target values with the actual explicit scope. Register the task contract before saving as the first repository change; declare `migration`, explicit service Validation scope, exact Allowed paths/Modified files for this contract and reports to save, and `exists:` Acceptance checks.

Review JSON contains only minimal decision results (do not copy large scan JSON/reports):

```json
{
  "scan_id": "対象artifactのscan_id",
  "reviewed_naming_context_id": "対象artifactのnaming_context_id",
  "reviewed_names": ["全名称材料のid"],
  "reviewed_judgments": ["全残判断材料のid"],
  "diagnostic_assignments": {"所属未確定診断id": "service-id"},
  "issues": [{"service": "s3", "message": "resource/property、具体的問題と根拠", "source": {"path": "model/dev/cde/s3/part-001.properties", "line": 12}}],
  "resolved": [],
  "existing_issue_judgments": [{
    "id": "既存issue材料のid", "service": "s3", "status": "resolved",
    "verification": "local", "reason": "同じResourceの該当チェックが成功し不一致が解消",
    "evidence": [{"kind": "scan", "section": "check_results", "id": "今回の完了チェックid",
      "subject": "S3.Bucket 001の該当Property", "details": "該当ルールによる検証成功と元Issueとの対応"}]
  }]
}
```

All seven existing review keys are required, including empty additions/resolutions/assignments. `existing_issue_judgments` is additionally mandatory when this Scan contains existing Issues; it may be omitted or empty only when none exist. Save requires exact scan/context IDs and complete naming/judgment ID sets. Read common naming rules/target/review policy once through `detail --section naming_context`, then every naming/judgment page. Name pages refer to the shared context ID; their values, sources, exception scope and Human context remain available. A new scan always requires a new complete review even when name IDs are unchanged. Record concrete unconfirmed matters such as missing ordinary component evidence in `issues`; do not substitute human confirmation for success of unexecuted AWS checks. Resolving old issues merely because they were absent from a new scan is prohibited.

Use the following only to save already obtained results. Input JSON accepts only `issues`/`resolved`; do not automatically start scan, naming reinvestigation, IaC comparison, or AWS checks. Do not omit existing validation at save time.

```console
python3 framework/scripts/issues_scan.py --task-file tasks/save-results.md save-results --environment dev --target-directory cde --service s3 --results /tmp/acquired-results.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/save-results.md
```

Exit 0 means command completion (IaC differences are non-blocking), 1 means ordinary validation diagnostics from existing validators, and 2 means input/processing/save errors. State partial in summaries/reports; do not call it complete equality/PASS. Even if scan detects ordinary validation errors, save artifacts and proceed to saving results. If the post-save loop is FAIL, report that result and do not mark the task completed.

## Existing Issue state decisions

`existing-issue-correspondence` materials remain in v3 `judgments`. The material ID
identifies that Scan's existing item; the saved `issue-id` marker identifies its
continuing Issue across evidence updates. Legacy items without a marker receive one
when updated. `current_diagnostic_ids` supplies exact machine-marker correspondence;
other mappings require the corresponding resource/rule judgment. Do not infer resolution
from an empty diagnostic list, a successful unrelated check or IaC-only comparison.

`verification_targets` binds each Issue to structured `service`, `check_id`, `rule`,
`resource`, `property` and `scope` (environment/target/service). Scan derives these
only from the CheckResult that actually emitted the exact diagnostic; the rule is
that check's registered ID. `resource: "*"` / `property: "*"` denotes that original
check's entire validation domain, not a wildcard match to arbitrary Issues or fields.
Only exact target equality is accepted. Checks without identifiable provenance and
old Issues without this binding remain unverified. Check results expose the same
targets and their existing status/completion; no save-time revalidation is added.
Nonmechanical Issues may carry the same structured targets with an additional `path`
for their actual evidence source. Do not fabricate a binding from subject/details.

Unknown-Service materials have `service: null` and an `ownership_reason`. Review all
of them as `unverified`, with a specific `not_checked_reason` and `not_run` evidence.
They are retained without modification or service reassignment, while scoped decisions
continue normally. Existing ownership resolution from headings, markers and same-target
evidence links still applies; out-of-scope known Services are not review/update targets.

Every decision has `id`, `service`, `status`, `verification` (`local` or `aws`),
nonempty `reason` and nonempty structured `evidence`. IDs must cover exactly all existing
scoped Issues, once each. Duplicate/unknown/out-of-scope IDs, wrong Services, missing
decisions and contradictory evidence fail before publication. `reviewed_judgments`
still covers every judgment material and does not replace these decisions.

- `continuing`: current evidence proves the problem remains. Supply `diagnostic_id`
  for a current `ordinary` candidate and reference it in evidence; Python reuses its
  message/source and consumes the candidate to avoid duplication. Alternatively supply
  `issue: {"message": "current problem", "source": {"path": "relative/path", "line": 12}}`
  with concrete nonmechanical revalidation. Update only `issue-generated:start/end`
  machine content and the current `issue-review:start/end` annotation, retaining its
  marker, Service and all surrounding Human prose. Unmarked old text is retained;
  show the latest diagnostic inside the replaceable review annotation. Repeated updates
  replace that annotation rather than adding history. `issue-targets` metadata stays
  with the generated diagnostic in the same Issue; no persistent sidecar is created.
- `resolved`: the relevant check completed and positively established that the original
  mismatch/violation is absent. Every evidence entry must establish successful completed
  revalidation. A current corresponding ordinary diagnostic prevents resolution.
- `unverified`: the relevant check was unexecuted, failed, incomplete or unable to decide.
  Require `not_checked_reason`; keep the previous problem text and visibly replace its
  current state/reason/evidence annotation. Do not register unchecked scope as a new Issue.

Evidence forms:

- `{"kind":"scan","section":"ordinary","id":"current-diagnostic-id"}` proves a
  current problem. `section: "check_results"` reuses a current scoped machine check,
  with additional nonempty `subject` and `details` explaining the original Issue/check
  correspondence. Only `status: PASS` with `complete: true` and a matching recorded
  structured target proves absence. Subject/details alone cannot establish it. Other states
  are unverified. `unverified`/`processing_errors` evidence may reference a record's `id`
  or, for older records without IDs, its existing `identifier(record)` value.
- Individual/nonmechanical revalidation uses `kind: "revalidation"`, `verification`,
  `check`, `subject`, `rule`, `source: {"path":"relative/path","line":12}`, `details`,
  boolean `completed` and `outcome: "present" | "absent" | "unverified"`. For absence,
  `target` must exactly match one recorded `verification_targets` entry, with `check`
  matching its `check_id`, `rule` matching its rule and `source.path` matching its `path`.
  Cite the actual checked resource, applicable rule and observed result. Incomplete or
  unbound absence claims are unverified. The reviewer must acquire that evidence; a structured claim
  alone does not execute or independently verify a check.
- If no relevant check ran, use `{"kind":"not_run","check":"specific check", "details":"why unexecuted"}`
  with `unverified` and `not_checked_reason`. This never proves resolution.

All current Scan evidence is local. `verification: aws` requires already acquired AWS
revalidation evidence for resolution; the issues skill never executes AWS APIs and local
PASS cannot prove current AWS equality. Unverified evidence may accompany positive
continuing evidence, but never a resolution. Lack of information remains unverified.

`existing_issue_judgments` is the single authority. Keep `resolved: []`; `save_scan()`
derives the reason/evidence deletion records and uses the existing merge removal path.
A nonempty legacy `resolved` is accepted only if it exactly equals that derived projection;
independent or contradictory legacy resolutions are rejected. `save-results` retains its
existing acquired `issues`/`resolved` contract and conservative preservation behavior:
it requires neither Scan-wide decisions nor automatic checks and never interprets
missing acquired results as resolution.

The artifact remains v3 and all existing commands/sections remain supported, with additive
`check_results` and `detail --section check_results`. Individual revalidation requires
the same recorded correspondence; otherwise mark Issues unverified. Missing machine evidence never
becomes PASS. Unsupported artifact versions are still rejected. Saving rereads only the
ordinary report under the existing lock; a decision that no longer identifies its item
fails atomically. Keep later/unreviewed report items and all out-of-scope content. Do not
compare/fingerprint Model/IaC/Scan inputs or rerun checks during saving.

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

Invalid identifiers/contracts retain their existing uncompared/error classification; they are not normal waits. All six record categories (`matched`, `difference`, `deferred`, `uncompared`, `error`, `excluded`) remain in the v3 artifact and record counts. Only difference/uncompared/error records enter `iac_issues` and Issue category counts; deferred/excluded records have no Issue ID. `iac_status` priority is error → partial (uncompared or deferred) → differences → complete match → no compared records. Deferred is partial, never matched or complete. `pending_deploy` requires no comparison at present: it contributes neither uncompared/deferred nor partial/repair-required status; excluded-only scope is no compared records, not equality.

Normal Markdown shows `PENDING_DEPLOY（比較対象外）` as a dedicated count, separate from the Issue category `CFn非対応・比較対象外`; it omits these excluded records' causes and details. Deduplicate parent/child propagation by consumer service/resource and structured cause for this count; raw excluded record counts remain separate. Retrieve retained causes through `detail --section iac --record-category excluded`; use `--record-category deferred` for deferred records. These record filters cannot be combined with Issue category/ID filters. Deferred/excluded alone do not create ordinary issues or fail scan validation; retain independent ordinary diagnostics, unverified scope and processing errors.

## Input reuse and publication

`load_model` shares validated parsing, actual files/parts/keys/line positions, and text; retain the public `read_model` API. Row indexes use fixed Resource numbers and reject orphan rows. Ordinary material and comparison within a new scan do not reparse the same model entries/parts. Scan generation equality uses the existing read-only sync API per target, omitting extra generator processes and scope rereads. Retain ordinary validator/loop default process paths and at most 4 parallel workers. Issue scans execute diagnostics without PASS-cache reuse or publication. Do not add service subagents, nested parallelism, or persistent caches. Preserve Scan-time evidence paths/positive line numbers without rereading source files during saving. Template decoding is per file, evaluation per stack/parameters/context, and catalog/index/reference symbols are shared within the run.

Scan artifacts are temporary handoffs outside the repository, not next-run caches.
Do not fingerprint inputs, compare bytes/file sets or reject execution/publication for
changes during or after scanning. Save the reviewed artifact with its execution time and
confirmed/unverified scope. No input-change warnings, automatic rescan or renewed review
are required. Keep complete Scan/Review ID/content validation. A new explicitly requested
scan still requires its own complete review. Never promote unverified or failed results to PASS.

Save reports with indivisible atomic publication/rollback. Reread/merge ordinary `issues.md` service blocks using the complete current state decisions, preserving out-of-scope services, human confirmations and unverified Issues. IaC Markdown is instead this run's Scope only: no old result merge, no automatic resolution claim and no out-of-scope results in current counts. Do not parse old IaC Markdown or preserve its notes; retain previous bytes only for publication rollback. Mask secrets/current ARNs/NoEcho values in artifacts, detail and reports. No additional comparison or Model/IaC parsing during saving.

The IaC summary starts with environment/target, selected Services, execution time and a judgment limited to this run. State that out-of-scope Services are unverified without inventing their counts. Distinguish no compared records (empty or excluded-only), match within scope, differences, partial/uncompared and errors. State action-unit problem counts separately from affected record counts; matched/excluded never become problems. Categories are 要修正 / 要対応 / 要判断 / 比較未完了 / CFn非対応・比較対象外 / 処理エラー / 原因未確定. Show 要修正 first.

Keep the response category independent of `repair_direction` (IaC修正 / Model修正 / 修正先要確認 / 入力修正 / 未確定) on the existing Issue action. Confirmed value mismatch, property/resource/inline CREATE child missing, AWS::NoValue omission and proven KMS format violations are 要修正. A confirmed difference stays 要修正 even when its repair destination needs confirmation. Desired Model requirements govern ordinary mapped setting differences: reflect them in IaC, with a separate confirmation that the Model matches design intent. For format violations, use structured per-side format diagnostics to identify a proven invalid side; otherwise state 修正先要確認. Do not guess service-specific repair directions or claim AWS differences without AWS evidence. Render repair targets from direction and target path in both the compact list and detail, never from whether the category is 要判断. Retain existing IDs, grouping keys, members, artifact version and publication/exit contracts.

Render one unit per structured cause/repair target/action, without merging unknown causes by message, Service or filename alone. Show cause (or uncertainty), necessary action, repair target type and affected Services/counts. At most 16 detailed units, 10 representatives/unit, 10 differing fields/deferred children/reference diagnostics per example and 160 characters/value; selection/order are deterministic. Give each present category a representative, show all original category counts, and state displayed/total/omitted units plus omitted counts by action and record category. Limits affect display only, never classification, totals or exit codes. Show Model/IaC vertically and mask before shortening. Add a complete compact list of every Issue ID, category, cause/problem, repair target, action, affected record count and Services independently of the detailed limit. Keep scan stdout bounded. Omit source-line lists, full Stack lists, whole documents and matched/excluded detail from normal Markdown; retrieve full masked data through the existing temporary artifact detail path.

If an explicitly mapped CREATE template is absent, state “モデルに対応するtemplateが存在しない（CREATE未実装）” in IaC differences with target resources, stacks, and missing paths. Do not link to absent files. If stack/template mappings are unconfirmed, state uncompared reasons rather than asserting absence; exclude IMPORT from missing-item decisions.

## IaC report grouping and publication

Aggregation runs once over finished comparison records, using dictionaries and deterministic keys. A missing file groups by environment/target, structured cause kind, missing path, and action. Direct missing-template diagnostics and propagated `export-search-incomplete` metadata share that action; these prove comparison search interruption, not direct producer/consumer dependency. Different missing inputs remain separate. Selected direct setting differences group by template, Stack, service/resource/property, difference kind, and response; uncertainty is never merged by prose similarity. Proven missing-template/parameter input actions retain 要対応 / 入力修正; missing inputs that only interrupt reference search remain 比較未完了, without confirming a setting difference. A shared missing-input group retains the direct proven action when it also has unresolved dependent members. Condition-disabled CREATE with unconfirmed design intent remains 要判断. Unresolved Export/Import remains 比較未完了, processing failures remain 処理エラー and unknown difference causes remain 原因未確定; do not promote every difference record to 要修正. CFn非対応・比較対象外 remains unchanged. Investigation statuses and unresolved members do not establish equality or completion.

All comparison records (including matched/excluded), unchanged `iac_key` identities, masked field-display information and deterministic Issue-to-record membership belong to the execution's temporary artifact outside the repository. `iac_issues[].members` indexes the original `iac` list. `detail` retrieves category/Issue filters before offset/limit pagination without source reads or comparison. No persistent sidecar, embedded JSON, record restoration, old-result merge, or Markdown digest check.

`iac-issues.md` is replaced from the current valid artifact only. Never restore old results, human annotations, embedded JSON or out-of-scope Services. Existing `iac-issues.state.json` is ignored even if stale, malformed or inconsistent; do not read, write, migrate or automatically delete it. Do not replace state with another persistent file/cache. Only `issues.md` and `iac-issues.md` belong to the indivisible save batch. Preserve destination authority, atomic writes and rollback of all outputs on failure. Saving performs no comparison, lint, full regrouping or input freshness checks. Ordinary Issue Gate and CREATE/IMPORT logic remain unchanged.


## Framework regression and fixture benchmark

Select development checks and final validation of this entrypoint under [Validation policy](loop-engineering.md#validation-policy), keeping framework implementation scope separate from ordinary issues. `framework/scripts/tests/integrations/issues_scan.checks.py` checks isolated fixtures using existing checks format; `--benchmark --log-dir /tmp/issues-performance` repeatedly measures A (ordinary path equivalent to before changes in current checkout)/B (the same ordinary checks plus per-service reference comparison)/C (batch scan) with the same runtime, fresh cache, and no profile. Place benchmark fixtures and diagnostics only outside the repository.

Measure A/B LLM volume as old-skill-required full model/Markdown reads and list reediting; C as actual scan stdout plus minimal review JSON UTF-8 bytes/characters. Add required rule input to A/B/C under the same conditions; C stdout shares patterns/scope/paths without duplicate body output. Actual LLM tokens, LLM wall time, and total actual project time are unmeasured. Do not call fixture Python scan/material extraction/formatting/saving whole-path wall/process/read/parse/decode/decision coverage measurements actual speed of the entire skill. Post-save local loops and actual LLM time are excluded from this benchmark and unmeasured. Count actual input reads separately; also include staged models in aggregation.

## Complete membership and interrupted comparison

The Markdown Issue IDs address the same temporary artifact via `issues_scan.py detail --artifact <path> --section iac --issue-id ISSUE-<id> --offset 0 --limit 50`. Page through all members until the reported total is covered. Ten representatives are a display limit only. Subsequent explicitly authorized repair tasks must inspect every member, distinguish common repairs from individual decisions, and recompare every affected member before completion. Uncompared members are not resolved before successful recomparison. The issues skill itself never repairs Model/IaC.

When the existing comparison exception boundary catches an error, retain accumulated `Comparison.results` and append scoped incomplete/error records. Preserve reference-warning versus processing-error semantics and explicitly mark interrupted coverage in artifact, summary and Markdown. Unexecuted scope is never matched/verified; do not rerun comparison or broaden exception catches to hide the cause.

## Package and single aggregation

`issues_scan.py` preserves the CLI and optional `--repository-root` (cwd defaults to the repository root); `issues.cli` lazily selects scan/detail/save runtime. `runner` owns scan order and partial results; `inputs` owns Model/template/parameter reads; `references` owns existing expression/reference evaluation through the shared evaluators; `comparison.Comparison` retains explicit stack/index/templates/compare_rows/desired_value APIs and the single mutable scan state. These modules do not replace the shared IaC/Model APIs. No Mixins or dynamic forwarding.

`records` owns pure IDs/masking/field differences, `aggregate` produces canonical IaC records, stable Issue IDs/members, lightweight record metadata and the bounded overview once. `artifact` reads this v3 data for review/detail; filter the saved action index, slice indices, then format only page records. `reports` formats current-run IaC from this aggregation and conservatively merges ordinary issues. `publication` owns authority/review/atomic writes. No duplicate record body, persistent sidecar, second Model snapshot or lint cache. `summary`, `detail`, `validate_artifact` and `save_scan` support only v3 scan artifacts; explicitly reject v2 and other unsupported versions without compatibility conversion or deriving replacement indexes.

## Input reads and report publication

Create a new scan ID and validate the explicit target/scope. Retain invocation-local Model
parsing and actual read/parse error diagnostics. Always run selected scoped design checks,
even when a View is missing; retain independent source/service diagnostics and mark
unavailable View checks unverified. Do not build or revalidate input fingerprints, service
cache keys or pending Issue PASS-cache candidates. Ordinary Validator cache checks and
publication guards remain unchanged.

For issues only, a selected saved View read/decode failure is a structured service/path/phase
processing error. Mark dependent View and incomplete scope-wide checks unverified and
continue independent Model/service/comparison/lint checks. Normal Validator failure
propagation is unchanged.

Under the publication lock, reread ordinary issues, format both reports and use the existing
indivisible atomic batch/rollback. Refresh continuing ordinary Issues with current evidence, remove only explicitly
revalidated resolved Issues and retain unverified Issues with their reason; preserve
out-of-scope services/Human prose. Replace only this
scope's machine notice marker. Exclude machine notices from Human review materials.
`save-results` accepts acquired ordinary results only and never scans/compares/lints.

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

Normal Error is an ordinary candidate only when ownership is proven. E0000 is ordinary only with concrete parser/scanner/CfnParse/JSON/Unicode/root-type provenance from observing existing YAML/JSON loader calls; keep fallback and Match construction unchanged. I/O/internal/unproven decode failures are processing errors, including suppressed failures. E0001 defaults to processing (transform cause unproven); E0002/E0003, unknown severity and protocol/launch/timeout failures are processing. Iterator completion does not prove downstream rules ran; retain suppressed decode and transform coverage as unverified without promoting suppressed input diagnostics to exit 1/2. Warning/Informational remain separate non-numbered channels and never enter Issue Gate.

Use diagnostic Resources/logical-ID paths plus explicit origins to prove one selected owner. Common/multiple/unknown owner Errors require judgment and explicit diagnostic_assignments; selected cloudformation-stacks may own common errors. Proven outside-resource findings remain scope-external diagnostics. Never assign to the first service by convenience or confuse a scope-wide failure with an outside resource finding. Retain Rule ID, severity, path, position and provenance. Merge NoEcho defaults/effective parameters and known comparison/Model secrets into redaction before final artifact construction; malformed decode text is withheld. Mask before shortening; reports/detail never restore secret text.

## Status, output and measurements

validation_status priority is ERROR (processing, including IaC category=error), FAIL (selected ordinary or unassigned Error), INCOMPLETE (required mechanical/lint checks unexecuted), CHECKED. Keep review_required, iac_status and lint coverage separate. Differences/uncompared only affect iac_status; not_applicable is never lint PASS. Error plus downstream-unexecuted coverage remains FAIL plus incomplete coverage; independent processing errors take ERROR precedence. Separate stage-error counts from affected IaC record counts.

scan exit: processing/input failure 2; ordinary/unassigned Error 1; otherwise 0. Coverage-only/Warning/Info/IaC differences alone do not raise the code. Save errors in authority/review/I/O return 2; successful publication returns 2 when the artifact has processing errors, otherwise 0 even with ordinary issues. stdout includes publication_status=SAVED and validation_status. Save/CHECKED/exit 0 never means AWS equality or all-range PASS.

warnings/information/unverified/processing_errors summaries expose total, at most five masked/brief previews, omitted counts and paged detail; code lists are bounded. Retain IaC 16 groups/10 examples/10 fields/160-character limits, the Markdown complete compact Issue list and external all-member retrieval. Metrics separate mechanical, IaC comparison, aggregation and lint. runner wall_seconds ends after aggregation and excludes CLI JSON/output and LLM time; outer process wall time is a separate measurement. No unmeasured project speedup or worker/default changes.

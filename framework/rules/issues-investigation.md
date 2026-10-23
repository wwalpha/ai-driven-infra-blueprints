# Local issues investigation

## Scope and responsibilities

The local issues-only entrypoint is `framework/scripts/issues_scan.py`. Process multiple services in the same environment/target in one process. Actual project models, generated designs, and IaC are read-only. There is no fallback to AWS API/SDK, change sets, Terraform init/plan/provider retrieval, deploy, or scenarios. Do not add new comparisons to implement/deploy/update or the post-save loop.

Ordinary issues use `issues/<environment>/<target-directory>/issues.md`, model desired → IaC differences use `iac-issues.md` with full data only in the temporary external scan artifact, and environment comparisons retain `diff.md`. Ordinary gate implementation, service ownership format, and stop decisions remain unchanged. IaC differences alone must not cause failure exit, ordinary issue registration, suspension, or Issue remediation requirements. Retain existing validator diagnostics for schema, model/Markdown equality, references, policies, account/region, etc., and post-save validation under [Validation policy](loop-engineering.md#validation-policy).

The scoped report-only `migration` Task runs without a worktree and is independent of
Task-start/current main/master commits. HEAD changes alone do not stop investigation,
save, validation or completion, suspend the Task, create a replacement Task or expand
Validation scope. Validate current worktree/index changes and untracked files against
the existing report-only Allowed paths and contract; other Tasks retain Git baseline checks.

## Read and review

Apply AGENTS.md section-reading rules. Apply common rules, target namespace rules, Model authority/Properties format, Markdown structure, and target resource display/reference rules specified by the issues skill's naming check. This scan does not permit omitting mandatory rules.

| Machine checks | Decisions and inputs remaining for the LLM |
| --- | --- |
| Project topology, scope, model/index/part syntax and line counts | Scope is explicit. Confirm only service ownership of ambiguous diagnostics |
| Existing service validators, generated Markdown/JSON equality, catalog/schema, references, policies, observed persistence prohibitions | Existing issues whose concrete diagnostic meaning/mapping is unclear. Retrieve diagnostic details/resources only when needed |
| Naming coverage, mandatory Name, existing name value checks | Name patterns for all resources, human-confirmed components, human exceptions and their scope. Do not check only error names/representative examples |
| Formal IaC type/ID/stack mappings and comparison of confirmed values and supported expressions | Do not regenerate machine differences as prose. Do not send uncompared items to full-text comparison or AWS |
| Scoped report formatting, exclusion, saving, input fingerprints | Evidence-backed additional ordinary issues and resolution specifications for explicitly revalidated existing issues |

`scan` stdout contains execution/Scope, per-category counts, bounded cause/action summaries and representatives, artifact path and detail/review instructions. Never expand all uncompared/errors/names/judgments in initial output. Retrieve all naming/judgment pages through `detail`; the complete-review requirement and exit/save decisions remain unchanged. Diagnostics, full records, rules and masked field differences stay in the same run's external artifact.

Review every `naming.names[].id`, distinguishing missing/unknown components, pattern mismatches, and explicit exceptions. Service-common `desired.note.*`, row comments, existing human confirmations, and design prose not mechanized remain decision material. For insufficient information, additionally retrieve only the corresponding model's `model/cli.py resource` or relevant rule/section. Do not classify as conforming/problem-free or resolve existing issues with insufficient material.

## Commands

The following `python3` uses the registered Python runtime, the shared comparison decoder and the isolated cfn-lint adapter. Comparison parse failures remain separate from lint input defects. Do not add a full loop before scan.

```console
python3 framework/scripts/issues_scan.py scan --environment dev --target-directory cde --service s3 --service iam --artifact /tmp/issues-scan.json
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section naming_context
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section naming --offset 0 --limit 50
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section judgments --offset 0 --limit 50
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
  "resolved": [{"id": "既存issue材料のid", "reason": "明示された修復scopeでの解消理由", "evidence": "実施済み再検証の根拠"}]
}
```

All seven review keys are required, including empty additions/resolutions/assignments. Save requires exact scan/context IDs and complete naming/judgment ID sets. Read common naming rules/target/review policy once through `detail --section naming_context`, then every naming/judgment page. Name pages refer to the shared context ID; their values, sources, exception scope and Human context remain available. A new scan always requires a new complete review even when name IDs are unchanged. Record concrete unconfirmed matters such as missing ordinary component evidence in `issues`; do not substitute human confirmation for success of unexecuted AWS checks. Resolving old issues merely because they were absent from a new scan is prohibited.

Use the following only to save already obtained results. Input JSON accepts only `issues`/`resolved`; do not automatically start scan, naming reinvestigation, IaC comparison, or AWS checks. Do not omit existing validation at save time.

```console
python3 framework/scripts/issues_scan.py --task-file tasks/save-results.md save-results --environment dev --target-directory cde --service s3 --results /tmp/acquired-results.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/save-results.md
```

Exit 0 means command completion (IaC differences are non-blocking), 1 means ordinary validation diagnostics from existing validators, and 2 means input/processing/save errors. State partial in summaries/reports; do not call it complete equality/PASS. Even if scan detects ordinary validation errors, save artifacts and proceed to saving results. If the post-save loop is FAIL, report that result and do not mark the task completed.

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

Uncompared: Terraform (no existing reliable local mapping/evaluator), Transform, ImportValue whose approved handoff cannot be proved locally, external input for IMPORT references, unknown attributes/nonunique mappings, unsupported expressions, and unconfirmed values/types. This is not a configuration marking all resources unsupported. IMPORT itself is not generated; absent IaC is not missing. Explicit missing CREATE templates/resources/properties are non-blocking differences. Input syntax/read/save failures are errors, not success.

## Input reuse and publication

`load_model` shares validated parsing, actual files/parts/keys/line positions, and text; retain the public `read_model` API. Row indexes use fixed Resource numbers and reject orphan rows. Ordinary material and comparison within a new scan do not reparse the same model entries/parts. Scan generation equality uses the existing read-only sync API per target, omitting extra generator processes and scope rereads. Retain ordinary validator/loop default process paths, successful caches, and at most 4 parallel workers. Do not add service subagents, nested parallelism, or persistent caches. Also share evidence-line verification per file within saving. Template decoding is per file, evaluation per stack/parameters/context, and catalog/index/reference symbols are shared within the run.

Scan artifacts are temporary handoffs outside the repository, not next-run caches. Before saving, confirm models, part sets, IaC, parameters, references, and rules/framework using existing digest/service dependency/common input helpers. Reject saving on changes and rescan the relevant scope. Do not rerun comparisons merely for saving.

Keep `fingerprint` / `verify_inputs()` content checks: a changed commit SHA with unchanged
inputs permits the existing scan. Changed actual inputs require a new scan of the necessary
scope and renewed naming/judgment review before saving in the same Task. A stale scan is
an input-integrity failure, independent of HEAD; never save it as current or call failed or
unverified checks PASS. Reinvestigation grants no Model/IaC write authority.

Save reports with indivisible atomic publication/rollback. Reread/merge ordinary `issues.md` service blocks conservatively, preserving out-of-scope services, human confirmations and unresolved issues. IaC Markdown is instead this run's Scope only: no old result merge, no automatic resolution claim and no out-of-scope results in current counts. Do not parse old IaC Markdown or preserve its notes; retain previous bytes only for publication rollback. Mask secrets/current ARNs/NoEcho values in artifacts, detail and reports. No additional comparison or Model/IaC parsing during saving.

The IaC summary starts with environment/target, selected Services, execution time and a judgment limited to this run. State that out-of-scope Services are unverified without inventing their counts. Distinguish no compared records (empty or excluded-only), match within scope, differences, partial/uncompared and errors. State action-unit problem counts separately from affected record counts; matched/excluded never become problems. Categories remain 要対応 / 要判断 / 比較未完了 / 処理エラー / 原因未確定.

Render one unit per structured cause/repair target/action, without merging unknown causes by message, Service or filename alone. Show cause (or uncertainty), necessary action, repair target type and affected Services/counts. At most 16 detailed units, 10 representatives/unit, 10 differing fields/deferred children/reference diagnostics per example and 160 characters/value; selection/order are deterministic. Give each present category a representative, show all original category counts, and state displayed/total/omitted units plus omitted counts by action and record category. Limits affect display only, never classification, totals or exit codes. Show Model/IaC vertically and mask before shortening. Add a complete compact list of every Issue ID, category, cause/problem, repair target, action, affected record count and Services independently of the detailed limit. Keep scan stdout bounded. Omit source-line lists, full Stack lists, whole documents and matched/excluded detail from normal Markdown; retrieve full masked data through the existing temporary artifact detail path.

If an explicitly mapped CREATE template is absent, state “モデルに対応するtemplateが存在しない（CREATE未実装）” in IaC differences with target resources, stacks, and missing paths. Do not link to absent files. If stack/template mappings are unconfirmed, state uncompared reasons rather than asserting absence; exclude IMPORT from missing-item decisions.

## IaC report grouping and publication

Aggregation runs once over finished comparison records, using dictionaries and deterministic keys. A missing file groups by environment/target, structured cause kind, missing path, and action. Direct missing-template diagnostics and propagated `export-search-incomplete` metadata share that action; these prove comparison search interruption, not direct producer/consumer dependency. Different missing inputs remain separate. Selected direct setting differences group by template, Stack, service/resource/property, difference kind, and response; uncertainty is never merged by prose similarity. Unproven cause/target remains `要調査`, with the facts and necessary investigation stated. Action-needed means a proven missing-input action; judgment-needed includes value/setting choices and investigation. Incomplete includes uncompared/error members.

All comparison records (including matched/excluded), unchanged `iac_key` identities, masked field-display information and deterministic Issue-to-record membership belong to the execution's temporary artifact outside the repository. `iac_issues[].members` indexes the original `iac` list. `detail` retrieves category/Issue filters before offset/limit pagination without source reads or comparison. No persistent sidecar, embedded JSON, record restoration, old-result merge, or Markdown digest check.

`iac-issues.md` is replaced from the current valid artifact only. Never restore old results, human annotations, embedded JSON or out-of-scope Services. Existing `iac-issues.state.json` is ignored even if stale, malformed or inconsistent; do not read, write, migrate or automatically delete it. Do not replace state with another persistent file/cache. Only `issues.md` and `iac-issues.md` belong to the indivisible save batch. Preserve the input-change check immediately before publication, atomic writes and rollback of all outputs on failure. Saving performs no comparison, lint or full regrouping; retain Model dependency reads needed by scoped/service/common fingerprints. Ordinary Issue Gate and CREATE/IMPORT logic remain unchanged.


## Framework regression and fixture benchmark

Select development checks and final validation of this entrypoint under [Validation policy](loop-engineering.md#validation-policy), keeping framework implementation scope separate from ordinary issues. `framework/scripts/tests/integrations/issues_scan.checks.py` checks isolated fixtures using existing checks format; `--benchmark --log-dir /tmp/issues-performance` repeatedly measures A (ordinary path equivalent to before changes in current checkout)/B (the same ordinary checks plus per-service reference comparison)/C (batch scan) with the same runtime, fresh cache, and no profile. Place benchmark fixtures and diagnostics only outside the repository.

Measure A/B LLM volume as old-skill-required full model/Markdown reads and list reediting; C as actual scan stdout plus minimal review JSON UTF-8 bytes/characters. Add required rule input to A/B/C under the same conditions; C stdout shares patterns/scope/paths without duplicate body output. Actual LLM tokens, LLM wall time, and total actual project time are unmeasured. Do not call fixture Python scan/material extraction/formatting/saving whole-path wall/process/read/parse/decode/decision coverage measurements actual speed of the entire skill. Post-save local loops and actual LLM time are excluded from this benchmark and unmeasured. Separate read_text from input-integrity read_bytes; also include staged models in aggregation.

## Complete membership and interrupted comparison

The Markdown Issue IDs address the same temporary artifact via `issues_scan.py detail --artifact <path> --section iac --issue-id ISSUE-<id> --offset 0 --limit 50`. Page through all members until the reported total is covered. Ten representatives are a display limit only. Subsequent explicitly authorized repair tasks must inspect every member, distinguish common repairs from individual decisions, and recompare every affected member before completion. Uncompared members are not resolved before successful recomparison. The issues skill itself never repairs Model/IaC.

When the existing comparison exception boundary catches an error, retain accumulated `Comparison.results` and append scoped incomplete/error records. Preserve reference-warning versus processing-error semantics and explicitly mark interrupted coverage in artifact, summary and Markdown. Unexecuted scope is never matched/verified; do not rerun comparison or broaden exception catches to hide the cause.

## Package and single aggregation

`issues_scan.py` preserves the CLI and optional `--repository-root` (cwd defaults to the repository root); `issues.cli` lazily selects scan/detail/save runtime. `runner` owns scan order and partial results; `inputs` owns Model/template/parameter reads; `references` owns existing expression/reference evaluation through the shared evaluators; `comparison.Comparison` retains explicit stack/index/templates/compare_rows/desired_value APIs and the single mutable scan state. These modules do not replace the shared IaC/Model APIs. No Mixins or dynamic forwarding.

`records` owns pure IDs/masking/field differences, `aggregate` produces canonical IaC records, stable Issue IDs/members, lightweight record metadata and the bounded overview once. `artifact` reads this v2 data for review/detail; filter the saved action index, slice indices, then format only page records. `reports` formats current-run IaC from this aggregation and conservatively merges ordinary issues. `publication` owns authority/review/guard/atomic writes. No duplicate record body, persistent sidecar, second Model snapshot or lint cache. Only v2 scan artifacts are supported; reject unsupported artifact formats without deriving replacement indexes.

## Input and cache completion order

Create a new scan ID and validate the explicit target/scope. Use `FileReads` only for one starting `PassCache.common_key(snapshot=reads)`; do not register it as a generation recorder or change GenerationInputs Task conditions. Share this PassCache with mechanical checks and service dependency verification. Always run selected scoped design checks even when a View is missing; retain independent source/service diagnostics and mark unavailable View checks unverified.

Only issues calls `check_scoped_designs(defer_cache=True)`. Hold new successful mechanical candidates (never cache hits) under the existing no-errors/no-warnings/no-unverified eligibility conditions. After material collection, comparison and lint, redact and aggregate once. Verify initial and actually consumed Model/part/Markdown/IaC/parameter/reference bytes and file sets, service dependencies and lint dependencies; then enumerate/read common Framework/project/runtime inputs live and compare to the starting key. Only after every guard succeeds call `finalize_service_cache(current_common_key)`. Normal Validator remains immediate by default. Stale inputs, exceptions and interruptions never finalize pending candidates. This cache represents mechanical validation only, never comparison or lint success.

Save separately revalidates scoped/file-set/service/common/lint inputs against live data; artifact start keys do not replace current reads. Under the publication lock, reread ordinary issues, format both reports, run the fresh guard immediately before the existing indivisible atomic batch/rollback. Preserve old ordinary issues unless explicit resolution evidence identifies them; preserve out-of-scope services/Human prose. Replace only this scope's machine notice marker. Keep legacy unknown-scope warnings unverified, consolidate duplicates, and exclude all machine notices from Human review materials. `save-results` still accepts acquired ordinary results only and never scans/compares/lints.

## Offline cfn-lint and coverage

`issues.cfn_lint` plans independently of comparison success and decoded documents. CREATE/default Resources with explicit logical ID and declared Stack contribute raw templates; explicitly selected cloudformation-stacks contributes declared templates. IMPORT/API-only/Terraform are not_applicable. Missing or ambiguous mappings remain unverified without guessed files. Missing explicit templates are input_missing; malformed templates and invalid/missing Stack parameters do not suppress raw lint. Reference-discovered outside templates do not expand the plan. Deduplicate by canonical template path, requested target region and lint policy, retaining every origin. Stack parameters are never automatically injected.

`utils.cfn_lint` confines private APIs to fixed cfn-lint 1.57.2. A single imported helper forks a fresh child per deduplicated template; Windows uses a new Python process. The compatibility Worker.run/scope retain their historical semantics, without restoring deploy lint deleted in the current checkout. Always reap helper/child, distinguish timeout/abnormal exit/protocol failure, continue independent jobs, and mark remaining jobs not_run when common schema/runtime is unavailable.

Use ConfigMixIn with explicit region/template/JSON format, validate conflicts, check effective template selection before Runner.run, and consume its iterator incrementally. Honor HOME/cwd rc precedence, Metadata, merge/rule configuration, parameters and suppression. Record requested/effective regions and effective config fingerprint. Do not invoke Runner.cli, stdin fallback, configured output_file, graph/update/output modes or lint_all batch assumptions. Missing/different runtime versions are processing errors, never unverified private-API execution. The current checkout removed the dependency under a separate deploy task; do not silently restore/change requirements or deploy policy.

Record repository raw templates separately from external lint locators: all six HOME/cwd config candidate existence states, adopted config content hashes, parameter selections, custom rules/override/registry directory sets, provider mapping and selected schema bytes, bundle/cache selection/version inputs, Python/package/runtime/HOME/cwd. Only hashes/kinds/sets/locators/version metadata are persisted; never config/parameter/secret bodies. Reenumerate/hash at scan completion and before save, without lint reruns. A different runtime/HOME cannot reuse evidence. Provider prerequisites are checked before access; child-only offline replacements prohibit provider update/download and network access without editing the installed package or changing legacy CLI compatibility behavior.

Normal Error is an ordinary candidate only when ownership is proven. E0000 is ordinary only with concrete parser/scanner/CfnParse/JSON/Unicode/root-type provenance from observing existing YAML/JSON loader calls; keep fallback and Match construction unchanged. I/O/internal/unproven decode failures are processing errors, including suppressed failures. E0001 defaults to processing (transform cause unproven); E0002/E0003, unknown severity and protocol/launch/timeout failures are processing. Iterator completion does not prove downstream rules ran; retain suppressed decode and transform coverage as unverified without promoting suppressed input diagnostics to exit 1/2. Warning/Informational remain separate non-numbered channels and never enter Issue Gate.

Use diagnostic Resources/logical-ID paths plus explicit origins to prove one selected owner. Common/multiple/unknown owner Errors require judgment and explicit diagnostic_assignments; selected cloudformation-stacks may own common errors. Proven outside-resource findings remain scope-external diagnostics. Never assign to the first service by convenience or confuse a scope-wide failure with an outside resource finding. Retain Rule ID, severity, path, position and provenance. Merge NoEcho defaults/effective parameters and known comparison/Model secrets into redaction before final artifact construction; malformed decode text is withheld. Mask before shortening; reports/detail never restore secret text.

## Status, output and measurements

validation_status priority is ERROR (processing, including IaC category=error), FAIL (selected ordinary or unassigned Error), INCOMPLETE (required mechanical/lint checks unexecuted), CHECKED. Keep review_required, iac_status and lint coverage separate. Differences/uncompared only affect iac_status; not_applicable is never lint PASS. Error plus downstream-unexecuted coverage remains FAIL plus incomplete coverage; independent processing errors take ERROR precedence. Separate stage-error counts from affected IaC record counts.

scan exit: processing/stale/input failure 2; ordinary/unassigned Error 1; otherwise 0. Coverage-only/Warning/Info/IaC differences alone do not raise the code. Save errors in authority/review/guard/I/O return 2; successful publication returns 2 when the artifact has processing errors, otherwise 0 even with ordinary issues. stdout includes publication_status=SAVED and validation_status. Save/CHECKED/exit 0 never means AWS equality or all-range PASS.

warnings/information/unverified/processing_errors summaries expose total, at most five masked/brief previews, omitted counts and paged detail; code lists are bounded. Retain IaC 16 groups/10 examples/10 fields/160-character limits, the Markdown complete compact Issue list and external all-member retrieval. Metrics separate mechanical, IaC comparison, aggregation, lint and final input guards. runner wall_seconds ends after aggregation/guard/cache finalization and excludes CLI JSON/output and LLM time; outer process wall time is a separate measurement. No unmeasured project speedup or worker/default changes.

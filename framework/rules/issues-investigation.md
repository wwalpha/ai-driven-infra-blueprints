# Local issues investigation

## Scope and responsibilities

The local issues-only entrypoint is `framework/scripts/issues_scan.py`. Process multiple services in the same environment/target in one process. Actual project models, generated designs, and IaC are read-only. There is no fallback to AWS API/SDK, change sets, Terraform init/plan/provider retrieval, deploy, or scenarios. Do not add new comparisons to implement/deploy/update or the post-save loop.

Ordinary issues use `issues/<environment>/<target-directory>/issues.md`, model desired → IaC differences use `iac-issues.md` with full data only in the temporary external scan artifact, and environment comparisons retain `diff.md`. Ordinary gate implementation, service ownership format, and stop decisions remain unchanged. IaC differences alone must not cause failure exit, ordinary issue registration, suspension, or Issue remediation requirements. Retain existing validator diagnostics for schema, model/Markdown equality, references, policies, account/region, etc., and the post-save local loop.

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

Review every `naming.names[].id`, distinguishing missing/unknown components, pattern mismatches, and explicit exceptions. Service-common `desired.note.*`, row comments, existing human confirmations, and design prose not mechanized remain decision material. For insufficient information, additionally retrieve only the corresponding model's `model_files.py --resource` or relevant rule/section. Do not classify as conforming/problem-free or resolve existing issues with insufficient material.

## Commands

The following `python3` uses an existing local validation runtime that can import cfn-lint (missing decoders are processing errors). Do not add a full loop before scan.

```console
python3 framework/scripts/issues_scan.py scan --environment dev --target-directory cde --service s3 --service iam --artifact /tmp/issues-scan.json
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
  "reviewed_names": ["全名称材料のid"],
  "reviewed_judgments": ["全残判断材料のid"],
  "diagnostic_assignments": {"所属未確定診断id": "service-id"},
  "issues": [{"service": "s3", "message": "resource/property、具体的問題と根拠", "source": {"path": "model/dev/cde/s3/part-001.properties", "line": 12}}],
  "resolved": [{"id": "既存issue材料のid", "reason": "明示された修復scopeでの解消理由", "evidence": "実施済み再検証の根拠"}]
}
```

Empty additions/resolutions/assignments may be omitted. Save requires review of all names/remaining decision IDs. Record concrete unconfirmed matters such as missing ordinary component evidence in `issues`; do not substitute human confirmation for success of unexecuted AWS checks. Resolving old issues merely because they were absent from a new scan is prohibited.

Use the following only to save already obtained results. Input JSON accepts only `issues`/`resolved`; do not automatically start scan, naming reinvestigation, IaC comparison, or AWS checks. Do not omit existing validation at save time.

```console
python3 framework/scripts/issues_scan.py --task-file tasks/save-results.md save-results --environment dev --target-directory cde --service s3 --results /tmp/acquired-results.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/save-results.md
```

Exit 0 means command completion (IaC differences are non-blocking), 1 means ordinary validation diagnostics from existing validators, and 2 means input/processing/save errors. State partial in summaries/reports; do not call it complete equality/PASS. Even if scan detects ordinary validation errors, save artifacts and proceed to saving results. If the post-save loop is FAIL, report that result and do not mark the task completed.

## Comparison coverage

Desired properties are authoritative. Do not use observed/generated Markdown bodies for IaC comparison. Use CloudFormation formal catalog types, `cfn-logicalId`, stack models, per-stack parameters, and target context. Legacy mappings use only existing unique-ID compatibility. Read only reference-target model information for external services; do not expand investigation scope.

Supported scope: literals, values with confirmed schema types, nested objects/ordered arrays, JSON documents/policies, Ref/GetAtt resource identities and attributes, parameters/defaults, Condition/If/Equals/And/Or/Not, parameter/pseudo-only Sub/Join, Select/Split/FindInMap, formal independent children, and inline children with unique parent Refs. Retain formal conversion of model `.Name` to Name tags and exclusions such as S3.Region/identifier outputs. Unselected settings present only in IaC are not violations. Only Tag arrays use formal key matching; other arrays retain order and duplicates. Compare the whole object/document when specified as a whole.

Uncompared: Terraform (no existing reliable local mapping/evaluator), Transform, ImportValue whose approved handoff cannot be proved locally, external input for IMPORT references, unknown attributes/nonunique mappings, unsupported expressions, and unconfirmed values/types. This is not a configuration marking all resources unsupported. IMPORT itself is not generated; absent IaC is not missing. Explicit missing CREATE templates/resources/properties are non-blocking differences. Input syntax/read/save failures are errors, not success.

## Input reuse and publication

`load_model` shares validated parsing, actual files/parts/keys/line positions, and text; retain the public `read_model` API. Row indexes check hyphens in legacy IDs and ambiguous prefixes. Ordinary material and comparison within a new scan do not reparse the same model entries/parts. Scan generation equality uses the existing read-only sync API per target, omitting extra generator processes and scope rereads. Retain ordinary validator/loop default process paths, successful caches, and at most 4 parallel workers. Do not add service subagents, nested parallelism, or persistent caches. Also share evidence-line verification per file within saving. Template decoding is per file, evaluation per stack/parameters/context, and catalog/index/reference symbols are shared within the run.

Scan artifacts are temporary handoffs outside the repository, not next-run caches. Before saving, confirm models, part sets, IaC, parameters, references, and rules/framework using existing digest/service dependency/common input helpers. Reject saving on changes and rescan the relevant scope. Do not rerun comparisons merely for saving.

Briefly serialize report saving with the existing shared registration lock, reservations and indivisible atomic publication/rollback. Reread/merge ordinary `issues.md` service blocks conservatively, preserving out-of-scope services, human confirmations and unresolved issues. IaC Markdown is instead this run's Scope only: no old result merge, no automatic resolution claim and no out-of-scope results in current counts. Preserve human notes under `## 人間注記` outside generated `iac-summary:start/end` markers. Mask secrets/current ARNs/NoEcho values in artifacts, detail and reports. No additional comparison or Model/IaC parsing during saving.

The IaC summary states Scope/time/status, independent Issues per category, proven causes, all original record categories and directly affected resources. Categories: 要対応 / 要判断 / 比較未完了 / 処理エラー / 原因未確定. Display groups are separate from independent causal Issues. At most 8 groups, 3 representatives/group, 1 field/example and 160 characters/value; every omitted group/example/field/Stack is counted and available through artifact detail. Model/IaC values remain vertical; normal mismatch display hides source paths/lines. Machine Markdown normally stays under 300 lines and at most about 500, excluding preserved human notes. Keep cause/action/impact information for displayed groups and classify omitted Issues in full counts; retrieve omitted groups before deciding repairs. Preserve ordinary Markdown structure and gate behavior unchanged.

If an explicitly mapped CREATE template is absent, state “モデルに対応するtemplateが存在しない（CREATE未実装）” in IaC differences with target resources, stacks, and missing paths. Do not link to absent files. If stack/template mappings are unconfirmed, state uncompared reasons rather than asserting absence; exclude IMPORT from missing-item decisions.

## IaC report grouping and persistence

Aggregation runs once over finished comparison records, using dictionaries and deterministic keys. A missing file groups by environment/target, structured cause kind, missing path, and action. Direct missing-template diagnostics and propagated `export-search-incomplete`/`legacy-search-incomplete` metadata share that action; these prove comparison search interruption, not direct producer/consumer dependency. Legacy candidate-search causes are propagated only when every failed candidate has the same structured missing-input cause; mixed/unknown failures remain investigation items. Different missing inputs remain separate. Selected direct setting differences group by template, Stack, service/resource/property, difference kind, and response; uncertainty is never merged by prose similarity. Unproven cause/target remains `要調査`, with the facts and necessary investigation stated. Action-needed means a proven missing-input action; judgment-needed includes value/setting choices and investigation. Incomplete includes uncompared/error or retained-unconfirmed members.

All comparison records (including matched/excluded), unchanged `iac_key` identities, masked field-display information and deterministic Issue-to-record membership belong to the execution's temporary artifact outside the repository. `iac_issues[].members` indexes the original `iac` list. `detail` retrieves category/Issue filters before offset/limit pagination without source reads or comparison. Old artifacts may derive membership from their own records through the same `iac_actions()` helper. No persistent sidecar, embedded JSON, record restoration, old-result merge, or Markdown digest check.

During one-time disposal of an existing legacy state/embedded report, read only annotation metadata (`annotations` and `generated_line_ids`) to identify contextual human additions, preserve them in Markdown, and atomically delete the explicitly reserved legacy state. Never restore records from it. Failure/interruption restores all outputs, including deleted state; unknown/corrupt annotation metadata or opaque legacy prose stops for inspection. Existing state deletion is an allowed report-only exception only when the file already exists. No state is generated. Ordinary Issue Gate, comparison/input fingerprints and CREATE/IMPORT logic remain unchanged.


## Framework regression and fixture benchmark

During development of this entrypoint, run the full loop with framework scope. This does not mean adding all framework regression to ordinary issues. `issues_scan.checks.py` checks isolated fixtures using existing checks format; `--benchmark --log-dir /tmp/issues-performance` repeatedly measures A (ordinary path equivalent to before changes in current checkout)/B (the same ordinary checks plus per-service reference comparison)/C (batch scan) with the same runtime, fresh cache, and no profile. Place benchmark fixtures and diagnostics only outside the repository.

Measure A/B LLM volume as old-skill-required full model/Markdown reads and list reediting; C as actual scan stdout plus minimal review JSON UTF-8 bytes/characters. Add required rule input to A/B/C under the same conditions; C stdout shares patterns/scope/paths without duplicate body output. Actual LLM tokens, LLM wall time, and total actual project time are unmeasured. Do not call fixture Python scan/material extraction/formatting/saving whole-path wall/process/read/parse/decode/decision coverage measurements actual speed of the entire skill. Post-save local loops and actual LLM time are excluded from this benchmark and unmeasured. Separate read_text from input-integrity read_bytes; also include staged models in aggregation.

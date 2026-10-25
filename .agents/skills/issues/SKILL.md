---
name: issues
description: Use when locally investigating/validating the specified AWS Blueprint environment, target, and service and saving/updating issue lists under issues, or when saving already presented investigation results. AWS API checks are handled by the aws-check skill.
---

[Service Model source authority](../../../framework/rules/model-templates.md) applies.
Read the environment-specific properties through `model.sources.load_model` and
`model/cli.py trace <service.properties> <key>`. Edit desired/display/reference keys
only within the selected Task; authorized observations change only the selected
`observed.row.<id>.value`. Record the entry and actual parts, required incoming
consumers and generated paths in the Task. Read dependencies grant no write scope.
Retain this skill's deployment target and AWS permission boundary.


Follow [task-contract](../../../framework/rules/task-contract.md) for save/repair contract registration.


# Issue organization

The common authority for this skill is maintained in the `ai-driven-infra-blueprints` repository.

For ordinary investigation, use the Python entrypoint in [Scoped scan and saving](../../../framework/rules/issues-investigation.md) and check only mechanical diagnostics + all naming materials + remaining judgment points. Do not routinely reread full model/Markdown/IaC, rerun equality confirmation, or have the LLM re-edit full reports.

Save confirmed problems/validation errors within the requested scope to `issues/<environment>/<target-directory>/issues.md`. Python formats/saves model desired → local IaC differences to a separate `iac-issues.md`; do not mix them into ordinary issues. Separate uncompared items and processing errors from difference counts; IaC differences themselves are non-blocking. Replace both reports from the same whole-target Snapshot on each publication. AWS API checks and SDK current-value retrieval/comparison are not included in this skill. Handle AWS check requests with [aws-check](../aws-check/SKILL.md); do not automatically start them from issues execution. Do not start design/model/IaC repair or deploy/apply.

External already acquired evidence may be included in the whole Scan Review, within the authorized scope. It cannot directly update a partial target report or prove unexecuted AWS checks succeeded.

## Saving and updating

- Treat saving as a `migration` task. Read AGENTS and Local loop; register its own contract first with exact authorized service Validation scope, report paths, Requirement IDs and exists Acceptance. Allowed paths / Modified files contain only the reports and its own Task. Human confirmations are read-only and remain outside both declarations. Model/IaC/AWS writes remain forbidden.
- Run this report-only task in the selected repository checkout without a worktree. Use `issues_save_only()` to identify its contract and service scope. Do not collect or compare repository Git changes (HEAD, worktree, index or untracked files) for investigation, saving, validation or completion. Other Tasks' changes are not this Task's changes. Enforce Allowed paths on the actual report destinations; Model/IaC/AWS writes remain forbidden.
- Do not monitor or compare scan inputs or reject publication when they change. Save the reviewed Scan artifact with its execution time and confirmed/unverified scope even when inputs changed during or after scanning. No change-triggered rescan, renewed review or warning is required. Retain Scan/Review IDs and complete review validation; never promote failed/unverified diagnostics to PASS.
- Save with the same environment/target directory structure as `docs/designs/<environment>/<target-directory>/`. Separate multiple targets into different files and create only necessary directories.
- Generate both reports from this Scan and complete LLM Review only. Never read old reports as inputs, preserve service blocks, recover old IDs, or decide old Issue state. Require whole-target `target_services`/`services`/`service_results` coverage before publication; refuse partial scope and report missing services without expanding investigation. Failed/unexecuted checks remain unverified/processing errors, including when there are zero numbered Issues.
- Record Scan execution time (Asia/Tokyo) and this confirmed scope at the file start. Explicitly state any unverified scope at the start. Even when the target has no remaining problems, retain the file and record `未解決issueなし` and confirmed scope. Do not add history/timestamp-specific files.
- After saving, complete final validation under [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy); report links to saved files and validation results in chat. Even on validation failure, retain saved investigation results and report failure; do not proceed to out-of-scope repair or another task.

## Scope confirmation

- Confirm environment/target using `project.json` and target file paths. Use aliases for targets with aliases, or AWS account IDs without aliases.
- Python confirms services using authoritative service metadata and mechanical design-integrity diagnostics; do not mix problems from different environments/aliases in one block.
- For reference inconsistencies, the existing target-service-scoped validator compares resources, names, and anchors in current `docs/designs/**` and corresponding `model/**` within the same environment/target. The LLM additionally retrieves only corresponding resources necessary for non-mechanized/diagnostic judgments. Do not conclude resources are absent by looking only at files before relocation or another environment.
- Ask if the target is unclear; do not automatically expand to another environment/target/service.
- Record inability to execute or compare as unverified scope with the check/target/specific error; do not infer an AWS resource problem instead. Record specific validation errors detected by executed checks as issues; do not treat unexecuted checks as successful.
- Even if an undeployed generated ID is `PENDING_DEPLOY`, do not treat it as a missing reference if the design reference target resolves. For a validated IMPORT reference, `pending_deploy` is `excluded`, not missing, uncompared or repair-required. Record other items unconfirmed in this investigation in unverified scope.

Issues uses `check_display=False` without Model/saved Markdown display synchronization
or generation equality. Do not register display-only differences (string/link,
link-label or JSON/policy presentation) as Issues. Retain saved Markdown internal
consistency, reference destination validity and Resource identity checks. Preserve
every actual diagnostic ID and aggregate only in Report by
environment/target/service/cause_key. Retain dependent NOT_RUN reasons and scope.
Retain independent Model schema/required values, typed
`$modelRef` syntax/logicalId/attribute/target checks, invalid Resource references,
existing Markdown link destinations/anchors, resource identity/ownership/naming,
CodeBuild PLAINTEXT reference prohibition and substantive Model/IaC comparison.
Generation/synchronization validation and the common Validator remain strict by default.

## Issue registration decisions

- WARNING diagnostics, including unresolved/unverified CloudFormation intrinsics (`json.intrinsic.unresolved`), are not numbered issues and do not increase unresolved-Issue counts. Keep them in the existing scan `warnings` channel and non-numbered warning section; never promote them to ERROR/BLOCKER because deployment, physical IDs, external values or local function support are pending. Retain function, JSON Pointer, Property and reason. Keep unresolved comparisons as uncompared in `iac-issues.md`, while retaining validated IMPORT deferred/excluded classifications and comparing proven values; never count them as MATCH. Preserve actual JSON syntax, proven intrinsic-structure, Model-integrity and prohibited Resource-link errors as ordinary issues.
- Register numbered issues only when evidence confirms a specific inconsistency, applicable rule violation, missing mandatory design value, or reproducible failure of a specified check for the target resource/property. Do not use the fact that this investigation did not check AWS APIs/behavior, optional implementation notes, or account/region string differences alone as problem evidence. Summarize unverified scope as ordinary text at the start, separate from numbered issues under services.
- Read all Human facts from the required separate human-confirmations.yaml; no Markdown extraction or automatic migration. Require exact structured Environment/Target/Service/Resource/Property/Rule correspondence and the Human exception's diagnostic_id/condition before excluding a diagnostic. Missing identities and `*` never authorize exclusion. Current reason/evidence cannot override structural mismatch. Contradictions retain the Issue and a Human conflict/unverified notice. Follow the single [Human file contract](../../../framework/rules/issues-investigation.md#independent-human-confirmations); require schema v2, report missing/invalid fields and refuse unsupported data without migration. Never write the Human file or store Issue history in it. Changes to confirmed facts require an independent explicitly authorized Task with ordinary permissions.
- Follow `framework/rules/observed-values.md` and `model-information.md` for ARNs; distinguish generated current ARNs from existing or human-provided design inputs. Do not conclude an ARN is generated solely because the string is an actual ARN or appears in desired notes. If evidence that the prohibition applies is insufficient, state the confirmation-scope limitation and do not create a rule-violation issue. Retain the prohibition on saving generated ARNs.

## Naming rule confirmation

For local investigation, read [aws-resource-naming](../../../framework/rules/aws-resource-naming.md), [Model authority](../../../framework/rules/model-information.md#model-authority), [Properties format](../../../framework/rules/model-information.md#properties-format), [Markdown structure](../../../framework/rules/detailed-design.md#markdown-structure), and target resource display/reference sections. Do not treat local loop naming diagnostics alone as completed pattern-conformance confirmation. If only saving already investigated results is requested, do not automatically add reinvestigation; explicitly state unperformed naming confirmation scope.

- Python validates/parses target service authoritative properties once from entry indexes/parts and extracts all resource names and actual file/part/key/line positions. From all extracted materials, the LLM confirms selected `desired.*` name properties, mandatory `.Name`, and mandatory or human-selected `Name` tags. Do not limit confirmation to names in diagnostics; judge independent child resources by their own resourceMode. Do not use observed values or generated Markdown display labels as name authority.
- For CREATE (including unspecified mode), map resource types/formal properties to naming rule Naming targets and confirm coverage, patterns, service-specific constraints, and mandatory Name presence. Compare `environment`, `target_alias`, `account_id`, and `region` against the `project.json` target, and application/purpose etc. against human-confirmed components. Do not infer unknown components from name strings and treat them as conforming.
- Do not apply framework naming conventions, coverage, or mandatory Name policy to IMPORT. Confirm evidence/applicable scope and respect property-specific exemptions and naming exceptions explicitly stated by the human. Do not extend coverage-only exemptions to pattern/value validation exemptions. Do not apply name patterns to AWS-generated IDs/ARNs/DNS names/IPs/display labels. Retain provider schema, catalog, reference, and confirmed-value validation.
- Record applicable mismatches, unregistered naming rules, and missing mandatory Names as problems supported by the target resource/property/actual value and applicable rule. For insufficient component/exception evidence or read/validation failures, specify missing confirmation as `未確認`; do not treat it as `問題なし` or resolved.
- Resolve reference values to desired targets in the same environment/target and distinguish them from name properties. If the reference target service is within investigation scope, collect naming mismatches under that service. For out-of-scope services, confirm only information necessary for reference resolution; do not automatically expand to naming investigation. Do not correct names, rename, add tags, or change models.

## Output

- Do not record work/completion reports or execution history such as “調査しました”, “保存しました”, or “検証PASS” in issue-list Markdown; report them only in chat. Also remove existing work reports from the scope being updated. Retain update time, confirmed/unverified scope, and diagnostics necessary as problem evidence.
- For ordinary `issues.md`, use `環境／alias` as H2 and service names as H3, followed by numbered lists. Without an alias, use `環境／AWS account ID` as H2.
- Start numbering at 1 for each service block and state one problem per item. Do not create empty blocks.
- Briefly and specifically state the target resource/property and what is inconsistent/missing/unconfirmed for each problem. Attach its undecided point only when necessary judgments can be confirmed.
- For ordinary `issues.md`, combine repeated diagnostics with the same cause within the same environment/target/service, stating counts and targets. Do not confuse diagnostic counts, resource counts, and derived errors.
- Use paths relative to the saved file for issue evidence links. Put line numbers in display text, such as `[athena.md:20](../../../docs/designs/dev/cde/athena.md)`, rather than in link targets. Retain Scan-time source paths and positive line numbers without rereading current input files; do not save absolute paths. Enclose link targets in `<...>` if paths contain spaces.
- Add remedies/priorities when requested; limit output to the list when only an issue list is requested.

### IaC classification summary

- Use Python's bounded cause/action summary; do not reread/reaggregate all records or paste the whole `iac-issues.md` into chat. Retrieve required naming/judgment pages through `detail` and review every ID before saving.
- Both Markdown files are generated anew from the same reviewed whole-target Snapshot; no previous results, Human prose or service blocks are carried forward.
- See [IaC report grouping and publication](../../../framework/rules/issues-investigation.md#iac-report-grouping-and-publication) for limits, omission counts, temporary artifact detail, masking and publication safety. No legacy state migration or deletion is part of saving.

Output example (`issues/dev/cde/issues.md`):

```markdown
# 問題一覧

Scan実行日時: 2026-09-30 12:00:00 Asia/Tokyo
今回確認した範囲: dev／cdeのMacie

## dev／cde

### Macie

1. 個人情報用の旧bucket参照が切れており、現在のどの個人情報用bucketを対象にするか未確定。
2. 部門データ用の旧bucket参照が切れており、現在のどの部門別bucketを対象にするか未確定。

```

Save `dev／non-cde` problems to `issues/dev/non-cde/issues.md` in the same format.

Follow AGENTS.md “How to read required rules” for reading rules. Read [project-configuration](../../../framework/rules/project-configuration.md) for target determination and account/profile validation. Only for repository changes, additionally read [task-contract](../../../framework/rules/task-contract.md), [Local loop](../../../framework/rules/loop-engineering.md#local-loop), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), and [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion).

Only for framework changes, additionally read [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression).

## IaC Issue handoff to repair tasks

Use the complete compact Issue list independently of the 16 detailed groups. The 10 examples and 10 fields are display limits, never repair scope limits. For a subsequent explicitly authorized repair task, use each `ISSUE-<id>` with the same external artifact and `issues_scan.py detail --section iac --issue-id ISSUE-<id> --artifact <path> --offset 0 --limit 50`; advance offset until every `iac_issues[].members` record is inspected. Distinguish a common repair from member-specific decisions and recompare all members afterward. Interrupted/uncompared records remain unverified and cannot be called resolved. Do not start Model/IaC repair from this investigation skill.

## Immutable Snapshot and local lint

The scan emits only version 5. Read naming_context once and every naming/judgment/Human confirmation page. Submit exact Scan/context and all reviewed ID sets, current diagnostic assignments/decisions, additional current issues and unverified scope. Follow the [complete Review and Human file contract](../../../framework/rules/issues-investigation.md#commands-and-complete-review). Unsupported artifacts and extra/old Review fields are rejected. There is no partial-result saving API.

Keep comparison categories separate: `deferred` means reference comparison is on hold, `excluded` means outside the current comparison, `uncompared` means resolution/comparison could not complete, and `error` means a processing/evaluation failure. For validated IMPORT references subject to the existing handoff checks, `unobserved` and `awaiting_handoff` are deferred; `pending_deploy` is excluded. Deferred/excluded records remain in the artifact but receive no Issue ID and do not enter Issue counts. Deferred contributes to partial; pending_deploy does not contribute to uncompared, partial or repair-required counts. Its normal Markdown display is a dedicated exclusion count; causes remain available through explicit detail. Follow the existing [classification and aggregation contract](../../../framework/rules/issues-investigation.md#comparison-coverage).

Raw cfn-lint is planned from explicit selected CREATE Stack/template mappings independently of comparison success; shared templates lint once per region/policy, without auto-injecting Stack parameter files. IMPORT/API-only/Terraform are not_applicable. Respect effective HOME/cwd/Metadata configuration and offline schema selection. Missing/excluded/unmapped/unexecuted coverage remains unverified. Concrete owned template Errors become ordinary candidates; common/multiple/unknown ownership requires judgment and diagnostic_assignments. Proven scope-external resource diagnostics do not fail selected services. E0000 needs concrete decode provenance; I/O/internal failures and E0001/2/3 default to processing errors. Warning and Informational stay separate and non-numbered. Suppressed syntax diagnostics still leave downstream rule coverage incomplete.

Use validation_status ERROR/FAIL/INCOMPLETE/CHECKED separately from iac_status, review_required, lint coverage and publication_status. scan returns 2 for processing/input failures, 1 for ordinary/unassigned Error, otherwise 0. A saved artifact with processing errors reports SAVED and exit 2; preservation of acquired results does not make processing successful. Warning/Info or coverage-only do not promote to ordinary issues.

Retrieve bounded summary channels through detail for full coverage; do not ask for all raw diagnostics on stdout. Save the reviewed artifact without comparing current inputs or lint dependencies. Machine notices are scope-marked, non-numbered and generated only from the current Scan. Human confirmations come exclusively from the separate file. After saving, run `blueprint-loop.py --mode local --task-file tasks/<task-name>.md`
without `--write`, `--all` or `--staged`. For an `issues_save_only()` Task this checks
only the report save contract using existing Task/save authority checks: explicit
services, running status, Required changes/Allowed paths/Modified files, both readable
report files and exact `exists:` Acceptance checks for both. Do not rerun generic
scope/input presence, Model/design/display/IaC validation, Scan, cfn-lint, AWS or Git
diff checks. Snapshot/Review/publication guards remain at save time. Treat
publication_status, Scan validation_status and actual post_save_validation as separate
results; save returns NOT_RUN plus the command until Local Loop executes. A valid save
may be SAVED / Scan FAIL / post-save PASS; processing errors still return 2.
Retain saved reports if post-save validation fails. See [issues investigation](../../../framework/rules/issues-investigation.md#offline-cfn-lint-and-coverage) for the complete contract.

---
name: issues
description: Use when locally investigating/validating the specified AWS Blueprint environment, target, and service and saving/updating issue lists under issues, or when saving already presented investigation results. AWS API checks are handled by the aws-check skill.
---

Follow [task-contract](../../../framework/rules/task-contract.md) for save/repair contract registration.


# Issue organization

The common authority for this skill is maintained in the `ai-driven-infra-blueprints` repository.

For ordinary investigation, use the Python entrypoint in [Scoped scan and saving](../../../framework/rules/issues-investigation.md) and check only mechanical diagnostics + all naming materials + remaining judgment points. Do not routinely reread full model/Markdown/IaC, rerun equality confirmation, or have the LLM re-edit full reports.

Save local investigation results/validation errors within the requested scope to `issues/<environment>/<target-directory>/issues.md`. Python formats/saves model desired → local IaC differences to a separate `iac-issues.md`; do not mix them into ordinary issues. Separate uncompared items and processing errors from difference counts; IaC differences themselves are non-blocking. Update the same file on each execution. AWS API checks and SDK current-value retrieval/comparison are not included in this skill. Handle AWS check requests with [aws-check](../aws-check/SKILL.md); do not automatically start them from issues execution. Do not start design/model/IaC repair or deploy/apply.

If saving separately retrieved/investigated AWS check results is requested, treat those results as evidence and reflect them in the list without calling AWS APIs. Do not treat local validation alone as confirmation of current AWS value equality or problem resolution.

## Saving and updating

- Treat saving as a `migration` task. Before changes, read `AGENTS.md` and [loop Local loop](../../../framework/rules/loop-engineering.md#local-loop); newly register `tasks/<task-name>.md` with this scope/Goal as the first repository change. Explicitly state the target environment/target/service in Validation scope. Limit Allowed paths to `tasks/<task-name>.md` and this task's target issue-list files (`issues.md` and `iac-issues.md` for ordinary investigation, only `issues.md` for saving already retrieved ordinary results); record Requirement IDs and corresponding `exists:` Acceptance checks for each Required change.
- This save-only task is exempt from stop decisions due to existing issues. Continue investigation/list updates even with unresolved issues; do not add repair exceptions through Issue remediation. Ordinary issue gates apply to design/model/IaC changes and AWS mutation.
- Save with the same environment/target directory structure as `docs/designs/<environment>/<target-directory>/`. Separate multiple targets into different files and create only necessary directories.
- For ordinary `issues.md`, Python extracts existing list scope/ownership/human confirmation. The LLM checks only existing issues with unconfirmed correspondence; immediately before saving, Python rereads, uses shared mutual exclusion, and atomically writes scope-limited updates. Remove only resolutions supported by explicit revalidation; retain problems absent from the new scan. Retain problems with detected specific inconsistencies/deficiencies whose resolution is unconfirmed, stating that they are unconfirmed. Do not register unverified scope alone as a new issue. Preserve services/problems outside this scope.
- Record update time (Asia/Tokyo) and this confirmed scope at the file start. Explicitly state any unverified scope at the start. Even when the target has no remaining problems, retain the file and record `未解決issueなし` and confirmed scope. Do not add history/timestamp-specific files.
- After saving, run `python3 framework/scripts/blueprint-loop.py --mode local`; report links to saved files and validation results in chat. Even on validation failure, retain saved investigation results and report failure; do not proceed to out-of-scope repair or another task.

## Scope confirmation

- Confirm environment/target using `project.json` and target file paths. Use aliases for targets with aliases, or AWS account IDs without aliases.
- Python confirms services using authoritative service metadata and mechanical generated-design diagnostics; do not mix problems from different environments/aliases in one block.
- For reference inconsistencies, the existing target-service-scoped validator compares resources, names, and anchors in current `docs/designs/**` and corresponding `model/**` within the same environment/target. The LLM additionally retrieves only corresponding resources necessary for non-mechanized/diagnostic judgments. Do not conclude resources are absent by looking only at files before relocation or another environment.
- Ask if the target is unclear; do not automatically expand to another environment/target/service.
- Record inability to execute or compare as unverified scope with the check/target/specific error; do not infer an AWS resource problem instead. Record specific validation errors detected by executed checks as issues; do not treat unexecuted checks as successful.
- Even if an undeployed generated ID is `PENDING_DEPLOY`, do not treat it as a missing reference if the design reference target resolves. Record items unconfirmed in this investigation in unverified scope.

## Issue registration decisions

- Register numbered issues only when evidence confirms a specific inconsistency, applicable rule violation, missing mandatory design value, or reproducible failure of a specified check for the target resource/property. Do not use the fact that this investigation did not check AWS APIs/behavior, optional implementation notes, or account/region string differences alone as problem evidence. Summarize unverified scope as ordinary text at the start, separate from numbered issues under services.
- For items the human explicitly states are confirmed for scope/configuration/behavior, retain the confirmed scope and that the evidence is human confirmation at the start. Do not relist them as unconfirmed without concrete contradictory diagnostics. Do not substitute human confirmation for this execution of AWS APIs or success of unexecuted checks; do not remove unrelated existing issues.
- Follow `framework/rules/observed-values.md` and `model-information.md` for ARNs; distinguish generated current ARNs from existing or human-provided design inputs. Do not conclude an ARN is generated solely because the string is an actual ARN or appears in desired notes. If evidence that the prohibition applies is insufficient, state the confirmation-scope limitation and do not create a rule-violation issue. Retain the prohibition on saving generated ARNs.

## Naming rule confirmation

For local investigation, read [aws-resource-naming](../../../framework/rules/aws-resource-naming.md), [Model authority](../../../framework/rules/model-information.md#model-authority), [Properties format](../../../framework/rules/model-information.md#properties-format), [Markdown structure](../../../framework/rules/detailed-design.md#markdown-structure), and target resource display/reference sections. Do not treat local loop naming diagnostics alone as completed pattern-conformance confirmation. If only saving already investigated results is requested, do not automatically add reinvestigation; explicitly state unperformed naming confirmation scope.

- Python validates/parses target service authoritative properties once from entry indexes/parts and extracts all resource names and actual file/part/key/line positions. From all extracted materials, the LLM confirms selected `desired.*` name properties, mandatory `.Name`, and mandatory or human-selected `Name` tags. Do not limit confirmation to names in diagnostics; judge independent child resources by their own resourceMode. Do not use observed values or generated Markdown display labels as name authority.
- For CREATE (including unspecified mode), map resource types/formal properties to naming rule Naming targets and confirm coverage, patterns, service-specific constraints, and mandatory Name presence. Compare `environment`, `target_alias`, `account_id`, and `region` against the `project.json` target, and application/purpose etc. against human-confirmed components. Do not infer unknown components from name strings and treat them as conforming.
- Do not apply framework naming conventions, coverage, or mandatory Name policy to IMPORT. Confirm evidence/applicable scope and respect property-specific exemptions and naming exceptions explicitly stated by the human. Do not extend coverage-only exemptions to pattern/value validation exemptions or automatically apply env-diff-only exceptions to issues. Do not apply name patterns to AWS-generated IDs/ARNs/DNS names/IPs/display labels. Retain provider schema, catalog, reference, and confirmed-value validation.
- Record applicable mismatches, unregistered naming rules, and missing mandatory Names as problems supported by the target resource/property/actual value and applicable rule. For insufficient component/exception evidence or read/validation failures, specify missing confirmation as `未確認`; do not treat it as `問題なし` or resolved.
- Resolve reference values to desired targets in the same environment/target and distinguish them from name properties. If the reference target service is within investigation scope, collect naming mismatches under that service. For out-of-scope services, confirm only information necessary for reference resolution; do not automatically expand to naming investigation. Do not correct names, rename, add tags, or change models.

## Output

- Do not record work/completion reports or execution history such as “調査しました”, “保存しました”, or “検証PASS” in issue-list Markdown; report them only in chat. Also remove existing work reports from the scope being updated. Retain update time, confirmed/unverified scope, and diagnostics necessary as problem evidence.
- For ordinary `issues.md`, use `環境／alias` as H2 and service names as H3, followed by numbered lists. Without an alias, use `環境／AWS account ID` as H2.
- If the service name differs from the model service ID, place `<!-- issue-service: <service-id> -->` so the issue gate can determine ownership.
- Start numbering at 1 for each service block and state one problem per item. Do not create empty blocks.
- Briefly and specifically state the target resource/property and what is inconsistent/missing/unconfirmed for each problem. Attach its undecided point only when necessary judgments can be confirmed.
- For ordinary `issues.md`, combine repeated diagnostics with the same cause within the same environment/target/service, stating counts and targets. Do not confuse diagnostic counts, resource counts, and derived errors.
- Use paths relative to the saved file for issue evidence links. Put line numbers in display text, such as `[athena.md:20](../../../docs/designs/dev/cde/athena.md)`, rather than in link targets. Confirm target file existence and line numbers; do not save absolute paths. Enclose link targets in `<...>` if paths contain spaces.
- Add remedies/priorities when requested; limit output to the list when only an issue list is requested.

### IaC classification summary

- Reuse `iac_actions()` and unchanged stable Issue IDs. Proven causes may aggregate causally; unknowns remain independent Issues even when grouped for display. Categories are 要対応, 要判断, 比較未完了, 処理エラー, 原因未確定. Do not count cascaded uncompared records as independent actual failures.
- The summary states Environment/Target/Services, execution time, comparison status, per-category independent Issue counts, proven cause count, all original record counts, direct difference resource count, uncompared and processing-error counts. Display grouping never alters comparison decisions or Issue membership.
- Display at most 8 groups and 3 examples per group, at most 1 differing field per example, and at most 160 characters per displayed value. State every omission. Keep cause, remedy, Service/Stack impact and explicit unknown cause/target; retrieve omitted groups/Stacks/full values from the artifact. Model and IaC appear vertically. Normal mismatch output contains no file paths/line numbers; full metadata remains in the artifact. Machine Markdown normally stays below 300 lines, capped around 500; preserved human notes may exceed this.
- Scan stdout contains summaries and bounded examples only. Retrieve every naming/judgment page with `detail`; save still requires every ID reviewed. Do not equate output omission with validation omission.
- IaC reports show only this run's Scope. Never merge/restore old results, infer resolution from absence, or treat out-of-scope services as compared. `issues.md` retains its existing conservative service/history behavior unchanged.
- All full records, masked field data and Issue membership belong to the temporary external scan artifact. `detail --section iac_issues` lists Issues; `--section iac --category <分類> --issue-id ISSUE-<id> --offset 0 --limit 50` retrieves members, applying filters before pagination. No additional comparison, Model/IaC parse or AWS calls.
- Never save state or embedded JSON. Only when an old state/embedded report exists, read annotation metadata once for disposal, preserve contextual human notes, reserve the exact legacy state deletion path and remove it in the atomic report batch with rollback. Corrupt annotation metadata or opaque legacy prose blocks replacement for inspection, without discarding old files. New human notes belong outside `iac-summary:start/end`, normally under `## 人間注記`; generated content inside those markers is replaced on each save.
- Keep input fingerprints, Scope/Allowed paths, reservations, publication locks, atomic write/rollback, secret/ARN/NoEcho masks, ordinary Issue Gate and CREATE/IMPORT decisions. State digests, result restoration/history merging and sidecar generation are abolished.

Output example (`issues/dev/cde/issues.md`):

```markdown
# 問題一覧

更新日時: 2026-09-30 12:00:00 Asia/Tokyo
今回確認した範囲: dev／cdeのMacie

## dev／cde

### Macie

<!-- issue-service: macie -->

1. 個人情報用の旧bucket参照が切れており、現在のどの個人情報用bucketを対象にするか未確定。
2. 部門データ用の旧bucket参照が切れており、現在のどの部門別bucketを対象にするか未確定。

```

Save `dev／non-cde` problems to `issues/dev/non-cde/issues.md` in the same format.

Follow AGENTS.md “How to read required rules” for reading rules. Read [project-configuration](../../../framework/rules/project-configuration.md) for target determination and account/profile validation, and [issue-gate](../../../framework/rules/issue-gate.md) for stop and investigation/repair/save exception decisions. Only for repository changes, additionally read [task-contract](../../../framework/rules/task-contract.md), [Local loop](../../../framework/rules/loop-engineering.md#local-loop), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), and [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion).

Only for framework changes, additionally read [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression).

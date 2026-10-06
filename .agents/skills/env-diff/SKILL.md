---
name: env-diff
description: Use when comparing selected desired properties pairs from dev→stg/stg→prod and cde/non-cde using the comparison source as authoritative, briefly summarizing differences per service, and saving them to the comparison destination's diff.md.
---

Follow [task-contract](../../../framework/rules/task-contract.md) for save/repair contract registration.


# Desired comparison between environments

The common authority is maintained in the ai-driven-infra-blueprints repository.

## Comparison

- Read `AGENTS.md`, [Model authority](../../../framework/rules/model-information.md#model-authority), [Properties format](../../../framework/rules/model-information.md#properties-format), [loop Local loop](../../../framework/rules/loop-engineering.md#local-loop), and [aws-resource-naming](../../../framework/rules/aws-resource-naming.md).
- Comparison candidates are 4 pairs: dev↔stg/cde, stg↔prod/cde, dev↔stg/non-cde, and stg↔prod/non-cde. Select only requested pairs; ask if comparison pairs are unspecified. Do not automatically expand to all 4 pairs. Confirm `project.json` environments and confirmed aliases only for selected pairs. Do not infer correspondence to other aliases/accounts; report deficiencies as unconfirmed.
- Treat desired values in the preceding environment as authoritative (comparison baseline). For dev→stg, dev is the baseline; for stg→prod, stg is the baseline. Treat JSON `left` as baseline and `right` as comparison destination. Record `不足` when the destination lacks a baseline resource/property, `追加` when it exists only in the destination, and `値の相違` when values differ on both sides.
- Select environment pairs with `--pair dev-stg` or `--pair stg-prod` and targets with `--target cde` or `--target non-cde`. Specifying both selects 1 pair; specifying only pair compares its 2 targets. Do not read unselected models. Incomplete prod is unnecessary for dev↔stg alone.
- Read model entries/split parts with the existing reader and compare only `desired.*`. `observed.*`, `display.*`, current AWS values, and CFn/Terraform comparison are out of scope. Without service specification, target the union of all service entries on both sides of each pair.
- Exclude resources with `desired.resource.<番号>.resourceMode=IMPORT` from comparison. Do not include their setting values, names, comments, JSON, or resource metadata in differences/naming confirmation or count them as missing/additional/unconfirmed/rule mismatches. If one side is IMPORT in a pair with the same Logical ID or confirmed resource correspondence, exclude both sides of that resource pair from comparison. Compare unspecified mode as CREATE; do not infer unknown mode as IMPORT. Judge independent child resources by their own mode; do not automatically exclude CREATE children solely because their parent is IMPORT.
- Do not treat IMPORT existing on only one side as missing/additional either. Do not infer correspondence with different IDs. Exclude IMPORT itself; retain opposing CREATE resources with unconfirmed correspondence as unconfirmed. Confirm necessary correspondence using existing design/instructions as evidence and pass it to `--resource-map`. Record excluded resources in JSON `excluded` with side/type/Logical ID/mode/exclusion reason/file/line. Also exclude `resource_matches` entries with `excluded=true` from comparison counts.
- Do not count derived `ownedCatalogResourceTypes` lists of services containing IMPORT as specification differences; compare remaining CREATE resources individually. If IMPORT exclusion leaves 0 comparison resources on both sides, do not count service metadata as differences either. Do not exclude common notes or stack/deployment settings by inferring resource ownership. Compare CREATE references to IMPORT as CREATE settings. Do not compare reference-target IMPORT settings/name conformance; confirm only identity information needed for correspondence confirmation.

```console
# dev↔stg／cdeだけ:
python3 -B framework/scripts/compare-environments.py --pair dev-stg --target cde
# dev↔stgのcde／non-cdeだけ:
python3 -B framework/scripts/compare-environments.py --pair dev-stg
# 全4組を明示依頼された場合:
python3 -B framework/scripts/compare-environments.py
```

- To limit services, add selectors such as `--service vpc --service iam`. The program without arguments compares all 4 pairs; do not omit selectors for limited requests.
- If multiple selected comparisons can be processed in 1 command, do not split them into separate processes per pair without reason. Since common model parse results are reused within the same CLI execution, run the above argument-free command once when all 4 pairs are explicitly requested. For limited requests, retain existing selectors; do not add unselected pairs/targets/services for performance.
- stdout is JSON containing `status`, compared `services`, `differences`, `difference_count`, `environment_differences`, `errors`, `resource_matches`, `unconfirmed`, and `excluded` for each selected pair. `difference_count` is the count of Python-detected `differences` after excluding confirmed environment differences. Save to a temporary file outside the repository as needed and read pairs individually. Completed comparison exits 0 even with differences; missing inputs/read failures/stale exclusion specifications yield `incomplete`, and unconfirmed resource correspondence yields `unconfirmed`, with exit code 1. Confirm raw fields/values/files/line numbers in comparison JSON; do not transcribe all into diff.md. Even with `difference_count=0`, do not treat `incomplete`, `unconfirmed`, or empty compared services as “問題なし”. Even if IMPORT exclusion alone leaves 0 comparison targets, do not treat IMPORT settings as matched; retain exclusion reasons in internal JSON.
- Do not include Logical IDs themselves in environment specification differences. Retain `logicalId` and display-name-derived `anchor` as correspondence evidence, but do not treat their string differences alone as missing/additional/value differences. Handle Logical ID change impacts in existing CloudFormation stack updates separately from this desired environment comparison.
- Initially compare resources with `resourceType` + the same `logicalId` as correspondence candidates. Do not automatically treat resources with different Logical IDs as missing/additional; output them in `unconfirmed`. Do not determine correspondence solely from the same type, resource count, numbering, ordering, or similar setting values. Confirm the same role from formal names, uses, parent-child relationships, reference targets, and human instruction/current design evidence. Reconsider even same-Logical-ID correspondence if roles differ.
- Once correspondence is confirmed, create JSON outside the repository with the selected single pair's `left`, `right`, `target`, and `resources` in the following format; add `--resource-map <file>` and recompare the same pair/services. This argument requires `--pair` and `--target`. `left`/`right` are each model's Logical IDs; `resourceType` is the formal type; `reason` is role/correspondence evidence such as both model files/line numbers. Only for resources confirmed absent on one side, use `null` for that side and compare as missing/additional. Do not pass unselected services, nonexistent IDs, duplicate mappings, or invalid pairs to processing. Do not fill unconfirmed correspondence by inference; save it as unconfirmed.

```json
{
  "left": "dev", "right": "stg", "target": "cde",
  "resources": [
    {"service": "logs", "resourceType": "Logs.LogGroup",
     "left": "DevFlowLogs", "right": "StgFlowLogs",
     "reason": "形式例。両側modelの正式名称・用途・参照元で同じ役割と確認した根拠を記載"}
  ]
}
```

- After confirming allowed environment differences through initial comparison and the AI judgments below, specify them in optional `environment_differences` in the same resource-map JSON. Use comparison JSON `service`/`identity` unchanged for each entry; put both sides' actual strings in `left`/`right` as their `value` and evidence confirming the allowed environment difference in `reason`. Retain `resources` determining resource correspondence too. If only same Logical IDs are involved, `resources: []` is acceptable. AI creates the temporary file outside the repository; do not require the human to edit files. Do not infer allowances by uniformly replacing environment/account etc. in strings.

```json
{
  "left": "dev", "right": "stg", "target": "cde",
  "resources": [
    {"service": "athena", "resourceType": "Athena.WorkGroup",
     "left": "DevReport", "right": "StgReport", "reason": "形式例。同じ用途の対応確認根拠"}
  ],
  "environment_differences": [
    {"service": "athena",
     "identity": ["row", "Athena.WorkGroup", "DevReport", "Athena.WorkGroup.Name", "1", "value"],
     "left": "athwg-app-dev-reporting", "right": "athwg-app-stg-reporting",
     "reason": "形式例。両側の命名適合と同じ用途の環境別名称を確認した根拠"}
  ]
}
```

- After confirmation, recompare with the same single pair/services and `--resource-map`. Python validates identity and both actual values, removes confirmed items from `differences`, and retains them in `environment_differences` with actual values/evidence/reasons. `excluded` continues to represent only IMPORT resource exclusion. Exclusion specifications for additional/missing items, unconfirmed resources, nonexistent differences, duplicates, and stale values are rejected. On rejection, check exclusions/latest inputs and recompare without excluding unconfirmed items by inference. No recomparison is necessary if there are no exclusion targets.

- Compare mapped resource rows by formal property name + occurrence order of the same property. Do not count resource/row renumbering as differences. Preserve repeated property order. Compare JSON documents with normalized object key order/whitespace and preserve array order. Do not count derived `artifactSha256` matching the document as an independent specification difference. Treat mismatch as input inconsistency making comparison impossible.
- Compare logical references to mapped resources within selected services by mapped targets, rather than display text/anchor strings. Apply this to self identifier references, links to the same/other selected services, parent `parentReference`, and Markdown resource links within JSON documents. Retain differences when reference targets change. Do not automatically replace unselected services, external/cross-target links, or unresolved links. Confirm necessary reference-target correspondence in AI organization; treat insufficient confirmation as unconfirmed. When the target is a compared CREATE resource, do not omit formal name/name-conformance confirmation.
- Continue comparing actual desired setting values, formal names, comments, resource metadata other than logicalId/anchor, and common notes/stack/deployment settings of compared CREATE resources. Except derived service metadata accompanying IMPORT exclusion, map desired keys outside resources/rows unchanged. Do not uniformly replace/exclude environment names, accounts, names, CIDRs, literal ARNs/IDs, or artifact paths in processing. Exclude only confirmed allowed environment differences through the explicit specifications above.

## AI organization

- For each selected pair, summarize differences/unconfirmed items excluding allowed environment differences per service in short prose/bullets. Attach `その他の差分`/`未確認` categories to necessary items; do not list empty categories or count tables. Use allowed `環境差異` only for internal judgment; do not include them in diff.md/completion report difference targets/counts or show representative examples. Differences may be design differences; do not treat them alone as misconfiguration, unresolved issues, or prohibitions. Use JSON `path`, `line`, `key`, and both values as evidence; additionally confirm only necessary model/existing-design sections.
- Do not include IMPORT-related items in diff.md/completion report difference summaries. Omit resource exclusion targets/reasons as well as differences in common IMPORT implementation notes, import-preparation dummy values, statements that values were not retrieved, actual-value checks before import, IMPORT resource connection confirmation status, etc. If common notes mix design differences unrelated to IMPORT, retain only those parts. Do not relist the presence/absence of service models containing only IMPORT resources as missing/additional/unconfirmed. Handle design differences/unconfirmed items for independent CREATE subscription filters, sending Roles, etc. in their owning services; do not omit them solely because parents/reference targets are IMPORT.
- When showing difference counts, use Python `difference_count` from recomparison with confirmed environment-difference exclusions; do not merely subtract at reporting time. If IMPORT-related notes are omitted from publication and Python counts differ from published targets, do not publish counts. Do not reduce counts merely because prose is combined. JSON retains raw actual values for both remaining `differences` and excluded `environment_differences`. Show unconfirmed/incomparable items separately; do not infer environment differences and exclude them. Do not mix naming rule mismatch counts into environment value-difference counts.
- For services without differences, naming rule mismatches, unconfirmed items, or incomparable items, publish neither headings nor bodies in diff.md/completion reports. Do not write explanations such as `比較完了範囲で差分なし` or lists of services without differences.
- Do not output lists of matching settings/uses/Logical IDs or matching methods such as `same_logical_id`. Confirm resource correspondence for comparison; do not publish it as differences. Confirm evidence internally; do not attach evidence links, file line numbers, or confirmation history to diff.md.
- Evaluate the comparison destination against comparison-source desired values. Show expected environment-specific names/accounts/references etc. based on naming rules, explicit naming exceptions, and confirmed environment correspondence. Do not copy actual comparison-source values directly into destination expected values. Record comparison-source naming rule mismatches outside allowed exceptions as baseline-side mismatches; do not treat them as conforming.
- To judge environment differences, confirm evidence such as human instructions, current design, and naming rules. Also confirm reasons for differences in capacity, retention days, feature enablement/disablement, permissions, etc. Treat differences with insufficient evidence as unconfirmed; do not conclude misconfiguration. Combine name/account/reference differences with the same reason; explain differences with different settings/uses separately.
- Briefly record causes/unverified scope for incomparability/unconfirmed resource correspondence; do not treat them as no differences. Do not include unconfirmed resources in missing/additional counts; separate them from differences within mapped scope. Use `resource_matches` and both models for correspondence confirmation; do not publish full correspondence tables or repeated evidence. Logical ID string differences themselves are not specification differences.

### Name/reference difference judgments

- For dev↔stg resources with the same target/role, treat differences in the presence/absence of target identifiers `cde`/`noncde`/`non-cde` in names as harmless `環境差異` allowed by the human. Judge together with dev/stg environment-component differences; do not treat this notation's presence/absence alone as naming rule mismatches, repair requests, or unconfirmed items. Treat both sides as `適合（明示例外）` and exclude from published/counted differences. Do not interpret this as allowing cde↔non-cde replacement between different targets or actual setting differences in uses, permissions, reference targets, etc. Do not automatically extend this dev↔stg exception to stg↔prod.
- For the human's explicit CloudTrail example, treat dev Logical ID `CDECLOUDTRAIL01` with `CloudTrail.Trail.TrailName=venusinf-dev-cloudtrail-cde` and stg Logical ID `CLOUDTRAIL01` with `CloudTrail.Trail.TrailName=venusinf-stg-cloudtrail` as corresponding resources; classify the TrailName difference as `環境差異（許容された環境固有名称）` and exclude it from published/counted differences. Allow both entire names as this explicit exception; differences from the general `ctrail-...` pattern are also not reasons to relist this example as a rule mismatch. Do not include Logical ID differences themselves as specification differences. Apply this exception to env-diff classification; do not change model values/common naming rules.
- Do not treat a name containing dev/stg/prod with the same identity alone as `環境差異`. For formal properties in each environment, confirm naming rule applicability/exceptions/patterns and compare against `project.json` environment/alias/account/region and human-confirmed application/purpose etc. Do not infer unknown components from values and treat them as conforming.
- Confirm `適合` (`適合（明示例外）` for explicit exceptions), `不一致`, `適用対象外`, and `未確認` for each side. Apply explicit human exceptions, including those above, before general patterns. If an applicable name outside allowed exceptions differs from the pattern/confirmed components/target environment, classify it as `その他の差分（命名規則不一致）`; do not combine it into environment differences. Briefly show targets/mismatches in diff.md; do not include full expected-pattern/actual-name comparison tables. If missing components or unknown rules prevent judgment, classify it as `未確認`.
- Do not limit naming confirmation to rows in raw JSON differences. For compared resources of selected services, briefly record environment-component etc. rule mismatches in diff.md even if names have the same value in both environments. Distinguish raw environment differences from rule mismatches; combine mismatches with the same reason.
- Exclude IMPORT from comparison/naming confirmation; do not classify name differences as environment differences, other differences, or unconfirmed items. Retain IMPORT exclusion targets/reasons in internal JSON; do not publish them at the start/body of diff.md or create service headings for exclusion explanation alone. For non-IMPORT naming exemptions, briefly state name differences/exemption evidence; do not determine environment differences solely from exemption. This is env-diff comparison/classification scope; do not repair naming rules, models, or existing issues.
- Classify as `環境差異` only when both names conform to applicable rules or explicit human exceptions and components other than environment-varying components are confirmed to represent the same confirmed role. Even if both names conform, classify differing roles such as purpose as `その他の差分`. Internally confirm explicit naming exception evidence and correspondence between both names; exclude allowed environment differences from published/counted differences.
- For compared CREATE reference values, resolve desired reference-target resources/identities and confirm the same role correspondence on both sides. If targets are also compared CREATE resources, resolve formal names too and confirm each environment's naming rule/explicit exception conformance. Exclude reference-target IMPORT setting/name confirmation. Do not apply naming patterns to URLs/ARNs/physical IDs themselves. Confirm Athena OutputLocation bucket/key prefix, KmsKey actual KMS Key/associated Alias, and Scheduler Target connected resource/Role/Input etc. separately. Treat unknown targets as unconfirmed. Do not mix reference-target/prefix/Target setting differences that cannot be confirmed as environment-component-only differences into name differences; retain them as other differences.
- Perform the above confirmation before combining name/reference differences. Exclude environment-specific output buckets/KMS Keys with the same role, or output prefixes for the same department/information category differing only in environment components, from published/counted differences when confirmed as allowed environment differences. Retain differences in output-prefix/connection-target uses, permissions, or actual settings. Record reference-target naming rule mismatches under the target service; do not duplicate publishing/counting the same mismatch at the source. Retain descriptions conveying the uses/contents of remaining diff.md differences; do not explain only with counts/property names. Do not require category counts or judgment lists for all resources/properties.

## Saving to diff.md

- Save brief per-service difference summaries for selected pairs to the comparison-destination environment according to the following mapping table. Do not create/update diff.md for unselected pairs.

| Comparison | target | Save destination |
| --- | --- | --- |
| dev↔stg | cde | `issues/stg/cde/diff.md` |
| dev↔stg | non-cde | `issues/stg/non-cde/diff.md` |
| stg↔prod | cde | `issues/prod/cde/diff.md` |
| stg↔prod | non-cde | `issues/prod/non-cde/diff.md` |

- Save comparison-destination differences using the comparison source as authoritative. Do not transcribe into `issues.md` or change existing issues. Do not count diff.md items as unresolved issues or treat differences as task stop reasons. Desired comparison and diff.md saving are exempt from stop decisions due to existing issues.md. In the save-only migration below, continue AI classification/saving/local validation even with unresolved issues; do not add Issue remediation. Retain ordinary issue gates for design/model/IaC changes and AWS mutation.
- Save as a `migration` task. Newly register `tasks/<task-name>.md` with this Goal as the first repository change; enumerate only both environments/targets/services of selected comparison targets in Validation scope. Limit Allowed paths to the active contract and selected pairs' diff.md save destinations; attach unique IDs and corresponding `exists:` Acceptance checks to each Required change. Do not mix in framework changes or repairs.
- At the start, show the update time (Asia/Tokyo), baseline environment (authoritative)/comparison destination/target, compared CREATE resource scope, and unverified scope in a few lines. Do not include IMPORT-related exclusion explanations. State once that allowed environment differences are excluded from difference targets/counts; do not list actual value differences such as environment names/accounts.
- In the body, under `## サービス別の差異`, place one `### <service-id>` only for services with differences, naming rule mismatches, unconfirmed items, or incomparable items; summarize in a few lines. Do not use a double summary/details structure. Specifically record main setting differences, resource additions/deficiencies, naming rule mismatches, unconfirmed/incomparable items; combine differences with the same reason. Show counts only when helpful for explaining, such as addition/deficiency scale.
- Briefly state each difference's target use/setting item; below it, place both environments on separate lines such as “devは、…” and “stgは、…”. Use environment names of the executed pair; specifically write each actual value/setting/presence/absence. Do not merely state “環境別名称・参照差” or “設定が異なる”. Show presence/absence on both sides for additions/deficiencies too. Do not infer unknown values; mark them unconfirmed. For incomparability, record the cause/unverified scope.
- Show actual setting differences such as capacity, retention days, enablement/disablement, permissions, and connection targets in this format. For JSON/policies, summarize changed permissions/targets/conditions etc. for each environment. Summarize comment-only differences in a phrase. Do not publish both-side notation of identical values, all field values, full JSON, resource correspondence tables, naming confirmation tables, or evidence links. Create separate detail files/appendices only when the human requests them.

Format example (values/counts are illustrative):

```md
## サービス別の差異

### cloudwatch-logs

アプリログの保持日数
- devは、30日。
- stgは、90日。

変更理由は未確認。

### quicksight

Snowflake接続・VPC接続
- devは、Snowflake接続3件とVPC接続1件がある。
- stgは、どちらもない。

### iam

- 比較不能: devのpolicy documentとartifactSha256が不一致。IAMの設定差は未検証。
```
- On each execution, update the same diff.md results for services compared this time; preserve out-of-scope service results. Do not treat old results for incomparable scope as current; explicitly mark unconfirmed. Remove old differences/name confirmation/related notes for resources excluded as IMPORT this time and initial IMPORT exclusion explanations from current results; also delete service headings/bodies containing only IMPORT-related items. Remove old differences confirmed as allowed environment differences this time from publication/counts. For services with no differences, naming rule mismatches, unconfirmed items, or incomparable items after recomparison, delete old headings/bodies. If no services have publishable items, retain only file-start information; do not write an empty `## サービス別の差異` or `差分なし` explanation. Do not add history/timestamp-specific files.
- After saving, run `python3 -B framework/scripts/blueprint-loop.py --mode local`. Report selected pair difference summaries, unconfirmed items, diff.md save destinations, and validation results, then finish. Do not proceed to design/model/IaC repair, AWS APIs, or deploy/apply.

Follow AGENTS.md “How to read required rules” for reading rules. Read [project-configuration](../../../framework/rules/project-configuration.md) for target determination and account/profile validation, and [issue-gate](../../../framework/rules/issue-gate.md) for stop and investigation/repair/save exception decisions. Only for repository changes, additionally read [task-contract](../../../framework/rules/task-contract.md), [Local loop](../../../framework/rules/loop-engineering.md#local-loop), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), and [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion).

Only for framework changes, additionally read [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression).

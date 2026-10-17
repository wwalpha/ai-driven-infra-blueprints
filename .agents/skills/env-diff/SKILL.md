---
name: env-diff
description: Compare only parameters.yaml between explicitly selected project.json environments and targets; explain actual differences and save diff.md only when explicitly requested.
---

# Parameter differences between environments

## Compare

- Read `AGENTS.md`, [issue-gate](../../../framework/rules/issue-gate.md) and [Topology](../../../framework/rules/project-configuration.md#topology). Read `project.json` as the sole Environment/Target authority. Resolve the Human-selected source and destination environments, independent targets and service IDs. Ask if either environment is unspecified. Auto-select only an environment with exactly one registered target; for multiple targets ask for its alias. Reject unknown environments/targets and ambiguous selections. The target directory is its alias, otherwise `awsAccountId`; never collapse aliases sharing an account. Do not infer promotion order from array order, split hyphenated environment names, discover environments from directories or compare unrequested combinations.
- Run the read-only comparison CLI from the repository root. In a managed worktree use the [worktree](../worktree/SKILL.md) Python wrapper.

```console
python3 -B framework/scripts/compare-environments.py --repository-root . --from-env test --from-target network --to-env production --to-target core --service vpc --service security-group
```

- `--from-env` and `--to-env` are required. Omit `--from-target` / `--to-target` only on a side with one registered target. `--service` is repeatable; omitting it compares the union of parameter services for these two targets. Each invocation compares only one explicit pair; `--pair` / `--target` are removed.
- The only comparison inputs are `model/parameters/<environment>/<target-directory>/<service>/parameters.yaml`, loaded by `model_parameter_inputs.yaml_read()`. Do not read templates, bindings, observed values, expanded Models, generated Markdown, IaC or AWS to interpret differences.
- Read JSON namespace `parameters` and each comparison's `left` / `right` environments, `left_target` / `right_target` directories, `status`, `services`, `differences`, `difference_count`, and `errors`. Differences contain `pair`, `alias`, `left_target` / `right_target`, `service`, `key_path`, `kind`, `left` / `right` values, `left_exists` / `right_exists` and side-specific `source_paths`. Compatibility `target` / `alias` retain the directory only when both targets are the same; otherwise they are null. `pair` is a display label, never an environment parser. An empty key path denotes a service file (or an unavailable selection when service is null).
- Compare dictionaries without key order and lists by index/order. Preserve scalar types and null versus absence. Match instance IDs exactly. Compare every YAML field, including `definition` and `ResourceMode=IMPORT`. Environment names, accounts and references are literal values; never substitute or exclude them.
- `changed`, `only_left`, and `only_right` are actual differences. A one-sided service file produces one existence difference. `incomplete` indicates missing required input or a read error; an absent environment/target is never a list of service deletions. Exit 0 allows differences; a nonzero exit requires reporting the errors and unverified scope.

## Explain

Start with the selected source and destination environments/targets/services and difference count. If results include `incomplete`, distinguish actual differences from incomplete records. Show only services with differences or unverified inputs, with key paths and actual values/presence on separate environment lines. Preserve type distinctions (`1`, `"1"`, `true`, `null`) and show absence as `不存在`. Show one-sided instances separately even if another ID looks similar. Summarize large values without concealing changed settings; do not repeat unchanged parameters or full service documents.

```md
### vpc

`parameters.ResourceMode`
- test/network: CREATE
- production/core: IMPORT

### security-group

`instances.ec2-vpcendpoint-sts-01`
- test/network: 存在
- production/core: 不存在
```

Report only differences and comparison errors. Do not judge correctness, allowed environment differences, naming conventions or reasons; do not propose repairs or plans. Design changes, repairs and reflection are separate tasks.

## Save only when explicitly requested

Save to `issues/<to-env>/<to-target-directory>/diff.md`, resolved from the selected destination in `project.json`.

- Apply [task-contract](../../../framework/rules/task-contract.md) and [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope) and [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion). Register a `migration` contract as the first repository change, with both selected environments/target directories/services in Validation scope, unique Requirement IDs and corresponding `exists:` Acceptance checks. Allowed/Modified paths contain only the contract and requested diff.md destinations. Retain the issue-gate save-only exception; do not modify issues.md or treat diff.md differences as unresolved issues.
- Start diff.md with Asia/Tokyo update time and the selected source/destination scope and actual difference count. Under `## サービス別の差異`, group results by `### <from-env>/<from-target-directory> → <to-env>/<to-target-directory>`, then `#### <service-id>`, using the explanation format above. Identify each comparison by the complete four fields; do not parse a hyphenated pair label or use only the destination/service as its identity.
- Replace only the compared services' previous sections within the matching comparison group. Preserve other comparison sources and out-of-scope service results exactly, labeling their coverage separately so the current count does not imply they were rerun. Delete obsolete classifications, IMPORT exclusions, naming judgments and correspondence tables only within replaced sections; remove those services' sections when they now have no differences. Replace incomparable services' old results with an explicit `未検証` and cause. When a whole selection is incomplete, mark its selected services unverified; do not infer deletions or publish old results as current.
- For a legacy report without comparison groups, associate its sections with a source only when the saved scope explicitly identifies both environments and targets. If ownership is unclear, ask before replacing those sections; do not guess the source, overwrite another comparison or silently relabel old results. A confirmed legacy group may be converted to the grouping above while preserving its out-of-scope content.
- Keep only current report information, with no history files or empty service sections. The CLI never saves diff.md. Finish required local validation and report saved paths; do not proceed to repairs, Model/IaC changes or AWS calls.

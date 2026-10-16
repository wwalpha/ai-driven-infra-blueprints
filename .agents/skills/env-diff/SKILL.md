---
name: env-diff
description: Compare only parameters.yaml between dev→stg or stg→prod for the same cde/non-cde alias and services; explain actual differences and save diff.md only when explicitly requested.
---

# Parameter differences between environments

## Compare

- Read `AGENTS.md` and [issue-gate](../../../framework/rules/issue-gate.md). Resolve the requested pair (`dev-stg` / `stg-prod`), alias (`cde` / `non-cde`) and service IDs; ask if the pair is unspecified. Do not expand the requested scope. Use `project.json` only to confirm environment/alias existence.
- Run the read-only comparison CLI from the repository root. In a managed worktree use the [worktree](../worktree/SKILL.md) Python wrapper.

```console
python3 -B framework/scripts/compare-environments.py --repository-root . --pair dev-stg --target cde --service vpc --service security-group
```

- `--service` is repeatable; omitting it compares the union of parameter services for the selected pair/alias. Omitting `--target` selects both aliases; omitting `--pair` selects both pairs only when the Human requested both.
- The only comparison inputs are `model/parameters/<environment>/<alias>/<service>/parameters.yaml`, loaded by `model_parameter_inputs.yaml_read()`. Do not read templates, bindings, observed values, expanded Models, generated Markdown, IaC or AWS to interpret differences.
- Read JSON namespace `parameters` and each comparison's `status`, `services`, `differences`, `difference_count`, and `errors`. Differences contain `pair`, `alias`, `service`, `key_path`, `kind`, `left` / `right`, `left_exists` / `right_exists` and `source_paths`. An empty key path denotes a service file (or an unavailable pair/alias when service is null).
- Compare dictionaries without key order and lists by index/order. Preserve scalar types and null versus absence. Match instance IDs exactly. Compare every YAML field, including `definition` and `ResourceMode=IMPORT`. Environment names, accounts and references are literal values; never substitute or exclude them.
- `changed`, `only_left`, and `only_right` are actual differences. A one-sided service file produces one existence difference. `incomplete` indicates missing required input or a read error; an absent environment/alias is never a list of service deletions. Exit 0 allows differences; a nonzero exit requires reporting the errors and unverified scope.

## Explain

Start with the selected pair/alias/services and difference count. If results include `incomplete`, distinguish actual differences from incomplete records. Show only services with differences or unverified inputs, with key paths and actual values/presence on separate environment lines. Preserve type distinctions (`1`, `"1"`, `true`, `null`) and show absence as `不存在`. Show one-sided instances separately even if another ID looks similar. Summarize large values without concealing changed settings; do not repeat unchanged parameters or full service documents.

```md
### vpc

`parameters.ResourceMode`
- dev: CREATE
- stg: IMPORT

### security-group

`instances.ec2-vpcendpoint-sts-01`
- dev: 存在
- stg: 不存在
```

Report only differences and comparison errors. Do not judge correctness, allowed environment differences, naming conventions or reasons; do not propose repairs or plans. Design changes, repairs and reflection are separate tasks.

## Save only when explicitly requested

Use these existing destinations:

| Pair | Alias | Destination |
| --- | --- | --- |
| dev→stg | cde | `issues/stg/cde/diff.md` |
| dev→stg | non-cde | `issues/stg/non-cde/diff.md` |
| stg→prod | cde | `issues/prod/cde/diff.md` |
| stg→prod | non-cde | `issues/prod/non-cde/diff.md` |

- Apply [task-contract](../../../framework/rules/task-contract.md) and [Validation policy](../../../framework/rules/loop-engineering.md#validation-policy), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope) and [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion). Register a `migration` contract as the first repository change, with both selected environments/aliases/services in Validation scope, unique Requirement IDs and corresponding `exists:` Acceptance checks. Allowed/Modified paths contain only the contract and requested diff.md destinations. Retain reservations and the issue-gate save-only exception; do not modify issues.md or treat diff.md differences as unresolved issues.
- Start diff.md with Asia/Tokyo update time, compared scope and actual difference count. Under `## サービス別の差異`, use `### <service-id>` and the explanation format above.
- Replace only the compared services' previous sections. Delete their obsolete classifications, IMPORT exclusions, naming judgments and correspondence tables; remove sections for services now without differences. Preserve out-of-scope service results exactly and label their coverage separately so the current count does not imply they were rerun. Replace incomparable services' old results with an explicit `未検証` and cause. When a whole pair/alias is incomplete, mark the selected services unverified; do not infer deletions or publish old results as current.
- Keep only current report information, with no history files or empty service sections. The CLI never saves diff.md. Finish required local validation and report saved paths; do not proceed to repairs, Model/IaC changes or AWS calls.

---
name: aws-check
description: Use when checking desired properties against current AWS values for the specified AWS Blueprint environment, target, and service with read-only AWS APIs and the existing SDK comparison program, and investigating detected differences and unconfirmed items.
---

# AWS API checks

The common authority is maintained in the `ai-driven-infra-blueprints` repository. This skill handles current-value retrieval/comparison through AWS APIs; local validation and issue-list saving are handled by [issues saving and updating](../issues/SKILL.md#saving-and-updating) and [Output](../issues/SKILL.md#output).

## Scope and execution permission

- Read `AGENTS.md`, [issue-gate](../../../framework/rules/issue-gate.md), [Model authority](../../../framework/rules/model-information.md#model-authority), and [Properties format](../../../framework/rules/model-information.md#properties-format); target only the requested environment/target/service/resource. Use the `project.json` alias as target directory, or `awsAccountId` without an alias. Ask if the scope is unclear; do not expand it by inference.
- For read-only investigation and chat reporting alone, do not start a repository task; save comparison JSON to a temporary file outside the repository as needed. Execute only list/get/describe-equivalent APIs and caller identity validation authorized by the AWS check request; do not perform AWS mutation.
- Use the existing comparator to validate `project.json` `awsProfile`, region, and execution account (`awsExecutionAccountId`, or `awsAccountId` when unspecified). Stop for an explicit profile differing from the configured profile, caller account mismatch, or authentication failure; do not fall back to another profile/account.
- If issue-list saving/updating is also explicitly requested, before AWS retrieval, record the investigation scope and read-only API permission in a `migration` contract following [issues saving and updating](../issues/SKILL.md#saving-and-updating). Limit Allowed paths/Modified files to this contract and the target issues.md; perform investigation, saving, and local loop in the same contract. Retain read-only issue investigation operations and save-only task exemption conditions even when unresolved issues exist.

## Investigation starting from SDK comparison

- Use `framework/scripts/check-model-aws.py` for ordinary properties/current AWS value comparison. Complete retrieval/comparison with Python + AWS SDK; do not use AI to reread every service each time. Do not invoke AI or issue saving from the program itself.
- `desired.*` is authoritative for expected values. Identify actual resources through SDK retrieval and use `observed.*` only as references to confirmed identifiers. Do not substitute Markdown or CFn for expected setting values.
- Execute operational AWS retrieval after confirming retrieval permission for the target environment/target/service/resource and necessary read-only APIs in this request. When saving is involved, also explicitly state this in the same investigation task's active contract. Use `--all` only when retrieval permission for all targets is explicit. Do not change configured profiles or fall back on authentication failure.
- Single-target comparison example: `python3 framework/scripts/check-model-aws.py --environment dev --target cde --service s3`. For all targets, explicitly use `--all`; for coverage inspection without a connection, use `--all --coverage`. Follow `framework/scripts/requirements-aws-compare.txt` for comparison dependencies.
- When this request/active task investigation scope includes multiple services in the same environment/target, combine them into one execution by repeating `--service` whenever possible. Example: `python3 framework/scripts/check-model-aws.py --environment dev --target cde --service s3 --service iam --service kms`. Do not default to separate command execution per service.
- Do not expand investigation scope for batching. Do not add IAM/KMS to a request authorizing only S3; retain the existing AWS read-only API scope, Task Contract, and Validation Scope. Performance optimization must not expand task scope.
- Starting only from resources/keys in JSON `difference`/`resource_missing`, AI investigates related authoritative properties, CFn, and actual AWS resources. Combine retrieval failures with a common cause into one unconfirmed item using `affectedKeys` and `scope`; do not duplicate them per property. Do not treat `design_unresolved`, `sdk_unavailable`, `unimplemented`, or `acquisition_failed` as matches.
- Exit code 0 means all match, 1 means differences exist, and 2 means validation is incomplete. Code 2 may also include known differences. `identifier` is for resource identification; `local_metadata` is outside SDK setting comparison. Do not report an overall match when retrieval remains impossible.
- If issue-list saving/updating is also requested, reuse existing issues when the same resource/key difference has already been investigated. Reinvestigate only when related properties/CFn contents or retrieved AWS values change. Record each evidence content hash and AWS comparison values (excluding secrets) in a verifiable form; do not resolve unconfirmed existing issues.
- Difference investigation reports must state all three properties/CFn/AWS values, model file/line and JSON retrieval API, CFn evidence location, confirmed cause, and necessary action. If any of the three cannot be confirmed, mark it unconfirmed. Do not conclude CFn repair is necessary from the AWS difference alone. Do not record secrets or credentials.
- Do not proceed from investigation/comparison/issue saving alone to design changes, CFn repair, or deploy. Repair only within a separate repair scope explicitly specified by the human. Do not execute or reimplement the old automatic properties↔CFn setting comparison.

## Result handling

- Report comparison scope, differences, unconfirmed items, and execution results in chat. Do not change `issues.md` unless issue-list saving is requested.
- Only when saving is also requested, use the formats/update rules in [issues saving and updating](../issues/SKILL.md#saving-and-updating) and [Output](../issues/SKILL.md#output) to save already retrieved results/investigation evidence in the same task. Do not rerun AWS APIs from issues.
- Do not change model desired/observed, design, or IaC; do not proceed to deploy/apply, scenarios, or another task.

Follow AGENTS.md “How to read required rules” for reading rules. Read [project-configuration](../../../framework/rules/project-configuration.md) for target determination and account/profile validation, and [issue-gate](../../../framework/rules/issue-gate.md) for stop and investigation/repair/save exception decisions. Only for repository changes, additionally read [task-contract](../../../framework/rules/task-contract.md), [Local loop](../../../framework/rules/loop-engineering.md#local-loop), [Validation scope](../../../framework/rules/loop-engineering.md#validation-scope), and [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion).

Only for framework changes, additionally read [Framework regression](../../../framework/rules/loop-engineering.md#framework-regression).

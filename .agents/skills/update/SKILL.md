---
name: update
description: Use for explicit Model changes, Model-only operations, or reflecting requested Model changes into IaC and AWS through the existing update branches.
---

Select the workflow using [Workflow selection](../../../framework/rules/task-contract.md#workflow-selection).

[Service Model source authority](../../../framework/rules/model-templates.md) applies.
Inspect environment-specific properties; use `model.sources.edit_base` for an invalid repair baseline and validate the corrected candidate through `model.sources.load_model`. Use
`model/cli.py trace <service.properties> <key>`. Edit desired/display/reference keys
only within the selected Task; authorized observations change only the selected
`observed.row.<id>.value`. Record the entry and actual parts, required incoming
consumers and generated paths in the Task. Read dependencies grant no write scope.
Retain this skill's deployment target and AWS permission boundary.

Read `framework/prompts/codex/05_update.md` at the repository root in full and execute only its contents as the authoritative text. Treat input following the Skill invocation as human input to the workflow. Do not duplicate, reinterpret, or extend the prompt body. If the prompt file does not exist, stop without changing the repository.

The corresponding prompt's Read section is authoritative for reading scope, conditional rules, and validation scope.

Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.

The Model-only branch composes model-transfer, model-retarget and model-delete under
one parent Task; each leaf's own skill is its procedure authority. Worktree finalization
owns the post-rebase final validation/completion/merge sequence.

For an explicit Human one-or-more-Resource deletion request, register and validate the
`import-delete` parent. Retain Model safety checks, forbidden AWS/deploy and unchanged
issue inventories. Apply [Reference diagnostics](../../../framework/rules/model-information.md#reference-diagnostics)
to read-only analysis. Final candidates must resolve their references; an invalid old
Model is never a repair/save/finalization blocker.

The separate value-preserving branch uses the shared read-only reference API only for
an explicitly authorized detach; neither ordering nor detach completion gates deletion. It uses an
ordinary design Task for an independent refactor request. When repairing dependencies
of registered deletions, use the import-delete parent with explicit related detach or
reference records and the existing intermediate writer. Process resources sequentially,
then generate/validate/integrate the parent once. Never create one Task or Merge per
Resource or require an earlier repair Merge before deletion.

For an explicit standalone reference-only request, use the separate `import-retarget`
branch in 05_update and the standalone Task contract. Call only model-retarget, saving
all declarations together; retain both producers. No merge
pair, transfer/delete or value-preserving detach authority is implied. Generate through
the existing APIs and finalize the running parent on the latest-base candidate.

Follow [JSON settings](../../../framework/rules/model-information.md) and
[Resource identity](../../../framework/docs/model-identity.md): JSON stores AWS configuration
values without Markdown Resource links, including `$resource`. Reuse external
`desired.reference.*` metadata with `format=identifier` and JSON Pointers for confirmed
non-ARN identifiers. Never guess IDs, automatically migrate existing Models, or replace
ARN selectors by saved generated ARNs; report unsupported cases. Keep Resource/artifact
links outside JSON bodies.

Model 更新時は **Change Validation のみ**実行する。Full Validation は Issue Scan や独立した明示的全量検証で使用し、更新の停止判定へ混入させない。変更した Resource / Property / Link と、それらが使用・破壊する参照契約を検証し、無関係な既存エラーを更新の停止理由にしない。読み取り依存先、検証対象、生成対象、Task の書き込み権限を区別する。

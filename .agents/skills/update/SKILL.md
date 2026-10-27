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

Read [Common update authority](../../../framework/prompts/codex/05_update.md#common-update-authority) for every branch, then select only the requested branch and its child headings and required references under AGENTS.md's section-reading rule:

- Ordinary Model correction: [Ordinary Model correction](../../../framework/prompts/codex/05_update.md#ordinary-model-correction).
- Value-preserving refactor: [Dependency analysis and value-preserving refactoring](../../../framework/prompts/codex/05_update.md#dependency-analysis-and-value-preserving-refactoring) and its related contract.
- Reference-only change: [Standalone Model reference retarget](../../../framework/prompts/codex/05_update.md#standalone-model-reference-retarget).
- Model-only IMPORT merge/deletion: [Model-only IMPORT merge or deletion](../../../framework/prompts/codex/05_update.md#model-only-import-merge-or-deletion) and the required leaf skills.
- Explicit infrastructure update: every section from [Check applicability and finish point first](../../../framework/prompts/codex/05_update.md#check-applicability-and-finish-point-first) through [Verify and finish](../../../framework/prompts/codex/05_update.md#verify-and-finish), including conditional references and AWS safety, approval, preflight, deploy/apply and completion requirements.

Treat input following the Skill invocation as human input; do not infer infrastructure authority from an ambiguous request. Model-only branches do not read infrastructure AWS Deploy procedures. If the prompt or a required reference is missing, stop. Within one Task do not unconditionally reread unchanged confirmed material; check additional portions when the classification, inputs or dependencies change or evidence is insufficient.

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

For JSON settings, references or generation, read [Properties-first updates and display generation](../../../framework/rules/model-information.md#properties-first-updates-and-display-generation); for derived Policy/Configuration JSON, also read [Policy derived views](../../../framework/rules/model-information.md#policy-derived-views). Read additional sections required by the selected operation. Follow
[Resource identity](../../../framework/docs/model-identity.md): JSON stores AWS configuration
values without Markdown Resource links, including `$resource`. Reuse external
`desired.reference.*` metadata with `format=identifier` and JSON Pointers for confirmed
non-ARN identifiers. Never guess IDs, automatically migrate existing Models, or replace
ARN selectors by saved generated ARNs; report unsupported cases. Keep Resource/artifact
links outside JSON bodies.

Model 更新時は **Change Validation のみ**実行する。Full Validation は Issue Scan や独立した明示的全量検証で使用し、更新の停止判定へ混入させない。変更した Resource / Property / Link と、それらが使用・破壊する参照契約を検証し、無関係な既存エラーを更新の停止理由にしない。読み取り依存先、検証対象、生成対象、Task の書き込み権限を区別する。

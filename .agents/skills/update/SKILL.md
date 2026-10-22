---
name: update
description: Use for explicitly authorized CREATE/IMPORT Model corrections, Model-only merge/delete or reference retarget, value-preserving refactors, or reflecting approved design into IaC and AWS through the separate 05_update branches.
---

[Service Model source authority](../../../framework/rules/model-templates.md) applies.
Inspect environment-specific properties; use `model.sources.edit_base` for an invalid repair baseline and validate the corrected candidate through `model.sources.load_model`. Use
`model/cli.py trace <service.properties> <key>`. Edit desired/display/reference keys
only within the selected Task; authorized observations change only the selected
`observed.row.<id>.value`. Record the entry and actual parts, required incoming
consumers and generated paths in the Task. Read dependencies grant no write scope.
Retain this skill's deployment target, issue gate and AWS permission boundary.


Read `framework/prompts/codex/05_update.md` at the repository root in full and execute only its contents as the authoritative text. Treat input following the Skill invocation as human input to the workflow. Do not duplicate, reinterpret, or extend the prompt body. If the prompt file does not exist, stop without changing the repository.

The corresponding prompt's Read section is authoritative for reading scope, conditional rules, and validation scope.

Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.

The Model-only branch composes model-transfer, model-retarget and model-delete under
one parent Task; each leaf's own skill is its procedure authority. Worktree finalization
owns the post-rebase final validation/completion/merge sequence.

For an explicit Human one-or-more-Resource deletion request, follow the prompt's pre-contract
exception: register and validate the `import-delete` parent before the task-aware Issue
Gate. Waive existing-issue stops only for its registered deletion source services; retain non-reference
Model safety checks, forbidden AWS/deploy and unchanged issue inventories. Apply
[Reference diagnostics](../../../framework/rules/model-information.md#reference-diagnostics)
to read-only analysis. Final ordinary candidates must resolve their references; an invalid old Model is never a repair/save/finalization blocker. Merge,
ordinary updates and later Tasks retain the ordinary pre-task gate.

The separate value-preserving branch uses the shared read-only reference API only for
an explicitly authorized detach; neither ordering nor detach completion gates deletion. It uses an
ordinary design Task for an independent refactor request. When repairing dependencies
of registered deletions, use the import-delete parent with explicit related detach or
reference records and the existing intermediate writer. Process resources sequentially,
then generate/validate/integrate the parent once. Never create one Task or Merge per
Resource or require an earlier repair Merge before deletion.

For an explicit standalone reference-only request, use the separate `import-retarget`
branch in 05_update and the standalone Task contract. Call only model-retarget, saving
all declarations together; retain both producers and the ordinary Issue Gate. No merge
pair, transfer/delete or value-preserving detach authority is implied. Generate through
the existing APIs and finalize the running parent on the latest-base candidate.

Follow [JSON settings](../../../framework/rules/model-information.md) and
[Resource identity](../../../framework/docs/model-identity.md): JSON stores AWS configuration
values without Markdown Resource links, including `$resource`. Reuse external
`desired.reference.*` metadata with `format=identifier` and JSON Pointers for confirmed
non-ARN identifiers. Never guess IDs, automatically migrate existing Models, or replace
ARN selectors by saved generated ARNs; report unsupported cases. Keep Resource/artifact
links outside JSON bodies.

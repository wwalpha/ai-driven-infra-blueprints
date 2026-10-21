---
name: model-transfer
description: Perform only the named Model-only leaf under an explicit existing parent update contract.
---

# model-transfer

## Read and input boundary

Read [Model-only contract](../../../framework/rules/task-contract.md#model-only-import-operation-contract),
[service sources](../../../framework/rules/model-templates.md) and the selected parent Task.
Require its explicit worktree and Task selector, running design /update Model-only contract,
forbidden AWS/deploy, and the exact requested subset of its normalized operation records.
A missing parent or a record differing from the parent returns input failure; do not
create a child contract or infer authority, IDs, properties or reference locations.

Load the canonical snapshot with `model.sources.load_model`; inspect authoritative
keys, source locations and raw file bytes. Use `model.files.read_resource`,
`trace_model` and `find_model` for focused reads. Prepare ordinary format-2 properties
candidates with `model.format.patch`, retaining parts and unrelated bytes. The agent
chooses edits; Python verifies preservation and never infers an edit plan.

## Operation

Accept only an exact subset of the parent's import-merge pairs. Read source and
destination together. Transfer source settings, complete formal Property/array shape,
structural JSON and observations. Preserve destination fixed Resource IDs,
mode/type, logicalId/cfn-logicalId and placementName. Match rows
by formal Property, array order and ownership, never equal numeric Row IDs; retain
matching destination Row IDs and allocate unused fixed IDs for new rows.

Keep source resources. Correct source self references to destination self identity;
leave references to other sources for model-retarget. Preserve shared consumers with
only the registered value-preserving reference edits; preserve their settings,
reference meanings and observations. Ambiguous or unrepresentable
correspondence returns failure, without guessing. Do not retarget consumers or delete.

## Save and return

Obtain a fresh `model.adapters.task.source_write_context(root, task_file)` for this save.
Load the selected snapshot with that context's recorded inputs, prepare the ordinary
properties candidate using `model.operations.prepare_edit(snapshot, changes, context)`,
and call `model.operations.publish_edit(plan, context)`. Changes map absolute source
paths to UTF-8 text (None means delete). A context is consumed by success, no-op or failure.
Save only this operation's changed raw sources; unchanged bytes are no-op. Keep
previous successful leaf saves on failure. Existing journal rollback applies only
to this write. Never bypass managed-worktree, Task revision, input snapshot, exact
path and consumer-scope guards. Do not require a fully expanded/completed merge to save.

Return success/no-change/failure, requested/completed records, saved paths and fixed
Resource/reference locations, performed operation, failure reason and retained changes.
Do not persist a separate history, receipt or workflow state. Success means only this
leaf completed. Do not call another leaf, generation, completion, commit, merge,
cleanup or AWS; do not create a worktree or modify parent Goal/permissions/operation/status
(including suspend). Return failure to the parent, which stops and may suspend.

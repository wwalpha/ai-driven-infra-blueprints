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

Read raw source with `model_sources.read_sources`; expansion-based `read_resource`,
`trace_model`, `find_model` and `load_for_edit` are optional editing aids and may fail
for unfinished sources. Use existing YAML editing and resolver helpers. The agent
chooses source edits; Python does not reconstruct or infer an edit plan.

## Operation

Accept only an exact subset of the parent's import-merge pairs. Read source and
destination together. Transfer source settings, complete formal Property/array shape,
structural JSON and observations. Preserve destination fixed Resource/Instance IDs,
anchor, mode/type, logicalId/cfn-logicalId and internal identity bindings. Match rows
by formal Property, array order and ownership, never equal numeric Row IDs; retain
matching destination Row IDs and allocate unused fixed IDs for new rows.

Keep source resources. Correct source self references to destination self identity;
leave references to other sources for model-retarget. Preserve shared consumers with
only necessary value-preserving new inputs; preserve their existing inputs/bindings/
observations. Use existing optional/choice/input forms. Ambiguous or unrepresentable
correspondence returns failure, without guessing. Do not retarget consumers or delete.

## Save and return

Obtain a fresh `import_guard.source_write_context(root, task_file)` for this save and
call `model_sources.write_sources(context, changes)` with absolute source paths and
UTF-8 text (None means delete). A context is consumed by success, no-op or failure.
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

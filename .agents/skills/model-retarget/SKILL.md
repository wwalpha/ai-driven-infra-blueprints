---
name: model-retarget
description: Perform only the named Model-only leaf under an explicit existing parent update contract.
---

# model-retarget

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

For an `import-retarget` parent also read
[Standalone reference contract](../../../framework/rules/task-contract.md#standalone-model-reference-retarget).
Require its full record set in one source save; no merge pair or comparison-source
substitution is allowed. Both producers must remain untouched. This standalone branch
permits value/document configuration references only, including explicit JSON scalar
pointers and numbered array Properties. No Subnet associations, parentReference,
D→D reevaluation, bindings/observed edits or new source structure. The ordinary Issue
Gate applies to every producer and consumer. The save guard resolves and proves the
full before/candidate meaning before publication; unlike merge leaves, an incomplete
standalone candidate cannot be saved. It uses the same one-use context and final
snapshot comparison. Return to the parent for generation/finalize; do not perform them here.

## Operation

Accept only an exact subset of the parent's reference changes. Change only the
registered consumer's complete value, non-root scalar JSON pointer or (merge only) parentReference.
Use bindings and the existing resolver to prove before source and after destination;
local Instance names resolve to fixed Resources. For destination consumers derive the
comparison source from the registered pair. Never choose a target from equal strings,
physical IDs or caller-supplied alternative comparison consumers.

Preserve CIDR/settings, JSON siblings/array order/scalar types, observations and fixed
identities. Preserve reference type, format, output Property and label policy; never
replace a reference by its rendered literal. D→D declares producer reevaluation only:
keep the consumer expression/selectors/inputs unchanged and avoid an unnecessary write.
Reject overlapping, absent, wildcard, root, container or partial free-text positions.
Do not transfer settings, delete source or edit undeclared references.

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

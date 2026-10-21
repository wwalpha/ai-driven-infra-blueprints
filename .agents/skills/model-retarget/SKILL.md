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

Load the canonical snapshot with `model.sources.load_model`; inspect authoritative
keys, source locations and raw file bytes. Use `model.files.read_resource`,
`trace_model` and `find_model` for focused reads. Prepare ordinary format-2 properties
candidates with `model.format.patch`, retaining parts and unrelated bytes. The agent
chooses edits; Python verifies preservation and never infers an edit plan.

For an `import-retarget` parent also read
[Standalone reference contract](../../../framework/rules/task-contract.md#standalone-model-reference-retarget).
Require its full record set in one source save; no merge pair or comparison-source
substitution is allowed. Both producers must remain untouched. This standalone branch
permits value/document configuration references only, including explicit JSON scalar
pointers and numbered array Properties. No Subnet associations, parentReference,
D→D reevaluation, observed edits or new source structure. The ordinary Issue
Gate applies to every producer and consumer. The save guard resolves and proves the
non-reference before/candidate preservation before publication. Semantic reference
ambiguity, mismatch or incompleteness is warning-only, including at source save. It uses the same one-use context and final
snapshot comparison. Return to the parent for generation/finalize; do not perform them here.

## Operation

Follow [Reference diagnostics](../../../framework/rules/model-information.md#reference-diagnostics).
Report semantic target/type/label/format or declaration mismatch as warnings without
blocking save/completion. Repair what is known within scope, ask about undetermined
repairs, and do not make repair a prerequisite. Keep all non-reference errors and guards.

Accept only an exact subset of the parent's reference changes. Change only the
registered consumer's complete value, non-root scalar JSON pointer or (merge only) parentReference.
Use saved reference records and direct links to diagnose source and destination
fixed Resource identities; never regenerate saved values from producer changes. For destination consumers derive the
comparison source from the registered pair. Never choose a target from equal strings,
physical IDs or caller-supplied alternative comparison consumers.

Preserve CIDR/settings, JSON siblings/array order/scalar types, observations and fixed
identities. Preserve reference type, format, output Property and label policy; never
replace a reference by its rendered literal. D→D declares producer reevaluation only:
keep the saved consumer value and reference metadata unchanged and avoid an unnecessary write.
Reject overlapping, absent, wildcard, root, container or partial free-text positions.
Do not transfer settings, delete source or edit undeclared references.

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

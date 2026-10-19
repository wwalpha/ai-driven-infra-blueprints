---
name: model-delete
description: Perform only the named Model-only leaf under an explicit existing parent update contract.
---

# model-delete

## Read and input boundary

Read [Model-only contract](../../../framework/rules/task-contract.md#model-only-import-operation-contract),
[service sources](../../../framework/rules/model-templates.md) and the selected parent Task.
Require its explicit worktree and Task selector, running design /update Model-only contract,
forbidden AWS/deploy, and the exact requested subset of its normalized operation records.
A missing parent or a record differing from the parent returns input failure; do not
create a child contract or infer authority, IDs, properties or reference locations.

Use the common task-aware Issue Gate for the selected parent. A valid `import-delete`
parent waives only existing-issue stops within its explicit Validation scope; do not
require Issue remediation or change issues.md. An `import-merge` parent retains the
ordinary gate. This exception never waives the reference/Model safety checks below.

Read raw source with `model_sources.read_sources`; expansion-based `read_resource`,
`trace_model`, `find_model` and `load_for_edit` are optional editing aids and may fail
for unfinished sources. Use existing YAML editing and resolver helpers. The agent
chooses source edits; Python does not reconstruct or infer an edit plan.

## Operation

Accept an exact subset of the normalized parent deletion source set (merge sources
or the single import-delete source). Inspect all effective Models in the same
environment/target for remaining references, including active optional/choice branches,
Property/JSON/parentReference and internal links in expanded free text. Use the
before anchor index even when a source is absent; service.md and ./service.md resolve
identically. Ignore unused Definitions/inactive branches and unrelated URLs/IDs.

Before editing, call `model_reference_usage.incoming_references(root, address)` for
each normalized fixed source address; use outgoing_references to explain ordering.
The thin read-only CLI is `framework/scripts/model_reference_usage.py <address>
--direction incoming`, run through the registered run-python.py wrapper. Match its
producer/consumer IDs, key/Property/pointer, kind/format, resolvedValue and source
location/provenance against raw sources. Do not infer them or treat unresolved errors
as no dependencies. Display links are not AWS-setting dependencies, but retained
Resource/service display links still need a separate repair before deletion.

If incoming usages survive this deletion, report their exact locations and values,
whether deleting an already authorized consumer first resolves the order, and whether
name generation offers a candidate for a separate value-preserving design Task. The
parent follows the dependency decision order in 05_update; this leaf never selects or
executes a detach, changes a surviving Resource, starts another Task or silently
changes deletion order. Name format alone is no safety proof. Keep the existing
verify_model_operation final check and single-source import-delete contract unchanged.

Fail if any surviving Resource refers to a source; do not retarget implicitly. Remove
only its Instance, binding, unused inputs and observations. Retain shared Definitions,
in-use inputs and sibling Resources. Reject a multi-resource source Instance that
cannot be safely separated; do not add an automatic splitting operation.

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

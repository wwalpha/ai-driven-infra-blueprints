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

Follow [Reference diagnostics](../../../framework/rules/model-information.md#reference-diagnostics).

Read the old authority with `model.sources.raw_model`; inspect raw fields, source
locations and bytes without requiring old semantic validity. Required operation fields
must remain parseable and unambiguous. Use focused Model helpers only when their inputs
can be loaded; they are not a whole-old-Model validity gate. Prepare ordinary format-2 properties
candidates with `model.format.patch`, retaining parts and unrelated bytes. The agent
chooses edits; Python verifies preservation and never infers an edit plan.

## Operation

Accept exactly one Resource from the normalized parent deletion source set (merge
sources or model-delete delete_sources), whether CREATE (explicit or implicit) or IMPORT.
This removes Model authority only and never deletes AWS resources or runs deploy/apply. The parent LLM invokes the next leaf only
after inspecting this result; multiple resources share the same Task and Worktree.
Inspect declared references, Property/JSON/parentReference and direct Markdown links
in all real Models of the same environment/target. Keep a before snapshot so deleted
producer anchors remain known; service.md./service.md resolve identically.

Before editing, call `model.references.incoming(snapshot, fixed_id, read_context)`.
The read-only CLI is `model/cli.py incoming <service.properties> <fixed-ID>`, run
through the registered run-python.py wrapper. Inspect each usage's fixed scope/ID,
consumerKey/pointer/occurrence, format and source position alongside
`model.references.diagnose`. I/O, syntax and scope errors remain errors; semantic
reference warnings do not prove an empty dependency set and do not block deletion.

If incoming usages survive deletion, report exact locations and known prior values.
The parent LLM chooses ordering and registered related repairs using existing reference
APIs and raw source editing. Perform those repairs and deletion within this same parent;
do not create an independent repair Task/Worktree/Merge. Repair records must identify
consumer fields/pointers and a deleted producer. Ask about undetermined repairs;
reference warnings never gate the original deletion. Keep final verify_model_operation
for all parent sources after the last leaf, not after each save. The final candidate guard rejects invalid remaining Resource references; resolve them through the parent
Task declarations before completion/integration. Remove
only its Resource block, owned Rows/documents/reference records and observations.
Retain sibling Resources, fixed IDs, unrelated blocks and part names; removing an
empty part never renumbers surviving parts.

## Save and return

Obtain a fresh `model.adapters.task.source_write_context(root, task_file)` for this save.
Pass the selected entrance Path to `model.operations.prepare_edit(path, changes, context)`;
it reads the dedicated operation's raw baseline through the context's recorded inputs and
validates the corrected properties candidate. Publish the prepared plan with
`model.operations.publish_edit(plan, context)`. Changes map absolute source
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
(including suspend). Return failure to the parent, which stops and may suspend; retain successful saves for
explicit same-parent repair/resume. Leaf status is returned in conversation, not a
persistent execution scheduler.

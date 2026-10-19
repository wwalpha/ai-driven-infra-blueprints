---
name: update
description: Use for explicit Model-only IMPORT merge/delete, value-preserving dependency refactors or reflecting Human design changes into IaC and AWS, following the separate branches of 05_update.
---

[Service Model source authority](../../../framework/rules/model-templates.md) applies
for runtime Models: read through model_files and trace expanded keys with `--trace`.
Design edits use the common template, parameters.yaml and fixed bindings.json;
authorized observed updates use observed.json. Include mechanically identified
common-template consumers in generation/Validation scope. Retain this skill's
single deployment target, issue gate and AWS permission boundary.


Read `framework/prompts/codex/05_update.md` at the repository root in full and execute only its contents as the authoritative text. Treat input following the Skill invocation as human input to the workflow. Do not duplicate, reinterpret, or extend the prompt body. If the prompt file does not exist, stop without changing the repository.

The corresponding prompt's Read section is authoritative for reading scope, conditional rules, and validation scope.

IMPORT acquisition/addition is exclusive to append-only `/import`; explicit Model-only merge/delete uses `/update` under the narrow operation guard. Follow [IMPORT configuration authority](../../../framework/rules/model-information.md#import-configuration-authority). Read/compare remains allowed. Value-preserving source refactors are allowed; CREATE workflow is unchanged. Other substantive IMPORT updates remain forbidden; read/compare and value-preserving refactors never bypass the mechanical guards.

The Model-only branch composes model-transfer, model-retarget and model-delete under
one parent Task; each leaf's own skill is its procedure authority. Worktree finalization
owns the post-rebase final validation/completion/merge sequence.

The separate value-preserving branch first distinguishes deletion ordering from a
necessary dependency detach using the shared read-only reference API. It uses an
ordinary design Task with explicit detach declarations and ordinary guarded saving;
it does not enter the operation-only intermediate writer. Each refactor and subsequent
single deletion is independently validated and integrated as specified by 05_update.

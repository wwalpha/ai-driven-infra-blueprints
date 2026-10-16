---
name: update
description: Use when reflecting Human changes to existing AWS detailed design into model, IaC, and AWS according to the existing 05_update workflow.
---

[Service Model source authority](../../../framework/rules/model-templates.md) applies
for runtime Models: read through model_files and trace expanded keys with `--trace`.
Design edits use the common template, parameters.yaml and fixed bindings.json;
authorized observed updates use observed.json. Include mechanically identified
common-template consumers in generation/Validation scope. Retain this skill's
single deployment target, issue gate, reservations and AWS permission boundary.


Read `framework/prompts/codex/05_update.md` at the repository root in full and execute only its contents as the authoritative text. Treat input following the Skill invocation as human input to the workflow. Do not duplicate, reinterpret, or extend the prompt body. If the prompt file does not exist, stop without changing the repository.

The corresponding prompt's Read section is authoritative for reading scope, conditional rules, and validation scope.

IMPORT desired configuration changes are exclusive to `/import`; follow [IMPORT configuration authority](../../../framework/rules/model-information.md#import-configuration-authority). Read/compare remains allowed. Value-preserving source refactors are allowed; CREATE workflow is unchanged. Ordinary design, aws-check and update must delegate substantive IMPORT changes to import and cannot bypass the mechanical evidence guard.

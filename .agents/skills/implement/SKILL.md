---
name: implement
description: Use when implementing approved AWS detailed design as IaC and performing local static validation according to the existing 03_implement workflow.
---

[Service Model source authority](../../../framework/rules/model-templates.md) applies.
Read the environment-specific properties through `model.sources.load_model` and
`model/cli.py trace <service.properties> <key>`. Edit desired/display/reference keys
only within the selected Task; authorized observations change only the selected
`observed.row.<id>.value`. Record the entry and actual parts, required incoming
consumers and generated paths in the Task. Read dependencies grant no write scope.
Retain this skill's deployment target and AWS permission boundary.


Read `framework/prompts/codex/03_implement.md` at the repository root in full and execute only its contents as the authoritative text. Treat input following the Skill invocation as human input to the workflow. Do not duplicate, reinterpret, or extend the prompt body. If the prompt file does not exist, stop without changing the repository.

The corresponding prompt's Read section is authoritative for reading scope, conditional rules, and validation scope.

Resource references retain their original Markdown label, relative path and fragment. Resolve with consumer scope through the common Model saved-anchor resolver; use fixed Resource numbers and typed logicalIds internally. Preserve independent saved anchors and desired links during IMPORT/observed updates. New anchors reuse `design_layout.resource_anchor()` and confirmed naming rules. No URI conversion or inferred consumer restoration.

A sealed CloudFormation deploy repair request is received through the prompt's explicit implement-only path. Use its pinned parent checkpoint, exact IaC paths and approved design. AWS APIs/mutations/deploy and Model changes are forbidden. Use `worktree_task.py repair-validate` and the existing completion/finalize helpers; never self-assert PASS or create new children to reset static failures. The supervising LLM returns only to that request's original deploy Task/session.

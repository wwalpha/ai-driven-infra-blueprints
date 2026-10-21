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
Retain this skill's deployment target, issue gate and AWS permission boundary.


Read `framework/prompts/codex/03_implement.md` at the repository root in full and execute only its contents as the authoritative text. Treat input following the Skill invocation as human input to the workflow. Do not duplicate, reinterpret, or extend the prompt body. If the prompt file does not exist, stop without changing the repository.

The corresponding prompt's Read section is authoritative for reading scope, conditional rules, and validation scope.

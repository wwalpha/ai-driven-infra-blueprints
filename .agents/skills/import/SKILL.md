---
name: import
description: Acquire one AWS service through Python, append explicitly managed new resources to authoritative Model sources while preserving existing resources, then verify/publish those sources before generating selected Markdown/JSON. Never directly edit generated design Markdown/JSON. Follow 08_import for the complete workflow.
---

Read `framework/prompts/codex/08_import.md` at the repository root in full and execute
only its contents as the authoritative workflow. Treat Skill arguments as its inputs.
Do not duplicate the Prompt specification. Stop if the Prompt is missing.
Follow its phase-specific reads; reuse unchanged rules already read in this execution.

Examples:

```text
/import --environment dev --service config --target cde
/import --environment stg --service security-hub --target non-cde
/import --environment dev --service config --target cde --dry-run
/import --environment dev --service config --target cde --no-profile
```

Run in the worktree selected by the Human, following the Prompt's contract and evidence procedure.

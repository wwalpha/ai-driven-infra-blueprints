---
name: import
description: Acquire once, prepare and present the complete normalized Import Review, and require trusted Human approval before source candidate edits. Follow 08_import for the fail-closed approval boundary, pre-save checks and sequential single-service workflow. Never directly edit generated design Markdown/JSON.
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

Environment and Service are required: ask the Human when either is missing. Multiple
services use separate single-service Tasks/acquisitions/publications in the LLM-selected
order; do not introduce a Python batch controller. See 08_import for all decisions.

Run in the worktree selected by the Human, following the Prompt's contract and evidence procedure.

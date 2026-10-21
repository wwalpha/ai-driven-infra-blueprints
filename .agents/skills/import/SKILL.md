---
name: import
description: Acquire once, let any LLM agent ask and checkpoint Human chat selections (including explicit bind), present the complete normalized Review, and obtain explicit Human final consent in chat before one service publication. Follow 08_import for the conversational consent and Review integrity boundary, pre-save checks and sequential single-service workflow. Never directly edit generated design Markdown/JSON.
---

Read `framework/prompts/codex/08_import.md` at the repository root in full and execute
only its contents as the authoritative workflow. Treat Skill arguments as its inputs.
Do not duplicate the Prompt specification. Stop if the Prompt is missing.
Follow its phase-specific reads; reuse unchanged rules already read in this execution.
The retained `codex/08_import.md` path is shared by GitHub Copilot, Codex, Claude Code
and other agents. Use ordinary agent chat; a product-specific question UI is optional.
No IDE, agent SDK or operating system is required by the Import approval contract.

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

Resource references retain their original Markdown label, relative path and fragment. Resolve with consumer scope through the common Model saved-anchor resolver; use fixed Resource numbers and typed logicalIds internally. Preserve independent saved anchors and desired links during IMPORT/observed updates. New anchors reuse `design_layout.resource_anchor()` and confirmed naming rules. No URI conversion or inferred consumer restoration.

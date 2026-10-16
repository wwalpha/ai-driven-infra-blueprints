---
name: import
description: Retrieve one AWS service through the CLI, reflect selected IMPORT sources atomically, then generate its Markdown/JSON in a separate transaction. Preserve CREATE, unselected settings and logical references. Design validation belongs to explicit issues execution.
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

The Human may explicitly request execution without creating a worktree; follow the
Prompt's current-checkout procedure.

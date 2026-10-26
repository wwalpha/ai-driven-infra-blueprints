---
name: deploy
description: Use for independent authorized infrastructure deployment, unfinished AWS operation recovery and a one-shot external Implement handoff.
---

Read `framework/prompts/codex/04_deploy.md` in full and execute its authoritative workflow and required rule readings. Treat invocation input as Human workflow input. Stop if the prompt is missing.

Every CloudFormation invocation uses current Worktree inputs and AWS state. DeployRunContext is memory-only. Never read or migrate old Deploy Sessions, Workflow ledgers/registries, repair histories or Human approval histories. Current destructive ChangeSets still require explicit Human consent and immediate ID/Stack/content/input revalidation. Only unfinished AWS/Secrets/Observed/publication operations use the minimal external Journal; confirmed completion removes it. Unknown submissions retain their original identity and never re-Execute with a new token.

Preserve lazy Stack inputs, shared Load Once / same-generation Validate Once Model Cache, DeployOrder/concurrency, fresh AWS boundaries, per-success Observed sync and atomic publication. Deploy never edits IaC. A proved defect uses a separate authorized Implement Task with a one-shot pinned request, static validation and exact commit integration. Discard temporary evidence after delivery. Subsequent Deploy is independent; do not automatically chain unlimited new invocations. Terraform, Import, Destroy and Issue Gate retain their separate boundaries.

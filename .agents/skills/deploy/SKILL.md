---
name: deploy
description: Use for authorized infrastructure deployment, guarded runtime recovery and supervising-LLM external implement handoff.
---

Read `framework/prompts/codex/04_deploy.md` at the repository root in full and execute its authoritative workflow. Treat input following invocation as Human workflow input. Stop if the prompt is missing. Its Read before changing files section defines mandatory and conditional readings; matching hashes never prove unread content was reviewed.

Deploy never edits authoritative IaC or starts another LLM/Task from Python. For an explicitly authorized external repair loop, the supervising LLM follows the prompt's request/checkpoint/suspend/implement-validation/integration/resume commands. Reuse the original workflow/session and existing Task helpers. Static PASS is a retry candidate; permission and histories survive Task switches. Terraform/update boundaries remain their existing separate contracts.

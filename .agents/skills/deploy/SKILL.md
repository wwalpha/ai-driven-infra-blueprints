---
name: deploy
description: Use for authorized infrastructure deployment, guarded runtime recovery and supervising-LLM external implement handoff.
---

Read `framework/prompts/codex/04_deploy.md` at the repository root in full and execute its authoritative workflow. Treat input following invocation as Human workflow input. Stop if the prompt is missing. Its Read before changing files section defines mandatory and conditional readings; matching hashes never prove unread content was reviewed.

For a validated `Task type: infrastructure` / `Infrastructure phase: deploy` contract,
the Issue Gate is diagnostic and reporting only. Regardless of Issue severity, cause,
content, ownership, count or diagnostic/read failure, it never stops Deploy execution,
resume, Observed synchronization or Task completion. Report non-blocking WARNINGs at
meaningful boundaries and in final validation; leave `issues.md` unchanged. Contract,
Validation scope, AWS identity/permissions, input snapshots, deletion/replacement
approval, atomic publication and AWS API failures retain their existing safety checks.
Other Task types and infrastructure phases retain their ordinary Issue Gate.

Deploy never edits authoritative IaC or starts another LLM/Task from Python. For an explicitly authorized external repair loop, the supervising LLM follows the prompt's request/checkpoint/suspend/implement-validation/integration/resume commands. Reuse the original workflow/session and existing Task helpers. Static PASS is a retry candidate; permission and histories survive Task switches. Terraform/update boundaries remain their existing separate contracts.

Cause identity belongs to the supervising LLM: diagnose SAME/NEW/UNKNOWN with concrete
reasons, compared prior IDs and revision-pinned evidence. UNKNOWN is saved without dummy
labels and never requests repair. Schema pointer/label changes cannot prove NEW; Python
only validates observations and enforces shared-cause attempts, cycles and input safety.
Budget extensions are unavailable without external verifiable Human approval; arbitrary
authorization text fails closed. Close/new Tasks cannot reset unresolved histories.

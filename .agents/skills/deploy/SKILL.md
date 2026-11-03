---
name: deploy
description: Use for authorized infrastructure deployment through the existing SDK controller or independent LLM-direct AWS CLI procedures, unfinished operation recovery and the SDK one-shot Implement handoff.
---

Use only for the Human-authorized infrastructure Deploy scope. Confirm the Task, Target, account/Region and permitted actions; never infer missing scope or expand AWS authority. Preserve fixed inputs, current request evidence and required Human approval. Stop on uncertain identity, unauthorized change, conflicting operation or missing evidence; never blindly resend an uncertain AWS request. Deploy does not change IaC, intended design or scenarios.

Independent Deploy uses a managed Worktree. Resolve the Task ID and Target and follow the Worktree [permission inspection and continuation procedure](../worktree/SKILL.md#sandbox-permission-approval-and-continuation) before invoking:

```console
python3 -B framework/scripts/worktree_task.py deploy-start --task-id <task-id>
```

Use the returned root for registration, preparation and child commands with the registered Python wrapper. Reuse the same valid unfinished Task and its Snapshot, progress and current request evidence; ambiguous ownership stops. Read-only diagnostics, offline preparation and help remain available outside managed Worktrees.

Before preparation or AWS access declare `Deploy execution method` as `sdk` or `cli` in the Task contract. Follow an explicit Human choice; otherwise select and report it (existing invocations without the field retain SDK). The methods are independent: never switch on resume, failure, observation or publication. CLI invokes AWS directly and never uses SDK Controller, sync, checkpoint or deploy-publish. No method selection grants AWS authority.

Read the [Phase Router](../../../framework/prompts/codex/04_deploy.md) once and follow its phase, method and operation-specific reads before acting. If applicability or evidence is unclear, read the potentially applicable safety procedure and stop if unresolved. Do not reread unchanged documents per Stack; this does not replace current AWS reads. Keep Deploy result, Model/View saves, Validation, Git publication and Task completion distinct. No Sub Agents, background writer or automatic IaC repair.

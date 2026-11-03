---
name: deploy
description: Use for authorized infrastructure deployment through the existing SDK controller or independent LLM-direct AWS CLI procedures, unfinished operation recovery and the SDK one-shot Implement handoff.
---

Use only for the Human-authorized infrastructure Deploy scope. Confirm the Task, Target, account/Region and permitted actions; never infer missing scope or expand AWS authority. Preserve fixed inputs, current request evidence and required Human approval. Stop on uncertain identity, unauthorized change, conflicting operation or missing evidence; never blindly resend an uncertain AWS request. Deploy does not change IaC, intended design or scenarios.

Independent Deploy uses the existing managed Worktree [entry procedure](../../../framework/prompts/codex/deploy/runbook.md#managed-entry); no additional Human `/worktree` invocation is required. Resolve the Task and Target, use the returned root, and preserve the same valid unfinished Task and its evidence on resume. Ambiguous ownership stops.

For CloudFormation, before preparation or AWS access declare `Deploy execution method` as `sdk` or `cli` in the Task contract. Follow an explicit Human choice; otherwise select and report it (existing invocations without the field retain SDK). The methods are independent: never switch on resume, failure, observation or publication. CLI invokes AWS directly and never uses SDK Controller, sync, checkpoint or deploy-publish. No method selection grants AWS authority.

Read the [Phase Router](../../../framework/prompts/codex/04_deploy.md) once and follow its phase, method and operation-specific reads before acting. If applicability or evidence is unclear, read the potentially applicable safety procedure and stop if unresolved. Do not reread unchanged documents per Stack; this does not replace current AWS reads. Keep Deploy result, Model/View saves, Validation, Git publication and Task completion distinct. No Sub Agents, background writer or automatic IaC repair.

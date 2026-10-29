---
name: deploy
description: Use for independent authorized infrastructure deployment, unfinished AWS operation recovery and a one-shot external Implement handoff.
---

Independent Deploy automatically uses a managed Worktree; the Human need not invoke `/worktree` separately. Resolve the Task ID and Target, follow the existing [permission inspection and continuation procedure](../worktree/SKILL.md#sandbox-permission-approval-and-continuation), then run the official lifecycle entrypoint from a surviving repository root:

```console
python3 -B framework/scripts/worktree_task.py deploy-start --task-id <task-id>
```

Use its returned `worktree` root for Task registration, Preparation and every child command, with the existing `run-python.py` wrapper. Reuse the same valid unfinished Task on resume; preserve its Snapshot, Journal and AWS evidence. Ambiguous ownership requires review, never a replacement Task. Read-only diagnostics, offline Preparation and help remain available outside managed Worktrees.

Read `framework/prompts/codex/04_deploy.md` in full and follow its AI judgment and authority boundaries. Treat invocation input as Human workflow input; stop if the prompt is missing.

Use the existing Python entrypoints' `--help` for execution, registration, approval, Recovery and one-shot Implement handoff. Follow the prompt's Read section to read applicable Rules directly before each phase. Rules remain authoritative for safety; the prompt is not a Deploy execution input.

Keep current Task/Target authority, immutable inputs, Human approval and AWS/Observed/generation completion distinct. A missing or null nextAction command requires review, never an inferred retry. [Managed Deploy snapshot and Git publication](../../../framework/rules/cloudformation.md#managed-deploy-snapshot-and-git-publication) owns Deploy baseline checks, sealed progress, per-Stack checkpoints and Git-only conflict recovery. Worktree retains lifecycle/setup, repair-child validation and guarded cleanup. Do not expand into other phases or automatically chain unlimited independent Deploy attempts.

For managed CloudFormation Deploy, use `cloudformation-deploy.py --action advance|status|sync|checkpoint` with the same full `--stack` scope. Start/poll AWS with `--action advance`, filling available same-DeployOrder slots first. When AWS is running and no immediate AWS work remains, choose successful unsynchronized Stacks and call `--action sync --sync-stack <StackName>`. After generation and validation, call `--action checkpoint --sync-stack <StackName>`, then return to AWS advancement. Repeat `--sync-stack` only for a shared indivisible candidate. Python never chooses the Model update time, launches agents, or runs a background Model writer. Do not use Sub Agents.

`status` publishes nothing. Completion requires every Stack's AWS, Observed, generation, checkpoint and Git publication barriers. When `gitPublication` is PENDING, inspect its saved checkpoint commits, `checkpointRequired`, `retryable` and `nextActions`. A proven retry uses only the existing `worktree_task.py deploy-publish --task-id <id>` command. It delivers saved checkpoint commits without AWS Execute, Model synchronization or committing working candidates. An unconfirmed candidate must first finish its explicit sync/generation/validation/checkpoint operations; an older saved checkpoint may be published separately. Unknown mode, inputs or ownership requires review. CONFLICT requires explicit Human judgment of the reported files/base/source and impact; do not automatically resolve it or generate executable resolution commands without approval. Treat Git work as complete only after the recorded publication commit is confirmed on the local base. SUCCESS with no unpublished checkpoint needs no Git retry.

A pending Producer/Consumer keeps generation/checkpoint pending; explicitly retry sync after the Producer is synchronized. Use the same actions after interruption: resume an interrupted local checkpoint with `--action checkpoint`; after its durable receipt exists, use Git-only publication for the saved commit. A merge already included on the local base only needs evidence acknowledgement, never a duplicate commit. Never reset automatically. Do not use final Task finalize for an intermediate checkpoint. The final contract commit remains part of the existing Task finalization lifecycle. Run the existing final Task validation/completion only after all barriers finish. Python never decides when to update the Model, and Sub Agents are not used.

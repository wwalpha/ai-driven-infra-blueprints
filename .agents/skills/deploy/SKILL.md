---
name: deploy
description: Use for independent authorized infrastructure deployment, unfinished AWS operation recovery and a one-shot external Implement handoff.
---

Independent Deploy automatically uses a managed Worktree; the Human need not invoke `/worktree` separately. Resolve the Task ID and Target, follow the existing [permission inspection and continuation procedure](../worktree/SKILL.md#sandbox-permission-approval-and-continuation), then run the official lifecycle entrypoint from a surviving repository root:

```console
python3 -B framework/scripts/worktree_task.py deploy-start --task-id <task-id>
```

Use its returned `worktree` root for Task registration, Preparation and every child command, with the existing `run-python.py` wrapper. Reuse the same valid unfinished Task on resume; preserve its Snapshot, progress and current AWS request evidence. Ambiguous ownership requires review, never a replacement Task. Read-only diagnostics, offline Preparation and help remain available outside managed Worktrees.

Read `framework/prompts/codex/04_deploy.md` in full and follow its AI judgment and authority boundaries. Treat invocation input as Human workflow input; stop if the prompt is missing.

Use the existing Python entrypoints' `--help` for execution, registration, approval, Recovery and one-shot Implement handoff. Follow the prompt's Read section to read applicable Rules directly before each phase. Rules remain authoritative for safety; the prompt is not a Deploy execution input.

Keep current Task/Target authority, immutable inputs, Human approval and AWS/Observed/generation completion distinct. A missing or null nextAction command requires review, never an inferred retry. [Managed Deploy snapshot and Git publication](../../../framework/rules/cloudformation.md#managed-deploy-snapshot-and-git-publication) owns Deploy baseline checks, sealed progress, per-Stack checkpoints and Git-only conflict recovery. Worktree retains lifecycle/setup, repair-child validation and guarded cleanup. Do not expand into other phases or automatically chain unlimited independent Deploy attempts.

For managed CloudFormation Deploy, use the same full `--stack` scope with
`cloudformation-deploy.py --action status|advance|sync|checkpoint`.

- `status` obtains current AWS and displays current state, this attempt's result,
  Model save, Snapshot validation and Git publication independently.
- `advance` advances one bounded AWS turn using current state, fixed inputs,
  DeployOrder, configured concurrency and destructive-change approval. Same-Order
  independent peers may continue after one failure. Later Orders still require success.
- `sync --sync-stack <name>` saves selected current observations, generates available
  services, validates the Snapshot and commits/publishes through existing Git helpers.
  Success, failure, rollback, partial, unexecuted, running and unknown are valid facts.
  No separate checkpoint stage is normally required. The LLM chooses timing and scope;
  repeat `--sync-stack` for an indivisible candidate. Python never schedules Model sync.
- `checkpoint --sync-stack <name>` resumes an already saved candidate's local
  validation/commit/publication without a fresh observation or AWS execution.

Normal start/resume reads scoped current AWS before deciding operations. Old Task,
mode, status, Outputs, synchronization, checkpoint or Git evidence never
qualifies the current state. External repair is adopted without a special repair-path
proof. A successful current Stack does not prove the fixed Desired is applied: inspect
its current ChangeSet. UNKNOWN is not absence; REVIEW_IN_PROGRESS requires current
ChangeSet classification.

Shared current requests prevent duplicate submissions under execution-account/Region/
StackName locks. Persist intent before sending, retain original Stack/ChangeSet/token
on a lost response and retire it after AWS settles, before Model/Git. One old COMPLETE
read is insufficient after uncertain Execute. Corrupt current requests withhold only
that Stack's new mutation. They never prohibit Model saves or unrelated Stacks.

Sync atomically saves Model authority before generation. Preserve Desired and unknown
identifier absence; do not reuse old link labels/IDs or infer deployed Consumer settings.
Keep confirmed sources and successful generated services if another View fails. Actual
Snapshot inconsistency retains the candidate and fails required validation.

For intermediate sync, Task remains running and the same Worktree/fixed IaC can continue.
For a settled final snapshot, select `sync --final` explicitly. Include completed in
the private validation candidate; adopt it only after PASS, then commit/publish that
same Model/View/Task candidate. Omit --sync-stack when all needed observations are
already saved. `checkpoint` resumes the saved final intent without another --final. Deploy FAIL remains FAIL even when Snapshot validation and Git succeed.
No extra failure approval, force, all-Stack SUCCESS or individual checkpoint requirement.
Active/uncertain AWS requests retain tracking and prevent Task completion.

Git PENDING/CONFLICT never changes the Deploy result. Use existing
`worktree_task.py deploy-publish --task-id <id>` for saved commits, including a locally
completed candidate after commit success/merge failure. It does not execute AWS or
repeat observations. Existing Human conflict review and actual latest-base validation
remain required. After verified integration use ordinary finalize/guarded cleanup.

No Sub Agents, background writer, general workflow engine or automatic IaC repair.

A settled request with an unconfirmed attempt outcome may report Deploy UNKNOWN; this never becomes a physical identifier or an active-request bypass. Current root Stack events are scoped by StackId and original token, and never replace the independently read current Stack status.

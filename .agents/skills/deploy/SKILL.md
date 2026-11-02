---
name: deploy
description: Use for authorized infrastructure deployment through the existing SDK controller or independent LLM-direct AWS CLI procedures, unfinished operation recovery and the SDK one-shot Implement handoff.
---

Independent Deploy automatically uses a managed Worktree; the Human need not invoke `/worktree` separately. Resolve the Task ID and Target, follow the existing [permission inspection and continuation procedure](../worktree/SKILL.md#sandbox-permission-approval-and-continuation), then run the official lifecycle entrypoint from a surviving repository root:

```console
python3 -B framework/scripts/worktree_task.py deploy-start --task-id <task-id>
```

Use its returned `worktree` root for Task registration, Preparation and every child command, with the existing `run-python.py` wrapper. Reuse the same valid unfinished Task on resume; preserve its Snapshot, progress and current AWS request evidence. Ambiguous ownership requires review, never a replacement Task. Read-only diagnostics, offline Preparation and help remain available outside managed Worktrees.

Read `framework/prompts/codex/04_deploy.md` in full and follow its AI judgment and authority boundaries. Treat invocation input as Human workflow input; stop if the prompt is missing.

For large CloudFormation templates, `templateBucket` may name an existing bucket directly or use a same-target S3 Model reference. Template placement skips bucket preflight and retains object integrity and resume checks; Artifact bucket requirements remain unchanged. See [S3 deployment artifacts](../../../framework/rules/cloudformation.md#s3-deployment-artifacts).

## Select the execution method

Before preparation or AWS access, declare `Deploy execution method` as the backticked value `sdk` or `cli` in `## Task contract`. Follow an explicit Human choice; otherwise the LLM chooses and reports it (existing invocations without the field retain SDK). The methods are independent. Never switch a CLI Task automatically to SDK, including for recovery, observations or publication. An SDK-bound Task cannot become a CLI Task.

- **SDK**: Python Controller + boto3, using the existing `cloudformation-deploy.py` procedures below. Keep all existing behavior.
- **CLI**: the LLM runs `aws` directly in its execution tool and decides each next operation from AWS JSON. Read [Direct AWS CLI deployment](../../../framework/rules/cloudformation.md#direct-aws-cli-deployment) and the prompt's CLI section. Do not invoke the Controller, its `sync`/`checkpoint`, SDK Preparation, Scheduler, Journal or AWS locks. Do not call AWS CLI from Python, import boto3/botocore, or add an AWS backend, common interface, common state or common lock. AWS CLI v2 is the AWS runtime; no separate Python SDK installation or SDK receipt is required for this execution path. Local observation, generation, validation, Task completion and Git utilities perform no AWS operations; use the CLI Task's confirmed account/Region/Partition for local Model references.

Both methods retain Task authority, account/profile/Region, ChangeSet approval, DeployOrder/concurrency, fixed Snapshot, S3 integrity and existing Model/Validation/publication semantics. SDK and CLI concurrent mutation of the same Stack is outside the guarantee; stop CLI mutations on detected competing operations. No method selection authorizes AWS access in a governance task.

CLI sequence: confirm CLI/context/Task and fixed inputs → inspect scoped Stacks and dependencies → validate inputs and deliver declared objects → create/read the complete ChangeSet → obtain required destructive-change consent → recheck and execute that exact ChangeSet → inspect current Stack/events → synchronize permitted observations and validate/publish through existing non-AWS utilities. Resume by current AWS identity/token evidence; stop on ambiguity. After all requests settle and required saves/checks pass, use `task_contract.py --complete`, then ordinary Worktree `finalize`; the CLI branch validates the actual latest-base candidate without SDK progress/receipts. Do not use SDK `deploy-publish` or PR publication for this path.

## SDK execution

Use the existing Python entrypoints' `--help` for SDK execution, registration, approval, Recovery and one-shot Implement handoff. Follow the prompt's Read section to read applicable Rules directly before each phase. Rules remain authoritative for safety; the prompt is not a Deploy execution input. The Controller commands, shared request records and locks, sealed progress, repair handoff and final-save procedures below apply only to SDK execution.

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

## DeployOrder selection and synchronization scope

SDK offline Preparation supports repeated `--stack` or inclusive numeric
`--order-from` / `--order-to` bounds. `--service` is optional and only checks the
automatically discovered owner services. Review the resolved StackNames, Resource
ownership and output paths before registration. Resume uses the Task's full fixed
StackName scope for every Controller action, never the original Order selector.
External consumer services are deferred without Model/View writes. Follow
[DeployOrder selection and synchronization scope](../../../framework/rules/cloudformation.md#deployorder-selection-and-synchronization-scope)
for diagnostics, selected validation, external dependencies and CLI boundaries.

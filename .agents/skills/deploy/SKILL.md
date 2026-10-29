---
name: deploy
description: Use for independent authorized infrastructure deployment, unfinished AWS operation recovery and a one-shot external Implement handoff.
---

Read `framework/prompts/codex/04_deploy.md` in full and follow its AI judgment and authority boundaries. Treat invocation input as Human workflow input; stop if the prompt is missing.

Use the existing Python entrypoints' `--help` for execution, registration, approval, Recovery and one-shot Implement handoff. CloudFormation Preparation's `deploy/required_readings.py` owns required Rules selection; read all returned required bodies before registering. Rules remain authoritative for safety. The prompt is a thin AI entry and is not a Deploy execution input.

Keep current Task/Target authority, immutable inputs, Human approval and AWS/Observed/generation completion distinct. A missing or null nextAction command requires review, never an inferred retry. Worktree owns isolation, repair-child validation and integration. Do not expand into other phases or automatically chain unlimited independent Deploy attempts.

For managed CloudFormation Deploy, use `cloudformation-deploy.py --action advance|status|sync|checkpoint` with the same full `--stack` scope. Start/poll AWS with `--action advance`, filling available same-DeployOrder slots first. When AWS is running and no immediate AWS work remains, choose successful unsynchronized Stacks and call `--action sync --sync-stack <StackName>`. After generation and validation, call `--action checkpoint --sync-stack <StackName>`, then return to AWS advancement. Repeat `--sync-stack` only for a shared indivisible candidate. Python never chooses the Model update time, launches agents, or runs a background Model writer. Do not use Sub Agents.

`status` publishes nothing. Completion requires every Stack's AWS, Observed, generation and checkpoint barriers. A pending Producer/Consumer keeps generation/checkpoint pending; explicitly retry sync after the Producer is synchronized. Use the same actions after interruption: original Tokens are polled, publication is reconciled, and saved checkpoint intents prevent duplicate commits. Never reset automatically. Do not use final Task finalize for an intermediate checkpoint. Run the existing final Task validation/completion only after all barriers finish.

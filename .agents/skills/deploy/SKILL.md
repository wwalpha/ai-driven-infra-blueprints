---
name: deploy
description: Use for independent authorized infrastructure deployment, unfinished AWS operation recovery and a one-shot external Implement handoff.
---

Read `framework/prompts/codex/04_deploy.md` in full and follow its AI judgment and authority boundaries. Treat invocation input as Human workflow input; stop if the prompt is missing.

Use the existing Python entrypoints' `--help` for execution, registration, approval, Recovery and one-shot Implement handoff. CloudFormation Preparation's `deploy/required_readings.py` owns required Rules selection; read all returned required bodies before registering. Rules remain authoritative for safety. The prompt is a thin AI entry and is not a Deploy execution input.

Keep current Task/Target authority, immutable inputs, Human approval and AWS/Observed/generation completion distinct. A missing or null nextAction command requires review, never an inferred retry. Worktree owns isolation, repair-child validation and integration. Do not expand into other phases or automatically chain unlimited independent Deploy attempts.

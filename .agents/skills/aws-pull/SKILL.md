---
name: aws-pull
description: Compare existing CREATE Resources with AWS, review every proposed Model value with the Human, and save only explicitly approved changes without changing AWS or IaC.
---

Follow [AWS pull](../../../framework/prompts/codex/09_aws_pull.md).
For the requested environment, target and services, compare existing CREATE Resources,
analyze differences, show every Model Before/After, obtain explicit final Human consent,
save only reviewed changes and run related Change Validation. Process services sequentially,
with independent Review, consent and save for each service. Invocation is not approval.

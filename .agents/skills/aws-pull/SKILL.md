---
name: aws-pull
description: Fetch existing CREATE Resources, save confirmed identifiers directly, and review and approve settings changes without changing AWS or IaC.
---

Follow [AWS pull](../../../framework/prompts/codex/09_aws_pull.md).
For each requested service, use the existing CREATE acquisition to save confirmed
identifier observations directly. For settings changes, show every Model Before/After,
obtain explicit final Human consent, then save only reviewed changes. Run related Change
Validation. Process services sequentially. Invocation authorizes confirmed observation
saves in the requested scope and does not approve settings changes.

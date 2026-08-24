# Codex Task: Add the VPC Flow Log catalog resource

## Task contract

- Task type: `catalog-maintenance`
- Goal: add `AWS::EC2::FlowLog` from the Tokyo CloudFormation Resource Specification `258.0.0`
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden
- Network access: allowed only for official AWS specification and documentation

## Required changes

1. Add only `materials/aws/EC2_FlowLog.properties` with resource and nested properties from specification `258.0.0`.
2. Update the catalog file/property counts and integrity manifest.
3. Preserve all unrelated worktree changes.

## Allowed paths

- `README.md`
- `materials/aws/EC2_FlowLog.properties`
- `materials/catalog.properties`
- `materials/catalog.sha256`
- `prompts/codex/implement-infrastructure.md`
- `prompts/codex/run-scenario-test.md`
- `scripts/check-deploy-context.py`
- `scripts/check-deploy-context.checks.py`
- `scripts/validate-blueprint.py`
- `tasks/active.md`

## Verification

- Confirm every added property against the official Tokyo Resource Specification `258.0.0`.
- Run `python3 scripts/update-catalog-lock.py --write` and then its check mode.
- Run the local loop.
- Run `git diff --check`.
- Do not call AWS APIs or save verification evidence in the repository.

## Pre-existing worktree changes

The non-material paths above were already modified before this catalog-maintenance task. Preserve them without further changes.

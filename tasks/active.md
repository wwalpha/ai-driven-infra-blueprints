# Codex Task: Add reusable framework synchronization

## Task contract

- Task type: `migration`
- Goal: synchronize existing framework files from this repository into `viewcard-code`
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Allowed paths

- `scripts/sync-existing-files.py`
- `tasks/active.md`

## Out of scope

- Files that exist in only one repository
- `.git/**`
- `tasks/active.md` synchronization
- CloudFormation/Terraform implementation
- AWS resource changes
- IaC execution

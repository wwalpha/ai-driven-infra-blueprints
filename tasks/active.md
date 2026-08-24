# Codex Task: Remove globally unselected IaC engine directories

## Task contract

- Task type: `governance`
- Goal: keep only IaC engine directories selected by the confirmed project topology after initialization
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden
- Network access: not required

## Required changes

1. Remove an IaC engine root during initialization when no confirmed target selects that engine.
2. Keep both engine roots only when the confirmed topology selects both engines.
3. Make the local validator reject globally unselected IaC engine directories after initialization.

## Allowed paths

- `README.md`
- `prompts/codex/initialize-repository.md`
- `scripts/validate-blueprint.py`
- `tasks/active.md`

## Verification

- Run the local loop.
- Run focused initialized-topology checks for CloudFormation-only, Terraform-only, and mixed selections.
- Run `python3 -m py_compile scripts/validate-blueprint.py`.
- Run `git diff --check`.
- Do not call AWS APIs or save verification evidence in the repository.

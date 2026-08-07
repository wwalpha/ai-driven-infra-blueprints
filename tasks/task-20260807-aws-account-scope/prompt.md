# Codex Task: Use AWS account as the design scope

## Task contract

- Task ID: `task-20260807-aws-account-scope`
- Goal: replace the generic deployment scope with the exact AWS account scope throughout repository initialization and design paths
- AWS mutation: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

1. Use `docs/designs/<environment>/<aws-account-id>/`, `llm/designs/<environment>/<aws-account-id>/`, and `llm/actuals/<environment>/<aws-account-id>/`.
2. Remove the `Deployment ID` concept from System Overview, prompts, rules, and validation.
3. Use the 12-digit AWS account ID as the directory segment; do not introduce another account alias/key.
4. Keep arbitrary environment counts and arbitrary AWS account counts per environment.
5. Keep one selected IaC engine per environment/AWS-account pair.
6. Do not change `materials/aws/**` or perform AWS operations.

## Allowed paths

- `AGENTS.md`
- `README.md`
- `blueprint.properties`
- `copilot/**`
- `docs/system-overview.md`
- `prompts/**`
- `rules/**`
- `scripts/**`
- `tasks/**`
- `tests/results/**`

## Verification

- Run the local loop for this task.
- Verify template and populated multi-account System Overview fixtures.
- Run Python and shell syntax checks.
- Run `git diff --check`.

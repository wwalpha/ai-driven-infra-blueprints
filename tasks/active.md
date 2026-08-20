# Codex Task: Make initialization questions step-by-step

## Task contract

- Task type: `governance`
- Goal: collect repository initialization values through one question per response
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden
- Network access: not required

## Required changes

1. Replace the batched initialization questionnaire with a one-question-at-a-time flow.
2. Keep all answers in conversation context without questionnaire or session files.
3. Confirm the collected topology before changing repository files.

## Allowed paths

- `AGENTS.md`
- `README.md`
- `materials/catalog.properties`
- `prompts/codex/initialize-repository.md`
- `rules/detailed-design.md`
- `rules/loop-engineering.md`
- `rules/post-deploy-actuals.md`
- `rules/scenario-testing.md`
- `scripts/blueprint-loop.sh`
- `scripts/update-catalog-lock.py`
- `scripts/validate-blueprint.py`
- `tasks/**`

## Verification

- Run the local loop.
- Run `git diff --check`.
- Do not call AWS APIs or save verification evidence in the repository.

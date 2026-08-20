# Codex Task: Simplify active task contracts

## Task contract

- Task type: `migration`
- Goal: use one fixed active task contract and remove identifier-based task storage and metadata
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden
- Network access: not required

## Required changes

1. Use `tasks/active.md` as the only active task contract.
2. Remove identifier fields, arguments, metadata, validation, and per-task directories.
3. Keep Task type and Allowed paths as the task boundary.
4. Do not retain legacy task prompts or add a task history mechanism.
5. Keep scenario identity based on Scenario ID.

## Allowed paths

- `AGENTS.md`
- `README.md`
- `prompts/codex/initialize-repository.md`
- `rules/detailed-design.md`
- `rules/loop-engineering.md`
- `rules/post-deploy-actuals.md`
- `rules/scenario-testing.md`
- `scripts/blueprint-loop.sh`
- `scripts/update-catalog-lock.py`
- `scripts/validate-blueprint.py`
- `tasks/**`
- `materials/catalog.properties`

## Verification

- Run Python and shell syntax checks.
- Run catalog integrity check.
- Run the local loop using `tasks/active.md`.
- Use temporary fixtures to verify active task validation and task boundary behavior.
- Run `git diff --check`.
- Do not call AWS APIs or save verification evidence in the repository.

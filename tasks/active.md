# Codex Task: Rename project topology file

## Task contract

- Task type: `migration`
- Goal: rename `project-topology.json` to `project.json` across the framework and the initialized target repository
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Allowed paths

- `AGENTS.md`
- `README.md`
- `docs/system-overview.md`
- `prompts/chatbot/initial-service-design.md`
- `prompts/codex/implement-infrastructure.md`
- `prompts/codex/initialize-repository.md`
- `prompts/codex/run-scenario-test.md`
- `rules/detailed-design.md`
- `rules/loop-engineering.md`
- `rules/scenario-testing.md`
- `scripts/check-deploy-context.checks.py`
- `scripts/check-deploy-context.py`
- `scripts/sync-existing-files.py`
- `scripts/validate-blueprint.py`
- `tasks/active.md`

## Out of scope

- Detailed-design content changes
- `llm/designs/**`
- `llm/actuals/**`
- `infra/**`
- `tests/**`
- CloudFormation/Terraform implementation
- AWS resource changes
- IaC execution

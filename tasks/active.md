# Codex Task: Complete detailed-design migration with cross-platform execution

## Task contract

- Task type: `migration`
- Goal: preserve the detailed-design migration and replace required Bash execution with cross-platform Python
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Allowed paths

- `README.md`
- `rules/detailed-design.md`
- `rules/llm-design-information.md`
- `rules/post-deploy-actuals.md`
- `rules/loop-engineering.md`
- `prompts/chatbot/initial-service-design.md`
- `prompts/codex/initialize-repository.md`
- `prompts/codex/implement-infrastructure.md`
- `prompts/codex/run-scenario-test.md`
- `scripts/blueprint-loop.py`
- `scripts/blueprint-loop.sh`
- `scripts/validate-blueprint.py`
- `docs/designs/**`
- `llm/designs/**`
- `tasks/active.md`

## Out of scope

- `materials/aws/**`
- `llm/actuals/**`
- CloudFormation/Terraform implementation
- AWS resource changes
- scenario definitions and results

# Codex Task: Migrate detailed-design framework

## Task contract

- Task type: `migration`
- Goal: enforce service-based design grouping and minimal detailed-design Markdown
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

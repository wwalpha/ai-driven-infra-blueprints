# Codex Task: Codex-driven repository initialization

## Task contract

- Task ID: `task-20260820-codex-driven-initialization`
- Task type: `migration`
- Goal: separate background information from initialization configuration and make Codex create project topology and target paths through the initialization prompt
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden
- Network access: not required

## Required changes

1. Treat `docs/system-overview.md` as background/reference information that may contain `UNSET` without blocking initialization.
2. Make `prompts/codex/initialize-repository.md` collect all required initialization values from the user in a compact interaction without requiring or deriving them from System Overview.
3. Make Codex create `project-topology.json`; do not instruct the human to edit JSON directly.
4. Use `project-topology.json` as the machine-readable source of truth for project name, environment, AWS account, region, and IaC engine after initialization.
5. Create target paths from the generated topology and end the initialization task without starting another task.
6. Update repository instructions, related prompts/rules, and the standard-library validator for the separated model.
7. Do not create sample project topology, design, IaC, scenario, or result data.

## Allowed paths

- `AGENTS.md`
- `README.md`
- `project-topology.json`
- `docs/system-overview.md`
- `prompts/chatbot/initial-service-design.md`
- `prompts/codex/initialize-repository.md`
- `rules/loop-engineering.md`
- `rules/scenario-testing.md`
- `scripts/validate-blueprint.py`
- `tasks/task-20260820-codex-driven-initialization/**`

## Verification

- Run Python and shell syntax checks.
- Run catalog integrity check.
- Run the local loop for this migration task.
- Use temporary fixtures to verify pre-initialization, valid generated topology, and invalid topology behavior.
- Run `git diff --check`.
- Do not call AWS APIs or save verification evidence in the repository.

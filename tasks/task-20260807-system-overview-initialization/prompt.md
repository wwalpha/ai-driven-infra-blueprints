# Codex Task: System Overview driven repository initialization

## Task contract

- Task ID: `task-20260807-system-overview-initialization`
- Goal: make repository initialization derive arbitrary environment and AWS account topology from the completed System Overview
- AWS mutation: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

1. Make `docs/system-overview.md` the human-maintained source of truth for project identity, environments, AWS accounts, regions, and IaC engines.
2. Add a reusable Codex initialization prompt that assumes the System Overview is complete.
3. Define initialized paths as `docs/designs/<environment>/<aws-account-id>/`, `llm/designs/<environment>/<aws-account-id>/`, `llm/actuals/<environment>/<aws-account-id>/`, and the selected IaC engine's matching target path.
4. Do not require fixed environment names, environment counts, account counts, or identical account counts between environments.
5. Update repository instructions, rules, and local validation for the new topology.
6. Remove `blueprint.properties` rather than keep a second project-configuration source of truth.
7. Do not create example infrastructure, resource design files, or session state.
8. Preserve `materials/aws/**` unchanged.

## Allowed paths

- `AGENTS.md`
- `README.md`
- `blueprint.properties`
- `copilot/**`
- `docs/**`
- `llm/**`
- `infra/**`
- `prompts/**`
- `rules/**`
- `scripts/**`
- `tasks/**`
- `tests/results/**`

## Verification

- Run the local loop for this task.
- Run Python and shell syntax checks.
- Verify both template and populated multi-environment/multi-account System Overview fixtures.
- Run `git diff --check`.

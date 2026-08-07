# Codex Task: Generic infrastructure blueprint

## Task contract

- Task ID: `task-20260807-generic-blueprint`
- Goal: make the repository itself a reusable AWS infrastructure workflow blueprint, not a blueprint for a particular system architecture
- AWS mutation: forbidden
- CloudFormation deploy/update/delete: forbidden
- Terraform apply/destroy/import: forbidden
- Network access: not required

## Required changes

1. Remove the web-nginx sample, completed historical tasks, and migration evidence from the active blueprint tree. Git history is sufficient retention.
2. Add one machine-readable source of truth for project name, environments, AWS account/region constraints, and the selected IaC engine.
3. Replace the sample/migration-specific validator with a generic validator that discovers project design groups dynamically and permits task-authorized IaC/test changes.
4. Add catalog provenance and integrity metadata for `materials/aws/` without changing the catalog property files.
5. Update the initial-use instructions and active governance text for the generic blueprint.

## Boundaries

- Keep the existing ChatGPT + human + Codex operating model.
- Keep the human design -> LLM design -> selected IaC update order.
- Keep one IaC engine per environment.
- Keep explicit deploy/apply authorization and missing-input stop rules.
- Keep behavior-oriented scenario tests and task evidence rules.
- Use only Python standard library and shell already used by the repository.
- Do not add a project generator, deployment framework, or example infrastructure.
- Do not change any `materials/aws/*.properties` file.

## Allowed paths

- `AGENTS.md`
- `README.md`
- `blueprint.properties`
- `rules/**`
- `scripts/**`
- `materials/catalog.properties`
- `materials/catalog.sha256`
- `docs/designs/**`
- `llm/**`
- `infra/**`
- `tests/**`
- `tasks/**`

## Verification

- Run the generic local loop for this task.
- Run Python and shell syntax checks.
- Verify catalog file count, property count, and checksums.
- Run `git diff --check`.

# Codex Task: Unify machine-readable service models

## Task contract

- Task type: `migration`
- Goal: `llm/designs`と`llm/actuals`を、service単位でdesired/observedを保持する`model`へ統合する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] project固有pathを`llm/designs/**`と`llm/actuals/**`から`model/<environment>/<aws-account-id>/**`へ移行する。
- [R2] 一つの詳細設計Markdownから、同じserviceの`desired.*`と`observed.*`を一つのpropertiesへ生成する。
- [R3] frameworkのrule、prompt、validator、説明、commandを新model contractへ統一する。
- [R4] 旧`llm/**`path、旧mirror command、desired/observed分離directoryを残さない。

## Acceptance checks

- [R1] `exists:model/.gitkeep`
- [R1] `absent:llm`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:AGENTS.md`
- [R3] `changed:README.md`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R4] `absent:framework/scripts/sync-design-mirror.py`
- [R4] `absent:framework/rules/llm-design-information.md`

## Allowed paths

- `README.md`
- `AGENTS.md`
- `llm/**`
- `model/**`
- `framework/**`
- `tasks/active.md`

## Out of scope

- `docs/**`、`infra/**`、`tests/**`の内容変更
- `project.json`の作成または変更
- catalog/schema、IaC、scenarioの内容変更
- AWS API、deploy、apply

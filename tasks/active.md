# Codex Task: Package reusable framework files

## Task contract

- Task type: `migration`
- Goal: reusable framework資産を`framework/`へ集約し、project固有directoryと分離して一括コピー可能にする
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] `copilot`、`materials`、`prompts`、`rules`、`scripts`を`framework/`配下へ移動する。
- [R2] root entrypoint、prompt、rule、scriptの全path参照を新layoutへ更新する。
- [R3] project固有の`docs`、`infra`、`llm`、`tasks`、`tests`、`project.json` path contractを維持する。
- [R4] framework copy/sync workflowとrepository構造説明を新layoutへ更新する。

## Acceptance checks

- [R1] `exists:framework/materials/catalog.properties`
- [R1] `exists:framework/scripts/blueprint-loop.py`
- [R1] `absent:materials`
- [R1] `absent:scripts`
- [R2] `changed:AGENTS.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `exists:docs/designs/.gitkeep`
- [R3] `exists:llm/designs/.gitkeep`
- [R4] `changed:README.md`
- [R4] `changed:framework/scripts/sync-existing-files.py`

## Allowed paths

- `README.md`
- `AGENTS.md`
- `copilot/**`
- `materials/aws/**`
- `materials/**`
- `prompts/**`
- `rules/**`
- `scripts/**`
- `framework/**`
- `materials/cloudformation-schema/**`
- `tasks/active.md`

## Out of scope

- `docs/**`、`infra/**`、`llm/**`、`tests/**`の移動または内容変更
- `project.json`の作成または変更
- layout移行に不要なframework behavior、設計contract、catalog/schema内容の変更
- AWS API、deploy、apply

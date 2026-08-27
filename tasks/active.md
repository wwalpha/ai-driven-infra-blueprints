# Codex Task: Document existing AWS configuration request

## Task contract

- Task type: `governance`
- Goal: 既存AWS resourceの現在値を詳細設計へ反映する依頼例をprompt guideへ追加する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] `service-design.md`を使って既存VPCの現在値を詳細設計へ反映する、再利用可能な依頼例を記載する。

## Acceptance checks

- [R1] `changed:framework/prompts/README.md`

## Allowed paths

- `framework/prompts/README.md`
- `tasks/active.md`

## Out of scope

- prompt本体、rules、validatorの変更
- 詳細設計、model、IaC、scenarioの変更
- AWS API、deploy、applyの実行

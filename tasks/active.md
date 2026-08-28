# Codex Task: Use alias-based prompt guide examples

## Task contract

- Task type: `governance`
- Goal: `framework/prompts/README.md`のtarget指定サンプルをaliasベースへ統一する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] targetを指定する使用例にTarget aliasを含め、target directoryのpathをaliasベースにする。

## Acceptance checks

- [R1] `changed:framework/prompts/README.md`

## Allowed paths

- `framework/prompts/README.md`
- `tasks/active.md`

## Out of scope

- prompt本文、rule、script、catalogの変更
- `project.json`、design、model、IaC、scenarioの変更
- AWS API、deploy、applyの実行

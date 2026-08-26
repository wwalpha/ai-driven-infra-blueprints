# Codex Task: Infer manual update scope

## Task contract

- Task type: `governance`
- Goal: `05_update.md`がscopeを自動特定し、省略可能なdefault入力なしで使用できるようにする
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 手動修正された詳細設計fileを対象environment／AWS accountのgit diffから自動特定する。
- [R2] 対応するdeployment unitを既存IaCから自動特定し、一意に決まらない項目だけ質問する。
- [R3] scopeとdefault入力の指定が不要な最小使用例へPrompt Guideを更新する。

## Acceptance checks

- [R1] `changed:framework/prompts/README.md`
- [R1] `changed:framework/prompts/codex/05_update.md`
- [R2] `changed:framework/prompts/codex/05_update.md`
- [R3] `changed:framework/prompts/README.md`

## Allowed paths

- `framework/prompts/README.md`
- `framework/prompts/codex/05_update.md`
- `tasks/active.md`

## Out of scope

- 他prompt、rule、script、catalogの変更
- 既存projectのIaC、詳細設計、model、scenarioの変更
- AWS API、deploy、apply

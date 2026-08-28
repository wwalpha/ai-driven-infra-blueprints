# Codex Task: Add generic AWS resource naming rules

## Task contract

- Task type: `governance`
- Goal: 汎用AWS resource naming conventionの初版を定義し、詳細設計作成時に適用する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 組織固有名を含まないAWS resource naming conventionの初版を追加する。
- [R2] 詳細設計ruleとservice design promptからnaming conventionを必須参照する。

## Acceptance checks

- [R1] `exists:framework/rules/aws-resource-naming.md`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/prompts/chatbot/service-design.md`

## Allowed paths

- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design.md`
- `framework/prompts/chatbot/service-design.md`
- `tasks/active.md`

## Out of scope

- 既存詳細設計とmodelの命名変更
- validator、catalog、IaC、scenarioの変更
- AWS API、deploy、applyの実行

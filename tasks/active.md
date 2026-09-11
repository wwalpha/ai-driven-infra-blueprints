# KMS KeyPolicy派生表示の重複項目を省略

## Task contract

- Task type: `governance`
- Target: framework共通 / KMS KeyPolicyの派生表示契約
- Goal: KMS Keyの設定表直後に生成するKeyPolicy表示から、設定表とJSON artifactに重複するProperty、JSON、Version、Idを省略する。元の設定行、JSON artifact、policy内容、model値は保持する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 詳細設計ルール、chatbot prompt、local loopの検証基準へKMS KeyPolicy固有の省略契約を反映する。
- [R2] 共通policy rendererはKMS KeyPolicyの派生表示だけをanchor、見出し、Statement表に絞り、他のpolicy表示を維持する。
- [R3] focused checkとlocal loopでKMS固有項目の省略、JSON由来のStatement、決定的生成、validation、model不変を確認する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:framework/scripts/policy_tables.py`
- [R3] `changed:framework/scripts/policy_tables.checks.py`
- [R3] `check:framework.policy-tables`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/policy_tables.py`
- `framework/scripts/policy_tables.checks.py`
- `CMD.md`

## Out of scope

- CMD.mdは開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- KMS KeyPolicy以外のpolicy表示、policy JSONの内容、resource一覧・設定表、catalog、schema、model形式
- consumer同期、個別詳細設計・model実体・IaC、AWS操作、scenario

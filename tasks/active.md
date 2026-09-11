# リソース一覧と詳細の見出し階層を明確化

## Task contract

- Task type: `governance`
- Target: framework共通 / 全serviceの詳細設計Markdown
- Goal: リソース一覧とリソース詳細をH2で区切り、個々のresourceを詳細配下のH3、policyをH4として表示する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 共通設計rule・model rule・chatbot promptに、リソース一覧とリソース詳細のH2、resourceのH3、policyのH4を定義する。
- [R2] validator、grouped resource処理、model生成、policy表生成を新しい見出し階層へ対応させ、一覧と詳細の境界・見出し欠落・重複・配置・階層を検証する。
- [R3] 既存focused checkのMarkdownを更新し、全service共通の見出し検証、grouping・参照・model・policy派生表示を確認してlocal loopを完了する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/policy_tables.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/scripts/design_catalog.checks.py`
- [R3] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/scripts/policy_tables.checks.py`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/design_catalog.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/policy_tables.py`
- `framework/scripts/policy_tables.checks.py`
- `CMD.md`

## Out of scope

- CMD.mdは開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- resource/propertyの選択・値、anchor、logical ID、catalog、resource-layout.json、model生成形式、一覧column仕様
- consumer同期、個別詳細設計・model・IaC、AWS操作、scenario

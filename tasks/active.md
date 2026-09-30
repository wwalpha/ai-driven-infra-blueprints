# AWSサービスロールのリンク必須チェック修正

## Task contract

- Task type: `governance`
- Target: framework共通 / IAM Role参照の表示検証
- Goal: AWSServiceで始まるサービスロール名をリンクなしで設計・生成できるようにし、通常のIAM Role参照のリンク検証を維持する。

## Required changes

- [R1] IAM Roleを参照する表示propertyでAWSServiceから始まるロール名literalを許可する。ARN、role path、通常ロールのliteralは許可しない。
- [R2] IAM設計が存在しないConfigの検証・model生成・Markdown生成と、既存リンク検証の回帰チェックを追加する。
- [R3] 詳細設計rule、model rule、chatbot promptへ同じ例外を反映する。

## Acceptance checks

- [R1] `changed:framework/scripts/design_layout.py`
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/design_layout.checks.py`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`

## Out of scope

- target設計、target model、IaC、AWS操作、scenario、catalog、別repositoryの変更。

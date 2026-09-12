# Source / Commentの簡潔化

## Task contract

- Task type: `governance`
- Target: framework共通 / Source / Comment
- Goal: 見出し・Propertyから分かる対象resource名を繰り返さず、属性の意味を短く説明する共通ルールと生成文へ統一する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 共通ルール・例文と生成前の自己確認へ、対象resource名の重複省略と参照先・通信元・通信先の名称保持を明記する。
- [R2] Security Groupの固定生成コメントも同じ基準へ揃え、生成結果と参照対象の名称保持をfocused checkで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R2] `changed:framework/scripts/security_group_tables.checks.py`
- [R2] `check:framework.resource-layout`

## Allowed paths

- `tasks/active.md`
- `framework/materials/aws/*.properties`
- `framework/materials/api/Macie_ClassificationJob.properties`
- `framework/materials/api-catalog.sha256`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/rules/resource-name-properties.json`
- `framework/rules/detailed-design.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/observed-values.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/*.py`
- `CMD.md`

## Out of scope

- 今回の編集はtasks/active.mdと上記Acceptance checksに列挙した4ファイルのみ。他のAllowed pathsは前taskの未commit差分を保持して検証するために列挙している。
- 既存の個別詳細設計・model・IaC、catalog、AWS操作、scenario、commit/push、未追跡CMD.md
- 自然言語の一律置換や、参照対象の名称を誤って拒否する機械的な禁止判定

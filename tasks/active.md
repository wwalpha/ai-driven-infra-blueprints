# Codex Task: Classify identifiers for the complete AWS catalog

## Task contract

- Task type: `catalog-maintenance`
- Goal: 全catalog resource typeのprimary identifierを公式provider schemaに基づくinput、非ARN output、保存禁止ARNへ分類する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 全resource typeの非ARN generated primary identifierを`IDENTIFIER_OUTPUT`として登録する。
- [R2] 人間指定のprimary identifier componentをinput propertyとして漏れなく選択する。
- [R3] input property数とidentifier output数を分離したcatalog metadataとintegrity lockへ更新する。
- [R4] catalogと固定provider schemaのprimary identifier分類が全resource typeで一致することを検証する。

## Acceptance checks

- [R1] `changed:framework/materials/aws/*.properties`
- [R2] `changed:framework/materials/aws/Glue_Database.properties`
- [R3] `changed:framework/materials/catalog.properties`
- [R3] `changed:framework/materials/catalog.sha256`
- [R3] `changed:framework/scripts/update-catalog-lock.py`
- [R3] `changed:framework/scripts/update-catalog-lock.checks.py`
- [R4] `changed:framework/scripts/cloudformation_schema.py`
- [R4] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R4] `changed:framework/scripts/validate-blueprint.py`

## Allowed paths

- `framework/materials/aws/**`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/scripts/update-catalog-lock.py`
- `framework/scripts/update-catalog-lock.checks.py`
- `framework/scripts/cloudformation_schema.py`
- `framework/scripts/cloudformation_schema.checks.py`
- `framework/scripts/validate-blueprint.py`
- `tasks/active.md`

## Out of scope

- 詳細設計rule、prompt、model生成、resource table validationのbehavior変更
- 既存詳細設計とservice modelのmigration
- generated ARNの詳細設計またはmodelへの保存
- AWS API、deploy、apply

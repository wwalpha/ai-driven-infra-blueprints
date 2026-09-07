# 関連resourceの共通表示contractとKMS統合

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: resourceの表示関係を共通定義し、S3の既存統合を維持しながらKMS KeyとAliasを一つの詳細表へ統合する。子resourceの識別、親への関連付け、外部参照を保持し、新規catalog resourceの未判定を検出する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 全catalog resourceの表示方針を共通定義し、S3 BucketPolicyとKMS Aliasの親、親property、個数と識別方法を登録する。未判定resourceと不整合をlocal loopで検出する。
- [R2] KMS Key表内の複数Aliasを識別可能にし、Aliasの独立見出し、誤配置、重複、参照切れを検証する。S3の既存表示とpolicy統合を維持する。
- [R3] grouped Aliasの識別子、親への関連付けとAlias参照をmodelへ保持し、S3の既存model contractを維持する。
- [R4] 詳細設計、model、IaC参照、設計promptとcatalog保守手順へ共通contractを反映し、focused checksとlocal loopで検証する。

## Acceptance checks

- [R1] `exists:framework/rules/resource-layout.json`
- [R1] `exists:framework/scripts/design_layout.py`
- [R1] `check:framework.resource-layout`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `check:framework.schema-backed-design-validation`
- [R2] `exists:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/scripts/sync-model.py`
- [R3] `check:framework.generated-service-model`
- [R4] `changed:framework/rules/detailed-design.md`
- [R4] `changed:framework/rules/model-information.md`
- [R4] `changed:framework/rules/cloudformation.md`
- [R4] `changed:framework/rules/terraform.md`
- [R4] `changed:framework/rules/loop-engineering.md`
- [R4] `changed:framework/prompts/chatbot/service-design.md`
- [R4] `changed:README.md`

## Allowed paths

- `tasks/active.md`
- `README.md`
- `framework/rules/resource-layout.json`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`

## Out of scope

- consumer repositoryへのframework同期、既存の詳細設計とmodelの移行
- AWS catalog/schemaの内容変更
- S3とKMS以外のresourceの自動統合
- IaC implementation、AWS操作、scenario、resultの変更

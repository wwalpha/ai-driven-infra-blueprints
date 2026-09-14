# IAM User catalog 登録

## Task contract

- Task type: `catalog-maintenance`
- Target: framework 共通 / `IAM.User`
- Goal: `IAM.User` を CloudFormation schema-backed catalog resource として正式登録し、catalog metadata、checksum、resource layout、関連 validator を整合させる。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] `IAM.User` の正式 property catalog と東京 region の CloudFormation provider schema snapshot を追加する。
- [R2] catalog manifest、checksum、resource metadata を新規 resource と property 件数へ同期する。
- [R3] `IAM.User` を独立表示 resource として resource layout に登録する。
- [R4] schema、catalog、policy property、layout の登録漏れを関連 validator で回帰検証する。
- [R5] 同じ公式 schema snapshot で検出された既存 resource の廃止 identifier property を catalog から除外する。

## Acceptance checks

- [R1] `changed:framework/materials/aws/IAM_User.properties`
- [R1] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-iam-user.json`
- [R1] `check:framework.cloudformation-schema-catalog`
- [R2] `changed:framework/materials/catalog.properties`
- [R2] `changed:framework/materials/catalog.sha256`
- [R2] `changed:framework/materials/cloudformation-schema.properties`
- [R2] `changed:framework/materials/cloudformation-schema.sha256`
- [R3] `changed:framework/rules/resource-layout.json`
- [R3] `check:framework.resource-layout`
- [R4] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R4] `changed:framework/scripts/policy_tables.py`
- [R4] `changed:framework/scripts/policy_tables.checks.py`
- [R4] `check:framework.policy-tables`
- [R5] `changed:framework/materials/aws/Config_DeliveryChannel.properties`
- [R5] `changed:framework/materials/aws/Route53_RecordSet.properties`
- [R5] `check:framework.cloudformation-schema-catalog`

## Allowed paths

- `tasks/active.md`
- `framework/materials/aws/IAM_User.properties`
- `framework/materials/aws/Config_DeliveryChannel.properties`
- `framework/materials/aws/Route53_RecordSet.properties`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/materials/cloudformation-schema.properties`
- `framework/materials/cloudformation-schema.sha256`
- `framework/materials/cloudformation-schema/ap-northeast-1/**`
- `framework/rules/resource-layout.json`
- `framework/scripts/cloudformation_schema.checks.py`
- `framework/scripts/policy_tables.py`
- `framework/scripts/policy_tables.checks.py`
- `CMD.md`

## Out of scope

- 個別詳細設計、generated model、IaC、AWS 操作、scenario、consumer repository 同期、commit/push、未追跡 `CMD.md`

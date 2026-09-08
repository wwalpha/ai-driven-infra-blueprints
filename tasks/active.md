# Managed external secretのcatalog不足修正

## Task contract

- Task type: `catalog-maintenance`
- Target: framework共通 / SecretsManager
- Goal: provider schemaに存在するmanaged external secretの種別とrotation設定をcatalogへ登録し、未登録への回帰を検出する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] Secret.Type、RotationSchedule.ExternalSecretRotationMetadataのKey/Value、ExternalSecretRotationRoleArnを正式Propertyとして登録する。
- [R2] catalogのhashと件数を既存generatorで更新する。
- [R3] 追加Propertyのcatalog登録とprovider schemaの型をfocused checkで検証しlocal loopを完了する。

## Acceptance checks

- [R1] `changed:framework/materials/aws/SecretsManager_Secret.properties`
- [R1] `changed:framework/materials/aws/SecretsManager_RotationSchedule.properties`
- [R2] `changed:framework/materials/catalog.properties`
- [R2] `changed:framework/materials/catalog.sha256`
- [R3] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R3] `check:framework.cloudformation-schema-catalog`

## Allowed paths

- `tasks/active.md`
- `framework/materials/aws/SecretsManager_Secret.properties`
- `framework/materials/aws/SecretsManager_RotationSchedule.properties`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/scripts/cloudformation_schema.checks.py`

## Out of scope

- provider schema snapshot更新、他serviceのcatalog拡張、secret値の登録
- consumer同期、個別詳細設計・model・IaC、AWS操作、scenario

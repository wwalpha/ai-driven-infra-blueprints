# Glue / Athena / Lake Formation / QuickSight catalog 登録

## Task contract

- Task type: `catalog-maintenance`
- Target: framework共通 / `AWS::Glue::Connection`、`AWS::Glue::Catalog`、`AWS::Athena::WorkGroup`、`AWS::LakeFormation::PrincipalPermissions`、`AWS::QuickSight::DataSource`
- Goal: 指定されたCloudFormation resourceとproperty pathを正式catalogへ登録し、東京regionのprovider schemaとlockを整合させる。

## Required changes

- [R1] Glue Connection、Glue Catalog、Athena WorkGroupの指定されたcontainer property pathを既存catalogへ登録する。
- [R2] Lake Formation PrincipalPermissionsの指定されたproperty pathと必須のnon-ARN identifier outputを新規catalogへ登録し、独立resourceとして表示する。
- [R3] QuickSight DataSourceのKeyPairCredentialsとその指定されたproperty pathを既存catalogへ登録する。
- [R4] 公式東京region CloudFormation provider schema snapshotとcatalog/schema lockを更新し、指定pathのschema解決を検証する。

## Acceptance checks

- [R1] `changed:framework/materials/aws/Glue_Connection.properties`
- [R1] `changed:framework/materials/aws/Glue_Catalog.properties`
- [R1] `changed:framework/materials/aws/Athena_WorkGroup.properties`
- [R2] `changed:framework/materials/aws/LakeFormation_PrincipalPermissions.properties`
- [R2] `changed:framework/rules/resource-layout.json`
- [R3] `changed:framework/materials/aws/QuickSight_DataSource.properties`
- [R4] `changed:framework/materials/cloudformation-schema/ap-northeast-1/index.json`
- [R4] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-lakeformation-principalpermissions.json`
- [R4] `changed:framework/materials/cloudformation-schema.properties`
- [R4] `changed:framework/materials/cloudformation-schema.sha256`
- [R4] `changed:framework/materials/catalog.properties`
- [R4] `changed:framework/materials/catalog.sha256`
- [R4] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R4] `check:framework.cloudformation-schema-catalog`

## Allowed paths

- `tasks/active.md`
- `framework/materials/aws/Glue_Connection.properties`
- `framework/materials/aws/Glue_Catalog.properties`
- `framework/materials/aws/Athena_WorkGroup.properties`
- `framework/materials/aws/LakeFormation_PrincipalPermissions.properties`
- `framework/materials/aws/QuickSight_DataSource.properties`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/materials/cloudformation-schema.properties`
- `framework/materials/cloudformation-schema.sha256`
- `framework/materials/cloudformation-schema/ap-northeast-1/**`
- `framework/rules/resource-layout.json`
- `framework/scripts/cloudformation_schema.checks.py`

## Out of scope

- AWS schemaに存在しない`Athena.WorkGroup.DataCatalog.DatabaseName`と`Athena.WorkGroup.DataCatalog.TableName`はhuman確認により除外する。
- 詳細設計、model、IaC、AWS操作、consumer repository同期は実行しない。既存の未追跡`CMD.md`は保持し、今回のvalidation baselineから分離する。

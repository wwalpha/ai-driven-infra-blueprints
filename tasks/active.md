# Glue federated catalog / DataZone resource catalog 登録

## Task contract

- Task type: `catalog-maintenance`
- Target: framework共通 / `AWS::Glue::Catalog`、`AWS::DataZone::Domain`、`AWS::DataZone::Project`、`AWS::DataZone::DataSource`
- Goal: Glue federated catalogとそれを参照するDataZone resourceを詳細設計で決定的に生成できる正式resource catalogへ登録する。

## Required changes

- [R1] `Glue.Catalog`の識別子とfederated catalogを含む設定可能propertyをcatalogへ登録する。
- [R2] 今回の実体に必要な`DataZone.Domain`、`DataZone.Project`、`DataZone.DataSource`をcatalogへ登録する。`Environment`、`EnvironmentProfile`、`ProjectMembership`は対応する実体が指定されていないため登録しない。
- [R3] 4 resourceのCloudFormation provider schema snapshotと独立表示方針を登録する。
- [R4] ARNがprimary identifierの`Glue.Catalog`でもnon-ARNの`CatalogId`をidentifier outputとして扱い、既存generatorによるGlue / DataZone Markdownからservice modelへの決定的生成をfocused checkで検証する。
- [R5] catalogとprovider schemaのchecksumを正式手順で再生成する。

## Acceptance checks

- [R1] `changed:framework/materials/aws/Glue_Catalog.properties`
- [R2] `changed:framework/materials/aws/DataZone_Domain.properties`
- [R2] `changed:framework/materials/aws/DataZone_Project.properties`
- [R2] `changed:framework/materials/aws/DataZone_DataSource.properties`
- [R3] `changed:framework/rules/resource-layout.json`
- [R3] `changed:framework/materials/cloudformation-schema/ap-northeast-1/index.json`
- [R3] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-glue-catalog.json`
- [R3] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-datazone-domain.json`
- [R3] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-datazone-project.json`
- [R3] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-datazone-datasource.json`
- [R4] `changed:framework/scripts/glue_datazone_catalog.checks.py`
- [R4] `changed:framework/scripts/cloudformation_schema.py`
- [R4] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R5] `changed:framework/materials/catalog.properties`
- [R5] `changed:framework/materials/catalog.sha256`
- [R5] `changed:framework/materials/cloudformation-schema.properties`
- [R5] `changed:framework/materials/cloudformation-schema.sha256`

## Allowed paths

- `tasks/active.md`
- `framework/materials/aws/Glue_Catalog.properties`
- `framework/materials/aws/DataZone_Domain.properties`
- `framework/materials/aws/DataZone_Project.properties`
- `framework/materials/aws/DataZone_DataSource.properties`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/materials/cloudformation-schema.properties`
- `framework/materials/cloudformation-schema.sha256`
- `framework/materials/cloudformation-schema/ap-northeast-1/**`
- `framework/rules/resource-layout.json`
- `framework/scripts/glue_datazone_catalog.checks.py`
- `framework/scripts/cloudformation_schema.py`
- `framework/scripts/cloudformation_schema.checks.py`

## Out of scope

- 詳細設計、model、IaC、AWS操作、consumer repository同期は実行しない。先行GuardDuty catalog差分と未追跡`CMD.md`は保持し、今回のvalidation baselineから分離する。

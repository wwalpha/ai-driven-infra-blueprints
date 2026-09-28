# EventBridge Scheduler Schedule catalog 登録

## Task contract

- Task type: `catalog-maintenance`
- Target: framework共通 / `AWS::Scheduler::Schedule`
- Goal: Scheduler.Scheduleの正式CloudFormation property、resource表示方針、東京region provider schemaをcatalogへ登録し、詳細設計とmodel生成で解決可能にする。

## Required changes

- [R1] `Scheduler.Schedule`の設定可能propertyをprovider schemaに従ってcatalogへ登録する。生成ARNは登録しない。
- [R2] `Scheduler.Schedule`を独立resourceとして表示し、公式東京region provider schema snapshotとindexへ登録する。
- [R3] catalogとschemaのchecksumを更新し、property解決とCloudFormation型解決をfocused checkおよびlocal loopで検証する。

## Acceptance checks

- [R1] `changed:framework/materials/aws/Scheduler_Schedule.properties`
- [R2] `changed:framework/rules/resource-layout.json`
- [R2] `changed:framework/materials/cloudformation-schema/ap-northeast-1/index.json`
- [R2] `changed:framework/materials/cloudformation-schema/ap-northeast-1/aws-scheduler-schedule.json`
- [R3] `changed:framework/materials/catalog.properties`
- [R3] `changed:framework/materials/catalog.sha256`
- [R3] `changed:framework/materials/cloudformation-schema.properties`
- [R3] `changed:framework/materials/cloudformation-schema.sha256`
- [R3] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R3] `check:framework.cloudformation-schema-catalog`
- [R3] `check:framework.resource-layout`

## Allowed paths

- `tasks/active.md`
- `framework/materials/aws/Scheduler_Schedule.properties`
- `framework/rules/resource-layout.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/index.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-scheduler-schedule.json`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/materials/cloudformation-schema.properties`
- `framework/materials/cloudformation-schema.sha256`
- `framework/scripts/cloudformation_schema.checks.py`

## Out of scope

- 特定targetの詳細設計、model、IaC、AWS操作、consumer repositoryへの同期は行わない。

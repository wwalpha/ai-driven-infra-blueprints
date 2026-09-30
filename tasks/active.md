# Config／KDFの参照表示とSecurity Group設計分離

## Task contract

- Task type: `governance`
- Target: framework共通 / Config・KinesisFirehose・Security Group表示・model生成・検証
- Goal: ConfigurationRecorderのRoleName表示、KDFの実resource link、Security Group専用security_group.mdの出力境界を整備する。

## Required changes

- [R1] ConfigurationRecorderのRoleARNをRoleNameとして表示し、参照先RoleNameのみを値に表示する。正式model propertyは維持する。
- [R2] KDFのKeyARN、BucketARN、S3DestinationConfiguration.RoleARNを実KMS Key、S3 Bucket、IAM Roleへのlinkとして検証する。
- [R3] Security Groupと所属ruleをec2.mdから分離し、security_group.mdと対応modelへ生成するルールを整備する。
- [R4] 正常表示、誤った値・参照先、専用file境界とmodel整合性を既存focused checkで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/display-property-aliases.json`
- [R1] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`
- [R4] `changed:framework/scripts/design_layout.checks.py`
- [R4] `changed:framework/scripts/security_group_tables.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/display-property-aliases.json`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/security_group_tables.checks.py`

## Out of scope

- catalog、project設定、target設計、generated model、IaC、AWS操作、scenarioは変更しない。
- 実resourceの選択や未確定値を推測しない。別repositoryの設計移行は行わない。

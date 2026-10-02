# Secrets Manager RotationScheduleの生成・解析契約修復

## Task contract

- Task type: `governance`
- Target: fw内のRotationSchedule grouped child生成・解析・model照合
- Goal: 確定表示名、identity、observed値、正式SecretIdと親metadataを保持し、生成・解析・検証の不整合を修復する。

## Validation scope

- `framework`

## Required changes

- [R1] 現行コードでfixture再現後、RotationScheduleの親内表示、identity、正式SecretIdと親metadataの整合を生成・解析・照合で統一する。不足・矛盾はresource/property付きで拒否する。
- [R2] 直接関係する表示・model規則を統一し、具体的表示例を変更前に提示する。
- [R3] 単一・複数親、重複、不正参照、再解析・照合、既存grouping、Secrets Manager/KMS同時生成と既存リンク保護をfixtureで回帰検証する。

## Acceptance checks

- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/rules/resource-layout.json`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/scripts/rotation_schedule.checks.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/model_design.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/rotation_schedule.checks.py`
- `framework/scripts/design_layout.checks.py`
- `framework/rules/resource-layout.json`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`

## Out of scope

- consumer repositoryへのアクセス・変更・同期、catalog/provider schema変更、IaC、AWS、deploy、scenario、別taskを行わない。
- fixtureはrepository外の一時directoryに生成する。full loopと差分checkを実行して終了する。

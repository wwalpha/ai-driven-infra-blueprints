# S3 Propertyの短縮表示を追加

## Task contract

- Task type: `governance`
- Target: framework共通 / S3.BucketのProperty列
- Goal: BucketKeyEnabledとNoncurrentDaysの表示名を指定の短縮形へ変更し、正式propertyをmodelに維持する。

## Required changes

- [R1] 指定された二つのS3表示名を正式catalog propertyへ対応付ける。
- [R2] 表示名とmodel上の正式propertyの関係を文書化する。
- [R3] 短縮表示の検証とmodel生成をfocused checkで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/display-property-aliases.json`
- [R2] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/display-property-aliases.json`
- `framework/rules/model-information.md`
- `framework/scripts/design_layout.checks.py`

## Out of scope

- target設計、model、IaC、AWS操作、scenario、catalogは変更しない。

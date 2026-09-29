# CloudFormation Stack一覧の番号と説明を必須化

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation Stack一覧
- Goal: Stack一覧にNo.とCommentを必須化し、番号と説明をlocal checkで検証する。

## Required changes

- [R1] Stack一覧の5列形式、連番、CommentのFWルールと例を定義する。
- [R2] 共通parserとvalidatorで5列形式、連番、Commentを検証する。
- [R3] 正常系と欠落・不正行、modelへの表示情報非保存をfocused checkで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/detailed-design-samples.md`
- [R1] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `changed:framework/scripts/sync-model.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/model-information.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/sync-model.checks.py`

## Out of scope

- target設計、model、IaC、AWS操作、scenario、catalogは変更しない。

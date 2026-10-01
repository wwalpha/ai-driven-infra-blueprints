# CloudFormation provider schemaの複数型チェック修正

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation provider schema literal validation
- Goal: provider schemaの配列形式typeを例外なく検証し、許可された型と制約への適合を確認する。

## Required changes

- [R1] 共通literal validationで複数型を扱い、単一型と既存制約の検証を維持する。
- [R2] Events.Rule.EventPatternと他の複数型の受理・拒否を既存focused checkへ追加する。

## Acceptance checks

- [R1] `changed:framework/scripts/cloudformation_schema.py`
- [R1] `check:framework.schema-backed-design-validation`
- [R2] `changed:framework/scripts/cloudformation_schema.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/cloudformation_schema.py`
- `framework/scripts/cloudformation_schema.checks.py`

## Out of scope

- catalog、design/model、IaC、consumer repository、AWS API、deploy/apply、scenario、別taskの作成・実行は行わない。
- focused check、governance local loop、git diff --checkの結果を報告する。

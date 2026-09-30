# 検証用環境名をstgへ変更

## Task contract

- Task type: `governance`
- Target: framework共通 / focused check scripts
- Goal: 検証用の環境名と対応する参照をstgへ変更する。

## Required changes

- [R1] 3つのfocused check scriptsの環境名、パス、リソース名、リンク、期待値をstgへ統一する。

## Acceptance checks

- [R1] `changed:framework/scripts/check-deploy-context.checks.py`
- [R1] `changed:framework/scripts/export-design-pdf.checks.py`
- [R1] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/check-deploy-context.checks.py`
- `framework/scripts/export-design-pdf.checks.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- 検証ロジック、catalog、project設定、target設計、model、IaC、AWS操作、scenarioは変更しない。

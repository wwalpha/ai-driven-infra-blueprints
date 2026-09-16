# CloudFormation resource間へ空行を入れる

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation YAML formatting
- Goal: CloudFormation templateの`Resources`配下でresource間を空行区切りにし、可読性を保つ。

## Required changes

- [R1] CloudFormation ruleとimplement promptでresource間の空行を必須にする。
- [R2] validatorとfocused checkで空行のないresource境界を拒否する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R1] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- 既存IaC template、design/model、AWS操作、scenario、他のformat ruleは変更しない。未追跡`CMD.md`は保持する。

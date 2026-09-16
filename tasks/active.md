# Security Groupを利用resourceのCloudFormation templateへ同居させる

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation template boundary rule and validator
- Goal: Security GroupをIAM Role、CloudWatch Logsと同様に利用するresourceのtemplateへ含め、SG単独templateを禁止する。

## Required changes

- [R1] CloudFormation ruleでSecurity Groupを利用するresourceのtemplateへ含める。
- [R2] implement promptへ同じtemplate boundaryを反映する。
- [R3] validatorとfocused checkでSecurity Group単独templateを拒否する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/prompts/codex/03_implement.md`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- design/model、既存IaC、AWS操作、scenario、他のframework ruleは変更しない。未追跡`CMD.md`は保持する。

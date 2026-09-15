# CloudFormationのCloudWatch LogsとIAM Roleを利用側templateへ含める

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation template boundary
- Goal: CloudWatch Logs resourceとIAM Roleの単独CloudFormation templateを禁止し、利用resourceを持つtemplateへ含める。

## Required changes

- [R1] CloudFormation ruleにCloudWatch LogsとIAM Roleの配置境界を規定する。
- [R2] implement promptで利用側templateへの配置を指示する。
- [R3] repository validatorで単独templateを検出する。
- [R4] focused checkで単独配置の拒否と利用側配置の許可を検証する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/prompts/codex/03_implement.md`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- target、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`は保持する。

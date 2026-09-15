# CloudFormation の Environment parameter と resource 名の合成を規定する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation parameter・resource命名ルール
- Goal: resource名にEnvironmentを含める場合は独立したEnvironment parameterからtemplate内で合成し、他のparameter値へのEnvironmentの埋め込みを違反にする。

## Required changes

- [R1] `framework/rules/cloudformation.md`にEnvironment parameter、resource名の合成、他parameter値の禁止を規定する。
- [R2] repository validatorでtemplateのEnvironment宣言、target別parameter値とEnvironmentの一致、他parameter値への埋め込み違反を検出し、focused checkで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- target、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`は保持する。

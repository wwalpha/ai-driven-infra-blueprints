# CloudFormation YAMLルールのcheckerを追加する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation templateのlocal validation
- Goal: CloudFormation YAML templateの長形式組み込み関数、ブロック形式の配列引数、同一trust policy本文の重複をlocal loopで検出する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] CloudFormation YAML templateの長形式組み込み関数、ブロック形式の配列引数、同一trust policy本文の重複を検出するcheckerをlocal validatorへ追加する。
- [R2] checkerの許可例と拒否例をfocused checkで検証する。

## Acceptance checks

- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- 既存templateやtarget、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`を保持する。

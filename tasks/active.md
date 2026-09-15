# CloudFormation短縮関数のchecker対象を確認する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation templateのlocal validation
- Goal: CloudFormation短縮関数のcheckerがSelect/Split以外の関数にも適用されることを機械検証する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] Join/Subの長形式とJoinのブロック形式配列をfocused checkの拒否例へ追加する。

## Acceptance checks

- [R1] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- 既存templateやtarget、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`を保持する。

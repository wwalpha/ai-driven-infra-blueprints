# CloudFormation YAMLアンカー使用要求を削除する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation YAML記述ルール
- Goal: `sharedTrustPolicy`などのYAML anchor/aliasによる共通化要求を削除し、各resourceに元の値を明示するルールにする。

## Required changes

- [R1] `framework/rules/cloudformation.md`からanchor/aliasによる共通化要求を削除し、CloudFormation非対応のalias/hash mergeを使用しないことを記載する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`

## Out of scope

- validator、CloudFormation template、target、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`は保持する。

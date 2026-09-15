# IAM Roleの共通信頼ポリシーをtemplate内で共有する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation記載ルール
- Goal: 同一CloudFormation template内で内容が同じIAM Role trust policyをYAMLアンカーとエイリアスで共有する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 同一template内のIAM Roleが同じtrust policyを持つ場合に、Role別の設計JSONを維持しながらYAMLアンカーとエイリアスで実装を共有するルールを追加する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`

## Out of scope

- 既存templateやtarget、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`を保持する。

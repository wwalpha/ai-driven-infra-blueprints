# 共通信頼ポリシーの定義場所をMetadataへ変更する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation YAML記述ルール
- Goal: 同一template内で完全に同じIAM trust policyと非Policy設定ブロックを`Metadata.Constants`へ共通定義し、権限Policyは共有対象外とするルールへ変更する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 同一IAM trust policyの`&sharedTrustPolicy`はtemplate上部の`Metadata.Constants`に定義し、全Roleからalias参照するルールへ変更する。
- [R2] 同一template内で完全一致する非Policy設定ブロックは値と挙動を保って`Metadata.Constants`で共有するルールを記載する。
- [R3] IAM/KMSなどの権限Policy本体とStatement、Action等の部分をanchor/aliasで共通化しないことを明記する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/rules/cloudformation.md`
- [R3] `changed:framework/rules/cloudformation.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`

## Out of scope

- 既存templateやtarget、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。以前のtaskで変更済みの`framework/scripts/validate-blueprint.checks.py`と未追跡`CMD.md`を保持する。

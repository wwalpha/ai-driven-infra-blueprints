# Subnet一覧へのRoute Table関連付け統合

## Task contract

- Task type: `governance`
- Target: framework共通 / VPC詳細設計のリソース一覧
- Goal: 同じfile内のSubnetに対応するRoute Table関連付けをSubnet一覧へ表示し、関連付けの独立一覧を不要にする。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 共通設計ruleとchatbot promptに、Subnet一覧のRouteTableId・AssociationId列と関連付け詳細へのlinkを定義する。
- [R2] validatorがSubnetIdの参照先に基づいて統合先を検証し、一覧値の不一致、重複、欠落を拒否する。独立したresource詳細とmodelは維持する。
- [R3] focused checkで複数Subnet、未作成identifier、誤った関連付け、一覧変更前後のmodel不変を確認し、local loopを完了する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `CMD.md`

## Out of scope

- CMD.mdは開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- resource詳細tableの統合、catalog、resource-layout.json、model生成形式、他resourceの一覧仕様
- consumer同期、個別詳細設計・model・IaC、AWS操作、scenario

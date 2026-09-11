# Subnet Route Table関連付けをSubnet tableへ統合

## Task contract

- Task type: `governance`
- Target: framework共通 / EC2 Subnet Route Table関連付けの表示契約
- Goal: `EC2.SubnetRouteTableAssociation`の独立した詳細blockを廃止し、`RouteTableId`だけを所属する`EC2.Subnet`のtableへ記載する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] resource layout、詳細設計ルール、chatbot prompt、model ruleを、Associationの`RouteTableId`をSubnet tableへ統合する契約へ変更する。
- [R2] validatorを新しい表示契約へ合わせ、独立Association block、`Id`、`SubnetId`を不要にする。
- [R3] focused checkとlocal loopでSubnet tableへの統合、一覧との一致、model生成を確認する。

## Acceptance checks

- [R1] `changed:framework/rules/resource-layout.json`
- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `check:framework.resource-layout`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/resource-layout.json`
- `framework/rules/detailed-design.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/rules/model-information.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `CMD.md`

## Out of scope

- CMD.mdは開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- `framework/materials/**`、consumer詳細設計・model・IaC、AWS操作、scenario

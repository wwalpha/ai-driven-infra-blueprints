# Subnet Route Table参照の短縮表示

## Task contract

- Task type: `governance`
- Target: framework共通 / `EC2.SubnetRouteTableAssociation.RouteTableId`
- Goal: Subnet詳細表のRoute Table参照をMarkdownでは`EC2.RouteTableId`と表示し、正式propertyとの対応を維持する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 詳細設計とchatbot promptで、Subnetに統合したAssociationのRouteTableIdを`EC2.RouteTableId`と表示する。
- [R2] Markdownの短縮表示を正式な`EC2.SubnetRouteTableAssociation.RouteTableId`へ正規化し、validatorとgenerated modelで既存contractを維持する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`
- [R2] `check:framework.resource-layout`

## Allowed paths

- `tasks/active.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `CMD.md`

## Out of scope

- 既存の個別詳細設計・model・IaC、materials catalog、AWS操作、scenario、commit/push、未追跡`CMD.md`
- 前taskの未commit Flow Log Name変更

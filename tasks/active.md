# Subnet一覧のAssociationId列を省略

## Task contract

- Task type: `governance`
- Target: framework共通 / VPC詳細設計のリソース一覧
- Goal: EC2.SubnetのMarkdown一覧tableからAssociationId列を省き、RouteTableIdによる関連付け表示を維持する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 共通設計ruleとchatbot promptからSubnet一覧のAssociationId列と同列linkの要求を除き、同列を記載しないことを明記する。
- [R2] validatorをAssociationId列なしの一覧へ対応させ、RouteTableIdの一致、SubnetId参照先に基づく対応、重複・欠落の検証を維持する。
- [R3] focused checkでAssociationId列なしの一覧、不要な列の拒否、複数Subnet、未作成identifier、誤った関連付け、一覧変更前後のmodel不変を確認し、local loopを完了する。

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
- Association自身の詳細table・Id・model、catalog、resource-layout.json、model生成形式、他resourceの一覧仕様
- consumer同期、個別詳細設計・model・IaC、AWS操作、scenario

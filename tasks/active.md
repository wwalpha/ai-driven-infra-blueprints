# EC2 InstanceのName tag表示

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: EC2.Instanceの見出し・一覧・通常の参照linkにName tagの値を使用し、内部logical IDによる表示を防ぐ。

## Required changes

- [R1] EC2.InstanceのName tagを正式なTags[].Key／Tags[].Valueで必須とし、rule、prompt、表示例を更新する。
- [R2] 既存の必須Name tag処理をEC2.Instanceにも適用し、欠落・未確定値・表示labelによる代替を拒否する。logical IDとdesired／observedの分離を維持する。
- [R3] EC2.Instanceと既存VPC Endpointの生成・解析・検証・参照の回帰checkを実行する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R1] `changed:framework/rules/detailed-design-samples.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `check:framework.generated-service-model`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `check:framework.schema-backed-design-validation`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design-samples.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/model_design.checks.py`

## Out of scope

- AWS API、deploy/apply、catalog、project.json、実targetのdesign/model/IaC、consumer repository、scenario、別taskは変更・実行しない。
- Name tagの実値やlogical IDを推測しない。VPC／Subnet／RouteTable／Flow Logの.Name表示、Security GroupのGroupName表示を維持する。
- focused checks、governance local loop、git diff --checkを実行し、既存failureと今回の結果を分けて報告する。

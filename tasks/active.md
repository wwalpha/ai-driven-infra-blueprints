# 全resourceの名前を設定表の先頭へ統一

## Task contract

- Task type: `governance`
- Target: framework共通 / 全serviceのresource設定表
- Goal: IAM.Role.RoleNameを含む選択済みresource名を1行目へ配置し、生成ID先頭ルールとの衝突を解消する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 全catalog resourceの自己名称propertyを明示分類し、参照先名と区別する。詳細設計、命名、model、local loop、chatbotの表示順ruleを統一する。
- [R2] 名前、既存の固定2行目、残りの生成ID、その他の順序を共通validatorで検証する。名前未選択時は補完せず、名前のないresourceとgrouped child、SG横書き表示を保持する。
- [R3] 全名称分類のcoverage、直接名・nested名・DB識別名・Name tag・名前未選択・生成ID・既存固定2行目のfocused checkとlocal loopを実行する。

## Acceptance checks

- [R1] `changed:framework/rules/resource-name-properties.json`
- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `check:framework.resource-layout`

## Allowed paths

- `tasks/active.md`
- `framework/rules/resource-name-properties.json`
- `framework/rules/detailed-design.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/*.checks.py`
- `framework/scripts/policy_tables.py`
- `CMD.md`

## Out of scope

- 前taskの未commit変更を保持し、policyのVersion表示・Sid制限・Events.RuleのName/State指定を後退させない。policy_tables.pyは既存差分としてのみ許容する。
- 開始前から存在する未追跡CMD.mdは変更しない。
- consumer詳細設計・model・IaC、catalog、AWS操作、scenario、commit/push
- 未選択の名前property・Name tag・値の自動追加、resource所属関係の変更

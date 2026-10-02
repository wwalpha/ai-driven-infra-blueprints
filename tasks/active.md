# 名称propertyのないresourceの型名表示

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: 名称propertyのない独立resourceが同じservice内で同型1件の場合、表示labelを必須とせずresource typeだけを見出し・一覧・参照linkへ表示する。

## Required changes

- [R1] 詳細設計・model・local loopのrule、設計promptと表示例を更新する。同型複数件は区別できる確定済みlabelを要求し、既存の確定済みlabelとlogical ID、名称property・必須Name tagの契約を維持する。
- [R2] 型名だけの見出しを生成・解析・検証し、一覧見出しと区別する。型名由来anchorと非表示logical IDを維持し、派生型名をmodelのlabelへ重複保存しない。
- [R3] 単一・複数resource、名称を持つ型、Name tag、既存label、logical ID、desired/observedと参照linkの回帰checkを実行する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R1] `changed:framework/rules/detailed-design-samples.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/model_design.py`
- [R2] `changed:framework/scripts/policy_tables.py`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `check:framework.generated-service-model`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `check:framework.schema-backed-design-validation`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/detailed-design-samples.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/model_design.py`
- `framework/scripts/policy_tables.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/model_design.checks.py`

## Out of scope

- AWS API、deploy/apply、catalog、project.json、実targetのdesign/model/IaC、consumer repository、scenario、別taskは変更・実行しない。
- logical IDをresource typeから推測・新規決定しない。既存の確定済み値を保持し、不足時は確認を求める。
- focused checks、governance local loop、git diff --checkを実行し、既存failureと今回の結果を分けて報告する。

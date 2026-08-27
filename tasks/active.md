# Codex Task: Propagate generated resource identifiers

## Task contract

- Task type: `governance`
- Goal: catalogの正式identifier outputを詳細設計、service model、IaC output、deploy後の参照元更新で一貫して扱う
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 詳細設計のidentifier outputと参照propertyのlifecycle、anchorによるlogical reference、generated ARN非永続化を定義する。
- [R2] 同じidentifier row／reference rowから`desired.*`のlogical referenceと`observed.*`のphysical IDを生成する。
- [R3] CloudFormation Outputs／stack resourceとTerraform output／stateによる取得優先順位、IaCのlogical reference維持、参照元への反映手順を定義する。
- [R4] catalog identifier output、physical ID形式、参照先との一致、`PENDING_DEPLOY`伝播、Source / Commentのprefix非依存をvalidatorで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/observed-values.md`
- [R3] `changed:framework/rules/cloudformation.md`
- [R3] `changed:framework/rules/terraform.md`
- [R3] `changed:framework/prompts/codex/03_implement.md`
- [R3] `changed:framework/prompts/codex/04_deploy.md`
- [R4] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/rules/cloudformation.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/observed-values.md`
- `framework/rules/terraform.md`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- `framework/materials/aws/**`とcatalog lockの変更
- project固有の詳細設計、model、IaC、scenarioの変更
- 新しいidentifier管理file、compatibility alias、fallback labelの追加
- AWS API、deploy、applyの実行

# 必須項目の生成前検証

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: propertiesを設計入力として保持し、schema/catalogの必須項目不足をMarkdown／JSONの一時生成前に拒否する。

## Required changes

- [R1] provider/API schemaとcatalogの必須root property判定を再利用し、全serviceのmodelを生成前に検証する。grouped childの暗黙propertyを維持する。
- [R2] 不足serviceでは一時Markdown／JSONを作らず、既存生成物と正本propertiesを維持し、他serviceは処理する。新規・既存、read-only・writeの回帰checkを追加する。
- [R3] rulesと設計promptへproperties保存可／必須項目不足時の生成禁止を明記する。

## Acceptance checks

- [R1] `changed:framework/scripts/design_catalog.py`
- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/design_catalog.py`
- `framework/scripts/model_design.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/cloudformation-deploy.py`
- `framework/scripts/cloudformation-deploy.checks.py`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/rules/cloudformation.md`
- `framework/rules/detailed-design-samples.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`

## Out of scope

- Allowed paths内の既存のdeploy順序・並列制御の未commit差分は保持し、今回の変更として追加修正しない。
- AWS API、deploy/apply、catalog、project.json、実targetのdesign/model/IaC、consumer repository、Terraform、scenario、別taskは変更・実行しない。
- focused checks、governance local loop、git diff --checkを実行し、既存failureと今回の結果を分けて報告する。

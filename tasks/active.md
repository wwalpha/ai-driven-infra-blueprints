# CloudFormation stack詳細設計の文書反映

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation stack詳細設計文書
- Goal: CloudFormation stack詳細設計の3列形式を、共通ルール、サンプル、生成・検証処理へ反映する。

## Required changes

- [R1] CloudFormation stack詳細設計の共通ルールを提示された文面に合わせる。
- [R2] 対応するMarkdownサンプルを提示された3列のstack一覧に合わせる。
- [R3] 3列形式のstack設計をmodel生成とlocal validationで扱い、focused checkで確認する。
- [R4] stack設計の参照文書を3列形式に合わせる。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R2] `exists:framework/rules/detailed-design-samples.md`
- [R3] `changed:framework/scripts/design_layout.py`
- [R3] `changed:framework/scripts/sync-model.py`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`
- [R4] `changed:framework/rules/model-information.md`
- [R4] `changed:framework/rules/observed-values.md`
- [R4] `changed:framework/rules/cloudformation.md`
- [R4] `changed:framework/rules/loop-engineering.md`
- [R4] `changed:framework/prompts/chatbot/service-design.md`
- [R4] `changed:framework/prompts/codex/03_implement.md`
- [R4] `changed:framework/prompts/codex/04_deploy.md`
- [R4] `changed:README.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/model-information.md`
- `framework/rules/observed-values.md`
- `framework/rules/cloudformation.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.checks.py`
- `README.md`

## Out of scope

- CloudFormation stack詳細設計以外のルール、catalog、target設計、IaC、AWS操作、scenarioは変更しない。

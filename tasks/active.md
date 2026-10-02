# Secrets ManagerのSecretとRotationScheduleの表示統合

## Task contract

- Task type: `governance`
- Target: frameworkのSecrets Manager詳細設計表示
- Goal: Secretと所属RotationScheduleを一つの詳細tableへ統合し、両者の一覧はSecretだけにする。

## Validation scope

- `framework`

## Required changes

- [R1] RotationScheduleをSecret配下の単一childとして表示定義し、一覧・詳細の独立表示を禁止する。
- [R2] 正式property、親所属、設定値を保つ表示生成・model往復・検証を機械確認し、full local loopを実行する。

## Acceptance checks

- [R1] `changed:framework/rules/resource-layout.json`
- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `check:framework.resource-layout`
- [R2] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths


- `tasks/active.md`
- `AGENTS.md`
- `README.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/check-deploy-context.py`
- `framework/scripts/check-deploy-context.checks.py`
- `framework/scripts/cloudformation-deploy.py`
- `framework/scripts/cloudformation-deploy.checks.py`
- `framework/prompts/codex/*.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/README.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/detailed-design.md`
- `framework/rules/scenario-testing.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/issue_gate.py`
- `framework/scripts/issue_gate.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/model_design.py`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/design_catalog.py`
- `framework/scripts/sync-model.checks.py`
- `framework/rules/resource-layout.json`

## Out of scope

- 前taskの未commit差分は保持する。以前から許容されたpathを今回の修正対象へ広げない。
- 今回の編集は上記Required changesの3 fileとactive contractだけに限定する。
- 実design/model、project.json、IaC、catalog/schema、issue一覧、scenario/result、consumer repositoryは変更しない。
- AWS API、deploy/apply、別task作成・実行は行わない。
- SecretsManager.ResourcePolicyの表示方針は変更しない。fixture/logはrepository外の一時directoryに保存する。

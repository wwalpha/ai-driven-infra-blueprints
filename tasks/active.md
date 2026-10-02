# CloudFormation stackのMarkdown表示を調整する

## Task contract

- Task type: `governance`
- Target: frameworkのCloudFormation stack表示
- Goal: MaxConcurrentStacksをMarkdown描画で非表示にし、DeployOrder見出しを2行にする。

## Validation scope

- `framework`

## Required changes

- [R1] Deployment設定表を非表示metadataへ置換し、Deploy<br>Order見出しを生成・解析する。modelとdeploymentの値・検証は維持する。
- [R2] 表示rule、model rule、sampleを更新する。
- [R3] 表示・復元・不正値拒否・deployment前の不一致検出を既存fixtureで検証する。

## Acceptance checks

- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/rules/detailed-design-samples.md`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `changed:framework/scripts/cloudformation-deploy.checks.py`
- [R3] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/model_design.py`
- `framework/scripts/design_layout.py`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/detailed-design-samples.md`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/cloudformation-deploy.checks.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/rules/display-property-aliases.json`

## Out of scope

- 前taskの未commit Athena表示差分を保持する。
- consumer同期、実設計/model、catalog、IaC、AWS、scenarioは変更しない。
- repository外fixtureで検証し、framework scopeのfull local loopを実行する。

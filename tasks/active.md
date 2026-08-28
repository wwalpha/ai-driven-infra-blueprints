# Codex Task: Add optional environment aliases

## Task contract

- Task type: `governance`
- Goal: 一つのenvironmentに複数の論理配置先がある場合だけoptional aliasを使い、同じAWS account IDを持つalias別の設計とCloudFormation／Terraform実装を汎用的に管理できるframeworkを定義する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] `project.json.targets[]`のoptional `alias`、environment内のalias全件適用、重複AWS account ID、同一IaC engine、alias形式の契約を定義する。
- [R2] initializationとtarget選択でaliasをhumanから必要な場合だけ取得し、aliasがあればalias、なければAWS account IDをtarget directoryに使う。
- [R3] CloudFormation templateとTerraform moduleをalias別に管理し、aliasなしは従来の共通実装、parameter／root／stateはenvironment／target directory別に管理する。
- [R4] 詳細設計、model、scenario、read-only／deploy preflight、prompt、validatorがoptional alias targetを一貫して解決し、focused checksでaliasあり／なしの両方を検証する。

## Acceptance checks

- [R1] `changed:AGENTS.md`
- [R1] `changed:README.md`
- [R1] `changed:framework/prompts/codex/01_initialize.md`
- [R1] `changed:framework/prompts/codex/02_add-target.md`
- [R2] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/cloudformation.md`
- [R3] `changed:framework/rules/terraform.md`
- [R3] `changed:framework/prompts/codex/03_implement.md`
- [R3] `changed:framework/prompts/codex/04_deploy.md`
- [R3] `changed:framework/prompts/codex/05_update.md`
- [R4] `changed:framework/prompts/README.md`
- [R4] `changed:framework/prompts/codex/06_scenario-test.md`
- [R4] `changed:framework/rules/loop-engineering.md`
- [R4] `changed:framework/rules/scenario-testing.md`
- [R4] `changed:framework/scripts/check-deploy-context.py`
- [R4] `changed:framework/scripts/check-deploy-context.checks.py`
- [R4] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `AGENTS.md`
- `README.md`
- `framework/prompts/README.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/01_initialize.md`
- `framework/prompts/codex/02_add-target.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `framework/prompts/codex/06_scenario-test.md`
- `framework/rules/cloudformation.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/scenario-testing.md`
- `framework/rules/terraform.md`
- `framework/scripts/check-deploy-context.py`
- `framework/scripts/check-deploy-context.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- `framework/materials/aws/**`とcatalog lockの変更
- 既存projectの`project.json`、詳細設計、model、IaC、scenarioの移行
- aliasを後付けするための専用migration flow
- alias名の固定catalogまたは推測
- AWS API、deploy、applyの実行

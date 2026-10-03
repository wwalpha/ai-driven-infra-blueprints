# 複数タスクの並行管理と変更ファイル競合停止

## Task contract
- Task type: `governance`
- Task status: `completed`
- Target: framework task contract、検証、生成、workflow
- Goal: taskごとに契約を保持し、進行中taskと同じ変更予定fileを持つ新規taskを変更前に停止する。

## Validation scope
- `framework`

## Required changes
- [R1] 個別task契約の選択、file予約、競合停止と他task変更の分離を実装する。
- [R2] validator、local loop、model生成、issue gate、deployの契約参照を統一する。
- [R3] repository rule、workflow、skillを複数task運用へ揃える。
- [R4] 競合、未作成file、task選択、変更範囲、既存workflowを回帰検証する。

## Acceptance checks
- [R1] `changed:framework/scripts/task_contract.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validation_scope.py`
- [R3] `changed:AGENTS.md`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R4] `changed:framework/scripts/task_contract.checks.py`

## Modified files
- `tasks/concurrent-tasks.md`
- `AGENTS.md`
- `README.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/task_contract.py`
- `framework/scripts/task_contract.checks.py`
- `framework/scripts/validation_scope.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/issue_gate.py`
- `framework/scripts/model_files.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/cloudformation-deploy.py`
- `.agents/skills/issues/SKILL.md`
- `.agents/skills/env-diff/SKILL.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/01_initialize.md`
- `framework/prompts/codex/02_add-target.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `framework/prompts/codex/06_scenario-test.md`

## Allowed paths
- `tasks/concurrent-tasks.md`
- `AGENTS.md`
- `README.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/task_contract.py`
- `framework/scripts/task_contract.checks.py`
- `framework/scripts/validation_scope.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/issue_gate.py`
- `framework/scripts/model_files.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/cloudformation-deploy.py`
- `.agents/skills/issues/SKILL.md`
- `.agents/skills/env-diff/SKILL.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/01_initialize.md`
- `framework/prompts/codex/02_add-target.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `framework/prompts/codex/06_scenario-test.md`

## Out of scope
- 完了済みStackName変更は保持する。consumer、catalog、project.json、design、model、IaC、AWS API、deploy/apply、scenario、commit、pushは変更しない。

## Completion
- framework scopeのlocal loop、Acceptance checks、全framework回帰を通す。

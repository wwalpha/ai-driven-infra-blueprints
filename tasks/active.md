# active taskの不在状態と検知境界を見直す

## Task contract

- Task type: `governance`
- Target: framework共通 / active task lifecycle and local validation
- Goal: 変更のないアイドル状態では`tasks/active.md`の不在を許容し、変更中のtask contract不在は検出する。

## Required changes

- [R1] active taskの不在を許容する状態と変更中の必須条件をrepository ruleへ規定する。
- [R2] README、loop engineering rule、およびactive taskを参照するpromptのlifecycle説明を同期する。
- [R3] validatorでclean idle状態または`active.md`単独削除時の不在を許容し、他の変更中の不在を拒否する。
- [R4] focused checkでidle状態、単独削除、他の変更中の不在を検証する。

## Acceptance checks

- [R1] `check:framework.active-task-transition`
- [R2] `check:framework.active-task-transition`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `AGENTS.md`
- `README.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- target、design/model、IaC、AWS操作、scenario、prompt変更、commit/pushは変更・実行しない。未追跡`CMD.md`は保持する。

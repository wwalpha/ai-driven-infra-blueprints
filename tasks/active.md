# active taskの不在状態と検知境界を見直す

## Task contract

- Task type: `governance`
- Target: framework共通 / active task lifecycle and local validation
- Goal: 変更のないアイドル状態では`tasks/active.md`の不在を許容し、変更中のtask contract不在は検出する。

## Required changes

- [R1] active taskの不在を許容する状態と変更中の必須条件をrepository ruleへ規定する。
- [R2] README、loop engineering rule、およびactive taskを参照するpromptのlifecycle説明を同期する。
- [R3] validatorでclean idle状態の`active.md`不在を許容し、変更中の不在を拒否する。
- [R4] focused checkでidle状態と変更中の不在を検証する。

## Acceptance checks

- [R1] `changed:AGENTS.md`
- [R2] `changed:README.md`
- [R2] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/prompts/codex/04_deploy.md`
- [R2] `changed:framework/prompts/codex/05_update.md`
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

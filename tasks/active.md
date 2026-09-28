# CloudFormation stack詳細設計と複数instance管理

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation stack管理
- Goal: 同じCloudFormation templateを複数stackとして設計・実装・deployでき、既存stackをtarget別の詳細設計に対応付けて管理できるframeworkにする。

## Required changes

- [R1] target別のstack詳細設計形式と生成modelを定義し、stack名、template、個別parameter、依存先、設計resource対応を保持する。
- [R2] stack設計の整合性をlocal loopで検証し、同一templateの複数instanceを許可しつつ重複・欠落・曖昧な所有関係を拒否する。
- [R3] 設計、implement、deploy、updateのpromptとrepository ruleをstack instance単位の運用へ更新する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/scripts/sync-model.py`
- [R1] `changed:framework/scripts/sync-model.checks.py`
- [R1] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `changed:framework/rules/cloudformation.md`
- [R3] `changed:framework/prompts/codex/04_deploy.md`
- [R3] `changed:README.md`

## Allowed paths

- `tasks/active.md`
- `AGENTS.md`
- `README.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/cloudformation.md`
- `framework/rules/observed-values.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/README.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `framework/scripts/sync-model.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- 特定targetの詳細設計、model、IaC、AWS操作、consumer repositoryへの同期は行わない。

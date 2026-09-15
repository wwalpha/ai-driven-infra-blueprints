# CloudFormation の複数stackを依存関係に応じて並列deployする

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation deployment workflow
- Goal: 複数stackをdeployする際、依存元の完了が必要なstackは順序を守り、独立したstackは並列でdeployする。

## Required changes

- [R1] CloudFormation ruleに、dependencyを守った並列deployと失敗時の扱いを規定する。
- [R2] deploy promptに、並列で実行できるunitの起動、完了確認、observed value反映を規定し、update promptとの整合を取る。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/prompts/codex/04_deploy.md`
- [R2] `changed:framework/prompts/codex/05_update.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`

## Out of scope

- target、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`は保持する。

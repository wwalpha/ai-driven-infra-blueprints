# Destructive change confirmation and resume flow

## Task contract

- Task type: `governance`
- Goal: CloudFormation change setまたはTerraform planで未承認のdelete/replacementを検出した場合に、人間へ影響を説明して確認待ちとし、承認後に同じdeployment taskと同じchange setまたはplanを継続実行できるframework contractへ更新する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] repository全体のruleを、全deploymentへの一律human reviewは設けず、未承認のdelete/replacementだけを説明付き確認待ちにするcontractへ統一する。
- [R2] `04_deploy.md`へ、破壊的変更の説明項目、確認質問、追加read-only調査、承認後の同一change set／保存済みplan再確認と継続実行を追加する。
- [R3] `05_update.md`が`04_deploy.md`と同じ確認待ち・継続実行flowを使用することを明示する。
- [R4] governance taskのlocal validationとtask completion contractを実行する。

## Acceptance checks

- [R1] `changed:AGENTS.md`
- [R1] `changed:framework/rules/cloudformation.md`
- [R1] `changed:framework/rules/terraform.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:framework/prompts/codex/04_deploy.md`
- [R3] `changed:framework/prompts/codex/05_update.md`
- [R4] `check:framework.task-completion-contract`

## Allowed paths

- `AGENTS.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/loop-engineering.md`
- `tasks/active.md`

## Out of scope

- `docs/designs/**`、`model/**`、`infra/**`、`tests/**`の変更
- resource type固有の削除判定またはrisk catalog
- deploy runner、approval database、別のruntime helperの追加
- consumer repositoryの変更
- AWS API、change set作成・実行、Terraform plan・apply

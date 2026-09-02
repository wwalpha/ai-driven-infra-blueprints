# JSON artifactの意味ベースhash化

## Task contract

- Task type: `governance`
- Goal: JSON policy artifactの表示形式だけの変更ではgenerated service modelをstaleにせず、意味の変更だけを`artifactSha256`へ反映するframework contractへ更新する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] `sync-model.py`がlinked JSON artifactを決定的に正規化してからSHA-256を生成する。
- [R2] 意味が同じで整形だけ異なるJSONは同じhash、内容が異なるJSONは異なhashになるfocused checkを追加する。
- [R3] JSON artifactの最低限の保存形式をUTF-8、LF、末尾改行ありに統一し、配列の表示形式は強制しない。
- [R4] 現在の詳細設計からgenerated service modelを再生成し、governance taskのlocal validationを実行する。

## Acceptance checks

- [R1] `changed:framework/scripts/sync-model.py`
- [R1] `check:framework.generated-service-model`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/model-information.md`
- [R4] `check:framework.generated-service-model`

## Allowed paths

- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `model/**`
- `tasks/active.md`

## Out of scope

- `docs/designs/**`、IaC、scenario、resultの変更
- AWS API、AWS mutation、deploy/apply
- JSON配列の1行・複数行表示の強制
- format-on-saveの無効化またはformatter固有の整形規則
- consumer repositoryへのframework sync

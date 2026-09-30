# QuickSight・MWAA・Macieの命名ルールを追加する

## Task contract

- Task type: `governance`
- Target: framework共通 / QuickSight.DataSource.Name、QuickSight.VPCConnection.Name、MWAA.Environment.Name、Macie.ClassificationJob.name
- Goal: 承認された4件の命名patternをtarget_aliasなしで命名表へ追加する。

## Required changes

- [R1] QuickSight DataSourceはqsds-{{application}}-{{environment}}-{{source_type}}-{{purpose}}、VPCConnectionはqsvc-{{application}}-{{environment}}-{{purpose}}を登録する。
- [R2] MWAA Environmentはmwaa-{{application}}-{{environment}}[-{{purpose}}]、Macie ClassificationJobはmacie-{{application}}-{{environment}}-{{purpose}}を登録する。
- [R3] source_typeとpurposeの意味、MWAAのpurpose省略条件、4件の名称制約を明記する。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R2] `changed:framework/rules/aws-resource-naming.md`
- [R3] `changed:framework/rules/aws-resource-naming.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/aws-resource-naming.md`

以下は前taskの未commit差分の保持対象だけとし、今回変更しない。

- `framework/scripts/model_design.py`
- `framework/scripts/model_design.checks.py`

## Out of scope

- catalog/provider schema、validator実装、consumer repository、docs/modelの設計値、IaC、AWS API、deploy/apply、scenario、別taskの作成・実行。
- 指定4 property以外の命名ルールは変更しない。既存の未commit変更は保持し、今回の変更へ取り込まない。
- governance local loopとgit diff --checkを実行する。verification outputは完了報告だけに記載する。

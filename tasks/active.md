# Athena / CloudTrailの命名ルール登録

## Task contract

- Task type: `governance`
- Target: framework共通 / Athena.WorkGroup.Name、CloudTrail.Trail.TrailName
- Goal: humanが確定したathwg／ctrail prefixの命名パターンを登録し、命名ルール未登録エラーを解消する。

## Required changes

- [R1] Athena.WorkGroup.Nameをathwg-{{application}}-{{environment}}-{{purpose}}、CloudTrail.Trail.TrailNameをctrail-{{application}}-{{environment}}-{{purpose}}として命名ルール一覧に登録する。
- [R2] 2 propertyの命名ルールcoverageを既存focused checksへ追加する。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R2] `changed:framework/scripts/model_design.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/model_design.checks.py`
- `framework/rules/aws-resource-naming.md`

以下は前taskの未commit差分の保持対象だけとし、今回変更しない。

- `framework/scripts/model_design.py`
- `framework/rules/detailed-design.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`

## Out of scope

- catalog/provider schema、consumer repository、docs/modelの設計値、IaC、AWS API、deploy/apply、scenario、別taskの作成・実行。
- 既存CodeBuild必須化の未commit差分は保持する。今回humanが指定したprefixを使用し、4文字制限を追加しない。
- governance local loopとgit diff --checkを実行する。verification outputは完了報告だけに記載する。

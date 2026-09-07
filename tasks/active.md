# 詳細設計のpolicy表示を全serviceへ共通化

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: IAMの既存表示を維持し、各serviceのpolicy JSONからStatement表または設定表と一覧リンクを生成し、local loopで表示整合性を検証する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 全service共通のpolicy表示、所有resourceとの対応、非Statement形式の設定表、生成手順を設計ruleとpromptへ定義する。
- [R2] 正式なcatalog propertyごとにpolicy表示方式を定義し、既存IAM生成処理を共通化する。JSONとの不一致、表示欠落、不正な所属をvalidatorで拒否する。
- [R3] 派生表示をmodelへ重複保持せず、既存のresource設定、JSONリンク、canonical hash、S3/KMS groupingを維持する。
- [R4] IAM回帰、各policy形式、複数resource、設定表、表示不一致、model非重複とCLIをfocused checksとlocal loopで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R2] `exists:framework/scripts/policy_tables.py`
- [R2] `absent:framework/scripts/iam_policy_tables.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `check:framework.policy-tables`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/scripts/sync-model.py`
- [R3] `check:framework.generated-service-model`
- [R4] `exists:framework/scripts/policy_tables.checks.py`
- [R4] `absent:framework/scripts/iam_policy_tables.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/iam_policy_tables.py`
- `framework/scripts/iam_policy_tables.checks.py`
- `framework/scripts/policy_tables.py`
- `framework/scripts/policy_tables.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.py`

## Out of scope

- materials catalog/schema、IaC、AWS操作、deploy/apply、scenario
- consumer repositoryへの同期、個別targetの詳細設計・JSON・modelの作成や移行
- 権限評価engine、policyの設計値や権限の自動修正、resource表示関係の変更

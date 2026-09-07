# IAM詳細設計にpolicy Statement表を追加

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: IAM Role設定表とpolicy JSONを維持し、RoleNameの一覧とJSONから生成する信頼・inline policyのStatement表を詳細設計へ追加する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] IAMの一覧・Statement表・所有RoleとJSONの対応・派生表示の生成手順を設計ruleとpromptへ定義する。
- [R2] policyの全要素とStatementの所属を保つ決定的な表生成を追加し、一覧・表とJSONの不一致をvalidatorで拒否する。
- [R3] 派生表示をmodelへ重複保持せず、既存のRole設定、JSONリンク、canonical hashを維持する。
- [R4] 複数Role・複数policy・複数条件・省略不可の要素・表示不一致・model非重複をfocused checksとlocal loopで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R1] `changed:framework/rules/loop-engineering.md`
- [R2] `exists:framework/scripts/iam_policy_tables.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `check:framework.iam-policy-tables`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/scripts/sync-model.py`
- [R3] `check:framework.generated-service-model`
- [R4] `exists:framework/scripts/iam_policy_tables.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/iam_policy_tables.py`
- `framework/scripts/iam_policy_tables.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.py`

## Out of scope

- materials catalog/schema、IaC、AWS操作、deploy/apply、scenario
- consumer repositoryへの同期、個別targetの詳細設計・JSON・modelの作成や移行
- IAMの権限評価engine、policyの設計値や権限の自動修正

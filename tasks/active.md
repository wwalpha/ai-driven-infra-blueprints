# KMS Keyのalias由来表示名

## Task contract

- Task type: `governance`
- Target: framework共通のKMS Key表示生成・検証
- Goal: KMS.KeyのResourceNameと詳細見出しを、所属するKMS AliasのAliasNameから先頭のalias/を除いた名称へ統一する。

## Required changes

- [R1] 共通名称解決・model生成・表示検証で所属AliasNameを使用する。Aliasの正式値、logical ID、desired/observed分離を保持する。複数aliasでは既存display labelで明示されたaliasだけを選択し、曖昧なら停止する。alias未設計のKeyは既存の表示規則を保持する。
- [R2] 表示ルールと例を更新し、一覧・見出し・anchor・roundtripと複数aliasの回帰checkを実行する。

## Acceptance checks

- [R1] `changed:framework/scripts/design_layout.py`
- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R1] `check:framework.generated-service-model`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/scripts/model_design.checks.py`
- [R2] `check:framework.resource-layout`
- [R2] `check:framework.focused-check-runner`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/model_design.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/model_design.checks.py`
- `framework/rules/detailed-design.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/model-information.md`

## Out of scope

- consumer repository、正本model、生成済み設計、IaC、project.json、catalog/lock、scenario/resultは変更しない。
- AWS API・mutation、deploy/apply、別task作成・実行へ進まない。
- focused checks、governance local loop、差分チェックを実行し、今回の成功と既存失敗を分けて報告する。検証ログはrepository外へ保存する。

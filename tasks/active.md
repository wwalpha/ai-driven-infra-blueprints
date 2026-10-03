# 環境比較Pythonで確認済み環境差異を検知件数から除外

## Task contract
- Task type: `governance`
- Target: `framework/scripts/compare-environments.py`と対応する回帰検証・env-diffスキル
- Goal: 確認済みの許容された環境差異を比較Pythonのdifferencesと検知件数から除外し、実値・除外理由を別に保持する。未確認の差異や古い除外指定による見落としを防ぐ。

## Validation scope
- `framework`

## Required changes
- [R1] 既存resource-mapの任意environment_differencesで、確認済みのservice・semantic identity・両側の実値・理由を指定できるようにする。比較組・対象・重複・実値不一致・不存在・未確認resourceの除外を拒否する。
- [R2] Pythonのdifferencesから一致した確認済み環境差異を除外し、environment_differencesへ証拠・理由を保持する。difference_countを残った差分件数として出力し、IMPORT除外と未確認・入力エラーの契約を維持する。
- [R3] 名称・保存先の検知件数減少、設定差の保持、古い除外指定・不正入力の拒否、read-only動作を回帰検証する。
- [R4] env-diffで初回比較・AI確認・確認済み除外を渡した再比較を行い、Pythonのdifference_countを報告に使うよう指示を更新する。前turnの許容環境差異を掲載しない変更を維持する。

## Acceptance checks
- [R1] `changed:framework/scripts/compare-environments.py`
- [R2] `changed:framework/scripts/compare-environments.py`
- [R3] `changed:framework/scripts/compare-environments.checks.py`
- [R4] `changed:.agents/skills/env-diff/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/compare-environments.py`
- `framework/scripts/compare-environments.checks.py`
- `.agents/skills/env-diff/SKILL.md`

## Out of scope
- 他program、共通rule、catalog、consumer同期、既存diff.md、issues.md、model、設計、IaC、project.json、AWS API、deploy/apply、commit、push、別task。

## Completion
- skillの形式と分類・出力・件数集計指示の整合を確認し、framework scopeのfull local loopで対応する回帰検証とAcceptance checksを実行する。

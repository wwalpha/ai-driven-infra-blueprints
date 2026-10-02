# Service生成時の保存済み参照保護

## Task contract

- Task type: `governance`
- Target: framework共通のservice model表示生成・検証
- Goal: 同targetの保持された参照元を含めて候補生成物による新たなlink切断を保存前に検出し、切断する参照先serviceを復元・再検証して無関係な成功serviceの保存を維持する。

## Required changes

- [R1] 既存validatorと復元処理を再利用して保存済みlinkの既存失敗と新たな切断を区別し、対象service・参照元・linkを報告する。正本modelを変更せず、復元後に候補を再検証する。
- [R2] 参照元の生成失敗時の保持、双方を整合して変更した場合の成功、read-only実行の非変更を最小の回帰checkで確認する。無関係な成功serviceと既存参照エラーの分離も確認する。

## Acceptance checks

- [R1] `changed:framework/scripts/sync-model.py`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `check:framework.generated-service-model`
- [R2] `changed:framework/scripts/model_design.checks.py`
- [R2] `check:framework.focused-check-runner`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/sync-model.py`
- `framework/scripts/model_design.checks.py`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`

## Out of scope

- rule変更は必要な場合だけ行う。新しい依存、正本model、設計、IaC、project.json、catalog/lock、scenario/result、別taskを変更・実行しない。
- viewcard-codeのmodel／設計／IaC、AWS API・mutation、deploy/applyを変更・実行しない。KMS旧参照396件の移行を自動実行しない。
- focused checks、governance local loop、差分チェックを実行し、今回の成功と既存失敗を分けて報告する。検証ログはrepository外へ保存する。

# 保存済み参照によるservice生成の連鎖停止を解消する

## Task contract

- Task type: `governance`
- Target: frameworkのservice単位生成・保存
- Goal: 検証に成功したserviceを保存し、他serviceの保存済み旧リンク切断は警告とする。参照元修復は後続の別taskで行えるようにする。

## Validation scope

- `framework`

## Required changes

- [R1] candidate breaks saved referenceによる成功serviceの除外・rollbackをやめ、保存後に旧参照切断を警告する。生成service自身の検証、失敗serviceの保存済み表示維持、書込失敗時の保護は維持する。
- [R2] 旧参照が残っても成功serviceを保存し、後続の参照元修復で整合すること、生成失敗・書込失敗を既存fixtureで回帰検証する。
- [R4] 元フォルダのRotationSchedule修復を保持し、旧参照切断の回帰検証を警告方式に合わせる。
- [R3] 他serviceの旧参照切断を許容するservice単位保存規則を記載する。

## Acceptance checks

- [R1] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/model_design.checks.py`
- [R2] `changed:framework/scripts/sync-model.checks.py`
- [R3] `changed:framework/rules/model-information.md`

- [R4] `changed:framework/scripts/rotation_schedule.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/rotation_schedule.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/sync-model.checks.py`
- `framework/rules/model-information.md`

## Out of scope

- 関連serviceの自動追加・一括修復、consumer同期、design/model、catalog、IaC、AWS、scenarioは行わない。
- 元フォルダへ専用worktreeの差分を反映し、既存のRotationSchedule修復を保持する。
- fixtureはrepository外の一時directoryに作成する。framework scopeのlocal loopを実行する。

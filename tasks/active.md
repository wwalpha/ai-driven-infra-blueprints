# 全回帰ガードをrepo直下の.lockだけへ簡素化

## Task contract
- Task type: `governance`
- Target: Windows framework regression guard
- Goal: repo直下の.lockへhashだけを保存し、全回帰前の人間入力照合に絞る。ProgramDataへの設置、管理者登録、ACL操作を削除する。

## Validation scope
- `framework`

## Required changes
- [R1] 登録は通常権限でrepo直下の.lock一つだけを作成する。password/hash形式は既存登録と互換にし、ProgramData、管理者チェック、別helper設置とACL操作を削除する。
- [R2] Windowsの全回帰は当該repoの.lockと人間入力が一致する場合だけ開始する。未登録・破損・不一致・非対話・キャンセルは失敗とし、解除flagやtokenを追加しない。
- [R3] .lockをtask変更契約から分離したローカル設定として扱い、staged snapshotへ同じ登録値を引き継ぐ。対象限定チェックと既存scopeを維持する。
- [R4] 最小構成の登録・照合・snapshot・ローカル設定の回帰checkとframework local loopを実行し、READMEとruleを簡素化する。

## Acceptance checks
- [R1] `changed:framework/scripts/regression_guard.py`
- [R2] `changed:framework/scripts/regression_guard.checks.py`
- [R3] `changed:framework/scripts/blueprint-loop.py`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/blueprint-loop.checks.py`
- [R4] `changed:README.md`
- [R4] `changed:framework/rules/loop-engineering.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/regression_guard.py`
- `framework/scripts/regression_guard.checks.py`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/validate-blueprint.py`
- `README.md`
- `framework/rules/loop-engineering.md`

## Out of scope
- 実passwordをエージェントが決める／受け取ること、実repoの.lock登録・書換え、Windows実機のProgramData削除・管理者操作、消費側同期、AWS操作、実設計/model/IaC/project、catalog変更、scenario、commit、push、index変更。
- macOSのガード有効化、OS権限分離、ガード迂回、実repoの全回帰を既知passwordやmockで解除すること。fixture内だけで登録・照合を検証する。

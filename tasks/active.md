# Local loopの再現性と実行時間を改善する

## Task contract
- Task type: `governance`
- Target: framework local validation
- Goal: 文字コードとfixture依存を修復し、固定staged snapshot、保守的なcheck選択、並列回帰、重点計測を追加する。

## Validation scope
- `framework`

## Required changes
- [R1] UTF-8事前確認、staged snapshotと比較元固定、変更検知を実装する。
- [R2] 回帰fixtureとpath比較をOSとconsumer状態から独立させる。
- [R3] 保守的なcheck選択、最大2並列と順序付き診断、重点計測を実装する。
- [R4] 実行ruleと使用方法を更新し、回帰検証する。

## Acceptance checks
- [R1] `changed:framework/scripts/blueprint-loop.py`
- [R1] `changed:framework/scripts/blueprint-loop.checks.py`
- [R2] `changed:framework/scripts/blueprint-loop.checks.py`
- [R2] `changed:framework/scripts/model_files.checks.py`
- [R3] `changed:framework/scripts/blueprint-loop.py`
- [R3] `changed:framework/scripts/design_catalog.checks.py`
- [R4] `changed:framework/rules/loop-engineering.md`
- [R4] `changed:README.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/model_files.checks.py`
- `framework/scripts/design_catalog.checks.py`
- `framework/rules/loop-engineering.md`
- `README.md`

## Out of scope
- consumer同期、実設計/model、catalog、IaC、AWS、scenarioは変更しない。
- commit、push、現在のindexの変更は行わない。snapshot検証は一時fixtureで確認する。
- framework scopeのfull local loopを実行し、実Windows実行と静的確認を区別して報告する。

# model_design focused checkの改行依存修正

## Task contract

- Task type: `governance`
- Target: framework共通 / model_design.checks.py
- Goal: 入力propertiesのバイト保持検証がWindowsのCRLFでも成功するよう修正する。

## Required changes

- [R1] LF固定の期待値を同期前の実バイト列へ置き換え、入力propertiesの変更を引き続き検出する。

## Acceptance checks

- [R1] `changed:framework/scripts/model_design.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/model_design.checks.py`

## Out of scope

- production code、catalog、design/model、IaC、consumer repository、AWS API、deploy/apply、scenario、別taskの作成・実行は行わない。
- focused checkを通常実行およびCRLF書き込みを再現して実行し、governance local loopとgit diff --checkの結果を報告する。

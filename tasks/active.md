# Windowsでframework local loopを実行可能にする

## Task contract

- Task type: `governance`
- Target: framework共通 / catalog lockとfocused checksのWindows互換性
- Goal: OSによるPath比較順序、既定文字コード、symlink権限への依存を除去し、Windowsでも既存local loopを実行可能にする。

## Required changes

- [R1] catalog lockをcase-sensitiveなファイル名順で生成・検証し、Windows形式のPathでも同じ順序になる回帰checkを追加する。catalog本体とlockは変更しない。
- [R2] focused checksの文字コード未指定のテキスト読み書きをUTF-8指定に揃え、cp1252既定環境で日本語fixtureを扱えるようにする。
- [R3] focused checksのframework fixture用symlinkを標準ライブラリのdirectory copyへ置換し、管理者権限と開発者モードを不要にする。

## Acceptance checks

- [R1] `changed:framework/scripts/update-catalog-lock.py`
- [R1] `changed:framework/scripts/update-catalog-lock.checks.py`
- [R2] `changed:framework/scripts/design_catalog.checks.py`
- [R2] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R2] `changed:framework/scripts/policy_tables.checks.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/scripts/model_design.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/update-catalog-lock.py`
- `framework/scripts/update-catalog-lock.checks.py`
- `framework/scripts/design_catalog.checks.py`
- `framework/scripts/cloudformation_schema.checks.py`
- `framework/scripts/policy_tables.checks.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/model_design.checks.py`

## Out of scope

- catalog/schema snapshotとchecksum、design、model、IaC、consumer repository、AWS API、deploy/apply、scenario、別taskの作成・実行。
- 外部依存、OS設定変更、checkの抑制、環境変数による回避だけの修正は追加しない。
- governance local loop、cp1252既定とsymlink禁止を模擬したfocused checks、git diff --checkを実行する。Windows実機での検証とは区別し、verification outputは完了報告だけに記載する。

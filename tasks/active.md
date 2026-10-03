# Resource単位のmodel読み取り

## Task contract
- Task type: `governance`
- Target: framework service model reading
- Goal: service Markdownを一つに維持し、更新対象resourceの正本情報だけを位置付きで抽出してAIの読み取り量を減らす。

## Validation scope
- `framework`

## Required changes
- [R1] 既存model_files.pyへread-onlyのresource抽出を追加する。番号・logical ID・anchorの完全一致で一件を選び、単一fileと分割modelに対応する。対象のdesired/observed/display、同じgroupの親子、service metadataと共通注記を元の値・順序・file/行位置で表示する。未一致・曖昧な選択と不正modelを拒否する。
- [R2] 正本の部分読み取り、必要な参照情報の追加読み取り、生成後の差分確認とservice全体の既存検証をrulesとREADMEへ記載する。
- [R3] 50件以上のresource、part境界、grouped親子、JSON、namespace、選択失敗とread-onlyを既存の回帰checkで検証する。

## Acceptance checks
- [R1] `changed:framework/scripts/model_files.py`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:README.md`
- [R3] `changed:framework/scripts/model_files.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/model_files.py`
- `framework/scripts/model_files.checks.py`
- `framework/rules/model-information.md`
- `README.md`

## Out of scope
- Markdown分割、model保存形式や生成・validation scopeの変更、実model・設計・IaC・catalog変更。
- AWS取得・変更、consumer同期、scenario、別task、commit、push。
- 完了前にframework scopeのfull local loopと差分レビューを実施する。

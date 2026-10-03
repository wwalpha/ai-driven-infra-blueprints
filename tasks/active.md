# issuesスキルの専用CFn比較撤去

## Task contract
- Task type: `governance`
- Target: issuesスキルと専用CFn比較実装
- Goal: issues調査で毎回実行するproperties ↔ CFn比較と、その専用実装・参照を撤去する。

## Validation scope
- `framework`

## Required changes
- [R1] `.agents/skills/issues/SKILL.md`から、frontmatterのCFn比較固有の説明、`properties／CloudFormation比較`節、比較command・結果形式・判定条件・専用根拠出力の指示を削除する。一般的なissue調査・保存・更新、根拠リンク、local validationの指示は維持する。
- [R2] `framework/scripts/check-model-cfn.py`と`framework/scripts/check-model-cfn.checks.py`を削除する。他の処理が使用するmodel reader・catalog・CFn decoderなどの共通実装は維持する。
- [R3] `framework/rules/cloudformation.md`から、削除する比較commandの`--runtime-parameters`に関する専用説明を削除する。

## Acceptance checks
- [R1] `changed:.agents/skills/issues/SKILL.md`
- [R2] `absent:framework/scripts/check-model-cfn.py`
- [R2] `absent:framework/scripts/check-model-cfn.checks.py`
- [R3] `changed:framework/rules/cloudformation.md`

## Allowed paths
- `tasks/active.md`
- `.agents/skills/issues/SKILL.md`
- `framework/scripts/check-model-cfn.py`
- `framework/scripts/check-model-cfn.checks.py`
- `framework/rules/cloudformation.md`

## Out of scope
- 新しいPython＋AWS SDK比較の実装、viewcard-codeへの同期、model・設計・IaC・parameter・project・既存issueの変更、AWS API、deploy/apply、push。
- CloudFormationの構文・schema検証、deploy時のImportValue事前確認、modelと生成物の整合性検証、issue gateを維持する。
- AWS差分を受けてCFnを調査する将来の運用を禁止しない。比較機能の撤去を問題の修復や同期確認として扱わない。
- 既存の無関係な差分を保持する。別taskへ進まない。

## Completion
- 削除したcommand・専用moduleへの有効な参照が残っていないことを検索で確認する。
- 既存runnerの自動検出を利用し、`python3 framework/scripts/blueprint-loop.py --mode task`でframework scopeの検証と必要な回帰を完了する。
- 完了報告に削除・変更file、参照確認、local loop結果、実行した回帰件数を記載する。properties・CFn・AWS実体の同期を確認したとは報告しない。
- humanが明示した新しいworktreeで実施し、検証成功後にmasterへmergeする。このために必要なローカルcommitだけを許可する。

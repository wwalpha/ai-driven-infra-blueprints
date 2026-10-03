# desired環境間比較処理とskillの作成

## Task contract
- Task type: `governance`
- Target: frameworkのdesired環境間比較処理とenv-diff skill
- Goal: dev↔stg、stg↔prodをcde／non-cde別に計4組比較し、AIが差分を整理して環境差異以外の問題をissuesへ追記するための処理とskillを作成する。

## Validation scope
- `framework`

## Required changes
- [R1] 既存model readerを再利用し、desiredのみの4組の差分を根拠位置付きJSONとして出力するread-only比較処理を追加する。分割model、resource／row番号の違い、片側欠落、比較不能を扱い、環境差異の判断はAIへ渡す。
- [R2] 短い名前env-diffのskillを追加し、4組の比較・AI要約・環境差異の根拠確認・既存issuesを保持した問題追記・local loopを指示する。
- [R3] 比較処理の最小回帰checkを既存runnerの自動検出対象へ追加し、skill validationとframework local loopを実行する。

## Acceptance checks
- [R1] `exists:framework/scripts/compare-environments.py`
- [R2] `exists:.agents/skills/env-diff/SKILL.md`
- [R2] `absent:.agents/skills/compare-environments/SKILL.md`
- [R3] `exists:framework/scripts/compare-environments.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/compare-environments.py`
- `framework/scripts/compare-environments.checks.py`
- `.agents/skills/compare-environments/SKILL.md`
- `.agents/skills/env-diff/SKILL.md`

## Out of scope
- 実consumerの比較・issues追記、viewcard-codeへの同期、project・model・設計・IaC・catalog変更、AWS API、deploy/apply、commit、push、別taskの実行。

## Completion
- 一時fixtureで4組、desired限定、分割読込、番号変更、JSON本文、片側欠落、比較不能とread-only性を検証する。
- skill-creatorのquick_validate.pyとpython3 -B framework/scripts/blueprint-loop.py --mode taskを実行し、結果を報告して終了する。

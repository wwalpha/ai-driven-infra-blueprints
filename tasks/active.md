# env-diffのLogical ID・環境固有名称差を整理しIMPORTを比較対象外にする

## Task contract
- Task type: `governance`
- Target: env-diff skill、desired環境比較処理と既存回帰チェック
- Goal: Logical IDだけの違いを仕様差分にせず、確認済みのresource対応と参照先に基づいて設定を比較する。dev/stgの許容された環境固有名称差を環境差異に分類する。resourceMode=IMPORTと確認済みの対応先を比較・命名確認から除外し、CREATEと未指定の比較、CREATE側の参照確認、未確定対応の保持を維持する。

## Validation scope
- `framework`

## Required changes
- [R1] 確認済みresource対応を比較へ適用し、Logical ID・派生anchorだけの違いを除外する。未確定対応を不足／追加と断定せず、根拠を保持する。
- [R2] 確認済み参照先に基づいてlogical referenceを比較し、設定値・JSON・名称・実際の参照先変更は差分に残す。
- [R3] env-diff skillに対応確認、未確認の扱い、比較入力・出力を明記する。
- [R4] ID差、参照、未確定・不正対応、実設定差、既存scopeとread-only動作を既存回帰で検証する。
- [R5] dev/stgのcde／noncde表記の有無と明示されたCloudTrail名称例を許容された命名例外として環境差異に分類し、規則不一致件数へ含めないことをenv-diff skillへ明記する。
- [R6] IMPORT resourceと確認済み対応先のmetadata・rowを比較から除外し、不足／追加・未確認・命名規則不一致として数えず、除外根拠を保持する。未指定CREATE、CREATEの実設定・IMPORTへの参照、modeの妥当性は維持する。
- [R7] 両側IMPORT・片側IMPORT・ID違いの確認済み対応・片側のみのIMPORT・混在service・CREATE参照とmode不正を既存回帰で検証し、skillのIMPORT名称差分類を除外規則に置き換える。

## Acceptance checks
- [R1] `changed:framework/scripts/compare-environments.py`
- [R2] `changed:framework/scripts/compare-environments.py`
- [R3] `changed:.agents/skills/env-diff/SKILL.md`
- [R4] `changed:framework/scripts/compare-environments.checks.py`
- [R5] `changed:.agents/skills/env-diff/SKILL.md`
- [R6] `changed:framework/scripts/compare-environments.py`
- [R7] `changed:framework/scripts/compare-environments.checks.py`
- [R7] `changed:.agents/skills/env-diff/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/compare-environments.py`
- `framework/scripts/compare-environments.checks.py`
- `.agents/skills/env-diff/SKILL.md`

## Out of scope
- 実環境のdiff.md更新、consumer同期、model・設計・IaC・catalog・project変更、AWS API、deploy/apply、commit、push、merge、別task。

## Completion
- python3 -B framework/scripts/blueprint-loop.py --mode fullでframework scopeと全framework回帰を検証する。

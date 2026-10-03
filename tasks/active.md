# env-diffの命名規則照合と判定根拠を明確化

## Task contract
- Task type: `governance`
- Target: `.agents/skills/env-diff/SKILL.md`
- Goal: 名称・参照の環境差異判定前にnaming ruleへの適合を両環境で確認し、不一致は差分として期待値・実値・根拠を記載する。件数だけの曖昧な一括判定を避ける。

## Validation scope
- `framework`

## Required changes
- [R1] env-diffのAI整理へ正式な命名規則、確定済みcomponent、適用対象・例外と参照先の確認を追加し、不一致をその他の差分、判定不足を未確認とする。resource/propertyごとの両環境の判定・期待値・実値・根拠をdiff.mdへ記載させる。

## Acceptance checks
- [R1] `changed:.agents/skills/env-diff/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `.agents/skills/env-diff/SKILL.md`
- `framework/scripts/compare-environments.py`
- `framework/scripts/compare-environments.checks.py`

## Out of scope
- 前taskの比較組選択によるscript／checkの既存差分は保持し、今回編集しない。
- 比較program・命名規則・validator・issue gateの変更、実consumerの比較・既存diff再判定・issues更新、model・設計・IaC・project・catalog変更、AWS API、deploy/apply、commit、push、別task。

## Completion
- 命名規則の対象・例外と期待値の正本を確認し、skill validationとpython3 -B framework/scripts/blueprint-loop.py --mode taskを実行して終了する。

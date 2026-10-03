# env-diffのサービス別整理と比較基準を明確化

## Task contract
- Task type: `governance`
- Target: `.agents/skills/env-diff/SKILL.md`
- Goal: 差分とAI要約をサービス別に整理し、dev→stgではdev、stg→prodではstgを正として比較する。

## Validation scope
- `framework`

## Required changes
- [R1] env-diffで比較元を正とする基準、比較先の不足・追加・値の相違を明示し、要約と全差分をサービス別に保存する。環境固有値は命名規則等を踏まえ、比較元の規則不一致も記載する。

## Acceptance checks
- [R1] `changed:.agents/skills/env-diff/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `.agents/skills/env-diff/SKILL.md`

## Out of scope
- 比較program・命名規則・validator・issue gateの変更、実consumerの比較・既存diff再判定・issues更新、model・設計・IaC・project・catalog変更、AWS API、deploy/apply、commit、push、別task。

## Completion
- skill validationとpython3 -B framework/scripts/blueprint-loop.py --mode taskを実行して終了する。

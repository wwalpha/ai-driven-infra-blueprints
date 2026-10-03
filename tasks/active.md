# env-diff保存を既存issueによる停止対象から除外

## Task contract
- Task type: `governance`
- Target: env-diff skill、issue gate validator、共通運用ルール
- Goal: desiredの環境比較とdiff.md保存を既存issues.mdによる停止対象から除外し、通常task・model保存・AWS操作のgateを維持する。

## Validation scope
- `framework`

## Required changes
- [R1] 明示service scopeのissues.md／diff.mdとactive contractだけをAllowed paths・変更対象とするmigrationの停止判定を免除する。
- [R2] env-diffと共通ルールに保存限定taskの免除条件を明記する。
- [R3] diff保存・曖昧issueの免除と、scope外保存・通常task・model保存・AWS操作の拒否を既存回帰で確認する。

## Acceptance checks
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:.agents/skills/env-diff/SKILL.md`
- [R2] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:AGENTS.md`
- [R3] `changed:framework/scripts/issue_gate.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/issue_gate.checks.py`
- `.agents/skills/env-diff/SKILL.md`
- `framework/rules/loop-engineering.md`
- `AGENTS.md`

## Out of scope
- consumer repositoryへの同期、実環境のdiff.md作成、既存issue修復、model・設計・IaC・catalog・project変更、AWS API、deploy/apply、push、別task。

## Completion
- python3 -B framework/scripts/blueprint-loop.py --mode fullで検証する。
- 今回の変更をcommitし、既存未commit変更を保持してmasterへmergeする。

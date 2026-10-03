# CloudFormation比較とissue調査workflowの改善

## Task contract
- Task type: `governance`
- Target: 共通CFn比較、issues保存時の検証処理
- Goal: Fn::FindInMapを評価し、stack単位の失敗で他serviceの比較を中断せず、issue調査・保存を既存issue gateで停止しない。

## Validation scope
- `framework`

## Required changes
- [R1] Fn::FindInMapのlocal Mappings、Ref、nested lookupとDefaultValueを評価し、不正・未解決値は比較不能として報告する。CFn decoderのscalar型による同値の誤検知を修復する。
- [R2] stack読込み・Export・Conditionとserviceの失敗を分離し、正常な比較結果を保持して継続する。失敗・不明なcoverageをPASSと扱わない。
- [R3] 明示scopeのissues一覧とactive contractだけを許可・変更するmigration taskを調査保存として認識し、通常作業・model保存・AWS mutationのissue gateを維持する。
- [R4] issuesスキルとルールを更新し、上記動作の回帰とframework local loopを検証する。

## Acceptance checks
- [R1] `changed:framework/scripts/check-model-cfn.py`
- [R1] `changed:framework/scripts/check-model-cfn.checks.py`
- [R2] `changed:framework/scripts/check-model-cfn.checks.py`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/issue_gate.checks.py`
- [R4] `changed:.agents/skills/issues/SKILL.md`
- [R4] `changed:framework/rules/loop-engineering.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/check-model-cfn.py`
- `framework/scripts/check-model-cfn.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/issue_gate.checks.py`
- `.agents/skills/issues/SKILL.md`
- `framework/rules/loop-engineering.md`

## Out of scope
- consumer同期、実targetのmodel・設計・IaC・project・issues変更、AWS API、deploy/apply、scenario、commit/push。

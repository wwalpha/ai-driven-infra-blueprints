# env-diffで差分のないサービスを掲載しない

## Task contract
- Task type: `governance`
- Target: `.agents/skills/env-diff/SKILL.md`
- Goal: diff.mdと完了報告から差分のないサービスの見出し・説明を省き、再比較で不要になった旧記載も除去する。

## Validation scope
- `framework`

## Required changes
- [R1] 差分・命名規則不一致・未確認・比較不能事項がないserviceを掲載しない。IMPORTの除外理由は冒頭の比較範囲へまとめ、未確認・比較不能事項は維持する。
- [R2] 再比較で掲載事項がなくなったserviceの旧見出し・本文を削除する。全serviceに掲載事項がなければdiff.mdの冒頭情報だけを残す。

## Acceptance checks
- [R1] `changed:.agents/skills/env-diff/SKILL.md`
- [R2] `changed:.agents/skills/env-diff/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `.agents/skills/env-diff/SKILL.md`

## Out of scope
- 比較program、共通rule、catalog、consumer同期、既存diff.md、issues.md、model、設計、IaC、project.json、AWS API、deploy/apply、commit、push、別task。

## Completion
- 出力・更新指示の整合を確認し、framework scopeのfull local loopでtask固有checkとAcceptance checksを実行する。

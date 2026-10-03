# issuesスキルを正本repositoryへ統合

## Task contract
- Task type: `governance`
- Target: `.agents/skills/issues/SKILL.md`の共通正本
- Goal: viewcard-codeの既存issuesスキルと、このrepositoryのCFn比較対応スキルを統合し、ai-driven-infra-blueprintsを正本として保存する。

## Validation scope
- `framework`

## Required changes
- [R1] viewcard-code版の保存・更新、対象確認、出力形式、相対根拠link、検証失敗時の保持を維持し、正本repositoryの共通issuesスキルへ統合する。
- [R2] 前taskで追加済みのread-only比較処理と回帰を保持し、CFn比較の実行、不一致／比較不能の記録、検証範囲の限界を統合スキルに維持する。
- [R3] 統合スキルの形式検証とframework local loopを実行する。

## Acceptance checks
- [R1] `changed:.agents/skills/issues/SKILL.md`
- [R2] `exists:framework/scripts/check-model-cfn.py`
- [R2] `exists:framework/scripts/check-model-cfn.checks.py`
- [R3] `exists:.agents/skills/issues/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `.agents/skills/issues/SKILL.md`
- `framework/scripts/check-model-cfn.py`
- `framework/scripts/check-model-cfn.checks.py`

## Out of scope
- 実targetのmodel、design、IaC、project、issues一覧の変更、consumer同期、AWS API、deploy/apply、scenario、commit/push。

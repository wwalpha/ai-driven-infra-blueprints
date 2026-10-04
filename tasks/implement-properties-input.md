# Implementのauthoritative properties入力

## Task contract
- Task type: `governance`
- Task status: `completed`
- Target: frameworkのImplement workflow
- Goal: 承認済みdesignのauthoritative model propertiesだけをIaC inputとし、generated Markdownの事前二重読込・比較を廃止する。既存生成とlocal loopの整合性検証を維持する。
- AWS API execution: `forbidden`
- AWS mutation: `forbidden`
- Deploy/apply: `forbidden`

## Validation scope
- `framework`

## Required changes
- [R1] Implement正文をproperties基準へ統一し、resource抽出、Markdown path selector互換、stack・reference解決と不足時停止を明記する。
- [R2] 既存Implement契約チェックを更新し、properties入力とMarkdown整合性検証の維持を直接検証する。

## Acceptance checks
- [R1] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`

## Modified files
- `tasks/implement-properties-input.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/validate-blueprint.checks.py`

## Allowed paths
- `tasks/implement-properties-input.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope
- skill wrapper、model規則、Markdown生成・format、sync-model、validation scope/cache/並列数、IaC生成規則、design/deploy/update、resource schema、naming、IMPORT/CREATE、AWS API、plan/change set、consumer、commit、push、別task。

## Completion
- human指定に従い全framework回帰を実行しない。diffレビュー、git diff --check、framework scopeの既存validatorによるtask固有check・Acceptance checksと直接関連する既存チェックだけを既存local loop runnerで実行し、成功後に本契約だけcompletedへ変更する。

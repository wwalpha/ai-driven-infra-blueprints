# Update flowの既存performance契約への追従

## Task contract
- Task type: `governance`
- Task status: `completed`
- Target: frameworkのUpdate promptとprompt contract回帰check
- Goal: Updateの安全性と最終validationを維持し、重複context、CloudFormation preflight・observed同期とissue gate process起動を削減する。
- AWS API execution: `forbidden`
- AWS mutation: `forbidden`
- Deploy/apply: `forbidden`

## Validation scope
- `framework`

## Required changes
- [R1] Update入力をauthoritative propertiesと既存部分読込へ統一し、03/04全文読込を不要にして必要な安全契約とTerraform契約を維持する。
- [R2] CloudFormation final preflightとobserved同期を既存controllerへ集約し、cross-stack read-only確認、issue gate batch化、final task-local loopを明記する。
- [R3] 既存prompt regression方式に最小Update checkを追加し、4 caseと重複の再導入・final loop削除を検証する。

## Acceptance checks
- [R1] `changed:framework/prompts/codex/05_update.md`
- [R2] `changed:framework/prompts/codex/05_update.md`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Modified files
- `tasks/update-performance.md`
- `framework/prompts/codex/05_update.md`
- `framework/scripts/validate-blueprint.checks.py`

## Allowed paths
- `tasks/update-performance.md`
- `framework/prompts/codex/05_update.md`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope
- controller deploy/rollback/order/approval/session/cache semantics、Terraform behavior、schema、naming、import、evidence、framework regression policy、catalog、consumer、model、IaC、AWS execution、commit、push、別task。

## Completion
- 関連prompt regressionを含むframework scopeの既存full local loopでtask固有check、Acceptance checks、framework回帰と差分checkを実行し、成功後に本契約だけcompletedへ変更する。通常Updateへframework全回帰を追加しない。

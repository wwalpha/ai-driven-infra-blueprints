# active task対象だけの並列検証

## Task contract

- Task type: `governance`
- Target: frameworkのlocal loop・service model検証
- Goal: active taskで明示したenvironment/target-directory/serviceだけを検証し、複数targetを並列実行する。今回の回帰対象はdev/cde、dev/non-cde、stg/cde、stg/non-cdeのEC2だけ。

## Validation scope

- `framework`

## Required changes

- [R1] 明示scopeを共通化し、指定不足・不明target・検証範囲外の設計変更を拒否する。対象serviceのmodel、生成Markdown/JSON、schema、命名、参照を検証し、別serviceは参照解決情報だけを読む。
- [R2] 複数targetの検証を並列化する。通常設計では全検証テストを実行せず、全体検証は明示指定時だけ実行する。task契約と変更範囲の共通checkを維持する。
- [R3] 4targetのEC2、対象外エラー、リンク不整合、指定不足と明示全体検証の回帰check、運用ルールと設計handoffを更新する。

## Acceptance checks

- [R1] `changed:framework/scripts/validation_scope.py`
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R1] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/blueprint-loop.py`
- [R2] `check:framework.focused-check-runner`
- [R3] `changed:framework/scripts/validation_scope.checks.py`
- [R3] `changed:framework/scripts/blueprint-loop.checks.py`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`
- [R3] `changed:README.md`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/validation_scope.py`
- `framework/scripts/validation_scope.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/model_design.checks.py`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `README.md`

## Out of scope

- consumer repository、design/model、IaC、project.json、catalog/lock、scenario/resultは変更しない。
- AWS API、deploy/apply、別task作成・実行へ進まない。
- framework修正に対応するfocused checksとgovernance local loop、差分checkを実行する。通常設計の全check自動実行と区別する。

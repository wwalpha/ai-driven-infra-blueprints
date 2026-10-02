# 通常taskのservice限定検証

## Task contract

- Task type: `governance`
- Target: frameworkのlocal loop、検証scopeと運用規則
- Goal: 通常taskはValidation scopeだけを検証し、実設計の全体検証は明示指定の日次実行などに限定する。

## Validation scope

- `framework`

## Required changes

- [R1] task/local/fullからvalidatorとmodel照合へ指定scopeを維持し、暗黙の全体検証をなくす。共通契約・変更範囲・catalog整合性は維持する。
- [R2] ルール・README・設計prompt・配布skillの説明を統一し、対象検証後の念のための全体検証を禁止する。
- [R3] 実validator/generatorを使い対象外エラーの隔離、対象内エラーの失敗、明示all、scope欠落の停止を回帰検証する。

## Acceptance checks

- [R1] `changed:framework/scripts/blueprint-loop.py`
- [R2] `changed:framework/rules/loop-engineering.md`
- [R2] `changed:README.md`
- [R2] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:.agents/skills/implement/SKILL.md`
- [R3] `changed:framework/scripts/blueprint-loop.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `.agents/skills/*/SKILL.md`
- `README.md`

## Out of scope

- consumer repositoryへの同期、design/model/IaC/catalog変更、AWS操作、日次scheduleの作成・変更は行わない。
- framework scopeのlocal loopとframework回帰を実行する。実repositoryの全service検証は追加しない。
- fixture/logはrepository外の一時directoryに置く。

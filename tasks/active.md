# サービス単位の設計表示生成・保存

## Task contract

- Task type: `governance`
- Target: framework共通 / sync-model.pyの保存境界
- Goal: 成功したserviceのMarkdown／JSONを保存し、失敗serviceだけ既存生成物を維持する。

## Required changes

- [R1] 読み込み・生成・検証・保存のエラーをservice単位で収集し、他serviceの処理を続ける。失敗が残る場合の終了コードは非zeroとする。
- [R2] 同serviceのMarkdown／JSONをまとめて検証・保存し、書き込み失敗時は同serviceだけrollbackする。参照検証とread-only照合を維持し、modelや不足documentを推測・変更しない。
- [R3] 成功・失敗混在、document欠落、schema違反、保存失敗、参照と再実行をfocused checksで検証し、関連rule・promptを同期する。

## Acceptance checks

- [R1] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `changed:AGENTS.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`

## Allowed paths

- `tasks/active.md`
- `AGENTS.md`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/model_design.checks.py`
- `framework/rules/model-information.md`
- `framework/rules/detailed-design.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`

## Out of scope

- catalog、consumer repository、docs/modelの設計値、IaC、AWS API、deploy/apply、scenario、別taskの作成・実行。
- governance local loopとgit diff --checkを実行する。verification outputは完了報告だけに記載する。

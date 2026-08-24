# Codex Task: Require attribute meaning in Source / Comment

## Task contract

- Task type: `governance`
- Goal: 新規の詳細設計書で`Source / Comment`に各Propertyが設定・識別・制御する属性の意味を日本語で記載する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- `rules/detailed-design.md`を`Source / Comment`の記載規定の正本とする。
- 決定状態、決定主体、分類だけの説明、出典・経緯・証跡、Valueの無意味な言い換えを`Source / Comment`へ記載しない。
- generated current identifierにも属性の意味を記載し、`PENDING_DEPLOY`とdeploy成功後のcurrent value更新契約は維持する。
- 完成設計の出力前に全resource-detail rowを自己確認する指示を`prompts/chatbot/initial-service-design.md`へ追加する。

## Allowed paths

- `rules/detailed-design.md`
- `prompts/chatbot/initial-service-design.md`
- `tasks/active.md`

## Out of scope

- `docs/designs/**`
- `llm/designs/**`
- `llm/actuals/**`
- validator、script
- その他のprompt、rule、document
- table header、service ownership、table構造、row番号、JSON artifact契約の変更
- AWS resource changes
- IaC作成、validation、plan、deploy
- scenario作成、実行、結果更新

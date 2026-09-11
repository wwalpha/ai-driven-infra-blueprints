# ルール未設定のSecurity Groupの空表を省略

## Task contract

- Task type: `governance`
- Target: framework共通 / Security Group詳細設計の表示・model契約
- Goal: ルールがないSecurity Groupではヘッダーとalignmentだけの空ルール表を出力しない。SGの一覧情報・識別・参照・タグ設定は保持する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 詳細設計・modelルールとchatbot promptを更新し、ルール未設定のSGの空表を省略する。SGのanchorとheadingは一覧や他resourceからの参照先として維持する。
- [R2] 共通parserはルール表のないSGからも一覧属性と選択済みタグを生成し、ルールを補完しない。modelの識別・参照・値を保持する。
- [R3] ヘッダーだけの空表を検出し、ルール表省略・複数SG・タグの有無・model一致をfocused checkとlocal loopで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R3] `changed:framework/scripts/security_group_tables.checks.py`
- [R3] `check:framework.resource-layout`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/security_group_tables.checks.py`
- `CMD.md`

## Out of scope

- CMD.mdは開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- catalog/schema、SG以外の表示仕様、SGのタグ値・resource選択の追加または削除
- consumer同期、個別詳細設計・model実体・IaC、AWS操作、scenario

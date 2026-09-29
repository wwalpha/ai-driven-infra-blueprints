# リソース一覧Commentの用途説明を徹底

## Task contract

- Task type: `governance`
- Target: framework共通 / 詳細設計のリソース一覧
- Goal: ResourceNameを言い換えた定型文をCommentとして認めず、各resourceの機能・用途・役割を記載させる。

## Required changes

- [R1] 詳細設計ルールと設計promptにCommentの記載基準とSecurity Groupの具体例を明記する。
- [R2] 一覧Commentの定型的な言い換えをlocal validatorで拒否する。
- [R3] 拒否例と有効な用途説明のfocused checkを追加する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- target設計、model、IaC、AWS操作、scenario、catalogは変更しない。

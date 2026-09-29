# 詳細設計のリソース一覧に番号と説明を追加

## Task contract

- Task type: `governance`
- Target: framework共通 / resource overview
- Goal: 詳細設計の各リソース一覧表へ連番の`No.`列とリソース説明の`Comment`列を追加する。

## Required changes

- [R1] 全resource overviewのNo.とCommentの表示契約を設計ルールとchatbot手順に明記する。
- [R2] 通常一覧、IAM Role、Security Groupの解析・生成・検証を新しい列順へ対応させ、Commentをmodelへ重複保存しない。
- [R3] 一覧形式、連番、説明、policy再生成、Security Group modelのfocused checkを更新する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/policy_tables.py`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R3] `changed:framework/scripts/*.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/policy_tables.py`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/*.checks.py`

## Out of scope

- catalog、schema、target設計、IaC、AWS操作、scenarioは変更しない。

# 直接利用先のないIAM RoleのCloudFormation配置

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation IAM Role配置
- Goal: 直接利用するresourceがないIAM Roleを専用templateに配置できるようにする。

## Required changes

- [R1] IAM Roleの配置ルールと設計・実装手順を、直接利用先の有無に合わせて更新する。
- [R2] 設計で直接利用先がないと確認したRole専用templateだけを明示的な配置宣言で許可し、CloudWatch LogsとSecurity Groupの単独template禁止を維持する検証とfocused checkを更新する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R1] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- 特定targetの設計、model、IaC、AWS操作、consumer repositoryへの同期は行わない。

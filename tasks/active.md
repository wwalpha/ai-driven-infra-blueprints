# 全サービスのリソース一覧を3列化

## Task contract

- Task type: `governance`
- Target: framework共通 / 全serviceのリソース一覧
- Goal: 各リソース一覧を No.、ResourceName、Comment の3列に統一し、ResourceNameから詳細へ移動できるようにする。

## Required changes

- [R1] 共通設計ルール、サンプル、設計promptを3列形式にする。
- [R2] 一覧の生成・検証を3列形式にし、設定値とpolicyリンクを一覧から除く。
- [R3] Security Groupの一覧にしかない設計値を詳細側へ移し、model生成・検証を維持する。
- [R4] 変更をfocused checkで検証する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/detailed-design-samples.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/policy_tables.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/security_group_tables.py`
- [R3] `changed:framework/rules/model-information.md`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`
- [R4] `changed:framework/scripts/policy_tables.checks.py`
- [R4] `changed:framework/scripts/security_group_tables.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/policy_tables.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/policy_tables.checks.py`
- `framework/scripts/security_group_tables.checks.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/*.checks.py`

## Out of scope

- target設計、IaC、AWS操作、scenario、catalogは変更しない。

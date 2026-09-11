# Security GroupルールのPort列への集約

## Task contract

- Task type: `governance`
- Target: framework共通 / Security Group詳細設計の表示・model契約
- Goal: SG属性を一覧へ集約した構成とInbound／Outbound表記を維持し、ルール表のFromPort／ToPortを表示用のPort列へ集約する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 詳細設計・modelルールとchatbot promptにPort列を定義する。単一port・port範囲・ICMP type/code・未選択を同じ列で表し、FromPort／ToPortの表示列を廃止する。
- [R2] 共通parserでPortの表示値を正式catalog propertyのFromPort／ToPortへ展開する。既存のrule識別・親参照・inline ruleの要素境界と選択済みの値を保持する。
- [R3] Portの形式と廃止列を検証し、単一port・範囲・ICMP・未選択のmodel生成、既存modelとの一致をfocused checkとlocal loopで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/resource-layout.json`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/security_group_tables.checks.py`
- [R3] `check:framework.resource-layout`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/resource-layout.json`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/security_group_tables.checks.py`
- `framework/scripts/validate-blueprint.py`
- `CMD.md`

## Out of scope

- CMD.mdは元worktreeに開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- catalog/schemaの変更、SG以外の表示仕様変更、HTTP/HTTPSなどのType・サンプル値・region・未設計ルールの補完
- consumer同期、個別詳細設計や修正版Markdownの作成・変更、model実体・IaC、AWS操作、scenario

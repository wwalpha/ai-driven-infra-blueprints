# Security Groupの参照列と空詳細見出しを省略

## Task contract

- Task type: `governance`
- Target: framework共通 / Security Group詳細設計の表示・model契約
- Goal: rule tableのSourceSecurityGroupId／DestinationSecurityGroupId列を表示せず、ルールがないSGでは詳細見出しも省略する。SG参照、識別、タグ、model値は保持する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 詳細設計・modelルールとchatbot promptを更新し、SG参照列を非表示metadataへ移し、ルールがないSGの詳細見出しを省略する。
- [R2] 共通parserはDirectionの非表示metadataからSG参照を復元し、見出しのないルール未設定SGからも一覧属性・識別・VPC参照・選択済みタグを生成する。
- [R3] SG参照列・空見出しを拒否し、参照値・複数SG・タグ・model一致をfocused checkとlocal loopで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/security_group_tables.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/security_group_tables.checks.py`
- [R3] `check:framework.resource-layout`
- [R3] `check:framework.generated-service-model`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/security_group_tables.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/security_group_tables.checks.py`
- `CMD.md`

## Out of scope

- CMD.mdは開始前から存在する未追跡fileとしてscope検証上のみ許容し、内容を変更しない。
- catalog/schema、SG以外の表示仕様、SGの設計値・resource選択の追加または削除
- consumer同期、個別詳細設計・model実体・IaC、AWS操作、scenario

# Codex Task: Apply CloudFormation provider schemas

## Task contract

- Task type: `governance`
- Goal: 公式CloudFormation provider schemaをfull制約の正本として、既存properties選択リストと設計・template validationへ適用する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 東京regionの公式provider schema snapshot、provenance、lockをrepositoryへ追加し、既存propertiesの全pathをschemaへ対応付ける。
- [R2] propertiesを詳細設計対象の選択リストとして維持し、schemaにない項目とschema制約に違反するliteral値をlocal loopで拒否する。
- [R3] CloudFormation template validationでcfn-lintを必須化し、AWS validate-templateの構文検証と役割を分ける。
- [R4] Logs/Athenaの代表的な型、enum、pattern、required制約をfocused checkで固定する。

## Acceptance checks

- [R1] `check:framework.cloudformation-schema-catalog`
- [R2] `check:framework.schema-backed-design-validation`
- [R3] `check:framework.cfn-lint-validation`
- [R4] `changed:scripts/cloudformation_schema.checks.py`

## Allowed paths

- `README.md`
- `materials/cloudformation-schema/**`
- `materials/cloudformation-schema.properties`
- `materials/cloudformation-schema.sha256`
- `prompts/chatbot/initial-service-design.md`
- `prompts/codex/implement-infrastructure.md`
- `rules/cloudformation.md`
- `rules/detailed-design.md`
- `rules/loop-engineering.md`
- `scripts/check-deploy-context.py`
- `scripts/check-deploy-context.checks.py`
- `scripts/cloudformation_schema.py`
- `scripts/cloudformation_schema.checks.py`
- `scripts/validate-blueprint.py`
- `scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- `materials/aws/**`と既存catalog lockの変更
- project固有design、actual、IaC、scenario、scenario resultのmigration
- AWS API、deploy、apply
- 東京region以外のschema snapshot

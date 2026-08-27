# Codex Task: Import existing AWS configuration into detailed design

## Task contract

- Task type: `governance`
- Goal: chatbotが選択したresource type／propertyについて、Codexが既存AWS resourceの現在値をread-only取得し、詳細設計とservice modelへ直接差分反映できる汎用flowを定義する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] chatbotが外部作成済みresourceでは完成Markdownを出力せず、選択済みresource type／propertyを含むAWS取得用Codex反映依頼を生成する。
- [R2] design taskがresource候補のhuman選択後にread-only取得した現在値を詳細設計へ直接差分反映し、必要な非ARN identifierをobserved namespaceへ保存できるruleを定義する。
- [R3] deploy toolを要求せずtarget account／regionを検証できるread-only AWS context preflightを既存scriptへ追加する。
- [R4] generic flow、mutation禁止、secret／generated ARN禁止、Cloud Control API優先とservice API fallbackをvalidatorとfocused checksで検証し、利用手順を更新する。

## Acceptance checks

- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:AGENTS.md`
- [R2] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/rules/observed-values.md`
- [R2] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:framework/scripts/check-deploy-context.py`
- [R3] `changed:framework/scripts/check-deploy-context.checks.py`
- [R4] `changed:README.md`
- [R4] `changed:framework/prompts/README.md`
- [R4] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `AGENTS.md`
- `README.md`
- `framework/prompts/README.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/observed-values.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/check-deploy-context.py`
- `framework/scripts/check-deploy-context.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- VPC固有の取得処理またはservice別取得script
- CloudFormation/Terraform implementation、plan、deploy、apply
- 実AWS accountへのAPI実行
- 既存projectの詳細設計、model、IaC、scenarioの変更
- 外部作成者、管理者、resource出自の詳細設計またはmodelへの永続化

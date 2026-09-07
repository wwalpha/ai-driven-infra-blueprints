# CFn非対応のMacie Jobを詳細設計へ追加

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: CFn対応と詳細設計対象を分離し、Macie.ClassificationJobをAPI仕様に基づくcatalog、通常の詳細表、検証、generated modelで扱えるようにする。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 既存CFn catalogを維持し、公式API仕様を参照するMacie Jobの固定catalog/schemaとCFn非対応定義を追加する。
- [R2] Jobを通常のservice metadata、表示、詳細表、参照、desired/observed modelへ統合し、型・必須・条件付き設定を検証する。
- [R3] 設計prompt、設計・model・IaCルールと保守手順を整え、CFn非対応を実装完了と誤認しない境界を明記する。
- [R4] 正常なJob、誤設定、model同期、CFn型への誤変換拒否をfocused checksとlocal loopで確認する。

## Acceptance checks

- [R1] `exists:framework/materials/api/Macie_ClassificationJob.properties`
- [R1] `exists:framework/materials/api/Macie_ClassificationJob.json`
- [R1] `check:framework.api-design-catalog`
- [R2] `check:framework.resource-layout`
- [R2] `check:framework.generated-service-model`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/sync-model.py`
- [R3] `changed:framework/prompts/chatbot/service-design.md`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/cloudformation.md`
- [R3] `changed:README.md`
- [R4] `exists:framework/scripts/design_catalog.checks.py`
- [R4] `check:framework.schema-backed-design-validation`

## Allowed paths

- `tasks/active.md`
- `README.md`
- `framework/materials/api/Macie_ClassificationJob.properties`
- `framework/materials/api/Macie_ClassificationJob.json`
- `framework/materials/api-catalog.sha256`
- `framework/scripts/design_catalog.py`
- `framework/scripts/design_catalog.checks.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/rules/resource-layout.json`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/observed-values.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/loop-engineering.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/05_update.md`

## Out of scope

- 既存CFn catalog/schemaの変更、他のAPI resourceの追加
- consumer repositoryへの同期、個別targetの詳細設計やmodelの作成・移行
- Job作成の自動化、Custom Resource、IaC実装、AWS操作
- scenario、result、次taskの作成・実行

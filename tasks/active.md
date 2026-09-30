# CloudTrail全S3 bucket指定の表示対応

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudTrail DataResources表示・model生成・検証
- Goal: EventSelectors.DataResources[N].S3のValueに`All current and future S3 buckets`を許可し、正式なType/Valuesへ展開する。

## Required changes

- [R1] 全bucket指定と個別resource linkの表示・model生成ルールを定義し、設計生成promptへ反映する。
- [R2] 共通表示parserで全bucket指定を受け入れ、Type=`AWS::S3::Object`、Values=`["arn:aws:s3"]`へ展開する。既存のlink検証を維持する。
- [R3] 全bucket指定の検証・model生成、個別linkの維持、不正値の拒否をfocused checkで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`

## Out of scope

- catalog、project設定、target設計、generated model、IaC、AWS操作、scenarioは変更しない。
- Lambdaの全resource指定、AdvancedEventSelectorsの表示変更は行わない。

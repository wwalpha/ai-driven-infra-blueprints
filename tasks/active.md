# CodeCommit／CodePipeline詳細設計の表示見直し

## Task contract

- Task type: `governance`
- Target: framework共通 / CodeCommit・CodePipeline表示・model生成・検証
- Goal: RepositoryIdを非表示にし、CodePipelineのstage/actionとConfigurationを読みやすく表示し、CFn import式を実resourceへのlinkへ置き換える生成ルールを整備する。

## Required changes

- [R1] RepositoryId非表示、stage/actionの番号、Configurationのkey別表示、参照先resourceへのlink解決をruleと生成promptへ反映する。
- [R2] 共通parser、model生成とvalidatorを表示contractへ対応させ、catalogと既存の参照検証を維持する。
- [R3] 単一／複数action、Configurationの値・link、非表示identifierと不正表示をfocused checkで確認する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`

## Out of scope

- catalog、project設定、target設計、generated model、IaC、AWS操作、scenarioは変更しない。
- 実resourceの選択や未確定値を推測しない。別repositoryの設計移行は行わない。

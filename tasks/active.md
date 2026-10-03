# Description文字制約と実装前設計確認の補完

## Task contract
- Task type: `governance`
- Target: frameworkのschema-backed設計検証、03_implement手順と既存回帰コード
- Goal: IAM Role DescriptionとSecurity Group GroupDescriptionの異なるAWS文字制約を設計段階で検出し、実装開始前のread-only確認で不足事項をresource/property単位に集約する。

## Validation scope
- `framework`

## Required changes
- [R1] 公式仕様に基づき両propertyの文字制約を既存literal検証へ補完し、file・resource・property・違反理由を報告する。表示Commentを制限せず不正値を自動修正しない。
- [R2] 03_implementで対象と必要な依存先の設計、stack登録、template・parameter対応、参照、property制約をread-only確認し、不足をまとめて提示する。AWS API・IaC生成・deploy・変更scopeの自動拡張を禁止する。
- [R3] 不許可文字、許可英文、propertyごとの境界、日本語Comment、resource/property診断、不足集約と実装前確認手順を既存回帰へ追加する。

## Acceptance checks
- [R1] `changed:framework/scripts/cloudformation_schema.py`
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R1] `check:framework.schema-backed-design-validation`
- [R2] `changed:framework/prompts/codex/03_implement.md`
- [R3] `changed:framework/scripts/cloudformation_schema.checks.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/cloudformation_schema.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/cloudformation_schema.checks.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/prompts/codex/03_implement.md`
- `framework/rules/detailed-design.md`

## Out of scope
- 新しい汎用検証エンジン・依存パッケージ・承認工程、catalog更新、consumer同期、model・設計・IaC・project.json変更、AWS API、deploy/apply、commit、push、merge、別task。

## Completion
- 関連するcloudformation_schema.checks.pyとvalidate-blueprint.checks.pyを実行し、blueprint-loop.py --mode taskでgovernance必須local loopとframework回帰を完了する。実環境・全serviceへの検証scope拡張は行わない。

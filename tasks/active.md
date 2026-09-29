# リソース詳細Propertyの短縮表示を検証

## Task contract

- Task type: `governance`
- Target: framework共通 / リソース詳細のProperty列
- Goal: 見出しで分かるresource type接頭辞がProperty列に残る場合をlocal validatorで検出する。

## Required changes

- [R1] 共通設計ルールから正式表示の許容を削除する。
- [R2] 元のMarkdown行で見出しと同じresource type接頭辞を拒否し、統合された別resource typeを維持する。
- [R3] 短縮表示と拒否対象をfocused checksで検証し、既存fixtureを規則に合わせる。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/macie_bucket_tables.py`
- [R2] `changed:framework/scripts/design_layout.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/macie_bucket_tables.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/*.checks.py`

## Out of scope

- target設計、model、IaC、AWS操作、scenario、catalogは変更しない。

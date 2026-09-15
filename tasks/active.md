# 詳細設計PDFのページ構成と一覧番号

## Task contract

- Task type: `governance`
- Target: framework 共通 / 詳細設計PDFのページ構成とリソース一覧
- Goal: 表紙と目次を別ページにし、serviceごとに改ページして見出し下へ横線を引き、PDFのリソース一覧へNo.列を付ける。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] PDFの表紙・目次を分離し、serviceごとの改ページとservice見出し下の横線を追加する。
- [R2] PDF向けに生成するリソース一覧表へNo.列と行番号を追加する。
- [R3] 統合内容、番号と内部リンクをfocused checkで検証する。

## Acceptance checks

- [R1] `changed:framework/scripts/export-design-pdf.py`
- [R2] `changed:framework/scripts/export-design-pdf.py`
- [R3] `changed:framework/scripts/export-design-pdf.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/export-design-pdf.py`
- `framework/scripts/export-design-pdf.checks.py`

## Out of scope

- 既存の未commit Macie・S3表示変更、前taskのPDF出力実装とskill、未追跡 `CMD.md` を保持する。個別詳細設計、generated model、IaC、AWS操作、scenario、commit/pushには進まない。

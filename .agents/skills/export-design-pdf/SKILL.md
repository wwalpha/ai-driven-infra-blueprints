---
name: export-design-pdf
description: Use when exporting this AWS Blueprint repository's service-specific detailed design Markdown to a single PDF with internal links to the table of contents, resources, other services, and JSON appendices.
---

At the repository root, check `AGENTS.md`, [Markdown structure](../../../framework/rules/detailed-design.md#markdown-structure), [Resource-detail table](../../../framework/rules/detailed-design.md#resource-detail-table), [JSON design artifacts](../../../framework/rules/detailed-design.md#json-design-artifacts), and [Links and anchors](../../../framework/rules/detailed-design.md#links-and-anchors). Treat `docs/designs/**` already generated from models as PDF input; do not edit Markdown or `model/**` for PDF output.

Run `framework/scripts/export-design-pdf.py --output <PDFの絶対path>` with Python. Input is all service designs in `docs/designs/<environment>/<target-directory>/*.md`; JSON artifacts go into PDF appendices. The script converts existing anchors and links to unique references within the PDF. Pandoc, WeasyPrint, and Python `pypdf` are required. In Codex desktop, the Python returned by `load_workspace_dependencies` includes `pypdf`. If dependencies are missing in another environment, install them in an isolated environment and rerun; if installation is not possible, report the specific missing dependencies.

After output, render the PDF and check Japanese text, tables, and JSON appendix display; actually click links from the table of contents to distant headings, between services, and to JSON appendices. Mark complete only when both the script's PDF annotation check and visual check pass.

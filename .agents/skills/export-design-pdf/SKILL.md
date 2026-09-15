---
name: export-design-pdf
description: このAWS Blueprint repositoryのservice別詳細設計Markdownを、目次・resource・別service・JSON付録への内部リンクを持つ一つのPDFへ出力するときに使用する。
---

Repository rootで`AGENTS.md`と`framework/rules/detailed-design.md`を確認する。`docs/designs/**`を正本として保持し、PDF出力のためにMarkdownや`model/**`を編集しない。

Pythonで`framework/scripts/export-design-pdf.py --output <PDFの絶対path>`を実行する。入力は`docs/designs/<environment>/<target-directory>/*.md`の全service designで、JSON artifactはPDF付録に入る。scriptは既存anchorとlinkをPDF内の一意な参照へ変換する。Pandoc、WeasyPrint、Pythonの`pypdf`が必要。Codex desktopでは`load_workspace_dependencies`が返すPythonに`pypdf`が含まれる。ほかの環境で不足する場合は隔離環境に導入して再実行し、導入できなければ不足する依存関係を具体的に報告する。

出力後はPDFをrenderして日本語・表・JSON付録の表示を確認し、目次から遠い見出し、service間link、JSON付録へのlinkを実際にクリックして確認する。scriptのPDF annotation checkとvisual checkの両方が通った場合だけ完了とする。

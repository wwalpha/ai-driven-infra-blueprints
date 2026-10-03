---
name: issues
description: AWS Blueprintの指定environment・target・serviceの調査結果や検証エラーを、サービス別の番号付き問題一覧としてissues配下へ保存・更新するときに使用する。
---

# 問題の整理

本スキルの共通正本は`ai-driven-infra-blueprints`リポジトリで管理する。

依頼された範囲の問題を調査し、`issues/<environment>/<target-directory>/issues.md`へ保存する。実行ごとに同じファイルを更新する。AWS API、設計・model・IaC修正、deploy/applyは開始しない。

## 保存と更新

- 保存は`migration` taskとして扱う。変更前に`AGENTS.md`と`framework/rules/loop-engineering.md`を読み、最初のrepository変更として`tasks/active.md`を今回の対象・Goalへ切り替える。Validation scopeに今回対象のenvironment/target/serviceを明記する。Allowed pathsは`tasks/active.md`と今回対象の問題一覧ファイルだけとし、各Required changesにRequirement IDと対応する`exists:` Acceptance checkを記載する。
- この保存限定taskは既存issueによる停止判定の対象外となる。未解決issueがあっても調査と一覧の更新を続け、Issue remediationによる修復例外は追加しない。設計・model・IaC変更やAWS mutationには通常のissue gateが適用される。
- `docs/designs/<environment>/<target-directory>/`と同じ環境・target directory構成で保存する。複数targetは別ファイルに分け、必要なdirectoryだけ作成する。
- 既存ファイルがあれば読んでから今回の範囲を再確認し、その範囲の問題を最新の調査結果へ置き換える。解消を確認した問題は除去し、新規・継続する問題を記載する。未確認の問題は未確認と記載し、解消扱いにしない。今回対象外のservice・問題は保持する。
- ファイル冒頭に更新日時（Asia/Tokyo）と今回確認した範囲を記載する。未検証範囲があれば冒頭に明記する。対象targetの問題がなくなった場合もファイルを残し、`未解決issueなし`と確認範囲を記載する。履歴用・timestamp別ファイルは増やさない。
- 保存後は`python3 framework/scripts/blueprint-loop.py --mode local`を実行し、チャットには保存したファイルへのリンクと検証結果を報告する。検証失敗時も調査結果を保存したまま失敗を報告し、対象外の修正や別taskへ進まない。

## 対象の確認

- `project.json`と対象fileのpathで環境・targetを確認する。aliasがあるtargetはalias、ないtargetはAWS account IDを使う。
- serviceは対象設計のservice metadataで確認し、環境・aliasの異なる問題を同じblockへ混ぜない。
- 参照不整合は同じ環境・targetの現行`docs/designs/**`と対応する`model/**`のresource、名称、anchorを照合する。移動前のfileや別環境だけを見てresource不在と断定しない。
- 対象が不明なら質問し、別environment・target・serviceへ自動拡大しない。
- 実行失敗や比較不能は未確認として記録し、解消や「問題なし」と扱わない。
- 未deployのgenerated IDが`PENDING_DEPLOY`でも、設計の参照先が解決できれば参照欠落として扱わない。確認できていない事項は未確認と記載する。

## 出力

- H2を`環境／alias`、H3をservice名とし、その下に番号付きlistを置く。aliasがない場合のH2は`環境／AWS account ID`とする。
- service名がmodelのservice IDと異なる場合は`<!-- issue-service: <service-id> -->`を置き、issue gateが所属を確定できるようにする。
- 番号はservice blockごとに1から始め、1項目に1問題を記載する。空のblockは作らない。
- 各問題は対象resource・propertyと、何が不整合／不足／未確認かを具体的に短く書く。必要な判断が確認できた場合だけ、その未確定点を添える。
- 同じ環境・target・service内の同じ原因による反復診断はまとめ、件数と対象を記載する。診断件数とresource件数、派生エラーを混同しない。
- 問題一覧の根拠リンクは、保存先fileからの相対pathを使う。行番号はリンク先に付けず、`[athena.md:20](../../../docs/designs/dev/cde/athena.md)`のように表示文字列へ記載する。リンク先fileの存在と行番号を確認し、絶対pathは保存しない。pathにspaceがある場合はリンク先を`<...>`で囲む。
- 対応策・優先度は依頼された場合に追加し、問題一覧だけを求められた場合は一覧に絞る。

出力例（`issues/dev/cde/issues.md`）:

```markdown
# 問題一覧

更新日時: 2026-09-30 12:00:00 Asia/Tokyo
今回確認した範囲: dev／cdeのMacie

## dev／cde

### Macie

<!-- issue-service: macie -->

1. 個人情報用の旧bucket参照が切れており、現在のどの個人情報用bucketを対象にするか未確定。
2. 部門データ用の旧bucket参照が切れており、現在のどの部門別bucketを対象にするか未確定。

```

`dev／non-cde`の問題は`issues/dev/non-cde/issues.md`へ同じ形式で保存する。

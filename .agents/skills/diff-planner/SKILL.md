---
name: diff-planner
description: AWS Blueprintの必須指定された1 environmentについて、個別serviceまたはall serviceのdiff.md記載事項を修復する推奨案をPlan modeで調査し、ask question形式で方針を決めるときに使用する。修復は実行しない。
---

# diff.mdに基づく修復計画

共通正本は`ai-driven-infra-blueprints`リポジトリで管理する。`diff.md`に記載された差分・命名規則不一致・未確認事項の解消に向けて、根拠付きの修復案とhumanが選択した計画をチャットへ提示する。

## Plan modeと指定必須項目

- **Plan mode必須。** 実際のcollaboration modeを確認する。Plan modeでなければ対象調査を開始せず、このskillの要件を引用・リンクしてhumanへPlan modeへの切替を求める。skillの読み込みや「Plan modeとして扱う」という宣言ではmodeは変わらない。
- humanによるenvironment名の明示指定を必須とし、1回の実行は1 environmentだけに限定する。未指定、複数環境、全環境の指定ならask questionで1 environmentの選択を求め、回答まで対象調査を開始しない。path、既存契約、唯一のenvironmentから推測せず、環境ごとのtaskへの自動分割・順次実行もしない。
- 対象serviceは、humanが明示した1件以上のservice ID、または`all service`／全サービスのどちらかを必須とする。未指定ならask questionで確認し、全serviceへ自動拡大しない。
- `project.json`で指定environmentを、選択targetのmodel入口でservice IDを確認する。target directoryは確定済みalias、aliasなしはAWS account IDを使う。environmentに複数targetがあり対象が未指定ならask questionで選択を求める。targetが1件ならそのtargetを使用できる。
- 修復先は指定environment内だけ。diff.mdに記載された比較元environmentは、基準値・resource対応の確認に必要な読み取り専用の根拠としてだけ参照し、修復先・変更計画・Validation scopeへ含めない。比較元の指定は修復対象の複数環境指定とは区別する。

## 読み取り専用の調査

1. `AGENTS.md`、[issue-gate](../../../framework/rules/issue-gate.md)、[Model authority](../../../framework/rules/model-information.md#model-authority)と[Properties format](../../../framework/rules/model-information.md#properties-format)、[Markdown structure](../../../framework/rules/detailed-design.md#markdown-structure)と対象resourceの表示・参照section、[resource naming](../../../framework/rules/aws-resource-naming.md)と[env-diffの比較](../env-diff/SKILL.md#比較)と[AIによる整理](../env-diff/SKILL.md#aiによる整理)を読む。env-diffは比較・分類規約の参照に使い、このskillから実行・保存taskを開始しない。
2. 選択targetの`issues/<environment>/<target-directory>/diff.md`と`issues.md`を読む。diff.mdがない、比較元・比較先・targetが不明、指定environmentが修復先と一致しない場合は不足を質問する。比較組や対応targetを推測せず、diff.mdを自動作成・更新しない。
3. 個別指定では該当serviceの項目だけを扱う。`all service`では選択targetのdiff.mdに掲載された全serviceを対象とし、実際のservice ID一覧を示す。掲載のないserviceの調査・修復へ広げず、掲載がないことを検証済み一致とも扱わない。該当項目がなければその事実を報告して終了する。
4. 該当項目を現在の`model/<environment>/<target-directory>/<service-id>.properties`と照合する。既存readerで入口indexと必要なpartを一つの論理serviceとして読み、`desired.*`を正本とする。比較元はdiff.mdに明記された組・targetだけ参照し、古い報告、意図的な環境差、実際の設計差、未確認・比較不能を分ける。resource対応や不足値を推測しない。
5. env-diffのIMPORT除外・許容された環境差異・命名／参照確認に従う。比較元を基準としつつ、名称・account・region・参照先は修復先の確定済み値に合わせる案を示す。比較元の実名・ID・ARNをそのままコピーしない。権限差は対象resourceと必要性を確認してから修復案に含める。
6. 各項目について対象resource／property、現状と基準、根拠file、推奨する変更内容、影響、未確定値を確認する。model修復だけで済むか、IaC修正も必要かは既存IaCを読み取り専用で確認して区別する。AWS現在値は取得せず、AWS反映の必要性・実状態は未確認として扱う。
7. 最新issues.mdで未解決issueを確認する。diff.mdの項目自体は未解決issueではない。未解決issueがあるserviceでは通常の設計相談を進めず、issue調査とhumanが明示した修復範囲に限定する。対象外issueがblockerならその修復を先行する必要を示し、通常変更を承認待ちの計画へ混ぜない。保存限定taskの免除をmodel／IaC修復へ流用しない。

## 推奨案をask questionで提示

- 調査後、判断が必要な差分ごと、または同じ理由・同じ修復方針のまとまりごとに`request_user_input`で質問する。1回に1〜3問、各問に2〜3個の相互に区別できる選択肢を置く。推奨案を先頭にし、label末尾に`(Recommended)`を付け、descriptionに変更内容と影響・判断理由を短く示す。
- 推奨案は、確認済みの比較基準・命名規則・修復先の用途・影響から決める。選択肢は「修復先のmodelを基準へ合わせる」「環境差として維持する」「不足情報の確認まで保留する」など、その項目で根拠のあるものだけを使う。humanが既に確定した方針は再質問しない。
- 欠けた環境・service・targetやresource対応の確認も同じask question形式を使う。選択候補は現行project／modelで確認できる値だけとし、3件を超える候補や未確定の具体値は質問本文に候補・必要情報を示して自由入力で受ける。存在しない候補を作らない。
- 推奨を先頭に置くことは回答・承認ではない。回答が必要な判断は未決定として保持し、無回答・timeoutを推奨案への同意として扱わない。後続の独立した読み取り専用調査は続けてよい。
- 回答を計画へ反映する。回答が不足値や前提を変えた場合はその範囲だけ再調査する。選択した修復案への回答は修復実行、AWS API、deploy/applyの許可とは扱わない。

## 計画の提示と終了

- 最終計画は、指定environment／target／service、humanが選んだ方針、resource／propertyごとの修復内容と確定値、変更予定の具体的path、依存関係・作業順、必要な生成・検証、未決定事項を簡潔に示す。`all service`も実際のservice IDへ展開し、別environmentを修復先へ混ぜない。
- model修復、IaC修正、AWS反映を別の実行範囲として示す。model修復案は正本propertiesを先に変更してservice単位で`sync-model.py --write`によりMarkdown／JSONを生成し、修復を確認してから該当diff.md項目だけ更新する手順とする。報告だけが古い場合は再比較・分類後のdiff.md更新案とし、未修復の差分を報告から消す案にしない。
- 未確認・比較不能は確認方法と必要なhuman判断を示し、修復済みと扱わない。対象外serviceの報告と未解決issueを保持する手順を示す。将来のrepository変更では対象task typeの契約登録・具体的file予約・issue gate・scoped local loopが必要なことを計画へ含める。
- このskillは読み取り専用の計画で終了する。契約登録、diff.md／issues.md／model／生成物／IaCの変更、生成command、local loop、AWS API、deploy/apply、scenario、別taskの作成・実行を行わない。計画の保存・修復実行はhumanの別の明示依頼で扱い、Plan modeを終了しても自動実行しない。

読取規則はAGENTS.mdの「必要な規則の読み方」に従う。targetの確定・account／profile検証には[project-configuration](../../../framework/rules/project-configuration.md)、停止・調査／修復／保存の例外判定には[issue-gate](../../../framework/rules/issue-gate.md)を読む。このskillでは契約・local loopの文書を読み込まず、計画だけで終了する。

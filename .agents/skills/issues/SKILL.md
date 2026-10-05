---
name: issues
description: AWS Blueprintの指定environment・target・serviceをローカルで調査・検証し、問題一覧をissues配下へ保存・更新するとき、または提示済みの調査結果を保存するときに使用する。AWS APIチェックはaws-check skillで扱う。
---

保存・修復の契約登録は[task-contract](../../../framework/rules/task-contract.md)に従う。


# 問題の整理

本スキルの共通正本は`ai-driven-infra-blueprints`リポジトリで管理する。

依頼された範囲のローカル調査結果・検証エラーを、`issues/<environment>/<target-directory>/issues.md`へ保存する。実行ごとに同じファイルを更新する。AWS APIチェック、SDKによる現在値取得・比較は本skillに含めない。AWSチェックの依頼は[aws-check](../aws-check/SKILL.md)で扱い、issuesの実行から自動で開始しない。設計・model・IaC修正、deploy/applyは開始しない。

別途取得・調査済みのAWSチェック結果の保存が依頼された場合は、その結果を根拠として扱い、AWS APIを呼ばずに一覧へ反映する。ローカル検証だけでAWS現在値の一致・問題解消を確認したとは扱わない。

## 保存と更新

- 保存は`migration` taskとして扱う。変更前に`AGENTS.md`と[loopのLocal loop](../../../framework/rules/loop-engineering.md#local-loop)を読み、最初のrepository変更として`tasks/<task-name>.md`を今回の対象・Goalで新規登録する。Validation scopeに今回対象のenvironment/target/serviceを明記する。Allowed pathsは`tasks/<task-name>.md`と今回対象の問題一覧ファイルだけとし、各Required changesにRequirement IDと対応する`exists:` Acceptance checkを記載する。
- この保存限定taskは既存issueによる停止判定の対象外となる。未解決issueがあっても調査と一覧の更新を続け、Issue remediationによる修復例外は追加しない。設計・model・IaC変更やAWS mutationには通常のissue gateが適用される。
- `docs/designs/<environment>/<target-directory>/`と同じ環境・target directory構成で保存する。複数targetは別ファイルに分け、必要なdirectoryだけ作成する。
- 既存ファイルがあれば読んでから今回の範囲を再確認し、その範囲の問題を最新の調査結果へ置き換える。解消を確認した問題は除去し、新規・継続する問題を記載する。具体的な不整合・不足を検出済みで解消が未確認の問題は、未確認と記載して保持する。未検証範囲だけを新しいissueとして登録しない。今回対象外のservice・問題は保持する。
- ファイル冒頭に更新日時（Asia/Tokyo）と今回確認した範囲を記載する。未検証範囲があれば冒頭に明記する。対象targetの問題がなくなった場合もファイルを残し、`未解決issueなし`と確認範囲を記載する。履歴用・timestamp別ファイルは増やさない。
- 保存後は`python3 framework/scripts/blueprint-loop.py --mode local`を実行し、チャットには保存したファイルへのリンクと検証結果を報告する。検証失敗時も調査結果を保存したまま失敗を報告し、対象外の修正や別taskへ進まない。

## 対象の確認

- `project.json`と対象fileのpathで環境・targetを確認する。aliasがあるtargetはalias、ないtargetはAWS account IDを使う。
- serviceは対象設計のservice metadataで確認し、環境・aliasの異なる問題を同じblockへ混ぜない。
- 参照不整合は同じ環境・targetの現行`docs/designs/**`と対応する`model/**`のresource、名称、anchorを照合する。移動前のfileや別環境だけを見てresource不在と断定しない。
- 対象が不明なら質問し、別environment・target・serviceへ自動拡大しない。
- 実行不能や比較不能は、check・対象・具体的errorを未検証範囲として記録し、AWS resourceの問題へ推測で置き換えない。実行済みcheckが検出した具体的なvalidation errorはissueとして記録し、未実行のcheckを成功扱いにしない。
- 未deployのgenerated IDが`PENDING_DEPLOY`でも、設計の参照先が解決できれば参照欠落として扱わない。今回確認できていない事項は未検証範囲へ記載する。

## issue登録の判定

- 番号付きissueは、対象resource・propertyに対する具体的な不整合、適用ルール違反、必須設計値の不足、または指定checkの再現可能な失敗を根拠付きで確認した場合だけ登録する。今回AWS APIや動作を調べていないこと、任意の実装注記、account/regionの文字列差だけを問題の根拠にしない。未検証範囲は冒頭の通常文章にまとめ、service配下の番号付きissueと分ける。
- humanが対象・構成・動作を確認済みと明示した事項は、確認範囲と根拠がhuman確認であることを冒頭に保持する。反証となる具体的な診断がなければ未確認として再掲しない。human確認を今回のAWS API実行や未実行checkの成功に置き換えず、無関係な既存issueは除去しない。
- ARNは`framework/rules/observed-values.md`と`model-information.md`に従い、generated current ARNと既存またはhuman-provided design inputを区別する。文字列が実ARNであることやdesired注記に含まれることだけでgenerated ARNと断定しない。禁止対象への該当根拠が不足する場合は確認範囲の限界として記載し、規則違反issueを作らない。generated ARNの保存禁止は維持する。

## 命名規則の確認

ローカル調査を行う場合は、[aws-resource-naming](../../../framework/rules/aws-resource-naming.md)、[Model authority](../../../framework/rules/model-information.md#model-authority)と[Properties format](../../../framework/rules/model-information.md#properties-format)、[Markdown structure](../../../framework/rules/detailed-design.md#markdown-structure)と対象resourceの表示・参照sectionを読む。local loopの命名診断だけではpatternへの適合確認を完了扱いにしない。調査済み結果の保存だけを依頼された場合は再調査を自動追加せず、命名確認の未実施範囲を明記する。

- 対象serviceの正本propertiesを入口indexとpartを合わせて読み、`desired.*`の選択済み名称property、必須`.Name`、必須またはhuman-selectedな`Name` tagを確認する。診断に出た名称だけへ限定せず、独立した子resourceも自身のresourceModeで判定する。observed値や生成Markdownの表示labelを名称の正本にしない。
- CREATE（mode未指定を含む）はresource typeと正式propertyを命名ルールのNaming targetへ対応付け、coverage、pattern、service固有制約、必須Nameの有無を確認する。`environment`、`target_alias`、`account_id`、`region`は`project.json`の対象targetへ、application・purpose等はhuman-confirmedなcomponentへ照合する。名称の文字列から未知componentを推測して適合扱いにしない。
- IMPORTにはframework命名convention・coverage・mandatory Name policyを適用しない。propertyごとの適用除外とhumanが明示した命名例外は、根拠と適用scopeを確認して尊重する。coverageだけの除外をpatternや値検証の除外へ拡張せず、env-diffだけの例外をissuesへ自動適用しない。AWS生成ID・ARN・DNS名・IP・表示labelへ名称patternを適用しない。provider schema、catalog、参照、確定値の検証は維持する。
- 適用対象の不一致、命名ルール未登録、必須Nameの欠落は対象resource・property・実値と該当ruleを根拠に問題へ記録する。componentや例外の根拠不足、読込・検証失敗は不足する確認を具体的に示して`未確認`とし、`問題なし`や解消扱いにしない。
- 参照値は同じenvironment・targetのdesired参照先を解決し、名称propertyと区別する。参照先serviceが調査対象なら命名不一致は参照先serviceへまとめる。対象外serviceは参照解決に必要な情報だけを確認し、命名調査へ自動拡大しない。名称の補正、rename、tag追加、model変更は行わない。

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

読取規則はAGENTS.mdの「必要な規則の読み方」に従う。targetの確定・account／profile検証には[project-configuration](../../../framework/rules/project-configuration.md)、停止・調査／修復／保存の例外判定には[issue-gate](../../../framework/rules/issue-gate.md)を読む。repository変更時だけ[task-contract](../../../framework/rules/task-contract.md)と[Local loop](../../../framework/rules/loop-engineering.md#local-loop)と[Validation scope](../../../framework/rules/loop-engineering.md#validation-scope)、[Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion)を追加する。

framework変更時だけ[Framework regression](../../../framework/rules/loop-engineering.md#framework-regression)を追加で読む。

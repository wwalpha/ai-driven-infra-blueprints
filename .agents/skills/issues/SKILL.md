---
name: issues
description: AWS Blueprintの指定environment・target・serviceの調査結果や検証エラー、propertiesとCloudFormationの不一致を、サービス別の番号付き問題一覧としてissues配下へ保存・更新するときに使用する。
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

## properties／CloudFormation比較

CloudFormation targetの問題調査では、既存のlocal validationと別に次のread-only比較を毎回実行する。既存のmodel reader、catalog、CFn decoderを使うため、検証用Pythonに`cfn-lint`のPython moduleが必要。利用できない場合は検証環境不足として記録し、合格にしない。

```text
python framework/scripts/check-model-cfn.py --environment <env> --target-directory <alias-or-account-id> --service <service-id>
```

- `--service`は依頼された各serviceについて繰り返す。複数targetはtargetごとに実行する。Terraform targetにはCFn比較を適用しない。
- 正本`cloudformation-stacks.properties`からstack・template・parameterを選び、target固有parameter/defaultを適用したCFnとservice modelの`desired.*`を比較する。共用templateを別environmentのparameterで評価しない。Markdownやobserved valueを設計値の代わりにしない。
- JSON結果の`findings`をservice別に問題一覧へ反映する。`mismatch`は不一致、`unverified`は比較不能・未確認として明記する。exit 0は比較範囲の完了、exit 1は不一致／比較不能、exit 2は入力・実行環境などの検証失敗。`NOT_APPLICABLE`は比較対象なしであり全体一致ではない。
- 比較不能の原因をツール未対応、入力不足、resource対応不明へ分ける。humanが修復を依頼した場合はその明示scopeで原因を修復して同じenvironment/target/serviceを再比較する。未確定parameterは推測しない。`unverified`を`mismatch`へ付け替えたり、一覧から除去しただけで修復・同期完了としない。
- 全宣言stackの型coverageが完全な場合、必要型のactive resourceが0件、または同型候補すべての確定名称が設計の名称と異なることを根拠付きで欠落と判定できる。結果の`coverage`にlocal targetの調査stack、`expected`に必要型・名称、`actual`に候補名称とCFn位置を保持する。これはlocal CFnの未実装・名称差の確認であり、AWS実体の不在や修復済みを意味しない。型coverage不明、generated name、未確定名称、条件評価失敗、複数候補は比較不能を維持する。根拠付き欠落を特定した件数と一致確認・修復件数を分けて報告する。
- 承認済み`desired.*`とCFnの不一致は、根拠を確認した上で明示されたinfrastructure修復taskでCFn側を修正し、再比較する。今回の比較範囲の一致確認には、command全体と対象`service_results`が`PASS`、`findings`と`stack_findings`が空、対象serviceの`checked_properties`が1以上であることを要求する。併せて対象限定local loopでmodelと生成Markdown／JSONの一致を確認する。入力不足や曖昧な対応が残れば未完了と報告し、`NOT_APPLICABLE`・一部項目だけの成功で同期完了としない。この確認は選択済み設計値とlocal CFnの一致であり、AWS実体への反映確認は許可されたdeploy taskの成功確認が別途必要。
- stack読込み・Export・Conditionの失敗は`stack_findings`に残り、他stack・serviceの比較は継続する。`service_results`の成否と検証件数をserviceごとに確認する。stack失敗の影響が特定できない場合も比較済みと扱わず、一覧冒頭にstack名・根拠・比較不能範囲を保存する。stack診断だけが残る場合も「問題なし」としない。
- 検知対象はresource対応・型・余分なresource、選択済みliteralとparameter値、配列の値・順序・件数、`.Name`→Name tag、正本`document`内のpolicy JSON、基本的なresource参照。`!Ref`・`!GetAtt`はresourceと属性を、`!ImportValue`は同targetのlocal Output/Exportを照合する。AWS上にしかないExportは取得せず比較不能とする。
- `!FindInMap`はlocal Mappingsと確定parameter／pseudo parameterを使って評価する。nested lookupと明示DefaultValueも評価し、mapping欠落・未解決key・不正な式は比較不能として残す。Transformを必要とするtemplateは引き続き比較不能となる。
- `AWS::Partition`はtarget regionから通常AWS、中国、GovCloudのpartitionを解決する。KMS Aliasへの名称参照はAliasNameで比較し、Aliasの省略されたTargetKeyIdはmodelのparentReferenceから照合する。Keyのlogical IDが異なる場合は所属Aliasの一意なTargetKeyIdで対応を確認する。identityなしのS3 BucketPolicy／SubnetRouteTableAssociationは、包含する親への参照で対応を確認して選択済み設定を比較する。一意に対応しない候補や未対応partitionを推測で一致にしない。
- S3の設計用Regionはproject.jsonのtarget regionと比較する。resourceの名称対応ではcatalogの生成outputを除外する。確定Nameを返すRefはlocal値へ解決する。policy内のCondition objectをCFn Condition参照として評価せず、modelのdocument内のCFn式も同じtarget・stack条件で評価してから比較する。暗号化のKmsKeyId／KMSKeyId／KMSMasterKeyIDではlocal AliasのTargetKeyIdを照合し、同一KeyへのAlias・Ref・Arnを区別して不一致にしない。外部Aliasや未確定のphysical IDを推測で対応付けない。
- 確定したS3 BucketName／LogGroupNameから得られるArnは処理中だけ評価してliteralと比較し、modelへ保存しない。未解決の生成値とliteralの差、同じresourceの未正規化attribute差、PENDING_DEPLOY等の未確定値だけではmismatch／一致と断定しない。比較できた別の値・key・件数に確定した差があればmismatchを維持する。比較不能には理由と評価途中の両側の値を付け、判定できなかったpropertyをchecked_propertiesへ数えない。
- IMPORTとCFn非対応API型は`excluded`へ明示される。未知型、曖昧なresource対応、未対応式、JSON正本不足、一意に対応できないgrouped resourceは比較不能として残る。チェックがPASSでも、CFnの全未選択設定や全組み込み関数を検証済みとは報告しない。追加の調査が必要なら依頼範囲内で根拠を確認し、自動比較結果を黙ってPASSへ書き換えない。
- 同じ不一致を毎回AIで再判定せず、このチェック結果を根拠にする。AIは原因の整理と、依頼された場合の対応案に使う。

## 出力

- H2を`環境／alias`、H3をservice名とし、その下に番号付きlistを置く。aliasがない場合のH2は`環境／AWS account ID`とする。
- service名がmodelのservice IDと異なる場合は`<!-- issue-service: <service-id> -->`を置き、issue gateが所属を確定できるようにする。
- 番号はservice blockごとに1から始め、1項目に1問題を記載する。空のblockは作らない。
- 各問題は対象resource・propertyと、何が不整合／不足／未確認かを具体的に短く書く。CFn比較では設計値とCFn値を併記する。必要な判断が確認できた場合だけ、その未確定点を添える。
- 同じ環境・target・service内の同じ原因による反復診断はまとめ、件数と対象を記載する。診断件数とresource件数、派生エラーを混同しない。
- CFn比較の根拠はJSON結果の`model`・`cfn`のpathと行番号から確認する。
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

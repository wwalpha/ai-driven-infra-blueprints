---
name: aws-check
description: AWS Blueprintの指定environment・target・serviceのdesired propertiesとAWS現在値を、read-only AWS APIと既存SDK比較programでチェックし、検出された差分・未確認事項を調査するときに使用する。
---

# AWS APIチェック

共通正本は`ai-driven-infra-blueprints`リポジトリで管理する。AWS APIによる現在値取得・比較を担当し、ローカル検証と問題一覧の保存は[issuesの保存と更新](../issues/SKILL.md#保存と更新)と[出力](../issues/SKILL.md#出力)で扱う。

## 対象と実行許可

- `AGENTS.md`、[issue-gate](../../../framework/rules/issue-gate.md)、[Model authority](../../../framework/rules/model-information.md#model-authority)と[Properties format](../../../framework/rules/model-information.md#properties-format)を読み、依頼されたenvironment/target/service/resourceだけを対象とする。target directoryは`project.json`のalias、aliasなしは`awsAccountId`を使う。対象不明なら確認し、推測で拡大しない。
- read-only調査とchatでの報告だけならrepository taskを開始せず、比較JSONは必要に応じてrepository外の一時fileへ保存する。AWSチェックの依頼で許可されたlist/get/describe相当のAPIとcaller identity検証だけを実行し、AWS mutationは行わない。
- `project.json`の`awsProfile`・regionと実行account（`awsExecutionAccountId`、未指定時は`awsAccountId`）を既存comparatorで検証する。設定profileと異なる明示profile、caller account不一致、認証失敗では停止し、別profile/accountへのfallbackを行わない。
- 問題一覧の保存・更新も明示された場合は、AWS取得前に[issuesの保存と更新](../issues/SKILL.md#保存と更新)に従う`migration`契約へ調査対象とread-only API許可を記載する。Allowed paths／Modified filesは今回の契約と対象issues.mdだけとし、同じ契約で調査・保存・local loopまで行う。未解決issueがあってもissue調査のread-only操作と保存限定taskの免除条件は維持する。

## SDK比較を起点にする調査

- 通常のpropertiesとAWS現在値の比較は`framework/scripts/check-model-aws.py`で行う。Python＋AWS SDKで取得・比較を完結し、AIで全serviceを毎回読み合わせない。program自体からAIやissue保存を呼び出さない。
- `desired.*`が期待値の正本である。SDK取得で実体を特定し、`observed.*`は確認済みidentifierの参照にだけ使う。MarkdownやCFnを期待する設定値へ代用しない。
- 実運用のAWS取得は、今回の依頼で対象environment/target/service/resourceと必要なread-only APIの取得許可を確認してから実行する。保存を伴う場合は同じ調査taskのactive contractにも明記する。`--all`は全対象の取得許可が明示された場合だけ使う。設定profileの変更や認証失敗時のfallbackをしない。
- 単一対象の比較例: `python3 framework/scripts/check-model-aws.py --environment dev --target cde --service s3`。全対象は明示`--all`、接続なしの対応範囲確認は`--all --coverage`。比較用依存は`framework/scripts/requirements-aws-compare.txt`に従う。
- 同一environment/targetで今回の依頼・active taskの調査scopeに複数serviceが含まれる場合は、可能な限り`--service`を繰り返して1回の実行へまとめる。例: `python3 framework/scripts/check-model-aws.py --environment dev --target cde --service s3 --service iam --service kms`。service別のcommand実行をデフォルトにしない。
- batch化を理由に調査scopeを拡大しない。S3だけが許可された依頼へIAM/KMSを追加せず、既存のAWS read-only API scope、Task Contract、Validation Scopeを維持する。Performance optimization must not expand task scope.
- JSONの`difference`／`resource_missing`にあるresource・keyだけを起点に、AIが関連する正本properties、CFn、AWS実体を調査する。共通原因の取得失敗は`affectedKeys`と`scope`を一つの未確認事項へまとめ、propertyごとに複製しない。`design_unresolved`、`sdk_unavailable`、`unimplemented`、`acquisition_failed`は一致扱いにしない。
- 終了codeは0が全件一致、1が差分あり、2が検証未完了である。2には判明した差分も含まれ得る。`identifier`はresource特定用、`local_metadata`はSDK設定比較の対象外である。取得不能が残る結果を全体一致と報告しない。
- 問題一覧の保存・更新も依頼された場合は、同じresource・keyの差分を調査済みなら既存issueを利用する。関連properties・CFnの内容または取得AWS値が変化したときだけ再調査する。各根拠の内容hashとAWS比較値（秘密値を除く）を確認できる形で記載し、未確認の既存issueを解消しない。
- 差分調査の報告にはproperties・CFn・AWSの3者の値、modelのfile/行とJSONの取得API、CFnの根拠位置、確認できた原因、必要な対応を記載する。3者のいずれかを確認できなければ未確認とする。AWSとの差だけでCFn修正が必要と断定しない。秘密値・認証情報は記載しない。
- 調査・比較・issue保存だけで設計変更、CFn修正、deployへ進まない。修復はhumanが明示した別の修復scopeで行う。旧properties↔CFn設定の自動比較は実行・再実装しない。

## 結果の扱い

- chatへ比較範囲、差分、未確認事項と実行結果を報告する。問題一覧の保存を依頼されていなければ`issues.md`を変更しない。
- 保存も依頼された場合だけ[issuesの保存と更新](../issues/SKILL.md#保存と更新)と[出力](../issues/SKILL.md#出力)の形式と更新規則を使い、取得済みの結果・調査根拠を同じtaskで保存する。issuesからAWS APIを再実行しない。
- modelのdesired/observed、設計、IaCを変更せず、deploy/apply、scenarioや別taskへ進まない。

読取規則はAGENTS.mdの「必要な規則の読み方」に従う。targetの確定・account／profile検証には[project-configuration](../../../framework/rules/project-configuration.md)、停止・調査／修復／保存の例外判定には[issue-gate](../../../framework/rules/issue-gate.md)を読む。repository変更時だけ[task-contract](../../../framework/rules/task-contract.md)と[Local loop](../../../framework/rules/loop-engineering.md#local-loop)と[Validation scope](../../../framework/rules/loop-engineering.md#validation-scope)、[Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion)を追加する。

framework変更時だけ[Framework regression](../../../framework/rules/loop-engineering.md#framework-regression)を追加で読む。

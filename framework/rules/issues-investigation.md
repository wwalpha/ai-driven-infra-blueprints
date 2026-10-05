# Local issues investigation

## Scope and responsibilities

issuesだけのローカル入口は`framework/scripts/issues_scan.py`。同一environment/targetの複数serviceを一processで処理する。実案件のmodel・生成設計・IaCはread-only。AWS API/SDK、change set、Terraform init/plan/provider取得、deploy、scenarioへのfallbackはない。implement/deploy/updateや保存後loopへ新比較を追加しない。

通常issueは`issues/<environment>/<target-directory>/issues.md`、model desired → IaC差分は`iac-issues.md`、環境間比較は従来の`diff.md`。通常gate実装・service所属形式・停止判定は不変。IaC差分だけでは失敗終了、通常issue登録、suspend、Issue remediation要求をしない。既存validatorのschema・model/Markdown一致・参照・policy・account/region等の診断と保存後local loopは維持する。

## Read and review

AGENTS.mdのsection読取規則を適用する。issues skillの命名確認で指定する共通rule、対象namespace rule、Model authority/Properties format、Markdown structure、対象resourceの表示/参照ruleを適用する。必須ruleを省略するためのscanではない。

| 機械checkで行うもの | LLMに残すものと入力 |
| --- | --- |
| project topology、scope、model/index/part構文・行数 | scopeは明示値。曖昧な診断のservice所属だけ確認する |
| 既存service validator、生成Markdown/JSON一致、catalog/schema、参照、policy、observed保存禁止 | 具体的診断の意味・対応が不明な既存issue。必要時だけdiagnostic詳細/resourceを追加取得 |
| 命名coverage・必須Name・既存の名称値check | 全resourceの名称pattern、human-confirmed component、human例外と適用scope。エラー名だけ/代表例だけを確認しない |
| IaCの正式type/ID/stack対応、確定値と対応可能式の比較 | 機械差分の文章再生成は行わない。未比較を全文比較やAWSへ送らない |
| scope限定report整形・排他・保存・入力fingerprint | 根拠付き追加通常issue、明示再検証した既存issueの解消指定 |

`scan`のstdoutはsummary、共通target context/rule、全名称、残る判断材料、未比較/errorの理由。大きい差分・全一致・詳細診断はrepository外の同一実行artifactへ置く。`detail`で必要sectionだけ読む。通常issue候補が多い場合も機械結果はPythonが保存し、LLMへ全件の文章化を要求しない。名称は独立子resourceのmodeを使い、inline設定は親mode。IMPORT、Name tag必須条件、human例外、対象外参照先の調査scopeを拡大しない。unknown componentを名称から推定しない。

全`naming.names[].id`をreviewし、欠落/未知component/pattern不適合/明示例外を区別する。service共通の`desired.note.*`、row comment、既存human確認、機械化されない設計proseは判断材料として残る。情報不足は該当modelの`model_files.py --resource`または該当rule/sectionだけ追加取得する。材料不足で適合・問題なし・既存issue解消としない。

## Commands

以下の`python3`はcfn-lintをimportできる既存local validation runtimeを使用する（decoder不足は処理error）。scan前にfull loopを追加しない。

```console
python3 framework/scripts/issues_scan.py scan --environment dev --target-directory cde --service s3 --service iam --artifact /tmp/issues-scan.json
python3 framework/scripts/issues_scan.py detail --artifact /tmp/issues-scan.json --section ordinary --offset 0 --limit 50
python3 framework/scripts/issues_scan.py --task-file tasks/save-local-issues.md save --artifact /tmp/issues-scan.json --review /tmp/issues-review.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/save-local-issues.md
```

scope/targetは例示値を実際の明示scopeへ置き換える。task契約は保存前に最初のrepository変更として登録し、`migration`、明示service Validation scope、今回の契約と保存するreportの正確なAllowed paths/Modified files、`exists:` Acceptance checkを宣言する。

review JSONは最小の判断結果だけ（大きいscan JSON/reportをコピーしない）:

```json
{
  "reviewed_names": ["全名称材料のid"],
  "reviewed_judgments": ["全残判断材料のid"],
  "diagnostic_assignments": {"所属未確定診断id": "service-id"},
  "issues": [{"service": "s3", "message": "resource/property、具体的問題と根拠", "source": {"path": "model/dev/cde/s3/part-001.properties", "line": 12}}],
  "resolved": [{"id": "既存issue材料のid", "reason": "明示された修復scopeでの解消理由", "evidence": "実施済み再検証の根拠"}]
}
```

空の追加/解消/assignmentは省略できる。全名称・残判断idのreviewをsaveが要求する。通常のcomponent根拠不足等は`issues`へ具体的な未確認事項を記録し、human確認を未実行AWS checkの成功に置換しない。新scanに無かっただけの旧issue解消指定は禁止。

取得済み結果の保存だけは下記。input JSONは`issues`/`resolved`のみ受け付け、scan・命名再調査・IaC比較・AWS checkを自動開始しない。保存時の既存validationは省略しない。

```console
python3 framework/scripts/issues_scan.py --task-file tasks/save-results.md save-results --environment dev --target-directory cde --service s3 --results /tmp/acquired-results.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/save-results.md
```

exit 0はコマンド完了（IaC差分は非阻害）、1は既存validatorの通常validation診断、2は入力/処理/保存error。partialはsummary/reportに明示し、完全一致/PASSとしない。scanが通常validation errorを検出してもartifactを保存して結果保存へ進める。保存後loopがFAILならその結果を報告し、taskはcompletedにしない。

## Comparison coverage

正本はdesired properties。observed/生成Markdown本文をIaC比較に使わない。CloudFormationの正式catalog typeと`cfn-logicalId`、stack model、stack別parameter、target contextを使う。legacy対応は既存の一意ID互換のみ。外部serviceは参照先model情報だけ読み、調査scopeを広げない。

対応範囲: literal、schema型の確定した値、nested object/ordered array、JSON document/policy、Ref/GetAttのresource identityとattribute、parameter/default、Condition/If/Equals/And/Or/Not、parameter/pseudo限定Sub/Join、Select/Split/FindInMap、正式な独立childと一意な親Refのinline child。model `.Name`のName tagへの正式変換、S3.Region/identifier output等の除外を維持する。IaC側だけの未選択設定は違反にしない。Tag配列のみ正式keyの対応を使い、その他の配列は順序・重複を保持する。object全体/documentを指定した場合は全体比較する。

未比較: Terraform（既存の確実なローカル対応/evaluatorがない）、Transform、ImportValueの承認受渡しをローカルで証明できないもの、IMPORT参照の外部input、不明attribute/非一意mapping、未対応式、未確定値/型。resourceを全件unsupportedにする構成ではない。IMPORTそのものは生成対象外で、IaC不存在を欠落としない。CREATEの明示template/resource/property欠落は非阻害差分。入力syntax/読込/保存失敗はerrorとして成功にしない。

## Input reuse and publication

`load_model`は検証済みparse・実file/part/key/行位置・本文を共有し、`read_model`公開APIは維持する。row indexはlegacy IDのhyphenと曖昧prefixを確認する。新しいscan内で通常材料と比較が同じmodel入口/partを再parseしない。scanの生成一致確認は既存read-only sync APIをtarget単位で呼び、余分なgenerator processとscope再読込を省く。通常validator/loopの既定process経路、成功cache・最大4並列は維持する。新しいservice subagent/入れ子並列/永続cacheは追加しない。根拠行の確認も保存内でfile単位に共有する。template decodeはfile単位、評価はstack/parameters/context単位、catalog/index/参照symbolは実行内で共有する。

scan artifactはrepository外の一時受渡しであり次回cacheではない。既存digest/service dependency/common入力helperで保存前にmodel、parts集合、IaC、parameter、参照先、rule/frameworkを確認する。変更時は保存拒否し、該当scopeを再scanする。保存だけのための比較再実行をしない。

report保存は既存のrepository外共有registration lockで短く直列化し、保存直前に現reportを再読込・scope限定mergeし、同directory一時file＋atomic replaceで公開する。busy時は保存をretryし、比較を再実行しない。別service、human確認、適用例外、未解消issueを保持する。機械診断と既存issueの対応が不明なら削除せず限定確認。IaC既存差分も今回未比較/新scan不検出だけで除去せず未確認として保持する。不正report、不存在への架空link、架空行番号、未予約/対象外writeを拒否する。secret/current ARNは新診断・artifact/reportへ出力せずマスクする。

`iac-issues.md`冒頭は非阻害結果、scope、日時、今回差分/未比較/error件数とstatusを記載する。保持された旧差分は今回件数と区別する。通常MarkdownのH2環境/target、H3 service、issue-service marker、番号付きissue形式を維持する。作業/性能ログは一覧へ混ぜない。チャットは件数、未比較/残判断、保存先、保存後validationだけ短く返す。

CREATEの明示対応templateが存在しない場合は「モデルに対応するtemplateが存在しない（CREATE未実装）」と対象resource・stack・欠落pathをIaC差分に明記する。存在しないfileにはlinkを作らない。stack/template対応が未確定の場合は不存在と断定せず未比較理由を記載し、IMPORTは欠落判定から除外する。

## Framework regression and fixture benchmark

この入口の開発時はframework scopeのfull loopを実行する。通常issuesへframework全回帰を追加する意味ではない。`issues_scan.checks.py`は隔離fixtureと既存checks形式で検査し、`--benchmark --log-dir /tmp/issues-performance`でA（現checkoutの変更前相当通常経路）/B（同じ通常check＋service別reference比較）/C（一括scan）を同じruntime・fresh cache・profileなしで繰り返し測定する。benchmark fixtureとdiagnosticsはrepository外にだけ置く。

A/BのLLM量は旧skillが要求するmodel/Markdown全読込と一覧再編集、Cは実際のscan stdout＋最小review JSONのUTF-8 bytes/文字数として測る。必要ruleの入力はA/B/Cへ同じ条件で加算し、Cのstdoutは本文を重複出力せずpattern/scope/pathを共有する。実LLM token・LLM wall time・実案件の総時間は未測定。fixtureのPython scan/材料抽出/整形/保存全経路wall/process/read/parse/decode/判定coverageだけの測定をskill全体の実測速度と呼ばない。保存後local loopと実LLM時間はこのbenchmarkには含めず未測定とする。read_textと入力整合確認のread_bytesを分け、stageのmodelも含めて集計する。

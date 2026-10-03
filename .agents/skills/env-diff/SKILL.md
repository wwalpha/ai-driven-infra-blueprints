---
name: env-diff
description: desired propertiesをdevとstg、stgとprodのcde／non-cde別に4組比較し、AIが環境差異を整理してそれ以外の問題をissuesへ追記するときに使用する。
---

# 環境間のdesired比較

共通正本はai-driven-infra-blueprintsリポジトリで管理する。

## 比較

- `AGENTS.md`、`framework/rules/model-information.md`、`framework/rules/loop-engineering.md`と[issues skill](../issues/SKILL.md)の保存仕様を読む。
- 比較組はdev↔stg／cde、stg↔prod／cde、dev↔stg／non-cde、stg↔prod／non-cdeの4組。`project.json`に同名environmentと確定済みaliasがあることを確認する。別名・accountへの対応を推測せず、不足は未確認として報告する。
- 入口modelと分割partを既存readerで読み、`desired.*`だけを比較する。`observed.*`と`display.*`、AWS現在値、CFn／Terraformとの照合は対象外。サービス指定がなければ各組の両側にある全service入口の和集合を対象とする。

```console
python3 -B framework/scripts/compare-environments.py
# serviceを指定する場合（4組すべてで同じserviceを比較）:
python3 -B framework/scripts/compare-environments.py --service vpc --service iam
```

- stdoutは4組それぞれの`status`、比較済み`services`、`differences`、`errors`を含むJSON。必要ならrepository外の一時fileへ保存し、4組を個別に読む。差分があっても比較が完了すれば終了コード0、入力欠落・読込失敗などで比較不能があれば1となる。成功したserviceの差分は保持される。`incomplete`や空の比較済みserviceを「問題なし」と扱わない。
- resourceは`resourceType`＋`logicalId`、rowは正式property名＋同propertyの出現順で対応させる。resource／row番号の変更は差分にしない。反復propertyの順序は保持する。JSON documentはobject key順・空白を揃えて比較し、配列順を保持する。
- desiredの値・comment・resource metadata・共通注記・stack／deployment設定も出力される。resource／row以外のdesired keyはそのまま対応させる。logical IDが環境間で違うresourceは片側のみとして出るため、同型だからと自動対応させず、必要な対応関係を確認する。環境名・account・名称・CIDR・参照link・artifact pathを処理側で置換／除外しない。

## AIによる整理

- 4組それぞれで差分を要約し、`環境差異`、`環境差異以外の問題`、`未確認`に整理する。JSONの`path`・`line`・`key`・両側の値を根拠とし、必要なmodelや既存設計の該当箇所だけを追加確認する。
- 環境差異として除外するには、humanの指示、現行設計、命名ルール等の根拠を示す。dev／stg／prod、account、resource名が異なることだけで問題とせず、容量・保持日数・機能の有効／無効・権限等の違いを無条件で環境差異ともしない。名称・参照・JSON本文の差分も根拠を確認する。
- 環境差異と判断できないという理由だけで誤設定と断定しない。判断根拠不足は未確認として要約に残す。比較不能は原因と未検証範囲を報告する。

## issuesへの追記

- 環境差異以外と確認できた問題だけを、問題がある側の`issues/<environment>/<target-directory>/issues.md`へ追記する。片側の差分だけを見て誤り側を推測しない。両側に問題がある場合は両側に記載する。判断待ちの問題は不整合が確認できた事実と未確定点を区別して記載する。
- 保存は同じ調査の`migration` taskで行う。最初のrepository変更として`tasks/active.md`を今回のGoalへ切り替え、比較対象の全environment/target/serviceをValidation scopeに列挙する。Allowed pathsはactive contractと対象issues.mdだけとし、各Required changesに一意なIDと対応する`exists:` Acceptance checkを付ける。未解決issueがあっても保存限定の調査を継続できる。framework変更や修復は混ぜない。
- 既存issuesを先に読み、今回無関係な問題や未確認の問題を保持する。この比較は追記であり、既存issueを解消扱いで削除しない。stgは2組に登場するので同じ原因・resource・propertyの既存問題へ根拠を追加し、重複issueを増やさない。
- issues skillの日時・H2環境／target・H3 service・番号・相対根拠link仕様を使う。問題文に比較相手、両側の設定値、環境差異以外とした理由を短く添える。根拠位置がpartならpart fileへリンクし、保存前にfileと行番号を確認する。
- 対象issues fileがなければ確認範囲付きで作成する。今回追記が0件でも既存issueを保持し、「今回の環境間比較による追加issueなし」と記載する。file全体で問題がない場合だけ`未解決issueなし`とする。比較不能・未確認範囲を冒頭に明記する。
- 保存後は`python3 -B framework/scripts/blueprint-loop.py --mode local`を実行する。4組の差分要約、環境差異として除外した根拠、未確認事項、追記したissuesへのリンク、検証結果を報告して終了する。設計・model・IaC修正、AWS API、deploy/applyへ進まない。

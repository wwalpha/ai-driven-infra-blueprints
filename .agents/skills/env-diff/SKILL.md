---
name: env-diff
description: desired propertiesのdev→stg／stg→prod、cde／non-cdeから選択した組を比較元を正として比較し、サービス別の差分とAI要約を比較先のdiff.mdへ保存するときに使用する。
---

# 環境間のdesired比較

共通正本はai-driven-infra-blueprintsリポジトリで管理する。

## 比較

- `AGENTS.md`、`framework/rules/model-information.md`、`framework/rules/loop-engineering.md`、`framework/rules/aws-resource-naming.md`を読む。
- 比較候補はdev↔stg／cde、stg↔prod／cde、dev↔stg／non-cde、stg↔prod／non-cdeの4組。依頼された組だけ選択し、比較組の指定がなければ確認する。全4組へ自動拡大しない。選択した組についてだけ`project.json`のenvironmentと確定済みaliasを確認する。別名・accountへの対応を推測せず、不足は未確認として報告する。
- 前のenvironmentのdesiredを正（比較基準）とする。dev→stgはdevが基準、stg→prodはstgが基準。JSONの`left`を基準、`right`を比較先として扱う。比較先に基準のresource／propertyがなければ`不足`、比較先だけなら`追加`、両側の値が異なれば`値の相違`と記載する。
- `--pair dev-stg`または`--pair stg-prod`でenvironmentの組、`--target cde`または`--target non-cde`でtargetを選ぶ。両方指定すると1組、pairだけならその2targetを比較する。選択外のmodelは読まない。dev↔stgだけなら未完成のprodは不要。
- 入口modelと分割partを既存readerで読み、`desired.*`だけを比較する。`observed.*`と`display.*`、AWS現在値、CFn／Terraformとの照合は対象外。サービス指定がなければ各組の両側にある全service入口の和集合を対象とする。

```console
# dev↔stg／cdeだけ:
python3 -B framework/scripts/compare-environments.py --pair dev-stg --target cde
# dev↔stgのcde／non-cdeだけ:
python3 -B framework/scripts/compare-environments.py --pair dev-stg
# 全4組を明示依頼された場合:
python3 -B framework/scripts/compare-environments.py
```

- serviceを限定する場合は選択引数に`--service vpc --service iam`等を追加する。引数なしのprogramは全4組を比較するため、限定依頼では選択引数を省略しない。
- stdoutは選択した組それぞれの`status`、比較済み`services`、`differences`、`errors`を含むJSON。必要ならrepository外の一時fileへ保存し、組を個別に読む。差分があっても比較が完了すれば終了コード0、入力欠落・読込失敗などで比較不能があれば1となる。成功したserviceの差分は保持される。`incomplete`や空の比較済みserviceを「問題なし」と扱わない。
- resourceは`resourceType`＋`logicalId`、rowは正式property名＋同propertyの出現順で対応させる。resource／row番号の変更は差分にしない。反復propertyの順序は保持する。JSON documentはobject key順・空白を揃えて比較し、配列順を保持する。
- desiredの値・comment・resource metadata・共通注記・stack／deployment設定も出力される。resource／row以外のdesired keyはそのまま対応させる。logical IDが環境間で違うresourceは片側のみとして出るため、同型だからと自動対応させず、必要な対応関係を確認する。環境名・account・名称・CIDR・参照link・artifact pathを処理側で置換／除外しない。

## AIによる整理

- 選択した組それぞれでサービス別に差分を要約し、各service内で`環境差異`、`その他の差分`、`未確認`に整理する。差分はあり得る設計差であり、それだけで誤設定・未解決issue・禁止事項としない。JSONの`path`・`line`・`key`・両側の値を根拠とし、必要なmodelや既存設計の該当箇所だけを追加確認する。
- 比較先の評価は比較元のdesiredを基準とする。環境固有の名称・account・参照等は命名規則と確定済みの環境対応を踏まえて期待値を示す。比較元の実値をそのまま比較先の期待値へコピーしない。比較元自体の命名規則不一致は基準側の不一致として記載し、適合扱いにしない。
- 環境差異と判断するには、humanの指示、現行設計、命名ルール等の根拠を示す。容量・保持日数・機能の有効／無効・権限等の違いも理由を確認する。根拠が不足する差分は未確認とし、誤設定と断定しない。環境差異も保存する差分一覧から除外しない。
- 比較不能は原因と未検証範囲を報告し、差分なしと扱わない。

### 名称・参照差の判定

- 同じidentityで名称にdev／stg／prodが含まれることだけでは`環境差異`としない。各environmentの正式propertyについて命名規則の適用対象・例外とpatternを確認し、`project.json`のenvironment／alias／account／regionおよびhuman-confirmedなapplication／purpose等のcomponentへ照合する。値から未知componentを推測して適合扱いにしない。
- 判定は両側それぞれ`適合`、`不一致`、`適用対象外`、`未確認`で記録する。適用対象の名称がpattern・確定済みcomponent・対象environmentと一致しない場合は`その他の差分（命名規則不一致）`とし、環境差異へまとめない。期待するpatternと、全componentが確定済みなら期待する実名、実際の値、異なる箇所を記載する。不足componentや規則不明で判定できなければ`未確認`とする。
- 命名確認はJSONの生の差分に出たrowだけへ限定しない。選択したserviceの比較対象resourceについて、両環境で同じ名称値でも環境component等が規則に不一致ならdiff.mdへ記載する。生の環境間差分と規則への不一致を区別し、重複するresource/propertyは一つの詳細へまとめる。
- IMPORT等の適用対象外は命名違反と断定せず、名称差と対象外の根拠を記載する。対象外であることだけで名称差を環境差異と確定しない。これはdiff.mdの分類であり、命名規則・model・既存issueを修正しない。
- `環境差異`とできるのは、両側の名称が適用規則へ適合し、環境に応じて変わるcomponent以外が同じ確定済み役割を表すと確認できた場合。名称が両側とも規則に適合していてもpurpose等の役割が違えば`その他の差分`とする。明示された命名例外はその根拠と両側の名称の対応を示す。
- 参照値は参照先のdesired resourceと正式名称まで解決し、両側で同じ役割・identityに対応するか、その参照先の名称が各environmentの命名規則へ適合するかを確認する。URL、ARN、physical IDそのものへ名称patternを適用しない。AthenaのOutputLocationはbucketとkey prefix、KmsKeyは実KMS Keyと所属Alias、SchedulerのTargetは接続先resourceとRole・Input等を分けて確認する。参照先不明は未確認とする。環境componentだけの違いと確認できない参照先・prefix・Target設定の違いは名称差へ混ぜず、その他の差分として残す。
- 「Name／OutputLocation／KmsKeyやRoleName、Name／Targetは環境別名称・参照差」のような件数だけの一括説明では判定済みとしない。各resource/propertyの上記確認を残し、要約では分類別・適合状態別の件数と具体的な理由を示す。resource件数、生のproperty差分件数、規則不一致件数を分け、各集約から該当する詳細へ辿れるようにする。

## diff.mdへの保存

- 選択した組の全差分とAI要約を、次の対応表に従って比較先environmentへ保存する。未選択組のdiff.mdは作成・更新しない。

| 比較 | target | 保存先 |
| --- | --- | --- |
| dev↔stg | cde | `issues/stg/cde/diff.md` |
| dev↔stg | non-cde | `issues/stg/non-cde/diff.md` |
| stg↔prod | cde | `issues/prod/cde/diff.md` |
| stg↔prod | non-cde | `issues/prod/non-cde/diff.md` |

- 比較元を正として比較先の差分を保存する。`issues.md`へ転記せず、既存issuesを変更しない。diff.mdの項目を未解決issueとして数えず、差分の存在をtask停止理由にしない。既存issues.mdに対する通常のissue gateは維持し、issue保存限定taskの停止判定免除を使わない。
- 保存は`migration` taskとして行う。最初のrepository変更として`tasks/active.md`を今回のGoalへ切り替え、選択した比較対象の両側のenvironment/target/serviceだけをValidation scopeに列挙する。Allowed pathsはactive contractと選択した組の保存先diff.mdだけとし、各Required changesに一意なIDと対応する`exists:` Acceptance checkを付ける。framework変更や修復は混ぜない。
- 冒頭に更新日時（Asia/Tokyo）、基準environment（正）・比較先・target、比較したserviceと未検証範囲を書く。`## 要約`と`## 差分`の両方に`### <service-id>`を置き、要約・全差分をサービス別に整理する。各差分にはresource、正式property／field、基準値、比較先の値（片側欠落は明記）、不足／追加／値の相違、区分、判断根拠を含める。命名確認だけの項目は規則不一致と明記する。長いJSON documentは省略せずcode block等で記載する。
- 名称・参照差の詳細には両environmentの命名確認結果、適用pattern／例外の根拠、期待値または未確定component、実値と不一致箇所を追記する。分類の理由を「環境別名称・参照差」だけで済ませない。規則の該当箇所と両側modelへの相対根拠linkを付ける。
- 根拠リンクはdiff.mdからの相対pathを使い、行番号は`[part-002.properties:20](../../../model/stg/cde/logs/part-002.properties)`のようにlabelへ記載する。保存前に両側のfileと行番号を確認する。
- 実行ごとに同じdiff.mdの今回比較したserviceの結果を更新し、対象外serviceの結果は保持する。比較不能となった範囲の旧結果は最新と扱わず未確認と明記する。差分が0件でもfileを残し、比較完了範囲に`差分なし`と記載する。履歴用・timestamp別fileを増やさない。
- 保存後は`python3 -B framework/scripts/blueprint-loop.py --mode local`を実行する。選択した組の差分要約、未確認事項、保存したdiff.mdへのリンク、検証結果を報告して終了する。設計・model・IaC修正、AWS API、deploy/applyへ進まない。

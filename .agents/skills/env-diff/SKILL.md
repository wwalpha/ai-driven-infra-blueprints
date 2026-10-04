---
name: env-diff
description: desired propertiesのdev→stg／stg→prod、cde／non-cdeから選択した組を比較元を正として比較し、サービス別の差異を簡潔にまとめて比較先のdiff.mdへ保存するときに使用する。
---

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。


# 環境間のdesired比較

共通正本はai-driven-infra-blueprintsリポジトリで管理する。

## 比較

- `AGENTS.md`、`framework/rules/model-information.md`、`framework/rules/loop-engineering.md`、`framework/rules/aws-resource-naming.md`を読む。
- 比較候補はdev↔stg／cde、stg↔prod／cde、dev↔stg／non-cde、stg↔prod／non-cdeの4組。依頼された組だけ選択し、比較組の指定がなければ確認する。全4組へ自動拡大しない。選択した組についてだけ`project.json`のenvironmentと確定済みaliasを確認する。別名・accountへの対応を推測せず、不足は未確認として報告する。
- 前のenvironmentのdesiredを正（比較基準）とする。dev→stgはdevが基準、stg→prodはstgが基準。JSONの`left`を基準、`right`を比較先として扱う。比較先に基準のresource／propertyがなければ`不足`、比較先だけなら`追加`、両側の値が異なれば`値の相違`と記載する。
- `--pair dev-stg`または`--pair stg-prod`でenvironmentの組、`--target cde`または`--target non-cde`でtargetを選ぶ。両方指定すると1組、pairだけならその2targetを比較する。選択外のmodelは読まない。dev↔stgだけなら未完成のprodは不要。
- 入口modelと分割partを既存readerで読み、`desired.*`だけを比較する。`observed.*`と`display.*`、AWS現在値、CFn／Terraformとの照合は対象外。サービス指定がなければ各組の両側にある全service入口の和集合を対象とする。
- `desired.resource.<番号>.resourceMode=IMPORT`のresourceは比較対象外とする。設定値・名称・comment・JSON・resource metadataを差分や命名確認へ含めず、不足／追加・未確認・規則不一致件数にも数えない。同じLogical IDまたは確認済みresource対応で片側がIMPORTなら、その対応組の両側を比較から除外する。未指定modeはCREATEとして比較し、未知modeをIMPORTと推測しない。独立した子resourceは自身のmodeで判定し、親のIMPORTだけを理由にCREATEの子を自動除外しない。
- IMPORTだけが片側にある場合も不足／追加にはしない。IDが違う対応は推測しない。IMPORT自体は除外し、反対側のCREATEで対応が確定できないresourceは未確認として保持する。必要な対応は既存設計・指示を根拠に確認して`--resource-map`へ渡す。除外されたresourceはJSONの`excluded`へside・type・Logical ID・mode・除外理由・file／行番号を記録する。`resource_matches`の`excluded=true`も比較件数から除く。
- IMPORTを含むserviceの派生`ownedCatalogResourceTypes`一覧は仕様差分に数えず、残るCREATE resourceを個別に比較する。両側とも比較対象resourceがIMPORTによる除外で0件になる場合はservice metadataも差分にしない。共通注記やstack／deployment設定はresourceへの所属を推測して除外しない。CREATEからIMPORTへの参照はCREATEの設定として比較する。参照先IMPORTの設定・名称適合性の比較は行わず、対応確認に必要なidentity情報だけを確認する。

```console
# dev↔stg／cdeだけ:
python3 -B framework/scripts/compare-environments.py --pair dev-stg --target cde
# dev↔stgのcde／non-cdeだけ:
python3 -B framework/scripts/compare-environments.py --pair dev-stg
# 全4組を明示依頼された場合:
python3 -B framework/scripts/compare-environments.py
```

- serviceを限定する場合は選択引数に`--service vpc --service iam`等を追加する。引数なしのprogramは全4組を比較するため、限定依頼では選択引数を省略しない。
- 選択した複数比較が1 commandで処理可能な場合は、理由なくpairごとの別processへ分割しない。同一CLI実行内で共通modelのparse結果を再利用するため、全4組を明示依頼された場合は上記の引数なしcommandを1回実行する。限定依頼では既存selectorを維持し、performanceを理由に未選択のpair／target／serviceを追加しない。
- stdoutは選択した組それぞれの`status`、比較済み`services`、`differences`、`difference_count`、`environment_differences`、`errors`、`resource_matches`、`unconfirmed`、`excluded`を含むJSON。`difference_count`はPythonが検知した`differences`の件数で、確認済み環境差異の除外後の値とする。必要ならrepository外の一時fileへ保存し、組を個別に読む。差分があっても比較が完了すれば終了コード0、入力欠落・読込失敗・古い除外指定は`incomplete`、resource対応未確定は`unconfirmed`として終了コード1となる。生のfield・値・file・行番号は比較JSONで確認し、diff.mdへの全件転記は行わない。`difference_count=0`でも`incomplete`、`unconfirmed`、空の比較済みserviceを「問題なし」と扱わない。IMPORT除外だけで比較対象が0件の場合も、IMPORTの設定が一致したとは扱わず、除外理由は内部JSONに保持する。
- Logical ID自体は環境間の仕様差分に含めない。`logicalId`と表示名から派生する`anchor`は対応確認の根拠として保持するが、それらの文字列差だけを不足／追加／値の相違にしない。既存CloudFormation stack更新でのLogical ID変更の影響は、このdesired環境比較とは別に扱う。
- 初回は`resourceType`＋同じ`logicalId`を対応候補として比較する。Logical IDが異なるresourceは自動で不足／追加にせず`unconfirmed`へ出す。同型だけ、resource件数、番号、並び順、設定値が似ていることだけでは対応を確定しない。正式名称・用途・親子関係・参照先とhuman指示／現行設計の根拠から同じ役割を確認する。同じLogical IDの対応も役割が違えば見直す。
- 対応が確認できたら、選択した1組の`left`・`right`・`target`と下記形式の`resources`を持つJSONをrepository外の一時fileへ作成し、`--resource-map <file>`を追加して同じ組・serviceで再比較する。この引数には`--pair`と`--target`が必須。`left`／`right`はそれぞれのmodelのLogical ID、`resourceType`は正式type、`reason`は役割と両側modelのfile・行番号等の確認根拠とする。片側の不存在を確認できたresourceだけ、その側を`null`とし不足／追加として比較する。選択外service、存在しないID、重複対応、不正な組を処理へ渡さない。未確定対応は推測で埋めず未確認として保存する。

```json
{
  "left": "dev", "right": "stg", "target": "cde",
  "resources": [
    {"service": "logs", "resourceType": "Logs.LogGroup",
     "left": "DevFlowLogs", "right": "StgFlowLogs",
     "reason": "形式例。両側modelの正式名称・用途・参照元で同じ役割と確認した根拠を記載"}
  ]
}
```

- 許容された環境差異は、初回比較と下記のAI判定で確認してから、同じresource-map JSONの任意`environment_differences`へ指定する。各entryは比較JSONの`service`・`identity`をそのまま使い、`left`・`right`には両側の`value`の実文字列、`reason`には許容された環境差異の確認根拠を入れる。resource対応を確定する`resources`も保持する。同じLogical IDだけなら`resources: []`でもよい。AIがrepository外の一時fileを作成し、humanへfile編集を要求しない。文字列中のenvironment／account等を一律置換して許容を推測しない。

```json
{
  "left": "dev", "right": "stg", "target": "cde",
  "resources": [
    {"service": "athena", "resourceType": "Athena.WorkGroup",
     "left": "DevReport", "right": "StgReport", "reason": "形式例。同じ用途の対応確認根拠"}
  ],
  "environment_differences": [
    {"service": "athena",
     "identity": ["row", "Athena.WorkGroup", "DevReport", "Athena.WorkGroup.Name", "1", "value"],
     "left": "athwg-app-dev-reporting", "right": "athwg-app-stg-reporting",
     "reason": "形式例。両側の命名適合と同じ用途の環境別名称を確認した根拠"}
  ]
}
```

- 確認後は同じ1組・serviceと`--resource-map`で再比較する。Pythonがidentityと両側の実値の一致を検証し、確認済み項目を`differences`から除いて`environment_differences`へ実値・証拠・理由付きで保持する。`excluded`は引き続きIMPORT resourceの除外だけを表す。追加・不足、未確認resource、存在しない差分、重複、古い値の除外指定は拒否される。拒否時は除外指定と最新入力を確認し、未確認事項を推測で除外せず再比較する。除外対象がなければ再比較は不要。

- 対応済みresourceのrowは正式property名＋同propertyの出現順で比較する。resource／row番号の変更は差分にしない。反復propertyの順序は保持する。JSON documentはobject key順・空白を揃えて比較し、配列順を保持する。documentと一致する派生`artifactSha256`は独立した仕様差分にしない。不一致は入力不整合として比較不能とする。
- 選択したservice内の対応済みresourceを参照するlogical referenceは、表示text・anchorの文字列ではなく対応済み参照先で比較する。自身へのidentifier reference、同service／別の選択済みserviceへのlink、親の`parentReference`、JSON document内のMarkdown resource linkにも適用する。参照先が変われば差分に残す。選択外serviceや外部／cross-target link、未解決linkは自動置換しない。必要な参照先の対応はAIによる整理で確認し、確認不足は未確認とする。参照先が比較対象のCREATEの場合は正式名称と命名適合性の確認を省略しない。
- 比較対象CREATEのdesiredの実設定値・正式名称・comment・logicalId／anchor以外のresource metadataと、共通注記・stack／deployment設定は引き続き比較する。IMPORT除外に伴う派生service metadataを除き、resource／row以外のdesired keyはそのまま対応させる。環境名・account・名称・CIDR・literalのARN／ID・artifact pathを処理側で一律置換／除外しない。確認済みの許容された環境差異だけを上記の明示指定で除外する。

## AIによる整理

- 選択した組それぞれで、許容された環境差異を除いた差分・未確認事項をサービスごとに短い文章・箇条書きでまとめる。`その他の差分`、`未確認`の区分は必要な項目に添え、空の区分や件数表を並べない。許容された`環境差異`は内部判定にだけ使い、diff.md・完了報告の差分対象と差分件数に含めず、代表例も掲載しない。差分はあり得る設計差であり、それだけで誤設定・未解決issue・禁止事項としない。JSONの`path`・`line`・`key`・両側の値を根拠とし、必要なmodelや既存設計の該当箇所だけを追加確認する。
- IMPORT関連はdiff.md・完了報告の差分要約に掲載しない。resourceの除外対象・理由だけでなく、IMPORTに関する共通実装注記、import準備用dummy、取得値ではない旨、import前の実値照合、IMPORT resourceの接続確認状況などの注記差も省く。共通注記にIMPORT以外の設計差が混在する場合は、その部分だけを残す。IMPORT resourceだけのservice modelの有無を不足・追加・未確認として再掲しない。独立したCREATEのsubscription filterや送信Role等の設計差・未確認事項は各所有serviceで扱い、親や参照先がIMPORTであることだけでは省かない。
- 差分件数を示す場合は、確認済み環境差異の除外を渡して再比較したPythonの`difference_count`を使い、報告時だけの減算で済ませない。IMPORT関連注記を掲載から省き、Pythonの件数と掲載対象が一致しない場合は件数を掲載しない。文章をまとめただけでは件数を減らさない。JSONは残った`differences`と除外した`environment_differences`の双方に生の実値を保持する。未確認・比較不能は別に示し、環境差異と推測して差分から除外しない。命名規則不一致の指摘件数は環境間の値差分件数へ混ぜない。
- 差分・命名規則不一致・未確認・比較不能事項がないserviceは、diff.md・完了報告に見出しも本文も掲載しない。`比較完了範囲で差分なし`などの説明や差分のないservice一覧も書かない。
- 一致している設定・用途・Logical IDの列挙や、`same_logical_id`等の照合方法は出力しない。resource対応の確認は比較のために行い、差異として掲載しない。根拠の確認は内部で行い、diff.mdに根拠リンク・fileの行番号・確認経緯を付けない。
- 比較先の評価は比較元のdesiredを基準とする。環境固有の名称・account・参照等は命名規則・明示された命名例外と確定済みの環境対応を踏まえて期待値を示す。比較元の実値をそのまま比較先の期待値へコピーしない。許容された例外以外の比較元自体の命名規則不一致は基準側の不一致として記載し、適合扱いにしない。
- 環境差異と判断するには、humanの指示、現行設計、命名ルール等の根拠を確認する。容量・保持日数・機能の有効／無効・権限等の違いも理由を確認する。根拠が不足する差分は未確認とし、誤設定と断定しない。同じ理由の名称・account・参照差はまとめ、設定や用途が異なる差は分けて説明する。
- 比較不能・resource対応未確定は原因と未検証範囲を短く記載し、差分なしと扱わない。未確認resourceを不足／追加件数へ含めず、対応済み範囲の差分と分ける。resource対応の確認には`resource_matches`と両側modelを使い、全対応表や同じ確認根拠の反復掲載は行わない。Logical IDの文字列差自体は仕様差分にしない。

### 名称・参照差の判定

- dev↔stgの同じtarget・同じ役割のresourceで、名称にtarget識別の`cde`／`noncde`／`non-cde`が付くか付かないかの違いは、humanが許容した問題のない`環境差異`とする。environment componentのdev／stgの違いと合わせて判定し、この表記の有無だけを命名規則不一致・修正要求・未確認にしない。両側を`適合（明示例外）`とし、差分の掲載・集計から除外する。別targetのcde↔non-cdeの置換や、用途・権限・参照先など実設定の違いまで許容したと解釈しない。stg↔prodへはこのdev↔stgの例外を自動拡張しない。
- humanが明示したCloudTrail例は、devのLogical ID `CDECLOUDTRAIL01`・`CloudTrail.Trail.TrailName=venusinf-dev-cloudtrail-cde`と、stgのLogical ID `CLOUDTRAIL01`・`CloudTrail.Trail.TrailName=venusinf-stg-cloudtrail`を対応するresourceとして扱い、TrailNameの違いを`環境差異（許容された環境固有名称）`に分類し、差分の掲載・集計から除外する。両方の名称全体をこの明示例外として許容し、一般の`ctrail-...` patternとの違いもこの例を規則不一致として再掲する理由にしない。Logical IDの差自体は仕様差分に含めない。この例外はenv-diffの分類に適用し、model値・共通命名規則を変更しない。
- 同じidentityで名称にdev／stg／prodが含まれることだけでは`環境差異`としない。各environmentの正式propertyについて命名規則の適用対象・例外とpatternを確認し、`project.json`のenvironment／alias／account／regionおよびhuman-confirmedなapplication／purpose等のcomponentへ照合する。値から未知componentを推測して適合扱いにしない。
- 両側それぞれの`適合`（明示例外の場合は`適合（明示例外）`）、`不一致`、`適用対象外`、`未確認`を確認する。上記を含むhumanの明示例外を一般patternより先に適用する。許容された例外以外で適用対象の名称がpattern・確定済みcomponent・対象environmentと一致しない場合は`その他の差分（命名規則不一致）`とし、環境差異へまとめない。diff.mdには対象と不一致箇所を短く示し、期待pattern・実名の全件対照表は載せない。不足componentや規則不明で判定できなければ`未確認`とする。
- 命名確認はJSONの生の差分に出たrowだけへ限定しない。選択したserviceの比較対象resourceについて、両環境で同じ名称値でも環境component等が規則に不一致ならdiff.mdへ短く記載する。生の環境間差分と規則への不一致を区別し、同じ理由の不一致はまとめる。
- IMPORTは比較・命名確認から除外し、名称差を環境差異・その他の差分・未確認として分類しない。IMPORTの除外対象・理由は内部JSONに保持し、diff.mdの冒頭・本文へ掲載せず、除外説明だけのservice見出しも作らない。IMPORT以外の命名適用対象外は名称差と対象外の根拠を短く示し、対象外であることだけで環境差異と確定しない。これはenv-diffの比較・分類scopeであり、命名規則・model・既存issueを修正しない。
- `環境差異`とできるのは、両側の名称が適用規則またはhumanの明示例外へ適合し、環境に応じて変わるcomponent以外が同じ確定済み役割を表すと確認できた場合。名称が両側とも規則に適合していてもpurpose等の役割が違えば`その他の差分`とする。明示された命名例外の根拠と両側の名称の対応は内部で確認し、許容された環境差異を差分の掲載・集計から除外する。
- 比較対象CREATEの参照値は参照先のdesired resourceとidentityを解決し、両側で同じ役割に対応するかを確認する。参照先も比較対象CREATEなら正式名称まで解決し、各environmentの命名規則／明示例外への適合を確認する。参照先IMPORTの設定・名称確認は除外する。URL、ARN、physical IDそのものへ名称patternを適用しない。AthenaのOutputLocationはbucketとkey prefix、KmsKeyは実KMS Keyと所属Alias、SchedulerのTargetは接続先resourceとRole・Input等を分けて確認する。参照先不明は未確認とする。環境componentだけの違いと確認できない参照先・prefix・Target設定の違いは名称差へ混ぜず、その他の差分として残す。
- 名称・参照差をまとめる前に上記の確認を行う。同じ役割の環境別の出力bucket・KMS Keyや、同じ部署・情報区分で環境componentだけが違う出力prefixは、許容された環境差異と確認できた場合に差分の掲載・集計から除外する。出力prefixや接続先の用途、権限、実設定が異なる場合は残す。参照先の命名規則不一致は参照先serviceへ記載し、参照元で同じ不一致を重複掲載・集計しない。diff.mdには残った差分の用途と内容が分かる説明を残し、件数やproperty名だけの説明にしない。分類別件数や全resource/propertyの判定一覧は要求しない。

## diff.mdへの保存

- 選択した組のサービス別の簡潔な差異要約を、次の対応表に従って比較先environmentへ保存する。未選択組のdiff.mdは作成・更新しない。

| 比較 | target | 保存先 |
| --- | --- | --- |
| dev↔stg | cde | `issues/stg/cde/diff.md` |
| dev↔stg | non-cde | `issues/stg/non-cde/diff.md` |
| stg↔prod | cde | `issues/prod/cde/diff.md` |
| stg↔prod | non-cde | `issues/prod/non-cde/diff.md` |

- 比較元を正として比較先の差分を保存する。`issues.md`へ転記せず、既存issuesを変更しない。diff.mdの項目を未解決issueとして数えず、差分の存在をtask停止理由にしない。desired比較とdiff.md保存は既存issues.mdによる停止判定の対象外とする。下記の保存限定migrationでは、未解決issueがあってもAI分類・保存・local validationを続け、Issue remediationは追加しない。設計・model・IaC変更やAWS mutationには通常のissue gateを維持する。
- 保存は`migration` taskとして行う。最初のrepository変更として`tasks/<task-name>.md`を今回のGoalで新規登録し、選択した比較対象の両側のenvironment/target/serviceだけをValidation scopeに列挙する。Allowed pathsはactive contractと選択した組の保存先diff.mdだけとし、各Required changesに一意なIDと対応する`exists:` Acceptance checkを付ける。framework変更や修復は混ぜない。
- 冒頭は更新日時（Asia/Tokyo）、基準environment（正）・比較先・target、比較対象CREATE resourceの範囲と未検証範囲を数行で示す。IMPORT関連の除外説明は載せない。許容された環境差異は差分対象・件数から除外した旨を一度示し、環境名・account等の実値の違いを列挙しない。
- 本文は差分・命名規則不一致・未確認・比較不能事項があるserviceだけを、`## サービス別の差異`の下に`### <service-id>`を一つずつ置き、数行程度でまとめる。要約と詳細の二重構成にしない。主な設定差、resourceの追加・不足、命名規則不一致、未確認・比較不能事項を具体的に記載し、同じ理由の差は集約する。件数は追加・不足の規模など説明に役立つ場合だけ示す。
- 各差異は対象の用途・設定項目を短く示し、その下に「devは、…」「stgは、…」のように両環境を別の行で並べる。実行した比較組のenvironment名を使い、それぞれの実値・設定内容・有無を具体的に書く。「環境別名称・参照差」「設定が異なる」だけで済ませない。追加・不足も両側の有無を示す。不明な値は推測せず未確認とし、比較不能は原因と未検証範囲を記載する。
- 容量・保持日数・有効／無効・権限・接続先などの実設定差をこの形式で示す。JSON／policyは変更された権限・対象・条件等を両環境ごとに要約する。コメントだけの差は一言でまとめる。同じ値の両側表記、全fieldの値、JSON全文、resource対応表、命名確認表、根拠リンクは載せない。詳細のための別fileや付録はhumanが求めた場合だけ作成する。

形式例（値・件数は例示）:

```md
## サービス別の差異

### cloudwatch-logs

アプリログの保持日数
- devは、30日。
- stgは、90日。

変更理由は未確認。

### quicksight

Snowflake接続・VPC接続
- devは、Snowflake接続3件とVPC接続1件がある。
- stgは、どちらもない。

### iam

- 比較不能: devのpolicy documentとartifactSha256が不一致。IAMの設定差は未検証。
```
- 実行ごとに同じdiff.mdの今回比較したserviceの結果を更新し、対象外serviceの結果は保持する。比較不能となった範囲の旧結果は最新と扱わず未確認と明記する。今回IMPORTとして除外したresourceの旧差分・名称確認・関連注記と冒頭のIMPORT除外説明は最新結果から除去し、IMPORT関連だけのservice見出し・本文も削除する。今回許容された環境差異と確認した旧差分は掲載・件数から除去する。再比較で差分・命名規則不一致・未確認・比較不能事項がなくなったserviceは、旧見出しと本文を削除する。全serviceに掲載事項がなければfileの冒頭情報だけを残し、空の`## サービス別の差異`や`差分なし`の説明は書かない。履歴用・timestamp別fileを増やさない。
- 保存後は`python3 -B framework/scripts/blueprint-loop.py --mode local`を実行する。選択した組の差分要約、未確認事項、diff.mdの保存先、検証結果を報告して終了する。設計・model・IaC修正、AWS API、deploy/applyへ進まない。

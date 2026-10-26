# Model properties v2

正本は `model/<environment>/<target-directory>/<service>.properties` です。
`project.json` が topology、Alias、account、Region、profile の正本です。
target-directory は Alias があれば Alias、なければ awsAccountId です。
awsExecutionAccountId は実行先照合に使い、Model のパスに使いません。
同一 account の複数 Alias は別の Model を持ちます。
環境・Alias・service は作業開始時に選択した scope、Model のパスと project.json から確定します。
dev、stg などを含む設定文字列は通常の保存値です。環境名由来の参照宣言は生成・受理せず、
文字列から環境を推測したり、環境名を自動置換したりしません。
登録済み target に Model がなければ、reader は生成しません。
各環境の値をすべて明記し、tpl、継承、overlay、共通値の展開はありません。

## データと固定 identity

ファイルの最初の物理行は必ず次の形式です。

```properties
# model-format: 2
desired.resource.007.resourceType=EC2.VPC
desired.resource.007.logicalId=network-primary
desired.resource.007.anchor=network-primary
desired.resource.007.resourceMode=IMPORT
display.resource.007.comment=既存ネットワーク
desired.row.007-001.property=EC2.VPC.VpcId
desired.row.007-001.value=[network](#network-primary)
desired.row.007-001.comment=取得済み識別子
observed.row.007-001.value=`vpc-synthetic`
```

Resource 一式の中で identity、display、Row の正式 Property・comment・value・document、
対応する observed、参照宣言を近くに置きます。
`desired.service`、`desired.note`、`desired.deployment`、`desired.artifact` と既存の設計情報も保持します。
Resource／Row／Stack ID、logicalId、anchor、resourceMode、cfn-logicalId、親子関係は固定です。
`desired.stack.<id>.name` は変更可能な StackName、`placementName` は固定配置 identity です。
変更時に二つを交換しません。

`observed.row.<id>.value` の不存在、空文字、`PENDING_DEPLOY` は異なる値です。
observed.property／comment は desired から導出します。JSON文書の派生ハッシュは生成・保存しません。
IMPORT 自身の物理 ID は一般の観測更新では変更できません。他 Resource だけを参照し、
Schema の primary identifier と catalog output のいずれでもない Row は観測更新対象にできます。
参照宣言で自分自身へのリンクを隠した場合や、物理 ID の値を外部リンクにした場合も拒否します。
これらを正本に保存できません。runtime 投影から正本を再構築して保存しません。
CloudFormation の template YAML と parameter JSON は引き続き IaC 入力です。

## parts

大きい Model の入口はコメントだけの index にします。

```properties
# model-format: 2
# model-index: 2
# part: network/part-001.properties
# part: network/part-003.properties
```

各 part も `# model-format: 2` で始まります。初回変換は約600行でまとめます。
Resource と配下の Row・document・参照宣言・observed は同じ part に保持します。
Stack 等の所有 block も分割しません。巨大な単一 Resource は600行を超えて構いません。
通常編集は既存の part 名・順序・block 配置と既存 Row 順序を維持します。
追加 Resource は末尾へ追加し、必要な場合だけ part を増やします。
空 part を削除しても他の part を改番しません。観測更新で再分割しません。

reader は入口と全 parts を組み立て、重複キー、未登録 part、欠落、重複登録、symlink、
パス逸脱、block 分割、未知の形式版を拒否します。

## scalar と JSON

通常 scalar の空白、引用符、backslash、数値風文字列は保存された文字列のままです。
Java properties の一般的な escape、型推測、新しい式評価はありません。
backtick の意味は従来どおり保持します。

`.document` と、backtick で囲んだ JSON object／array の `.value` に限り、明示的な継続を使えます。

```properties
# model-format: 2
desired.row.007-002.document={ \
  "Statement": [ \
    {"Effect":"Allow","Action":["logs:CreateLogGroup"],"Resource":"*"} \
  ] \
}
```

継続記号 `\` は JSON 文字列の外、物理行の最後の一文字に置きます。
記号の後の空白、JSON 文字列途中の改行、暗黙継続、途中コメント、EOF、part をまたぐ継続は禁止です。
reader は記号を除き、行間へ JSON 空白を入れて strict JSON を検査します。
重複 object key、不正定数、構文不正を拒否し、native type と配列順序を保持します。

### Row の値形式

`desired.row.<id>.valueShape` は `leaf`（省略時）または `projection` です。
`leaf` は正式 Property 自体の1件の値で、Property 自体が配列なら配列のまま検証します。
`projection` は取得時の Property パスの `[]` 選択階層を保持した列形式です。
`resourceMode=IMPORT`、値の見た目、schema 検証の成否から形式を推測・再解釈しません。

```properties
desired.row.001-002.property=QuickSight.DataSource.Permissions[].Actions
desired.row.001-002.value=`["ActionA","ActionB"]`
desired.row.001-002.valueShape=leaf
desired.row.001-002.comment=一つの Permission の Actions
desired.row.001-003.property=QuickSight.DataSource.Permissions[].Actions
desired.row.001-003.value=`[["ActionA","ActionB"]]`
desired.row.001-003.valueShape=projection
desired.row.001-003.comment=取得した Permissions 全体の Actions 列
```

検証では projection の選択階層だけを展開します。末端の Property 自体の配列は展開しません。
末端 `SubnetIds[]` は schema の要素を指すため、leaf は1要素、配列全体は projection です。
`EventSelectors[].DataResources[].Values` の projection は `[[["arn:aws:s3"]]]` となり、
検証する末端値は `["arn:aws:s3"]` です。親階層の不正な型はエラーです。
leaf の空配列は末端 schema、projection の空の親配列は該当する親 schema の件数制約で判定します。

Acquire は取得値ごとに `valueShape` を明示します。候補 Model には取得値と形式情報を併せて記載し、
Review は保存値・形式・取得値を保持します。観測値も同じ Row の形式契約に従います。
比較時は leaf を取得形式に揃えますが、多階層の複数 leaf 行から親子所属を推測しません。
`valueShape` は保存・再読込と変更検出で保持し、Markdown の列には表示しません。

既存の列形式の Row は、取得記録または明示した構築元から projection と確認した場合に限り、
保存値を変えず `valueShape=projection` を追加します。leaf は移行不要です。
意味を断定できない Row は未確認として個別に確認し、再取得は `/import` の権限と同意に従います。
reader・検証・保存による自動移行や legacy fallback はありません。

## 参照宣言

`desired.reference.<refid>.*` は保存された参照断片の意味を記録します。
refid はサービス内で固定し、並べ替えで採番し直しません。
宣言は値の生成命令ではありません。producer が変わっても保存値は変わりません。
値・宣言の変更は明示的な編集です。

| フィールド | 内容 |
| --- | --- |
| consumerKey | 実在する正本キー。observed と参照宣言自身は禁止 |
| pointer | JSON の既存文字列 leaf を指す RFC 6901 Pointer。通常 scalar では禁止 |
| text / occurrence | 保存 leaf 中の実在断片と、1始まりの出現番号 |
| producerKind / producerScope | resource／stack／context と environment/target/service。context は target まで |
| producerId | Resource／Stack の固定 ID。context では禁止 |
| resourceType | resource の期待型。stack／context では禁止 |
| format | resource: link／name／identifier、stack: name、context: literal |
| property | name／identifier の正式 Property。stack は name。resource.link／context では禁止 |
| labelPolicy | fixed／resource-id／display-name／none。link 以外は none |
| contextProperty | context の executionAccountId のみ。resource／stack では禁止 |
| valueSelector | 任意。Route53 CNAME の Endpoint DNS 参照で選ぶ `DnsEntries` の位置と DNS 名成分（下記） |

name は producer の desired の正式な名前 Property、identifier は対応 Row の observed を参照します。
入れ子の Name や Description を raw name へ代用しません。未観測・空・PENDING・不正な識別子は保存値を保持して診断します。
KMS Key と子 Alias の grouped display は raw name 参照へ流用しません。
Pointer は object key 名、配列の追加位置、非文字列値を指せません。

直接 Markdown リンクも解析します。環境・target をまたぐ相対 Markdown パスも、登録済み Model の固定 scope として解決します。Model tree 外への逸脱はエラーです。同じ位置で同じ producer を示す宣言と直接リンクは
一つの使用箇所です。意味が違う場合は両方を保持し、WARNING とします。
producer 不在・曖昧・未観測、型・名前・識別子・ラベルの不一致は参照 WARNING です。
consumer の所有者・使用位置が不明な宣言、構文不正、I/O、scope 違反は通常のエラーです。

### Endpoint DNS の valueSelector

`desired.reference.<id>.valueSelector` は、CNAME の
`Route53.RecordSet.ResourceRecords` に保存した Resource リンクについて、参照先の
Interface `EC2.VPCEndpoint` の `DnsEntries` から選ぶ DNS 名を比較用に明示します。
対応する参照先 ResourceType は `EC2.VPCEndpoint` のみです。
`ResourceRecords[]` や明示的な番号付き Row（例: `ResourceRecords[1]`）も対象です。

```properties
desired.reference.dns.valueSelector=dns-entry[0].dns-name
```

書式は `dns-entry[n].dns-name` です。`n` は0始まりの非負整数で、`0` 以外の先頭ゼロは認めません。
`[0]` は `DnsEntries` の先頭要素を意味し、その要素を `:` で分割した第2成分の DNS 名を選びます。
比較する抽出構造は `Select(1, Split(":", Select(n, DnsEntries)))` です。
省略しても既存の Resource リンク宣言は有効ですが、`n=0` を補完せず、DNS 選択の比較は未比較になります。

既存の `producerKind=resource`、`format=link` の宣言に追加し、`consumerKey`、保存断片の
`text`／`occurrence`、`producerScope`、`producerLogicalId`、`resourceType`、`labelPolicy` を引き続き使います。
`$modelRef` を拡張せず、AWS JSON 内の Resource リンクも許可しません。
Row の保存値・Markdown リンク・値の保存形式は変更せず、DNS 名や生成 ARN を正本へ保存しません。
比較には Model／IaC の CNAME・Interface 型、同じ Producer、同一 scope の一意な Export と抽出構造の証明が必要です。
証明が不足すれば未比較とし、構造が一致しても実行時の選択範囲や現在の AWS 値の検証済みを意味しません。

## API と CLI

公開 API と helper の接続は [Model helper integration](model-helper-integration.md)、

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py list --repository-root .
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py read model/<environment>/<target>/<service>.properties
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py resource model/<environment>/<target>/<service>.properties <fixed-id-or-anchor>
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py trace model/<environment>/<target>/<service>.properties <key>
```

read は正本全体と WARNING、trace は正本の場所または派生元とそのキーの参照宣言、render は生成候補を返します。
生成候補を返す処理と保存権限の取得は別です。

既存の CloudFormation 動的参照（`{{resolve:...}}`）と Markdown リンクは、backtick で囲っても scalar として原文を保持します。JSON object／array の継続・strict JSON 検査には流用しません。

## 固定Snapshotと実行内キャッシュ

`ModelSnapshot.authoritative` / `values` は所有された不変の `SnapshotValues` です。
外部の可変辞書や、その辞書の読み取り専用proxyとは区別します。
正本からのRuntime投影も同じ固定入力では一度だけ構築し、検証・生成で共有します。
固定入力のオブジェクト同一性を、既存 `memo_table()` の実行内キャッシュと
`RunModels.checks` のキーに使います。識別のためのJSON化・内容ハッシュは行いません。
`entries()` と行索引は固定入力だけを再利用し、返却した行の変更による汚染を防ぎます。
可変辞書には同一性キャッシュを適用しません。

参照キャッシュはScope、Model Key、Property、logicalId、除外位置と参照世代を区別します。
文書・Contextが固定入力から求めた内容と一致する場合だけ再利用し、結果は独立したコピーで返します。
参照のないJSONは参照キャッシュを通りません。構文・AWS文書・Schema検査は引き続き実行します。
Candidate / Rollbackは入力オブジェクト、別検証呼出しは `input_context()` により分離します。

Observedの原子的公開後に `RunModels.apply_observed()` が参照世代を更新します。
参照先の影響範囲を確定できないため、他Serviceを含む当該実行の参照結果を失効させます。
保持中のResolverもProducerと索引を再取得します。Desired自体は変更しません。
現行のModel検証結果はJSON参照・表示・識別子の診断を含みDesiredだけに分離できないため、
Observed更新後は全体を再検証します。同一世代の固定入力では既存 `RunModels.checks` を再利用します。
Modelの事前全件ロードは追加しません。Import承認、Deploy実行中の入力固定・未完了操作Journal、
配信・保存の整合性確認に使うSHA-256はこのキャッシュとは別の証跡として維持します。

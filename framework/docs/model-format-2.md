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
observed.property／comment は desired から、artifactSha256 は document から導出します。
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
パス逸脱、block 分割、未知の形式版を拒否します。通常 reader に旧形式 fallback はありません。

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

name は producer の desired の正式な名前 Property、identifier は対応 Row の observed を参照します。
入れ子の Name や Description を raw name へ代用しません。未観測・空・PENDING・不正な識別子は保存値を保持して診断します。
KMS Key と子 Alias の grouped display は raw name 参照へ流用しません。
Pointer は object key 名、配列の追加位置、非文字列値を指せません。

直接 Markdown リンクも解析します。環境・target をまたぐ相対 Markdown パスも、登録済み Model の固定 scope として解決します。Model tree 外への逸脱はエラーです。同じ位置で同じ producer を示す宣言と直接リンクは
一つの使用箇所です。意味が違う場合は両方を保持し、WARNING とします。
producer 不在・曖昧・未観測、型・名前・識別子・ラベルの不一致は参照 WARNING です。
consumer の所有者・使用位置が不明な宣言、構文不正、I/O、scope 違反は通常のエラーです。

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

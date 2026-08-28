# Detailed Design Rules

## Task boundary

- `design` taskはintended designを更新し、対応するservice modelを`framework/scripts/sync-model.py`で生成してlocal validation後に終了する。chatbotが指定した既存resource取得では必要な非ARN current identifierも反映できる。IaC、AWS mutation、scenarioへ自動的に進まない。
- `infrastructure` taskはintended designを変更しない。deploy/apply成功後のgenerated current valueだけを詳細設計へ反映できる。
- infrastructure `update` phaseは、humanがtask開始前に手動修正した未commitのintended designをimmutable inputとして受け取れる。Codexはそのintended designを変更せず、deploy/apply成功後のgenerated current valueだけを追加更新できる。
- designの不足または変更が必要な場合、infrastructure taskは停止して別のdesign taskを要求する。

## Existing resource configuration

chatbotが既存AWS resourceの現在値取得を指定した場合だけ、Codexの`design` taskは次を実行できる。

- 取得対象はchatbotが確定したtarget AWS service、catalog resource type、propertyに限定する。別service、同じresource typeの未選択property、materialsにないpropertyへ自動的にscopeを広げない。
- repository変更前に`project.json`のtarget、credentialのcaller account、regionをread-only preflightで検証する。
- AWS Cloud Control APIのList／Readを第一候補とし、非対応resource typeだけ対象service固有のread-only APIを使用する。AWS値とmaterials／provider schema propertyの対応が一意でなければ停止する。
- resource候補はprimary identifierなどsecretを含まない最小情報だけを提示し、候補が一件でもhumanが選択するまで取得対象を確定しない。primary identifierがARNの場合はresource選択と取得のためだけに一時利用してよい。
- humanがresourceを選択した後は、選択済みpropertyの現在値を再確認なしで詳細設計へ直接差分反映する。既存fileの未選択resourceと未選択propertyは維持し、AWS現在値に存在しない選択済みoptional propertyのrowは削除する。対応するresource sectionがなければlogical IDをhumanへ一つ質問し、service metadata、anchor、heading、tableを既存ruleどおり作成する。
- password、secret、token、credentialなどの機密値は表示または保存しない。generated ARNは詳細設計、JSON artifact、modelへ保存せず、resource選択またはAPI実行に必要な処理中だけ使用する。
- resourceの作成者、管理者、外部作成済みという出自は詳細設計またはmodelへ保存しない。詳細設計はtarget environmentに存在する設定を同じresource table形式で保持する。
- AWS mutation、IaC作成・変更、deploy/apply、scenarioへ進まない。

## AWS service ownership boundary

詳細設計のfile grouping unitは、security boundaryやIAM Permissions Boundaryではなく、人間が認識するAWS serviceごとの責務を表すAWS service ownership boundaryとする。一つのdesign fileは一つのAWS serviceだけを所有する。

- target directoryは`project.json`のtargetにaliasがあればalias、なければAWS account IDとする。
- fileは`docs/designs/<environment>/<target-directory>/<service-id>.md`に置く。
- Service IDはlower-kebab-caseとし、file stemおよび対応する`model/<environment>/<target-directory>/<service-id>.properties`と一致させる。
- 同じAWS serviceに属する複数resource typeとinstanceは同じfileに置いてよい。
- 運用上関連するだけの別AWS serviceを同じfileへ入れない。CloudFormation resource namespaceだけでgroupingを決めない。
- child componentは親resourceと同じAWS serviceに属する場合だけ同じfileに置いてよい。別AWS serviceのresourceはchild componentとして扱わない。
- IAM RoleとPolicyは利用先service専用でもIAM service fileへ置く。
- CloudWatch Logs resourceは利用元serviceではなくCloudWatch Logs service fileへ置く。
- VPC Flow LogはAmazon VPCのservice fileへ置き、IAM RoleとLog Groupをcross-file referenceで参照する。
- service間dependencyはfile統合ではなくrelative Markdown linkとexplicit anchorで表し、generated modelへ同じreferenceを保持する。
- 未使用serviceの空design fileを作らない。
- design file boundaryとCloudFormation stack/template boundaryは別概念とする。

generic validatorがservice ownershipを判断するため、各Markdownには次のmachine-readable service metadataだけを正確に1件ずつ記載する。

```md
- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`, `EC2.FlowLog`
```

- Owned catalog resource typesには`framework/materials/aws/*.properties`に存在し、このservice fileが所有するresource typeだけを記載する。
- 同じenvironment/target directory内で同じcatalog resource typeを複数service fileが所有してはいけない。

## Markdown structure

保存対象Markdownは、原則としてH1 title、service metadata、resourceごとのexplicit anchor、resource heading、resource-detail tableだけで構成する。tableだけでは表現できない場合に限り、必要最小限のimplementation noteを追加してよい。

- title、heading、implementation note、`Source / Comment`を含む説明文は日本語で記載する。AWS service/resource/propertyの正式名称、logical ID、code、JSON keyなど翻訳すると意味が変わる値は原文のままでよい。
- catalog-backed resource headingは`## <catalog-resource-type>: <logical-id>`とする。
- `Environment`、`AWS account ID`、`AWS region`、`Purpose`、`Deployment state`をfile metadataとして記載しない。これらは`project.json`、`docs/system-overview.md`、active task、`model/**`の該当する正本を参照する。
- `Design decisions`、`Out of scope`、`Generated values`または同義の日本語sectionを作らない。
- 確定済みの設計値は該当resource/component tableへ記載する。
- 対象外事項はactive taskまたはchatの完了報告だけに記載する。

## Resource-detail table

すべての resource-detail table は次の header と alignment row を正確に使う。

```md
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
```

- 各 table の row は 1 から連番にする。
- 1 file に複数 resource heading と table を置いてよい。
- Listener、Route、association、UserData、Bucket Policy などの child component は独立 table にしてよい。
- `framework/materials/aws/*.properties`はresource-detail tableへ載せてよい設計項目の選択リストとし、`Property`は同じspellingを使う。
- 選択項目の存在、型、`enum`、`pattern`、長さ、範囲、`required`は`framework/materials/cloudformation-schema/ap-northeast-1/`のCloudFormation provider schemaを正本とする。
- catalogにないrowは作成しない。generated current identifierも後述の`IDENTIFIER_OUTPUT` catalog propertyを使用する。derived documentation fieldやimplementation情報は必要最小限のtable外noteにする。
- catalog の全 field を掲載せず、選択済みで必要な design field だけを載せる。
- IaC template path を AWS resource property のように table に入れない。implementation note は table 外の prose section に書く。
- optional propertyを使用しない場合はrow自体を省略する。`not-used`、`none`、`UNSET`などのsentinel値や、schemaに存在しない説明用propertyを作らない。
- schemaの`required`に指定され、かつproperties選択リストにあるroot propertyは省略しない。

`Source / Comment`は、そのrowの`Property`が何を設定、識別、制御する属性なのかを日本語で説明する。次の内容は記載しない。

- `確定済み設計値`、`選択済み`、`承認済み`などの決定状態
- `人間が選択した`、`human-selected`などの決定主体
- `共通タグ`、`リソース固有タグ`などの分類だけの説明
- 設計値の出典、決定経緯、更新証跡、verification結果
- `Value`を意味なく言い換えただけの説明

例えば、VPCのCIDRには`VPCで使用するIPv4アドレス範囲`、inline policy nameには`IAM Roleへ埋め込む権限ポリシーの名前`、project tag keyには`リソースが属するプロジェクトを識別するタグのキー`と記載する。更新根拠やverification結果は詳細設計へ保存せず、observed valueまたは完了報告を扱う既存ルールに従う。

## JSON design artifacts

選択済みpropertyをJSON documentとして表現する必要がある場合、JSONをMarkdown tableへ埋め込まず、次の独立artifactとして保存する。

```text
docs/designs/<environment>/<target-directory>/<service-id>/<artifact-id>.json
```

- `<artifact-id>`は内容と所有resourceを表すstableなlower-kebab-caseとする。
- artifactはそのJSON propertyを持つresourceのAWS service ownership boundaryへ置く。IAM Roleのtrust/permissions policyは`iam/`、`EC2.VPCEndpoint.PolicyDocument`はendpointを所有する`vpc/`へ置く。
- 一つのJSON fileは一つのpolicy documentを保持する。複数のinline policyは別fileへ分ける。
- resource tableの`Value`は同じservice directoryのJSON fileへのrelative Markdown linkとする。
- JSONは構文的に有効なobjectとし、AWS policy key、Action、Condition keyなどの識別子を日本語化しない。
- 対応するgenerated service modelはJSON本文を複製せず、Markdownのrelative artifact linkとJSON内容のSHA-256を保持する。

### IAM Role policy artifact names

IAM Roleが所有するpolicy JSON artifactは、Roleのlogical IDを`<role-artifact-id>`として次の名前を使う。

- `IAM.Role.AssumeRolePolicyDocument`は`<role-artifact-id>-trust-policy.json`とする。`assume-role-policy-document`、`assume-role-policy`などの旧suffixを使わない。
- `IAM.Role.Policies[].PolicyDocument`は、同じinline policyの`IAM.Role.Policies[].PolicyName`を直前のrowへ明示し、`<role-artifact-id>-<policy-name-artifact-id>.json`とする。
- `PolicyName`が未確定の場合はartifact名を推測せずblockerとして停止する。一つのinline policy artifactは一つの`PolicyName`と一対一にし、複数policyはそれぞれ別artifactとする。
- `inline-policy-document`、`inline-policy`、`permissions-policy`など、`PolicyName`を表さないgeneric suffixを使わない。

`<role-artifact-id>`と`<policy-name-artifact-id>`は入力literalを次の順でlower-kebab-caseへ変換する。

1. acronymと通常wordの境界を分割する。
2. lowercaseまたはdigitからuppercaseへの境界を分割する。
3. 英数字以外を`-`へ置換する。
4. lowercase化する。
5. 連続する`-`を一つにし、先頭末尾の`-`を除去する。

例は`VPCFLOWLOGROLE01`から`vpcflowlogrole01`、`VPCFlowLogsToCloudWatchLogs`から`vpc-flow-logs-to-cloud-watch-logs`とする。AWS service名辞書や個別例外は使わない。IAM Role以外のpolicy artifactは既存のstable lower-kebab-case規約を維持する。

## Links and anchors

- 関連 resource は `Value` column の Markdown link で表す。
- link は relative path を使う。
- renderer 自動生成だけに依存せず、resource heading の直前に explicit HTML anchor を置く。
- anchorはlower-case Service IDとlower-case logical IDを`-`で結ぶ。
- 別fileの例: `[FLOWLOGROLE01](iam.md#iam-flowlogrole01)`。
- 同じfileの例: `[FLOWLOG01](#vpc-flowlog01)`。
- file と anchor の存在を local loop で検証する。
- catalogのidentifier outputを参照するpropertyは、link先anchorをlogical referenceの正本とし、表示textへ参照先のcurrent physical IDを記載する。deploy前とdestroy後は`[PENDING_DEPLOY](#vpc-vpc01)`、deploy成功後は`[vpc-0123456789abcdef0](#vpc-vpc01)`とする。
- IaC生成は表示textのphysical IDを使用せず、link先anchorに対応するresource headingのlogical IDを解決する。CloudFormationは`!Ref`、Terraformはresource attribute referenceを使用し、physical IDを直書きしない。

## Generated values and deployment state

- 必要なnon-ARN generated current identifierは独立sectionではなく、`framework/materials/aws/*.properties`で`IDENTIFIER_OUTPUT`と指定された正式なcatalog propertyを該当resource tableの個別行に記載する。`VPC ID`や`Subnet ID`などの合成labelを作らない。
- 未作成resourceのdeploy前はidentifier output rowの値を`PENDING_DEPLOY`とする。例えば`EC2.VPC.VpcId`の`Source / Comment`はprefixや取得元ではなく属性の意味だけを表す`VPCを一意に識別するID`とする。
- current identifierは、infrastructure taskのdeploy/apply成功後、またはdesign taskが選択済み既存resourceをread-only取得した場合だけ実値へ更新する。同じidentifierを参照する全propertyのMarkdown link表示textも同じphysical IDへ更新し、`Source / Comment`は属性の意味を維持する。
- replacement後はidentifier output rowと全参照元を新しいphysical IDへ同じ変更で更新する。destroy後はidentifier output rowを`PENDING_DEPLOY`へ戻し、全参照元のlink表示textも`PENDING_DEPLOY`へ戻す。
- human-selected nameなど通常のcatalog propertyがcurrent identifierになるresourceは、そのpropertyを使用し、`IDENTIFIER_OUTPUT`でない重複rowを作らない。
- generated ARNは詳細設計にも`model/**`にも永続化しない。
- old physical valueはGit履歴とAWS/IaC deployment historyで追跡し、詳細設計やscenario evidenceへ保存しない。
- `model/**`はidentifier output rowとidentifier参照rowの同じrow keyに、anchorから解決したlogical referenceを`desired.*`、Markdownの表示textまたはidentifier output valueを`observed.*`として保持する。

deploy前の参照例:

```md
| 4 | EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc01) | Subnetが所属するVPC |
```

deploy後の参照例:

```md
| 4 | EC2.Subnet.VpcId | [vpc-0123456789abcdef0](#vpc-vpc01) | Subnetが所属するVPC |
```

resource自身のidentifier output例:

```md
| 7 | EC2.VPC.VpcId | vpc-0123456789abcdef0 | VPCを一意に識別するID |
```

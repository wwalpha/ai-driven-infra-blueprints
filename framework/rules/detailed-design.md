# Detailed Design Rules

## Task boundary

- `design` taskはintended designを更新し、対応するservice modelを`framework/scripts/sync-model.py`で生成してlocal validation後に終了する。chatbotが指定した既存resource取得では必要な非ARN current identifierも反映できる。IaC、AWS mutation、scenarioへ自動的に進まない。
- `infrastructure` taskはintended designを変更しない。deploy/apply成功後のgenerated current valueだけを詳細設計へ反映できる。
- infrastructure `update` phaseは、humanがtask開始前に手動修正した未commitのintended designをimmutable inputとして受け取れる。Codexはそのintended designを変更せず、deploy/apply成功後のgenerated current valueだけを追加更新できる。
- designの不足または変更が必要な場合、infrastructure taskは停止して別のdesign taskを要求する。

## Existing resource configuration

chatbotが既存AWS resourceの現在値取得を指定した場合だけ、Codexの`design` taskは次を実行できる。

- 取得対象はchatbotが確定したtarget AWS service、catalog resource type、propertyに限定する。`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`では詳細設計専用の`.Name` propertyを含め、それ以外の別service、同じresource typeの未選択property、materialsにないpropertyへ自動的にscopeを広げない。
- repository変更前に`project.json`のtarget、credentialのcaller account、regionをread-only preflightで検証する。
- AWS Cloud Control APIのList／Readを第一候補とし、非対応resource typeだけ対象service固有のread-only APIを使用する。AWS値とmaterials／provider schema propertyの対応が一意でなければ停止する。
- resource候補はprimary identifierなどsecretを含まない最小情報だけを提示し、候補が一件でもhumanが選択するまで取得対象を確定しない。primary identifierがARNの場合はresource選択と取得のためだけに一時利用してよい。
- humanがresourceを選択した後は、選択済みpropertyと対象resourceでmandatoryな`Name` tagの現在値を`.Name`へ直接差分反映する。既存fileの未選択resourceと未選択propertyは維持し、AWS現在値に存在しない選択済みoptional propertyのrowは削除する。mandatory `Name` tagが存在しない場合は値を発明せず停止する。対応するresource sectionがなければ、上記3種類は`.Name` valueをheading identifierとして使用し、それ以外はlogical IDをhumanへ一つ質問してservice metadata、anchor、heading、tableを既存ruleどおり作成する。
- password、secret、token、credentialなどの機密値は表示または保存しない。generated ARNは詳細設計、JSON artifact、modelへ保存せず、resource選択またはAPI実行に必要な処理中だけ使用する。
- resourceの作成者、管理者、外部作成済みという出自は詳細設計またはmodelへ保存しない。詳細設計はtarget environmentに存在する設定を同じresource table形式で保持する。
- AWS mutation、IaC作成・変更、deploy/apply、scenarioへ進まない。
- 上記section作成にも`resource-layout.json`を適用し、grouped childは独立headingを作らない。選択済みの親propertyの現在値と設計済み親のcurrent identifierから所属を確認し、親table内へ反映する。所属が不明または親の設計がない場合は停止し、未選択resource/propertyへscopeを広げない。

## AWS resource naming

- human-selectedなAWS resource name、identifier、または`Name` tagを新規決定する場合は`framework/rules/aws-resource-naming.md`を適用する。
- root-levelの`Tags`または`HostedZoneTags`があっても`Name` tagを自動的に必須化しない。mandatory対象は`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`だけとし、詳細設計ではそれぞれ`.Name`の1 rowで表す。
- 上記3種類の`.Name`は詳細設計専用propertyであり、provider schemaのresource propertyではない。IaC実装時にcase-sensitiveな`Name` keyを持つtagへ変換し、詳細設計へ`Tags[].Key=Name`と`Tags[].Value`の2 rowを作らない。
- その他のresourceではhumanが`Name` tagを明示した場合だけ設計する。array形式では`Tags[].Key`または`HostedZoneTags[].Key`へ`Name`、直後の対応する`Value` rowへnon-empty nameを記載する。object形式では`Tags`に`Name` keyとnon-empty valueを持つJSON objectを記載する。
- naming componentがすべて確定済みならpatternから一意に導出し、未確定componentがあれば値を推測せずhumanへ確認する。
- 既存resourceから取得した名称と既存詳細設計の確定済み名称は、conventionと異なっても自動変更しない。
- 既存resourceに必須の`Name` tagが存在しない場合は`.Name` valueを発明せず、blockerとして停止する。
- final nameはprovider schemaとservice固有制約へ適合することを確認し、自動truncate、hash付与、略語化で補正しない。

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

- Owned catalog resource typesには`framework/materials/aws/*.properties`または`framework/materials/api/*.properties`に存在し、このservice fileが所有するresource typeだけを記載する。
- 同じenvironment/target directory内で同じcatalog resource typeを複数service fileが所有してはいけない。

## Markdown structure

保存対象Markdownは、原則としてH1 title、service metadata、resource一覧、resourceごとのexplicit anchor、resource heading、resource-detail tableだけで構成する。policy JSONを持つresourceは後述のJSONから生成するStatement表または設定表も持つ。tableだけでは表現できない場合に限り、必要最小限のimplementation noteを追加してよい。

- title、heading、implementation note、`Source / Comment`を含む説明文は日本語で記載する。AWS service/resource/propertyの正式名称、logical ID、code、JSON keyなど翻訳すると意味が変わる値は原文のままでよい。
- 独立表示するcatalog-backed resource headingは`## <catalog-resource-type>: <logical-id>`とする。親へ統合するresourceは後述の共通表示contractに従う。
- `S3.Bucket`だけは`## S3.Bucket: <BucketName>`とし、heading identifierを同じtableの`S3.Bucket.BucketName` valueと完全一致させる。
- `EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`の`<logical-id>`は同じtableの`.Name` valueと完全一致させる。
- `Environment`、`AWS account ID`、`AWS region`、`Purpose`、`Deployment state`をfile metadataとして記載しない。これらは`project.json`、`docs/system-overview.md`、active task、`model/**`の該当する正本を参照する。S3 Bucketの配置regionだけは後述のdesign-only `S3.Bucket.Region` rowにbucketごとの確定値を表示する。
- `Design decisions`、`Out of scope`、`Generated values`または同義の日本語sectionを作らない。
- 確定済みの設計値は該当resource/component tableへ記載する。
- 対象外事項はactive taskまたはchatの完了報告だけに記載する。

## Resource overview

各詳細設計fileはservice metadataの直後、最初のresource anchorより前に`## リソース一覧`を正確に1件置く。

- 一覧内はdetail blockを持つcatalog resource typeごとに`### <catalog-resource-type>`とtableを一つ置く。grouped child resource typeと下記のSubnet一覧に統合するAssociationは独立一覧を作らない。
- tableは1 resourceを1 rowで表示し、最初のcolumnはdetail blockへのsame-file linkにする。Subnet一覧に統合するAssociationを除く全detail blockを重複なく一覧へ載せる。
- columnはresource識別子を含めて2〜6個に絞る。識別・配置・security・可用性・保持期間など、resource間の比較に重要な確定済みparameterをdetail tableから選ぶ。
- column名は`BucketName`、`Region`、`SSEAlgorithm`、`KMSAlias`、`Versioning`、`RetentionDays`のような短く一意な名前とし、`S3.Bucket.BucketName`のようなcatalog prefix付きproperty pathを使用しない。
- IAM.Roleの一覧だけは後述の固定3列を使用し、最初のcolumnにRoleNameを表示する。日本語のpolicy列名を許可する。他のresource typeでpolicy JSONが選択されている場合は、選択済みの2〜6列に生成専用の`Policies`列を末尾へ追加する（合計最大7列）。同じtypeのpolicy未設定resourceは表示だけを`—`とする。
- 一覧は人間向けの派生summaryであり、intended designの正本ではない。値はdetail tableと一致させ、generated service modelへ重複保持しない。

`EC2.SubnetRouteTableAssociation.SubnetId`が同じfileの`EC2.Subnet`詳細へlinkしている場合、そのAssociationは該当Subnetの一覧rowへ統合する。

- `EC2.Subnet`一覧に`RouteTableId`を含め、合計2〜6列を維持する。`RouteTableId`はAssociation詳細の同名propertyのValueをそのまま表示する。`AssociationId`列は記載せず、Association詳細への一覧linkも不要とする。
- 対応は`SubnetId`のlink先anchorで確定し、physical ID、`PENDING_DEPLOY`、出現順で推測しない。同じSubnetへ複数のAssociationを割り当てない。
- 同じ一覧にAssociation未設計のSubnetがある場合、`RouteTableId`は表示だけを`—`とする。Main Route Tableなどの値を補完しない。
- 統合したAssociationの独立一覧rowは作らない。同じfileに参照先Subnetの詳細がないAssociationだけは独立一覧を維持する。
- Association自身のmetadata、anchor、heading、4列の詳細tableとmodelは維持する。この扱いは一覧だけの統合であり、`resource-layout.json`の詳細表示は変更しない。

S3の例:

```md
## リソース一覧

### S3.Bucket

| BucketName | Region | KMSAlias | Versioning |
| --- | --- | --- | --- |
| [app-dev-data-123456789012](#s3-app-dev-data-123456789012) | `us-east-1` | `alias/app-data` | `Enabled` |
```

## Resource-detail table

すべての resource-detail table は次の header と alignment row を正確に使う。

```md
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
```

- 各 table の row は 1 から連番にする。
- catalogで`IDENTIFIER_OUTPUT`と指定された全rowを、Propertyのcatalog順でtable先頭の連続rowとして配置する。通常propertyとidentifier参照rowはその後へ置く。
- `S3.Bucket`はbucketごとに一つのanchor、`## S3.Bucket: <BucketName>` heading、tableを使用する。heading identifierとanchorのidentifier部分は`S3.Bucket.BucketName` valueに一致させる。`S3.Bucket.BucketName`をtableの先頭row、design-only `S3.Bucket.Region`を2行目に置き、RegionのValueはbucketごとにhumanが確定したAWS region IDとする。`project.json`のtarget `awsRegion`は自動転記せず、`us-east-1`など別regionを許可する。対応する`S3.BucketPolicy`を設計する場合は、`S3.BucketPolicy.PolicyDocument`だけを同じtableの`S3.Bucket` rowの後へ置く。対象bucketは包含するblockから暗黙に特定し、`S3.BucketPolicy.Bucket` row、独立anchor、heading、tableは作らない。
- general purpose `S3.Bucket`でSSE-KMSを使用する場合、`S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID`のValueは、同じtargetに設計した`KMS.Alias`のanchorへのresource linkとし、linkの表示textはその`KMS.Alias.AliasName`と一致させる。`KMS.Key.KeyId`のgenerated valueは表示しない。
- 1 file に複数 resource heading と table を置いてよい。
- resource-detail tableの独立表示と親への統合は`framework/rules/resource-layout.json`を正本とする。未登録の型を推測で分割・統合せず、framework保守が必要なblockerとして停止する。リソース一覧の表示単位はResource overviewに従う。
- `framework/materials/aws/*.properties`と`framework/materials/api/*.properties`はresource-detail tableへ載せてよい設計項目の選択リストとし、`Property`は同じspellingを使う。`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`、`S3.Bucket.Region`だけをdesign-only exceptionとする。
- CFn由来の選択項目の存在、型、`enum`、`pattern`、長さ、範囲、`required`は`framework/materials/cloudformation-schema/ap-northeast-1/`のCloudFormation provider schemaを正本とする。design-only `.Name`には`framework/rules/aws-resource-naming.md`のpatternを適用し、`S3.Bucket.Region`はnon-emptyのlower-kebab-case AWS region IDとする。
- 上記4種類のdesign-only property以外にcatalogにないrowを作成しない。generated current identifierも後述の`IDENTIFIER_OUTPUT` catalog propertyを使用する。derived documentation fieldやimplementation情報は必要最小限のtable外noteにする。
- catalog の全 field を掲載せず、選択済みで必要な design field だけを載せる。
- IaC template path を AWS resource property のように table に入れない。implementation note は table 外の prose section に書く。
- optional propertyを使用しない場合はrow自体を省略する。ただし`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`とS3 Bucketの`S3.Bucket.Region`は省略しない。これら以外にschemaに存在しない説明用propertyを作らず、`not-used`、`none`、`UNSET`などのsentinel値を記載しない。
- schemaの`required`に指定され、かつproperties選択リストにあるroot propertyは省略しない。

`Source / Comment`は、そのrowの`Property`が何を設定、識別、制御する属性なのかを日本語で説明する。次の内容は記載しない。

- `確定済み設計値`、`選択済み`、`承認済み`などの決定状態
- `人間が選択した`、`human-selected`などの決定主体
- `共通タグ`、`リソース固有タグ`などの分類だけの説明
- 設計値の出典、決定経緯、更新証跡、verification結果
- `Value`を意味なく言い換えただけの説明

例えば、VPCのCIDRには`VPCで使用するIPv4アドレス範囲`、inline policy nameには`IAM Roleへ埋め込む権限ポリシーの名前`、project tag keyには`リソースが属するプロジェクトを識別するタグのキー`と記載する。更新根拠やverification結果は詳細設計へ保存せず、observed valueまたは完了報告を扱う既存ルールに従う。

## API-backed design resources

詳細設計の対象とIaCで作成できる対象を分離する。CFn非対応でも、登録済みのAPI catalog resourceは通常のservice metadata、リソース一覧、anchor、heading、4列の詳細表、generated modelへ含める。CFn非対応を理由に詳細設計を省略しない。

- 現在の対象は`Macie.ClassificationJob`だけとする。`Macie.Session`と同じ`macie.md`に置き、Jobごとに`## Macie.ClassificationJob: <logical-id>`を作る。表示関係は`resource-layout.json`に従う。
- 選択リストは`framework/materials/api/Macie_ClassificationJob.properties`、型・制約は同名の`.json`を正本とする。公式Macie APIのrequest/responseに基づく固定した設計用schemaであり、CloudFormation provider schemaではない。参照元、API version、取得元hash、確認日、`cloudFormationType: null`はframework側に保持し、詳細設計のAWS propertyとして追加しない。
- APIの正式な大小文字を維持し、`Macie.ClassificationJob.name`、`jobType`、`s3JobDefinition`などを使用する。catalogにないfield、架空のCFn型、実行時の`clientToken`、生成された`jobArn`を追加しない。
- 選択単位はAPIのroot propertyとする。`s3JobDefinition`、`scheduleFrequency`、`tags`はJSON object、識別子の配列はJSON arrayとしてValueへ記載する。長いobjectは既存のservice配下JSON artifactへのlinkを使用できる。配列要素の所属を失うleaf rowへの分解や、JSON内部へのMarkdown link埋込みは行わない。関連resourceへの説明上の参照には通常のrelative Markdown linkを使用する。
- `name`、`jobType`、`s3JobDefinition`を必須とし、未知のproperty、型、enum、長さ、範囲、nested object/arrayも検証する。未使用のoptional配列は空配列でなくrowを省略する。
- `SCHEDULED`は実行周期を正確に一つ指定する。`ONE_TIME`は`scheduleFrequency`と`initialRun`を省略する。S3対象は`bucketDefinitions`または`bucketCriteria`のどちらか一つにする。managed data identifierの選択方式とID配列、custom data identifierの必須関係も検証する。
- `Macie.ClassificationJob.jobId`は`IDENTIFIER_OUTPUT`としてtable先頭に置く。未作成は既存の`PENDING_DEPLOY`、取得済みは非ARNの実IDとする。この値はCFnでの作成予定を意味しない。
- 既存Jobの取得がactive taskで許可されている場合、`ListClassificationJobs`で候補を提示し、humanの選択後に`DescribeClassificationJob`で選択済みroot propertyと必要な`jobId`だけを取得する。Cloud Control API用の型は生成しない。optional fieldが欠落またはnullならrowを省略し、response全体、統計、実行状態、生成ARNを保存しない。
- API catalogを使用しても`design` taskのAWS mutation禁止とlocal validation後の終了を維持する。設計書の作成はJob作成の自動化、Custom Resource、Terraform導入を許可しない。

## Related resource display

`framework/rules/resource-layout.json`は全catalog resourceの詳細blockについて、`independent`または親へ統合する関係を明示する。独立した詳細blockを持つresourceでも、Resource overviewで定める条件に従って一覧rowへまとめられる。表示上のまとまりとAWS/IaC resourceの識別・lifecycleを分離する。

- 統合定義の`parent`は包含するresource type、`parentProperty`は子から親への正式property、`maxCount`は親あたりの子の最大数（`null`は複数可）、`identityProperty`は子を識別する先頭propertyとする。
- 親の全rowの後に子のrowを同じtableへ置き、No.はtable全体で連番にする。子の独立heading・table・一覧は作らない。子のresource typeも`Owned catalog resource types`へ含める。
- `parentProperty`のrowは省略し、包含する親へのlogical referenceとして解決する。外部の既存親を参照する子だけの設計はこの形式では表現せず、対応する親の設計または別の表示contractが必要であることを報告する。
- `identityProperty`がない単一の子は親のmodelへrowを保持する。既存のS3 BucketPolicyはこの形式を維持する。
- `identityProperty`がある子は、そのpropertyのrowから次の子のidentity rowまでを一つのinstanceとする。identity rowの`Source / Comment`先頭に`<a id="<service-id>-<logical-idのlowercase>"></a><!-- logical-id: <logical-id> -->`を置き、その後に日本語で属性の意味を記載する。この非表示markerは参照・識別用の構造情報であり、説明文やAWS propertyではない。
- 子のlogical IDは既存の確定値を保持する。新規で未確定ならhumanへ確認し、順番やAliasNameから推測して作らない。親子を通じてanchorとlogical IDを重複させず、同じ子のidentity valueを複数の親へ重複配置しない。
- 外部からの参照は子のanchorへ維持する。親へのlinkに置換したり、先頭の子を代表として選んだりしない。
- 各子のpropertyはその子自身のprovider schemaで検証する。所属親が異なる型、独立heading、欠落した識別情報、子の個数超過、重複、参照切れをlocal loopで拒否する。

KMSは`KMS.Key`のtable内に0個以上の`KMS.Alias`をまとめる。`KMS.Alias.TargetKeyId` rowは省略する。KeyId、Keyの設定、AliasNameの順とし、複数AliasではAliasName rowと識別markerをそれぞれ保持する。Key一覧の`AliasNames`列には対応するalias名を表示できる。

```md
<a id="kms-s3filetransferkey01"></a>

## KMS.Key: S3FILETRANSFERKEY01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | KMS.Key.KeyId | `PENDING_DEPLOY` | KMS keyを一意に識別するID |
| 2 | KMS.Key.EnableKeyRotation | `true` | key materialの自動rotationを有効にする設定 |
| 3 | KMS.Alias.AliasName | `alias/venus-dev-s3-file-transfer` | <a id="kms-s3filetransferkeyalias01"></a><!-- logical-id: S3FILETRANSFERKEYALIAS01 --> KMS keyを識別するalias |
```

S3の`KMSMasterKeyID`は引き続き`[alias/venus-dev-s3-file-transfer](kms.md#kms-s3filetransferkeyalias01)`とし、AliasNameを表示する。

新規catalog resourceの保守時には、同一service内の所属先、一対多、共有・複数対象、外部参照を確認して表示方針も登録する。schemaの型名や参照propertyだけから親子を自動推測しない。SQS/SNSの複数対象policy、IAM共有policy、associationのような共有・接続resourceを一つの親へ無条件に統合しない。条件付き統合が必要な場合は判定条件と検証を先に実装する。現時点でS3とKMS以外の詳細blockは独立表示を維持し、方針変更は明示scopeのframework taskで行う。

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
- JSONはUTF-8、LF、file末尾改行ありで保存する。配列の1行・複数行表示はformatterに任せ、repository ruleで強制しない。
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

## Service policy tables

設定表のpolicy JSONリンクだけでなく、所有resourceの設定表直後にJSON本文の派生表示を生成する。resource設定はMarkdownのproperty row、policy本文はそのrowが参照するJSON artifactを正本とし、派生表示を独立した設計入力にしない。

### 対象と形式

表示方式の機械可読な定義は`framework/scripts/policy_tables.py`の`POLICY_FORMATS`とする。正式なcatalog propertyを完全一致で登録し、provider schemaで型を確認する。property名の末尾だけでpolicy documentと判定しない。catalogへdocument形式のpolicy propertyを追加する場合は、表示方式の登録とfocused checkも同じ明示scopeのtaskで更新する。

| 形式 | 対象 |
| --- | --- |
| Statement表 | IAM Roleのtrust／inline、IAM ManagedPolicy、S3 BucketPolicy、KMS KeyPolicy、VPC endpoint、SQS／SNS、ECR repository、Secrets Manager、CloudWatch Logsのresource policy、API Gateway、EventBridge、SSO PermissionSet inline、DynamoDBのtable／stream／replica policy |
| 内包するStatement表 | `DynamoDB.Table.ResourcePolicy`のJSON object内の`PolicyDocument`。外側の構造を保持し、未知のwrapper keyは省略せず停止する |
| 設定表 | SNSのdelivery／filter／redrive／replay／archive／data protection、SQSのredrive／redrive allow、CloudWatch Logsのdata protection、ECR lifecycle |

`SecurityPolicy`、`SslPolicy`、policy名、ARN、booleanなどのscalar／referenceは通常の設定行を維持する。CloudFrontやNetwork Firewall、Auto Scaling等のcatalogで個別propertyへ展開されているpolicy設定も既存の4列表へ記載する。選択していないpolicy、policy名、権限を表示のために作成・補完しない。

### 所属と派生表示

- IAM Roleは下記の既存一覧・表・markerを維持する。それ以外は所有resourceの設定表直後を`<!-- policy-tables:start -->`と`<!-- policy-tables:end -->`で囲み、所有するpolicyを設定行の順に生成する。
- S3 BucketPolicyは引き続きBucketの設定表内へ置き、派生policy表もBucketに所属させる。KMSのAliasはKeyと同じ設定表内の既存groupingを維持する。SQS/SNSなど複数resourceを対象とする独立policyを、一つの対象へ勝手に統合しない。
- IAM Role以外の表示名はJSONリンクの表示text、anchorは`<resource-anchor>-policy-<artifact-id>`とする。artifact IDは既存のlower-kebab-case filename stemを使用する。同一resource内の複数policyには異なるartifactを使用し、anchor衝突は停止する。配列の各対象へ設定するpolicyも各JSONリンクから識別できるようにする。
- 見出しは`### ポリシー：<表示名>`または`### ポリシー設定：<表示名>`とし、正式な`Property`と元の`JSON`リンクを表の前に表示する。表示名を架空のresource propertyとして追加しない。
- IAM Role以外の一覧の`Policies`列には、その行のresourceが所有するpolicy表へのsame-file linkを`<br>`区切りで生成する。元の比較列と行順を維持する。同じtypeの全resourceからpolicyがなくなった場合は生成列を除去する。
- Statement表の連番、列、Principal展開、Condition、Version/Id、escape、省略禁止、未知要素の拒否は下記のIAMと同じ方式を使用する。権限policy以外のJSONをStatement形式と推測しない。
- 設定表は`Property | Type | Value`とし、PropertyはJSON Pointer、Typeは`object`／`array`／`string`／`number`／`boolean`／`null`を表示する。root pointerは空文字列、object keyは文字列順、配列は0始まりのindexと元の順序を保持する。`~`と`/`はpointer内で`~0`と`~1`へescapeする。子を持つcontainerのValueは表示だけを`—`、空object／arrayは`{}`／`[]`とする。全要素を表示し、構造や型を変換しない。
- `ECR.Repository.LifecyclePolicy`はwrapperの全設定を表示したうえで、`LifecyclePolicyText`がある場合はJSON文字列をparseした内容も設定表で表示する。JSON文字列以外や不正なJSONは停止する。表示からJSON本文を書き戻さない。
- 全形式で重複JSON key、不正なJSON定数、JSON object以外のartifact、他service配下のartifact参照を拒否する。marker欠落・重複・不正な所属、表や一覧リンクと正本との不一致をlocal loopでFAILとする。
- 生成は指定したMarkdown一件の派生範囲とpolicy一覧列だけを更新する。modelには派生表示を重複保持せず、既存のJSONリンクとcanonical hashを維持する。

policyを含む設計を保存・変更した後、model生成前に実行する。`--write`なしはread-onlyの一致検証になる。

```console
python3 framework/scripts/policy_tables.py docs/designs/<environment>/<target-directory>/<service-id>.md --write
```

### IAM Role policy tables

IAM Roleの4列のresource-detail tableと独立policy JSON artifactを維持し、各Roleの設定表の直後に信頼ポリシーとinline policyのStatement表を生成する。Roleの設定はMarkdownのproperty row、policy本文はそこから参照するJSON artifactを正本とする。Statement表はJSONの派生表示であり、独立した設計入力にしない。

- `## リソース一覧`内の`### IAM.Role`は`RoleName | 信頼ポリシー | インラインポリシー`の3列にする。RoleNameは対応するresource anchorへのsame-file link、policy名はそのRoleのpolicy anchorへのsame-file linkとする。複数inline policyは同じcellで`<br>`区切りにする。設定表にRoleNameがない場合は表示だけを`（RoleName未指定）`、inline policyがない場合は表示だけを`—`とし、propertyや名前を生成・推測しない。
- `Path`、`ManagedPolicyArns`、`PermissionsBoundary`など選択済みの他のRole設定は既存の4列表に保持する。IAM.ManagedPolicyとIAM.InstanceProfileの独立resource表示も維持する。
- 信頼ポリシーの表示名は`AssumeRolePolicyDocument`のJSONリンクの表示textを使用する。`FlowLogsTrust`は文書上の表示名であり、架空の`TrustPolicyName` propertyや独立IAM resourceを追加しない。inline policyの表示名は直前の`Policies[].PolicyName`を使用する。
- policy anchorは`<role-anchor>-trust`、`<role-anchor>-inline-<policy-name-artifact-id>`とする。inline suffixの正規化は既存のartifact命名と同じ処理を使い、別Roleの同名policyを混同しない。同一Roleで正規化後のanchorが衝突する場合は停止する。
- 見出しは`### 信頼ポリシー：<表示名>`または`### インラインポリシー：<PolicyName>`とする。JSONにある場合だけ`Version：`と`Id：`を表示し、値を補完しない。
- 表は1 Statementを1行とし、先頭列は`Statement`の1始まりの連番とする。JSONのStatement配列順を維持し、Statementが単一objectの場合は1行にする。表の番号と任意の`Sid`は別物とし、`Sid`を発明・変更しない。
- 列は`Statement`に続き、JSONに存在する`Sid`、`Effect`、`Principal`、`NotPrincipal`、`Action`、`NotAction`、`Resource`、`NotResource`、`Condition`をこの順序で掲載する。Principalがobjectなら`Principal.Service`、`Principal.AWS`、`Principal.Federated`、`Principal.CanonicalUser`のように種別ごとに展開する。NotPrincipalも同様とし、種別の列順は文字列順とする。Statement間で存在しない列のcellは表示だけを`—`にする。
- 複数Action・Resource・Principal値はcell内で`<br>`区切りにする。Conditionは演算子、context key、値を省略せず、演算子とkeyの文字列順で同じcellへ表示する。複数の条件値はJSON配列として表示し、条件の演算子や配列構造を変えない。Conditionを理由にStatementを分割・統合しない。
- JSON object key順やindentだけの変更では表を変えない。文字列内のMarkdown/HTML特殊文字をescapeし、表示上のescapeをJSON値へ書き戻さない。空配列も省略せず表示する。未知のpolicy/Statement要素、重複JSON key、解釈できない構造は黙って省略せず停止する。
- Roleごとの生成範囲は`<!-- iam-policy-tables:start -->`と`<!-- iam-policy-tables:end -->`で囲む。marker内にはそのRoleのpolicy anchor、見出し、Version/Id、Statement表だけを置く。設定表や手動のimplementation noteを入れない。markerの欠落・重複・不正な所属も検証対象とする。
- 生成処理は明示したMarkdown一件だけのIAM一覧とmarker内を更新する。policy JSON、Role設定、他のresource一覧・表を変更しない。表の内容やJSONを自動的に正しい権限へ修正しない。

IAMを含む設計を保存・変更した後、model生成前に実行する。`--write`を省略するとread-onlyの一致検証になる。

```console
python3 framework/scripts/policy_tables.py docs/designs/<environment>/<target-directory>/iam.md --write
```

生成される信頼ポリシー表の形式例（値は対象設計のJSONに従う）:

```md
<!-- iam-policy-tables:start -->

<a id="iam-vpcflowlogsrole-trust"></a>

### 信頼ポリシー：FlowLogsTrust

Version：`2012-10-17`

| Statement | Effect | Principal.Service | Action | Condition |
| ---: | --- | --- | --- | --- |
| 1 | Allow | `vpc-flow-logs.amazonaws.com` | `sts:AssumeRole` | `ArnLike`：`aws:SourceArn` = `arn:aws:ec2:ap-northeast-1:123456789012:vpc-flow-log/*`<br>`StringEquals`：`aws:SourceAccount` = `123456789012` |

<!-- iam-policy-tables:end -->
```

local loopは同じ生成処理で期待する一覧と表を計算し、保存済みMarkdownとの不一致をFAILにする。policy JSONの構造・表示整合性の検証であり、AWSの実効権限判定やActionごとのResource適合性を検証したという意味ではない。設計入力のResource ARN/ARNパターンは保持し、generated ARNの永続化禁止を緩和しない。

## Links and anchors

- 関連 resource は `Value` column の Markdown link で表す。
- link は relative path を使う。
- renderer 自動生成だけに依存せず、resource heading の直前に explicit HTML anchor を置く。
- anchorはlower-case Service IDとlower-case logical IDを`-`で結ぶ。
- `S3.Bucket`ではlogical IDの代わりにlower-case BucketNameを使用する。
- `EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`では`.Name` valueがlogical IDになるため、anchorにも同じvalueをlowercaseで使用する。
- 別fileの例: `[FLOWLOGROLE01](iam.md#iam-flowlogrole01)`。
- 同じfileの例: `[FLOWLOG01](#vpc-flowlog01)`。
- file と anchor の存在を local loop で検証する。
- catalogのidentifier outputを参照するpropertyは、link先anchorをlogical referenceの正本とし、表示textへ参照先のcurrent physical IDを記載する。deploy前とdestroy後は`[PENDING_DEPLOY](#vpc-vpc-app-dev)`、deploy成功後は`[vpc-0123456789abcdef0](#vpc-vpc-app-dev)`とする。
- IaC生成は表示textのphysical IDを使用せず、link先anchorに対応するresource headingのlogical IDを解決する。CloudFormationは`!Ref`、Terraformはresource attribute referenceを使用し、physical IDを直書きしない。

## Generated values and deployment state

- 必要なnon-ARN generated current identifierは独立sectionではなく、`framework/materials/aws/*.properties`で`IDENTIFIER_OUTPUT`と指定された正式なcatalog propertyを該当resource table先頭の連続rowにcatalog順で記載する。`VPC ID`や`Subnet ID`などの合成labelを作らない。
- 未作成resourceのdeploy前はidentifier output rowの値を`PENDING_DEPLOY`とする。例えば`EC2.VPC.VpcId`の`Source / Comment`はprefixや取得元ではなく属性の意味だけを表す`VPCを一意に識別するID`とする。
- current identifierは、infrastructure taskのdeploy/apply成功後、またはdesign taskが選択済み既存resourceをread-only取得した場合だけ実値へ更新する。同じidentifierを参照する全propertyのMarkdown link表示textも同じphysical IDへ更新し、`Source / Comment`は属性の意味を維持する。
- replacement後はidentifier output rowと全参照元を新しいphysical IDへ同じ変更で更新する。destroy後はidentifier output rowを`PENDING_DEPLOY`へ戻し、全参照元のlink表示textも`PENDING_DEPLOY`へ戻す。
- human-selected nameなど通常のcatalog propertyがcurrent identifierになるresourceは、そのpropertyを使用し、`IDENTIFIER_OUTPUT`でない重複rowを作らない。
- generated ARNは詳細設計にも`model/**`にも永続化しない。
- old physical valueはGit履歴とAWS/IaC deployment historyで追跡し、詳細設計やscenario evidenceへ保存しない。
- `model/**`はidentifier output rowとidentifier参照rowの同じrow keyに、anchorから解決したlogical referenceを`desired.*`、Markdownの表示textまたはidentifier output valueを`observed.*`として保持する。

deploy前の参照例:

```md
| 4 | EC2.Subnet.VpcId | [PENDING_DEPLOY](#vpc-vpc-app-dev) | Subnetが所属するVPC |
```

deploy後の参照例:

```md
| 4 | EC2.Subnet.VpcId | [vpc-0123456789abcdef0](#vpc-vpc-app-dev) | Subnetが所属するVPC |
```

resource自身のidentifier output例:

```md
| 1 | EC2.VPC.VpcId | vpc-0123456789abcdef0 | VPCを一意に識別するID |
```

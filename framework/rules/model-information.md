# Machine-readable Service Model Rules

- target directoryは`project.json`のtargetにaliasがあればalias、なければAWS account IDとする。
- human-readable current designは`docs/designs/<environment>/<target-directory>/`に置く。
- machine-readable service modelは`model/<environment>/<target-directory>/`に置く。
- CloudFormation stack詳細設計は`cloudformation-stacks.properties`の`desired.stack.*`に各stackの名前、templateのファイル名、parameterのファイル名、正の整数`deployOrder`を保持し、target policyは`desired.deployment.maxConcurrentStacks`（整数1以上）へ保持する。同じstemのMarkdownを生成する。`DeployOrder`はstack instanceごとの正式設計値であり、template identityやdependency fieldではない。`project.json`へpolicyを追加しない。一覧の`No.`は生成し、`Comment`は`display.stack.*.comment`に保持する。stackの実行状態、StackId/ARN、AWSからの一時取得値はmodelへ保存しない。
- catalog propertiesは選択可能項目の正本、model propertiesはdesired value・observed valueの正本とする。MarkdownとJSON artifactは表示・利用用の生成物とする。
- Codexは確定済み設計を`model/`へ先に保存する。humanによるmodel propertiesの手動修正も設計入力として扱う。`framework/scripts/sync-model.py --write`はmodelを上書きせず、Markdown／JSON artifactを生成する。
- Markdownと正本modelが一致しない場合はlocal loopを失敗させる。片方を黙って採用しない。
- 検証に成功したserviceのanchor変更が他serviceの保存済み旧リンクを切断しても、その成功serviceは保存する。新たな切断は参照元とリンクを警告し、参照元の正本修復・再生成は別taskで行える。関連serviceを自動で生成対象へ追加せず、失敗serviceの保存済み表示を手編集しない。生成対象自身の参照・schema・model照合は引き続き必須とし、切れたリンクを持つserviceを検証対象に含めたlocal loopは失敗する。
- design taskはmodel propertiesを保存した後、同じcoherent logical changeでMarkdownとJSON artifactを生成する。選択済み既存resourceをread-only取得した場合は必要な非ARN current identifierも`observed.*`へ生成する。
- infrastructure taskは成功したAWS mutation後にmodelのobserved identifierを更新し、Markdownのidentifier rowと全参照元を生成する。
- infrastructure `update` phaseはhuman-changed model propertiesをimmutable inputとし、deploy前にMarkdownを生成する。成功したAWS mutation後だけobserved identifierを更新し、Markdownを再生成する。
- Markdownの構造、service grouping、generated identifier rowは`framework/rules/detailed-design.md`を正本とする。
- `IAM.Role`の表示名は正式な`IAM.Role.RoleName`の確定済みdesired rowだけから導出し、一覧・詳細heading・参照linkに使用する。RoleNameは正確に1 rowを必須とし、欠落・重複・空値・未確定値を拒否する。Name tagや`display.resource.*.label`で代替せず、内部logical IDとpolicy artifactの命名を維持する。
- `## リソース一覧`と`## リソース詳細`は表示上のsection区切りとし、No.は生成する。一覧Commentは`display.resource.<番号>.comment`、Stack一覧Commentは`display.stack.<番号>.comment`を正本とする。AWS propertyとしては扱わない。詳細section配下のH3 resource headingは表示名を保持し、anchor直前の非表示`resource-logical-id` metadataから内部logical IDを識別する。markerがない既存形式はheading identifierを内部identityとして読める。非表示markerをnoteやpropertyへ出力せず、H4 policy表は派生表示として除外する。見出し階層だけの変更でresource番号、anchor、logical ID、desired/observed値を変えない。

- `EC2.VPCEndpoint`／`EC2.Instance`のName tagは各resource typeの正式な`Tags[].Key=Name`と対応する`Tags[].Value`をdesired rowへ保持する。設計専用`.Name`を追加しない。Name tagは必須であり、case違い・Value欠落・空値・未確定値を拒否し、display labelで代替しない。一覧・heading・通常の参照linkとanchorはそのValueを使用し、内部logical IDは非表示metadata、identifier参照は既存のdesired logical reference／observed IDの分離を維持する。VPC／Subnet／RouteTable／Flow Logの.Name表示は維持する。

- Security Groupと所属Ingress／Egressは`security_group.properties`に保持し、`security_group.md`を生成する。service metadataとanchor prefixは`security_group`とする。EC2の他resourceをこのmodelへ混在させない。
- ConfigurationRecorderのRoleName表示とKDFのBucketARN／RoleARNは、参照先の確定済み名称を表示したresource linkをdesiredへ保持する。参照するIAMロール名が`AWSService`から始まる場合（例: `AWSServiceRoleForConfig`）は、IAM Role設計やlinkを要求せず、ロール名literalを正式ARN propertyのdesired valueへ保持する。正式ARN propertyを名称propertyへ変更せず、ARNを生成・保存しない。KDFのKeyARNは実KMS Keyへのlogical referenceをdesiredへ、表示されたKeyId／PENDING_DEPLOYを既存identifier reference規則どおりobservedへ分離する。

## Policy derived views

- 各service modelの`desired.row.*.document`にpolicy／設定JSON本文をcompact JSONで保持する。`desired.row.*.value`のJSON artifact linkからservice-owned JSONを生成し、そのJSONからpolicy表を生成する。JSON artifactや表を設計入力として逆反映しない。
- リソース一覧のResourceNameとCommentの生成済みtable、`<!-- policy-tables:start -->`〜`<!-- policy-tables:end -->`およびIAMの`<!-- iam-policy-tables:start -->`〜`<!-- iam-policy-tables:end -->`内の表示はmodelへ重複保持しない。policy anchor、見出し、信頼ポリシーのVersion表、Statement表、設定表を`desired.note.*`や追加resourceとして保存しない。
- 全serviceで派生表示のProperty/JSON/Version/Idの独立metadata行を省略する。元の設定rowのpropertyとJSONリンク、およびVersion/Idを含むJSON全体のcanonical hashは引き続きmodelへ保持する。
- policy変更時は先にmodelの`document`を更新し、`sync-model.py --write`でJSON artifactとpolicy表を同時に生成する。local loopはproperties・JSON・表示の不一致を拒否する。

## CloudFormation deployment policy

```properties
desired.deployment.maxConcurrentStacks=2
desired.stack.001.name=cfn-stack-app-dev-job-01
desired.stack.001.template=job.yaml
desired.stack.001.parameters=job-01.json
desired.stack.001.deployOrder=10
display.stack.001.comment=日次集計jobを配置するstack
desired.stack.002.name=cfn-stack-app-dev-job-02
desired.stack.002.template=job.yaml
desired.stack.002.parameters=job-02.json
desired.stack.002.deployOrder=10
display.stack.002.comment=月次集計jobを配置するstack
```

- StackNameをidentityとし、同一templateを持つ別stackをまとめない。parameter fileはstack固有とする。
- `MaxConcurrentStacks`省略時の実効値は1。生成Markdownは実効値を非表示HTML comment `<!-- max-concurrent-stacks: N -->`へ保持し、正式model値への復元と不一致検出を維持する。新規設計では明記する。
- `DeployOrder`未設定の旧modelと旧5列Markdownはgeneration/validation/controllerで拒否する。通常deployで一覧順から推測・自動移行しない。humanが順序を確定し、明示されたdesign/migration taskで既存entry ID、name、template、parameter、commentを保持して値を追加し、sync-modelで再生成する。既存modelをMarkdown importで上書きしない。
- 同じDeployOrderと同じTemplateは許可する。`DependsOn`、`AfterStack`、`DependsOnStack`、`Dependencies`を追加しない。
- 表示はDeployOrder数値昇順、StackName文字列昇順とし、No.は表示用の連番。model entry IDやcommentの所属を並べ替えで変更しない。

## Properties先行更新と表示生成

1. 保存前に作成対象resourceの命名ルール有無、catalog選択項目、型・制約、未確定値を確認する。
2. 確定済みの全service model propertiesを先に更新する。通常は`desired.service.*`、`desired.resource.*`、正式propertyの`desired.row.*`と必要な`observed.row.*`を使用する。
3. service単位に正本propertiesからschema/catalogの必須root propertyを直接検証する。不足時はMarkdown／JSON artifactの一時生成にも進まず、resource／propertyを報告し、propertiesと既存生成物を保持する。他serviceは処理を続ける。必須項目が揃ったserviceだけMarkdownとJSON artifactを一時生成し、既存のservice表示parser・schema・参照検証で照合する。失敗serviceの保存済みMarkdown／JSONと修正済みmodelを保持する。参照先が失敗した場合は保存済み表示に戻して参照を再検証する。Markdownからmodelを復元しない。
4. 保存前に同targetの保持された参照元も検証し、保存済み表示では解決していたlinkを候補生成物が新たに切断する場合は、参照先serviceの生成物を元へ戻す。対象service・参照元・linkを報告し、復元後の候補を再検証する。既存の参照エラーは新たな切断と区別する。成功したserviceのMarkdownとJSON artifactをまとめて保存する。書き込み失敗時も元の表示へ戻し、保持された参照元と保存済み候補を同じ基準で再検証する。無関係な成功serviceは保存できるが、失敗が残る場合はservice別エラーを報告し、command全体の終了コードを非zeroとする。modelを正本として再実行できる状態を保つ。
5. local loopはread-only生成結果と保存済み表示を照合する。propertiesの上書きは行わない。

`display.service.title`にH1 title（`# ...`を含む）を保持する。`display.resource.<番号>.comment`はresourceの機能・用途・役割を日本語で記す。名称propertyのない型では、同じservice内に同型の独立resourceが1件だけあり、選択済みName tagと既存の確定済み表示labelもなければ、resource typeを表示名として導出する。この場合`display.resource.<番号>.label`を必須とせず、型名をlabelへ重複保存しない。詳細headingは`### <catalog-resource-type>`、一覧・通常の参照linkもresource type、anchorは型名由来とする。同型複数件を区別するhuman-confirmedな表示名、または既存の確定済み表示名は`display.resource.<番号>.label`へ保持する。型名表示でも非表示logical IDを必須とし、既存値を維持して型名から推測しない。名称propertyの省略・必須Name tag不足には適用しない。名称propertyがある型の表示名は正式rowの値から生成し、重複保存しない。`display.*`は表示入力であり、catalog AWS propertyやIaC設定へ追加しない。resource番号・row番号は既存の3桁形式を使用する。

JSON linkを持つrowは`desired.row.<番号>.document`を必須とし、重複JSON key・不正な定数・object以外を拒否する。artifact hashは生成時に照合可能な派生値であり、設計値の正本にしない。

名称propertyがない型のhuman-confirmedな`display.resource.<番号>.label`は、内部logical IDと同じ文字列でも表示名として有効とする。validatorは同じ番号の`desired.resource.<番号>.resourceType`・`logicalId`・明示labelを対応する詳細headingと照合する。labelがない内部IDの流用、別resource typeや別logical IDのlabelによる代替は拒否する。非表示logical ID markerを必須とし、表示label由来anchor、desired／observedのnamespaceと値を維持する。表示labelからName tagやcatalog property、IaC設定を作らない。

サービス別の短縮property、CodePipeline index／Configuration展開、CodeBuild変数、GuardDuty Features、CloudTrail記録対象、Security Group横書きrule、KMS Aliasの親内表示、policy表は既存表示ruleに従ってmodelから生成する。検証parserは表示を正式propertyへ展開してlosslessな一致を確認するためだけに使用する。

既存Markdownの採用は明示されたmigration taskだけで`sync-model.py --import-markdown --write`を実行する。既存modelを上書きしない。同型単一で名称propertyがない独立resourceの型名表示にはlabelを作らず、その他の不足する表示label／commentを推測しない。通常のdesign／infrastructure taskで自動移行しない。

## Formal properties and display verification

以下の表示展開は、propertiesから生成した表示を検証・明示migrationで採用するための逆変換規則とする。通常taskでMarkdownを設計入力にせず、propertiesの正式rowを上書きしない。

## Properties format

### File size and service index

- modelの各properties fileは最大600行とする。600行以下は既存の単一fileを維持し、空行による水増しをしない。600行超の本文は約550行ずつに分割する。末尾partは500行未満でもよい。
- service入口は引き続き`model/<environment>/<target-directory>/<service-id>.properties`とし、分割時は`# model-index: 1`と順序付きの`# part: <service-id>/part-001.properties`以降だけを持つindexとする。本文は同じtargetの`<service-id>/`配下に置き、index自身と各partも600行以下とする。
- partは新serviceではない。index順に連結した一つの正本modelから、従来の同じservice Markdown／JSONを生成する。service ID、resource/row番号、logical ID、anchor、key/valueの内容・順序、desired/observedの分離を変更しない。indexのcommentはAWS propertyではなく保存形式のmetadataとする。
- partの欠落、重複・不正な順序、別serviceへの参照、path traversal、symlink、nested index、index未登録part、連結後の重複key、600行超を拒否する。partをfile名から独立serviceへ推測しない。通常の`sync-model.py --write`はmodel/index/partを変更しない。
- 新しいmodelを保存するときは`framework/scripts/model_files.py`の`model_file_contents(path, text)`で保存先を決定する。既存modelの物理分割は明示したdesignまたはmigration taskで、Validation scopeとAllowed pathsに入口・partを含めて次を実行する。設計変更を伴わない分割はmigrationとし、未解決issue gateを維持する。infrastructure updateのimmutable入力を自動分割しない。

```console
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --split
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --find '<logical-id-or-property-key>'
```

- token節約のため、最初に入口indexを読み、検索結果のfile・行を使って必要なpartだけを読む。`--find`はkeyまたはidentifierを含む一致行の位置を`絶対file path:行番号:key`として出力し、長いJSONなどの値を一括出力しない。分割後の設計編集は対象partへ行い、同じservice scopeで全partと生成表示の一致を検証する。

Markdown設定表で使う`Config.ConfigurationRecorder.RoleName`、`EC2.RouteTableId`、`S3.Bucket.BucketEncryption.BucketKeyEnabled`、`S3.Bucket.BucketEncryption[].KMSMasterKeyID`、`S3.Bucket.BucketEncryption[].SSEAlgorithm`、`S3.Bucket.LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays`は`framework/rules/display-property-aliases.json`で正式propertyへ戻してmodelに保存する。表示名をmodelのpropertyとして保存しない。Property列では見出しのresource type接頭辞を省く。

`CodeCommit.Repository.RepositoryId`は非表示propertyとしてmodelへ生成せず、identifier output参照判定からも除外する。RepositoryNameとresource anchorによる参照はdesiredへ保持する。catalogを変更しない。

CodePipelineの`Stages[N]`と単一`Actions`／複数`Actions[M]`はmodelで正式な`Stages[]`／`Actions[]`へ戻し、stage/actionごとの元の行順と所属を維持する。同じactionの連続した`Configuration.<Key>` rowを一つの正式property `CodePipeline.Pipeline.Stages[].Actions[].Configuration`へまとめ、Valueを元の文字列値からなるJSON objectとして生成する。resource linkはJSON objectの該当keyの文字列値へlosslessに保持し、CFn import式やExport名へ戻さない。各keyの日本語commentはkey名付きで出現順にまとめる。表示専用indexとConfigurationのkey別propertyをmodelのpropertyとして保存しない。元Markdownを生成時に書き換えない。

`CodeBuild.Project.Environment.Variables.<Name>`の1行表示は、表示の検証時に同じ配列要素の正式property `EnvironmentVariables[].Name`、`Type`、`Value`の3行へ展開する。literalはType=PLAINTEXTとし、Valueをそのまま保持する。リソースlinkは`Source / Comment`先頭の非表示`codebuild-variable-type` markerからTypeを復元する。Valueのresource link、表示textの確定済み名称・selector、literal中の`:`をlosslessに保持し、identifier output参照への変換やobservedへの分離を行わない。表示専用の`Variables.<Name>`とType markerはmodelへ保存しない。

`CodeBuild.Project.VpcConfig.Subnets[N]`／`SecurityGroupIds[N]`の1リソース1行表示は、表示の検証時にそれぞれ正式property `VpcConfig.Subnets`／`VpcConfig.SecurityGroupIds`の複数行へ戻し、resource linkと順序を保持する。表示専用の`N`はmodelのpropertyへ保存しない。

`GuardDuty.Detector.Features.<Name>`の1行表示は、表示の検証時に同じ配列要素の正式property `Features[].Name`、`Features[].Status`の2行へ展開する。表示専用の`Features.<Name>`はmodelへ保存しない。`Features[].AdditionalConfiguration[]`は正式propertyのまま保持する。

`CloudTrail.Trail.EventSelectors.DataResources[N].S3`／`.Lambda`の1記録対象1行表示は、表示の検証時に行順を保って正式property `EventSelectors[].DataResources[].Type`と`EventSelectors[].DataResources[].Values`へ展開する。`Type`には対応するAWS resource type、個別resource指定の`Values`には対象resource linkを保持する。`.S3`のValueがbacktickで囲った`All current and future S3 buckets`の場合は、`Type`を`AWS::S3::Object`、`Values`をJSON配列`["arn:aws:s3"]`としてdesiredへ生成する。このARN prefixは設計上の記録対象であり、observedへ保存しない。表示専用の選択値、`N`と短いType名はmodelのproperty/valueへ保存しない。

UTF-8の`.properties` fileを使用する。一つのservice modelにdesiredとobservedをnamespaceで分けて出力する。

```properties
# Authoritative design values; Markdown is generated from these properties.
desired.service.vpc.serviceId=vpc
desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet
desired.resource.001.resourceType=EC2.VPC
desired.resource.001.logicalId=vpc-app-dev
desired.resource.001.anchor=vpc-vpc-app-dev
desired.row.001-001.property=EC2.VPC.VpcId
desired.row.001-001.value=[vpc-app-dev](#vpc-vpc-app-dev)
desired.row.001-001.comment=VPCを一意に識別するID
observed.row.001-001.property=EC2.VPC.VpcId
observed.row.001-001.value=vpc-0123456789abcdef0
observed.row.001-001.comment=VPCを一意に識別するID
desired.row.001-002.property=EC2.VPC.CidrBlock
desired.row.001-002.value=10.1.0.0/16
desired.row.001-002.comment=VPCで使用するIPv4アドレス範囲
desired.row.001-003.property=EC2.VPC.Name
desired.row.001-003.value=vpc-app-dev
desired.row.001-003.comment=VPCを識別するNameタグの値
desired.row.001-004.artifactSha256=<linked-json-sha256>
desired.note.001.text=実装注記: 必要最小限の注記
```

resourceとrowの番号はmodel propertiesで指定し、表示の再解析で同じ順序になることを検証する。`## リソース一覧`のtableは、全serviceで人間向けの案内としてmodel生成対象から除外する。Markdownのproperty rowはmaterialsのproperties行順に従い、未選択・非表示項目を省略する。Markdownはmodelのrow順を保持し、名前やidentifierを先頭へ並べ戻さない。design-only `.Name`と`S3.Bucket.Region`は既存の特殊表示位置を保持する。`S3.Bucket`のheading identifierはBucketNameと一致させ、内部logicalIdは非表示metadataから保持する。markerを省略した場合はBucketNameをlogicalIdとして使う。identityなしでgroup化した`S3.BucketPolicy.PolicyDocument`と、Markdownで`EC2.RouteTableId`と表示する正式property `EC2.SubnetRouteTableAssociation.RouteTableId`は独立した`desired.resource.*`を作らず、包含する親resourceの`desired.row.*`へ正式Property名で反映する。省略した`S3.BucketPolicy.Bucket`と`EC2.SubnetRouteTableAssociation.SubnetId`は包含する親から解決し、`EC2.SubnetRouteTableAssociation.Id`はmodelへ生成しない。catalogの`IDENTIFIER_OUTPUT` rowは、同じrow keyの`desired.*`へresource自身のanchor-based logical reference、`observed.*`へMarkdownのcurrent valueを生成する。identifier outputを参照するMarkdown link rowも、同じrow keyの`desired.*`へlogical IDを表示するanchor link、`observed.*`へMarkdown linkの表示textを生成する。KMS aliasを参照するrowはAliasNameを表示するMarkdown linkを`desired.*`へlosslessに保持する。policy JSON本文はdocumentを正本とし、parse後のJSONをobject key順、空白なし、UTF-8で決定的にserializeした内容のSHA-256を`desired.row.*`へ保持する。空白、indent、改行位置、LF／CRLF、file末尾改行、object key順だけの変更でhashを変えない。

未作成resourceのdeploy前またはdestroy後のgenerated identifierはMarkdownとmodelの両方で`PENDING_DEPLOY`とする。read-only取得した既存resourceの必要な非ARN identifierはcurrent valueを保持する。generated ARNは`observed.*`へ保存しない。

Markdown／JSON artifact生成command:

```console
python framework/scripts/sync-model.py --write --environment <environment> --alias <alias>
# aliasなしの場合:
python framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>
```

## API-backed resources

- `framework/materials/api/*.properties`も同じcatalog読込に含める。`Macie.ClassificationJob`のresource type、logical ID、anchorと全設計rowを既存の`desired.*`へ生成する。
- `jobId`は同catalogの`IDENTIFIER_OUTPUT`から判定し、desiredには自己anchorへのlogical reference、observedにはcurrent IDまたは`PENDING_DEPLOY`を保持する。Job IDを参照する通常のMarkdown linkも既存のidentifier reference処理を使う。
- JSON object/arrayのinline値はそのまま保持し、JSON artifactは既存のpathとcanonical hashを保持する。`clientToken`、`jobArn`、CFn対応情報や作成者情報をmodelへ追加しない。
- `bucketDefinitions`型Macie Jobはmodelの`desired.row.*.document`内の`bucketDefinitions`をJob・account・bucket対応の正本とする。modelの`desired.row.*.document`から同じserviceの`S3JobDefinition` JSON artifactとbucket対応表を生成し、表自体は`desired.note.*`や追加resourceへ保存しない。modelは従来のJSON linkとcanonical hashを保持する。`scoping`はJSON内の選択済み設定として保持し、`bucketCriteria`型Jobには対応表を生成しない。
- service modelにJobが存在することを、CFnで作成可能または実装済みという判定に使用しない。実装可否はresource typeから対応するcatalog/schemaへ解決する。

## Grouping

- 表示関係の正本は`framework/rules/resource-layout.json`とする。S3 BucketPolicyとSubnet Route Table Associationのようにidentityを持たない単一の子は、親resourceのrowとして保持する。
- KMS Aliasのようにidentityを持つ子は、Markdownの同一table内でも独立した`desired.resource.<番号>.resourceType`、`logicalId`、`anchor`と自身の`desired.row.*`を生成する。親の次に子を出現順で並べる。Markdown内の非表示markerは構造として解釈し、rowのcommentには日本語説明だけを保持する。
- KMS Keyの表示名は`parentReference`で所属を確認したAliasの`AliasName`から先頭`alias/`を除いて導出する。aliasが1種類なら派生表示名をlabelへ保存しない。複数種類なら確定済み`display.resource.*.label`がいずれかのalias由来名称と一致することを要求する。明示migrationで複数aliasの表示を読み込む場合は選択された表示名をlabelへ保持する。AliasNameのdesired valueやKeyIdのdesired/observedを変換しない。
- 子の`desired.resource.<番号>.parentProperty=KMS.Alias.TargetKeyId`と`parentReference=[S3FILETRANSFERKEY01](#kms-s3filetransferkey01)`を生成する。省略した親propertyはこのlogical referenceから復元し、physical KeyIdや先頭Aliasによる補完をしない。これはdesiredの所属関係であり、observed値を追加しない。
- Alias参照は子のanchorとAliasNameをそのまま保持し、KeyIdへの変換やobserved namespaceへの分離をしない。子の移動時はparentReferenceだけが新しい所属親を指し、確定済みlogical IDとanchorは維持する。

- 表示検証ではSecurity Group詳細表のId、GroupDescription、選択済みGroupName、VpcIdと、所属SGの非表示security-group-tags metadataを一度だけ読み、正本modelの値と照合する。Tagsの各要素は`Tags[].Key`、`Tags[].Value`へ順序を保って対応させる。Id、GroupDescription、選択済みGroupName、VpcId、Tagsの順に生成し、VPC参照も既存のdesired logical reference／observed current identifierの分離を使う。タグmetadataのcommentをdesired.noteへ生成しない。
- ルール未設定のSecurity GroupもH3 headingと基本設定表を持ち、識別・VPC参照・選択済みタグを同じSG modelへ生成する。ruleや空のrule resourceを補完せず、次のSGのanchorや所属を変えない。
- 表示検証ではSecurity Groupの単一rule tableを読み、Directionの`Inbound`／`Outbound`をIngress／Egressへ対応させる。独立ruleは既存のgrouped resource形式へ展開し、`parentProperty=EC2.SecurityGroupIngress.GroupId`または`EC2.SecurityGroupEgress.GroupId`と包含SGへの`parentReference`を生成する。Direction cellの非表示`rule-id` markerを正式propertyの`Id`へ、`security-group-id` markerをInboundでは`SourceSecurityGroupId`、Outboundでは`DestinationSecurityGroupId`へ対応させる。参照値をlosslessに保持し、visible columnやmodel上のmetadata propertyを追加しない。ruleのdesiredは自身へのlogical reference、observedはcurrent ID／`PENDING_DEPLOY`とし、複数の未作成ruleはlogical IDとanchorで区別する。
- inline ruleはSG自身の`EC2.SecurityGroup.SecurityGroupIngress[].<property>`／`SecurityGroupEgress[].<property>`へ保持し、独立resourceやIdを生成しない。SG属性の後にInbound、Outboundの順、各方向では表のrow順に並べる。独立ruleはその後に表のrow順で並べる。一つのinline ruleのpropertyを連続させ、必ず`IpProtocol`を先頭に置く。同じ配列の次の`IpProtocol`が次要素の開始を表し、optional propertyの有無から所属を推測しない。
- `Port`は単一値ならFromPort／ToPortの両方へ同値、範囲なら開始／終了値、ICMPの`Type=n, Code=n`ならtype／codeとして展開する。`—`なら両propertyを省略する。展開後は独立rule自身またはinline rule配下の正式catalog propertyへ保持し、modelにPortというpropertyを追加しない。
- 横書きruleの省略cell `—`はpropertyを生成しない。参照linkと選択値は保持し、propertyごとの日本語commentは共通parserの属性説明を使用する。DirectionやPortという表示column名、HTTP/HTTPSなどのType、rule table見出し、identity markerはmodelへ追加しない。

- AWS service ownership boundaryごとにMarkdownとpropertiesを一対一対応させ、同じService ID、相対path、file stemを使う。
- `desired.service.<service-id>.serviceId`のkeyとvalueはfile stemと一致させる。
- `desired.service.<service-id>.ownedCatalogResourceTypes`はMarkdownと同じresource typeを同じ順序でcomma区切りにする。
- 別serviceのresource referenceはMarkdownのrelative pathとexplicit anchorを`desired.*`へ保持する。identifier output参照のphysical IDは同じrow keyの`observed.*`へ分離する。
- 別serviceのvalueを参照元properties fileへ複製しない。
- AWS managed-policy ARNのような既存またはhuman-provided design inputは必要な場合に`desired.*`へ残してよい。
- referenceは同じenvironment/target directory内のstable logical referenceをdefaultとする。cross-account referenceは所有AWS accountと接続方式をhuman designに明示し、値を推測しない。

- resource名表示へ変更するときも`desired.resource.*.logicalId`とidentifier logical referenceの表示textは非表示metadataから従来の内部IDを保持する。`desired.resource.*.anchor`はresource表示名由来のanchorを保持し、desired/observedの分離は維持する。人間向けMarkdownでは内部IDを表示用linkに使わない。

properties形式の最小例（名称・用途は対象設計で確認する）:

```properties
desired.service.logs.serviceId=logs
desired.service.logs.ownedCatalogResourceTypes=Logs.LogGroup
desired.resource.001.resourceType=Logs.LogGroup
desired.resource.001.logicalId=FlowLogs
desired.resource.001.anchor=logs-cwlogs-app-dev-flow
desired.row.001-001.property=Logs.LogGroup.LogGroupName
desired.row.001-001.value=cwlogs-app-dev-flow
desired.row.001-001.comment=ログを保存する名前
desired.row.001-002.property=Logs.LogGroup.RetentionInDays
desired.row.001-002.value=30
desired.row.001-002.comment=ログを保持する日数
display.service.title=# CloudWatch Logs 詳細設計
display.resource.001.comment=VPCの通信ログを保存するLog Group
```

## RotationSchedule grouped identity

`SecretsManager.RotationSchedule`は親Secretと同じMarkdown tableに表示するが、独立した`desired.resource.*`、確定済み`display.resource.*.label`、表示名由来anchor、非表示logical IDを保持する。`parentProperty=SecretsManager.RotationSchedule.SecretId`と同model内のSecretへの`parentReference`を必須とし、正式なSecretIdのdesired rowも同じlogical referenceを一度だけ持つ。Idのdesiredは自身へのlogical reference、IdとSecretIdのobservedはcurrent identifier／`PENDING_DEPLOY`を保持する。Id rowの表示名prefixとidentity markerは再解析時に構造情報として取り出し、属性commentやdesired.noteへ混入させない。正式SecretId rowのcommentとobservedもlosslessに照合し、親metadataからの補完で正本rowを省略しない。親Secretごとに最大1件とし、別親の同じ`PENDING_DEPLOY`値はidentityの重複と扱わない。

# Detailed Design Rules

## 正本と更新順

catalog propertiesを項目の正本、model propertiesを設計値の正本とする。Markdownに表示される全項目・値・名称・説明はmodelから生成し、service固有表現はこのruleに従う。JSON artifactもmodelの`document`から生成する。model propertiesの更新に失敗したらMarkdownを更新しない。service単位で生成・検証し、成功したserviceの生成物を保存する。失敗serviceの保存済み生成物を維持し、他serviceの処理を続ける。詳細は`framework/rules/model-information.md`に従う。

## Task boundary

- `design` taskはmodel propertiesのintended designを先に更新し、対応するMarkdown／JSONを`framework/scripts/sync-model.py`で生成してlocal validation後に終了する。chatbotが指定した既存resource取得では必要な非ARN current identifierも反映できる。IaC、AWS mutation、scenarioへ自動的に進まない。
- `infrastructure` taskはintended designを変更しない。deploy/apply成功後のgenerated current valueだけを詳細設計へ反映できる。
- infrastructure `update` phaseは、humanがtask開始前にmodel propertiesへ手動修正した未commitのintended designをimmutable inputとして受け取れる。Codexはそのintended designを変更せず、deploy/apply成功後のgenerated current valueだけを追加更新できる。
- designの不足または変更が必要な場合、infrastructure taskは停止して別のdesign taskを要求する。

## Existing resource configuration

chatbotが既存AWS resourceの現在値取得を指定した場合だけ、Codexの`design` taskは次を実行できる。

- 取得対象はchatbotが確定したtarget AWS service、catalog resource type、propertyに限定する。`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`、`EC2.FlowLog`では詳細設計専用の`.Name` propertyを含め、`EC2.VPCEndpoint`では必須Name tagの正式な`Tags[].Key`と`Tags[].Value`を含め、それ以外の別service、同じresource typeの未選択property、materialsにないpropertyへ自動的にscopeを広げない。
- repository変更前に`project.json`のtarget、credentialのcaller account、regionをread-only preflightで検証する。
- AWS Cloud Control APIのList／Readを第一候補とし、非対応resource typeだけ対象service固有のread-only APIを使用する。AWS値とmaterials／provider schema propertyの対応が一意でなければ停止する。
- resource候補はprimary identifierなどsecretを含まない最小情報だけを提示し、候補が一件でもhumanが選択するまで取得対象を確定しない。primary identifierがARNの場合はresource選択と取得のためだけに一時利用してよい。
- humanがresourceを選択した後は、選択済みpropertyと対象resourceでmandatoryな`Name` tagの現在値を直接差分反映する。前4種類は`.Name`へ、`EC2.VPCEndpoint`は正式な`Tags[].Key=Name`と対応する`Tags[].Value`へ保持する。既存fileの未選択resourceと未選択propertyは維持し、AWS現在値に存在しない選択済みoptional propertyのrowは削除する。mandatory `Name` tagが存在しない場合は値を発明せず停止する。対応するresource sectionがなければ、上記4種類は`.Name` valueをheading identifierとして使用し、`EC2.VPCEndpoint`は取得したName tag value、それ以外は確定済みresource名をheadingへ使用し、内部logical IDが未確定の場合だけhumanへ一つ質問して非表示metadataへ保持する。resource名がない型ではhuman-confirmedな表示名を確認し、名前を発明せずservice metadata、anchor、heading、tableを作成する。
- password、secret、token、credentialなどの機密値は表示または保存しない。generated ARNは詳細設計、JSON artifact、modelへ保存せず、resource選択またはAPI実行に必要な処理中だけ使用する。
- resourceの作成者、管理者、外部作成済みという出自は詳細設計またはmodelへ保存しない。詳細設計はtarget environmentに存在する設定を同じresource table形式で保持する。
- AWS mutation、IaC作成・変更、deploy/apply、scenarioへ進まない。
- 上記section作成にも`resource-layout.json`を適用し、grouped childは独立headingを作らない。選択済みの親propertyの現在値と設計済み親のcurrent identifierから所属を確認し、親table内へ反映する。所属が不明または親の設計がない場合は停止し、未選択resource/propertyへscopeを広げない。

## AWS resource naming

- `CodeBuild.Project.Name`はprovider schemaのoptional指定にかかわらず詳細設計で必須とする。resourceごとに確定済みnon-empty literalを1 rowだけ保持し、欠落・空値・未確定値・重複を拒否する。Name tag、内部logical ID、表示labelで代替せず、未確定なら値を推測せず停止する。設計検証とmodel生成の共通名称検証で判定する。
- human-selectedなAWS resource name、identifier、または`Name` tagを新規決定する場合は`framework/rules/aws-resource-naming.md`を適用する。
- root-levelの`Tags`または`HostedZoneTags`があっても`Name` tagを自動的に必須化しない。mandatory対象は`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`、`EC2.FlowLog`、`EC2.VPCEndpoint`とする。前4種類は詳細設計でそれぞれ`.Name`の1 rowで表す。
- 上記4種類の`.Name`は詳細設計専用propertyであり、provider schemaのresource propertyではない。IaC実装時にcase-sensitiveな`Name` keyを持つtagへ変換し、詳細設計へ`Tags[].Key=Name`と`Tags[].Value`の2 rowを作らない。
- `EC2.VPCEndpoint`の必須Name tagは正式な`Tags[].Key=Name`と直後の対応する`Tags[].Value`で保持する。case違いのkey、Valueの欠落・空値・未確定値を拒否し、display labelで代替しない。設計専用`.Name`を作らず、一覧・heading・通常の参照linkへValueを表示し、その表示名からanchorを生成する。内部logical IDは非表示metadataへ保持し、identifier参照のdesired logical reference／observed IDは既存契約を維持する。
- その他のresourceではhumanが`Name` tagを明示した場合だけ設計する。array形式では`Tags[].Key`または`HostedZoneTags[].Key`へ`Name`、直後の対応する`Value` rowへnon-empty nameを記載する。object形式では`Tags`に`Name` keyとnon-empty valueを持つJSON objectを記載する。
- naming componentがすべて確定済みならpatternから一意に導出し、未確定componentがあれば値を推測せずhumanへ確認する。
- 既存resourceから取得した名称と既存詳細設計の確定済み名称は、conventionと異なっても自動変更しない。
- 既存resourceに必須の`Name` tagが存在しない場合はtag valueを発明せず、blockerとして停止する。
- final nameはprovider schemaとservice固有制約へ適合することを確認し、自動truncate、hash付与、略語化で補正しない。

## AWS service ownership boundary

service resource詳細設計のfile grouping unitは、security boundaryやIAM Permissions Boundaryではなく、人間が認識するAWS serviceごとの責務を表すAWS service ownership boundaryとする。一つのservice design fileは一つのAWS serviceだけを所有する。`cloudformation-stacks.md`は上記のdeployment unit専用とする。

- target directoryは`project.json`のtargetにaliasがあればalias、なければAWS account IDとする。
- fileは`docs/designs/<environment>/<target-directory>/<service-id>.md`に置く。
- Service IDは原則lower-kebab-case（Security Group専用の`security_group`だけ例外）とし、file stemおよび対応する`model/<environment>/<target-directory>/<service-id>.properties`と一致させる。
- 同じAWS serviceに属する複数resource typeとinstanceは同じfileに置いてよい。
- 運用上関連するだけの別AWS serviceを同じfileへ入れない。CloudFormation resource namespaceだけでgroupingを決めない。
- child componentは親resourceと同じAWS serviceに属する場合だけ同じfileに置いてよい。別AWS serviceのresourceはchild componentとして扱わない。
- IAM RoleとPolicyは利用先service専用でもIAM service fileへ置く。
- CloudWatch Logs resourceは利用元serviceではなくCloudWatch Logs service fileへ置く。
- VPC Flow LogはAmazon VPCのservice fileへ置き、IAM RoleとLog Groupをcross-file referenceで参照する。
- `EC2.SecurityGroup`と所属する`EC2.SecurityGroupIngress`／`EC2.SecurityGroupEgress`は`ec2.md`から分離し、`security_group.md`だけに置く。Design service IDは`security_group`、対応modelは`security_group.properties`、anchorは共通のresource表示名規則に従う。このfileに他resource typeを混在させず、参照元linkも専用fileのanchorへ向ける。
- service間dependencyはfile統合ではなく正本modelのrelative Markdown linkとexplicit anchorで保持し、Markdownへ同じreferenceを生成する。
- 未使用serviceの空design fileを作らない。
- design file boundaryとCloudFormation stack/template boundaryは別概念とする。

## CloudFormation stack詳細設計

CloudFormation targetでstackを作成・更新する前に、targetごとに`docs/designs/<environment>/<target-directory>/cloudformation-stacks.md`を作成する。これはservice resourceではなくdeployment unitの詳細設計であり、`AWS::CloudFormation::Stack`（nested stack）を表さない。stack名、使用templateのファイル名、stack固有parameterのファイル名、stack instanceごとの`DeployOrder`、target単位の`MaxConcurrentStacks`をここで確定する。template filenameから順序を推測しない。Import/Export、resource ownership、change/rollback unitから順序を提示し、確定できない場合はdesign taskでhumanへ確認する。accountとregionは`project.json`を参照し、deployment status、StackId/ARN、履歴を保存しない。

`## Deployment設定`は`Property | Value`の2列で`MaxConcurrentStacks`（整数1以上）を表示する。`## Stack一覧`は`No. | DeployOrder | StackName | Template | Parameters | Comment`の6列とする。`DeployOrder`は正の整数、値の間隔は自由とし、同じ値は並列実行可能な同一groupを意味する。小さいgroupの全stackがterminal successとなってから次groupへ進む。DeployOrder数値昇順、StackName文字列昇順で表示する。1 stack instanceを1 rowで表示し、`No.`は1からの連番、`Comment`はstackの用途・役割を日本語で短く説明する。`Comment`はmodelの`display.stack.*.comment`から生成し、AWS stack propertyとして扱わない。

[CloudFormation stack詳細設計の例](detailed-design-samples.md#cloudformation-stack)

generic validatorがservice ownershipを判断するため、各Markdownには次のmachine-readable service metadataだけを正確に1件ずつ記載する。

[Service metadataの例](detailed-design-samples.md#service-metadata)

- Owned catalog resource typesには`framework/materials/aws/*.properties`または`framework/materials/api/*.properties`に存在し、このservice fileが所有するresource typeだけを記載する。
- 同じenvironment/target directory内で同じcatalog resource typeを複数service fileが所有してはいけない。

## Markdown structure

保存対象Markdownは、原則としてH1 title、service metadata、`## リソース一覧`、`## リソース詳細`、resourceごとのexplicit anchor、resource heading、resource-detail tableだけで構成する。Security Groupは後述の属性を集約した一覧と、Direction付きの横書きrules表を使う。policy JSONを持つresourceは後述のJSONから生成するStatement表または設定表も持つ。tableだけでは表現できない場合に限り、必要最小限のimplementation noteを追加してよい。

- title、heading、implementation note、`Source / Comment`を含む説明文は日本語で記載する。AWS service/resource/propertyの正式名称、logical ID、code、JSON keyなど翻訳すると意味が変わる値は原文のままでよい。
- 一覧の後、最初のresource anchorより前に`## リソース詳細`を正確に1件置く。全resourceの詳細をこのsection内へ置き、一覧と詳細を同じH2階層で区切る。
- 独立表示するcatalog-backed resource headingは詳細section配下の`### <catalog-resource-type>: <resource-name>`とする。policy表の見出しはresource配下のH4とし、implementation noteにもresourceと同階層以上の見出しを使用しない。親へ統合するresourceは後述の共通表示contractに従う。
- `S3.Bucket`だけは`### S3.Bucket: <BucketName>`とし、heading identifierを同じtableの`S3.Bucket.BucketName` valueと完全一致させる。
- 全serviceでheadingの`<resource-name>`には同じ詳細tableの確定済み名称property（`Name`、`BucketName`、`RoleName`、`Scheduler.Schedule.Name`等）または選択済み`Name` tagの値を使用する。内部logical IDをheading、一覧のResourceName、参照linkの表示textへ出さない。名称propertyがない型はhuman-confirmedな表示名を使い、未確定なら停止する。generated IDや`PENDING_DEPLOY`をresource名の代用にしない。
- 内部logical IDはexplicit anchorの直前に独立行の`<!-- resource-logical-id: <logical-id> -->`で保持する。headingとIDが同じ確定済みresource名ならmarkerを省略してよい。markerは画面へ表示せず、modelのlogicalIdとIaC識別のためだけに使用する。
- `EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`、`EC2.FlowLog`のresource名は同じtableの`.Name` valueと完全一致させる。
- `Environment`、`AWS account ID`、`AWS region`、`Purpose`、`Deployment state`をfile metadataとして記載しない。これらは`project.json`、`docs/system-overview.md`、active task、`model/**`の該当する正本を参照する。S3 Bucketの配置regionだけは後述のdesign-only `S3.Bucket.Region` rowにbucketごとの確定値を表示する。
- `Design decisions`、`Out of scope`、`Generated values`または同義の日本語sectionを作らない。
- 確定済みの設計値は該当resource/component tableへ記載する。
- 対象外事項はactive taskまたはchatの完了報告だけに記載する。

## Resource overview

各詳細設計fileはservice metadataの直後に`## リソース一覧`を正確に1件置く。一覧の範囲は次の`## リソース詳細`直前までとし、resourceのanchor・詳細table・policy表を含めない。

- 一覧内はdetail blockを持つcatalog resource typeごとに`### <catalog-resource-type>`とtableを一つ置く。grouped child resource typeは独立一覧を作らない。
- tableは`No. | ResourceName | Comment`の3列とし、1 resourceを1 rowで表示する。`No.`はresource typeごとのtable内で1からの連番とする。`ResourceName`には対応するdetail headingのidentifierをsame-file linkで表示し、`Comment`にはそのresourceの機能・用途・役割を日本語で短く説明する。同型のresourceが複数ある場合は各行の用途を区別する。resource typeやResourceNameを繰り返しただけの`セキュリティグループ（VULNERABILITYSCANCDESECURITYGROUP01）の設定`のような文はCommentとしない。Security Groupは詳細のGroupDescription、通信rule、利用先から用途を確認し、不明なら推測しない。全detail blockを重複なく一覧へ載せる。
- 設定値、生成ID、policy linkは一覧に表示せず、対応するresourceの詳細blockに保持する。一覧は人間向けの案内であり、ResourceNameはmodelの名称row、Commentは`display.resource.*.comment`から生成する。生成済みtable自体はmodelへ重複保持しない。

S3の例: [S3リソース一覧の例](detailed-design-samples.md#resource-overview)

## Resource-detail table

resource-detail tableは、後述のSecurity Group rules表を除き、サンプルのheaderとalignment rowを正確に使う。

[Resource-detail tableのheader例](detailed-design-samples.md#resource-detail-table)

- 各 table の row は 1 から連番にする。
- Property列では、所属する`### <catalog-resource-type>: <resource-name>`の`<catalog-resource-type>.`を省く。例えば`CodeBuild.Project.Artifacts.Type`は`Artifacts.Type`、`CodeBuild.Project.Id`は`Id`と表示する。modelとcatalog照合ではheadingのresource typeを補って正式propertyへ戻す。同じtableへ統合された別resource typeのrowは所属を区別するため正式propertyを維持する。見出しと同じresource type接頭辞がProperty列に残る場合はlocal validationで拒否する。
- resource設定表のproperty表示順は`framework/materials/aws/<service>_<resource>.properties`の行順を正本とする。API resourceは`framework/materials/api/*.properties`の行順を使う。未選択・非表示項目は飛ばし、名前や生成IDを別途先頭へ移動しない。表示順の変更はcatalog-maintenance taskでpropertiesの行を移動し、checksumを更新する。alphabet順の強制や別の表示順一覧は設けない。特別な表示propertyから正式propertyへの対応は`framework/rules/display-property-aliases.json`を正本とする。
- 例外として、VPC／Subnet／RouteTable／Flow Logのdesign-only .Nameは1行目、S3.BucketのBucketName／design-only Regionは1／2行目の既存表示を維持する。Name tagの必須性、1行表示、heading・anchorとの一致を変更せず、catalogへ設計専用propertyを追加しない。
- grouped childは所属する設定範囲内、配列は各要素内でcatalog順を適用する。複数要素のrowをproperty単位で横断sortしない。親子の所属、identity marker、IAM PolicyNameとPolicyDocumentの対応を保つ。Security Groupの横書き一覧／rule table、JSONから生成するpolicy表は既存形式を維持する。
- `Config.ConfigurationRecorder.RoleARN`は表示専用aliasの`RoleName`とし、Valueは同一targetの`IAM.Role`へのlinkで参照先の`RoleName`だけを表示する。ARN、role path、CFn import式を表示しない。modelでは正式property `Config.ConfigurationRecorder.RoleARN`を維持する。
- `KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN`は同一targetの実`KMS.Key`へのlinkとし、表示textはその`KeyId`（未作成は`PENDING_DEPLOY`）とする。`S3DestinationConfiguration.BucketARN`は実`S3.Bucket`へのlinkで`BucketName`を、`S3DestinationConfiguration.RoleARN`は実`IAM.Role`へのlinkで`RoleName`を表示する。KMS Alias、別種resource、ARN literal、Export名、CFn import式を代用しない。提供templateのOutput/Exportや参照式から実resourceをたどり、参照先が未設計・不明・複数候補なら推測せず停止する。
- 上記のIAM Role参照で、ロール名が`AWSService`から始まる場合（例: `AWSServiceRoleForConfig`）はロール名のliteralを許可し、同一targetの`iam.md`へのlinkとIAM Role設計を要求しない。ARNやrole pathは表示・保存せず、modelの正式ARN propertyのdesired valueへロール名をそのまま保持する。通常のIAM Role参照はlinkを必須とする。
- `CodeCommit.Repository.RepositoryId`は表示しない。catalogは維持するがidentifier outputの必須表示・model生成から除外し、参照には確定済み`RepositoryName`とresource anchorを使用する。
- `CodePipeline.Pipeline.Stages[]`の全rowは`Stages[N].<Property>`と表示し、`N`はpipeline内で1からの連番とする。同じstageのrowをまとめ、同じstage内のactionが1件なら`Stages[N].Actions.<Property>`、複数なら全actionを`Stages[N].Actions[M].<Property>`とする。`M`はstageごとに1からの連番とし、同じactionのrowをまとめる。stage/actionの順序と各要素内のcatalog順を維持し、`Stages[]`／`Actions[]`、欠番・重複・0始まり、単一actionの不要なindexを禁止する。
- CodePipeline actionの`Configuration`はJSON object一行ではなく、keyごとに`Stages[N].Actions.Configuration.<Key>`または`Stages[N].Actions[M].Configuration.<Key>`のrowへ分ける。例えば`BranchName`と`PollForSourceChanges`は各literalを表示する。同じactionのkey rowは連続させ、keyを重複させず、元の文字列値（`false`も文字列）を保持する。Configuration内のkey順は入力順を維持する。これはcatalogのConfiguration objectの表示展開であり、catalogへkeyを追加しない。
- CodePipeline Configurationのresource参照に`Fn::ImportValue`、`Ref`、`Fn::GetAtt`などのCFn式やExport名を記載しない。提供されたtemplateのOutput/Exportとresource定義、同一targetの詳細設計から参照先の実resourceを一意にたどり、確定済み名称をそのresourceの相対linkとして表示する。CodeCommit providerの`RepositoryName`はCodeCommit.Repository、CodeBuild providerの`ProjectName`はCodeBuild.Projectへlinkし、表示textはそれぞれRepositoryName／Nameと一致させる。その他の参照も同一targetの実resource anchorへlinkする。参照先が未確定、設計未登録、複数候補なら推測せず不足情報を示して停止する。表示変更のためにAWS API権限を追加せず、既存resource取得は上記のtask boundaryに従う。
- `CodeBuild.Project.Environment.EnvironmentVariables[]`は変数ごとに1行とし、Propertyを`Environment.Variables.<Name>`とする。PLAINTEXTのliteralはValueに値だけ（例：`cde`）を表示し、Type接頭辞を付けない。リソース参照はValueに相対pathとexplicit anchorの単独Markdown link（例：`[venus-dev-snowflake-cicd-keypair-cde](secretsmanager.md#secretsmanager-snowflakekey)`）を置き、backtickで囲まない。参照rowの`Source / Comment`先頭に`<!-- codebuild-variable-type: SECRETS_MANAGER -->`などの非表示markerで確定済みType（PLAINTEXT／PARAMETER_STORE／SECRETS_MANAGER）を保持する。SECRETS_MANAGERは同一targetのSecretsManager.Secretへlinkし、表示textは確定済みNameと必要なselectorを保持する。PARAMETER_STOREの参照先がcatalogに未登録の場合はframework対応が必要なblockerとし、resourceを推測・追加しない。literal中の`:`とselectorを保持する。変数名の重複、Type接頭辞、正式Name／Type／Valueの個別表示を禁止し、行順は配列要素順とする。
- `CodeBuild.Project.VpcConfig.Subnets`と`SecurityGroupIds`は対象resourceごとに1行とし、Propertyをそれぞれ`VpcConfig.Subnets[N]`、`VpcConfig.SecurityGroupIds[N]`とする。`N`は各property内で1からの連番とし、Valueは同一targetの`EC2.Subnet`または`EC2.SecurityGroup`へのresource linkを1件だけ置く。`PENDING_DEPLOY`の参照linkも許可し、JSON配列・backtickで囲ったlink・正式propertyの単独表示を禁止する。表示順は`Subnets[N]`、`SecurityGroupIds[N]`、`VpcConfig.VpcId`とし、この2つの配列だけcatalog順の例外とする。modelへは行順のまま正式property `VpcConfig.Subnets`／`VpcConfig.SecurityGroupIds`として複数行を保持する。
- `GuardDuty.Detector.Features[]`はFeatureごとに1行とし、Propertyを`Features.<Name>`、Valueを`<Status>`で表示する。Nameの重複と、正式な`Features[].Name`／`Status`の個別表示を禁止する。行の順序は配列要素の順序とし、`Features[].AdditionalConfiguration[]`は従来どおり正式propertyの行で表示する。
- `CloudTrail.Trail.EventSelectors[].DataResources[]`は記録対象ごとに1行とする。Propertyは`EventSelectors.DataResources[N].S3`または`EventSelectors.DataResources[N].Lambda`とし、`N`は同じTrailのtable内で1から始まる連番とする。個別resource指定のValueは対象の`S3.Bucket`または`Lambda.Function`への同一target内resource linkを1件だけ置く。全S3 bucket指定の場合は`.S3`のValueにbacktickで囲った`All current and future S3 buckets`を置き、現在および今後作成される全S3 bucketのobject data eventを対象とする。bucketの列挙や架空のresource linkを作らず、配列・ARN文字列を表示しない。この選択値は`.Lambda`では許可しない。`S3`は正式な`Type=AWS::S3::Object`、`Lambda`は`Type=AWS::Lambda::Function`を表し、各表示行を正式な`EventSelectors[].DataResources[].Type`と`Values`の組へ展開する。個別resource指定の`Values`は対象resourceへのlinkとして保持し、S3 object対象はbucket ARN末尾の`/`、Lambda対象はfunction ARNを参照する。全S3 bucket指定は`Type=AWS::S3::Object`と`Values=["arn:aws:s3"]`へ展開する。正式な`Type`／`Values`の個別表示と、`N`の欠番・重複・0始まりを禁止する。他のEventSelectors設定rowは従来どおり表示する。
- `CidrBlock`、`DestinationCidrBlock`、`CidrIp`等のCIDR項目は、詳細表・リソース一覧とも`PENDING_DEPLOY`を禁止する。deploy前でも確定済みCIDRを表示し、未確定ならhumanへ確認する。参照linkの表示値や配列内も同じとし、catalogでidentifier outputとされるCIDRでも例外にしない。`VpcId`等の生成IDのPENDING_DEPLOY許容は維持する。
- `Events.Rule`はProperty `Name`と`State`をそれぞれ必ず一度だけ記載する。表示順はpropertiesに従う。NameとStateは確定済みの値を使用し、未確定の場合はhumanへ確認する。Stateを`ENABLED`などで自動補完しない。
- `S3.Bucket`はbucketごとに一つのanchor、`### S3.Bucket: <BucketName>` heading、tableを使用する。heading identifierとanchorのidentifier部分は`S3.Bucket.BucketName` valueに一致させる。Property `BucketName`をtableの先頭row、design-onlyの`Region`を2行目に置き、RegionのValueはbucketごとにhumanが確定したAWS region IDとする。`project.json`のtarget `awsRegion`は自動転記せず、`us-east-1`など別regionを許可する。対応する`S3.BucketPolicy`を設計する場合は、`S3.BucketPolicy.PolicyDocument`だけを同じtableの`S3.Bucket` rowの後へ置く。対象bucketは包含するblockから暗黙に特定し、`S3.BucketPolicy.Bucket` row、独立anchor、heading、tableは作らない。
- general purpose `S3.Bucket`でSSE-KMSを使用する場合、`S3.Bucket.BucketEncryption[].KMSMasterKeyID`のValueは、同じtargetに設計した`KMS.Alias`のanchorへのresource linkとし、linkの表示textはその`KMS.Alias.AliasName`と一致させる。`KMS.Key.KeyId`のgenerated valueは表示しない。暗号化方式は`BucketEncryption[].SSEAlgorithm`と表示し、両rowをmodelではalias fileの正式propertyへ戻す。
- 1 file に複数 resource heading と table を置いてよい。
- resource-detail tableの独立表示と親への統合は`framework/rules/resource-layout.json`を正本とする。未登録の型を推測で分割・統合せず、framework保守が必要なblockerとして停止する。リソース一覧の表示単位はResource overviewに従う。
- `framework/materials/aws/*.properties`と`framework/materials/api/*.properties`はresource-detail tableへ載せてよい設計項目の選択リストとし、`Property`はresource type接頭辞を省いたspelling、または`framework/rules/display-property-aliases.json`に登録した表示名から接頭辞を省いたspellingを使う。`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`、`EC2.FlowLog.Name`、`S3.Bucket.Region`だけをdesign-only exceptionとする。
- CFn由来の選択項目の存在、型、`enum`、`pattern`、長さ、範囲、`required`は`framework/materials/cloudformation-schema/ap-northeast-1/`のCloudFormation provider schemaを正本とする。design-only `.Name`には`framework/rules/aws-resource-naming.md`のpatternを適用し、`S3.Bucket.Region`はnon-emptyのlower-kebab-case AWS region IDとする。
- 上記5種類のdesign-only property以外にcatalogにないrowを作成しない。generated current identifierも後述の`IDENTIFIER_OUTPUT` catalog propertyを使用する。derived documentation fieldやimplementation情報は必要最小限のtable外noteにする。
- catalog の全 field を掲載せず、選択済みで必要な design field だけを載せる。
- IaC template path を AWS resource property のように table に入れない。implementation note は table 外の prose section に書く。
- optional propertyを使用しない場合はrow自体を省略する。ただし`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`、`EC2.FlowLog.Name`とS3 Bucketの`S3.Bucket.Region`、`EC2.VPCEndpoint`の必須Name tagの`Tags[].Key`／`Tags[].Value`は省略しない。これら以外にschemaに存在しない説明用propertyを作らず、`not-used`、`none`、`UNSET`などのsentinel値を記載しない。
- schemaの`required`に指定され、かつproperties選択リストにあるroot propertyは省略しない。
- 必須項目が不足したpropertiesは設計入力として保持できるが、詳細設計Markdown／JSON artifactは一時fileを含め生成しない。正本propertiesを直接検証し、row欠落・空値・未確定値のresource／propertyを報告する。既存生成物は維持し、値を推測・自動補完しない。必須項目が揃ったserviceだけ生成へ進み、不足が残るtaskを完了扱いにしない。

`Source / Comment`は、そのrowの`Property`が何を設定、識別、制御する属性なのかを日本語で短く説明する。見出し・`Property`から分かる対象resource名の繰り返しは省き、属性の意味だけを記載する。ただし、参照先・通信元・通信先を区別する名称は残す。grouped resourceのrowも、そのrowの`Property`が属するresourceを対象に判断する。次の内容は記載しない。

- `確定済み設計値`、`選択済み`、`承認済み`などの決定状態
- `人間が選択した`、`human-selected`などの決定主体
- `共通タグ`、`リソース固有タグ`などの分類だけの説明
- 設計値の出典、決定経緯、更新証跡、verification結果
- `Value`を意味なく言い換えただけの説明

例えば、VPCのCIDRには`使用するIPv4アドレス範囲`、inline policy nameには`埋め込む権限ポリシーの名前`、project tag keyには`所属するプロジェクトを識別するタグのキー`と記載する。`EC2.Subnet.SubnetId`には`一意に識別するID`、`EC2.Subnet.AvailabilityZone`には`配置するAvailability Zone`と記載する。参照先を表す`EC2.Subnet.VpcId`の`所属するVPCのID`や、`SourceSecurityGroupId`の`通信元として許可するSecurity GroupのID`は名称を残す。更新根拠やverification結果は詳細設計へ保存せず、observed valueまたは完了報告を扱う既存ルールに従う。

## API-backed design resources

詳細設計の対象とIaCで作成できる対象を分離する。CFn非対応でも、登録済みのAPI catalog resourceは正本modelへ含め、通常のservice metadata、リソース一覧、anchor、heading、4列の詳細表を生成する。CFn非対応を理由に詳細設計を省略しない。

- 現在の対象は`Macie.ClassificationJob`だけとする。`Macie.Session`と同じ`macie.md`に置き、Jobごとに`### Macie.ClassificationJob: <resource-name>`を作る。表示関係は`resource-layout.json`に従う。
- 選択リストは`framework/materials/api/Macie_ClassificationJob.properties`、型・制約は同名の`.json`を正本とする。公式Macie APIのrequest/responseに基づく固定した設計用schemaであり、CloudFormation provider schemaではない。参照元、API version、取得元hash、確認日、`cloudFormationType: null`はframework側に保持し、詳細設計のAWS propertyとして追加しない。
- APIの正式な大小文字を維持し、`Macie.ClassificationJob.name`、`jobType`、`s3JobDefinition`などを使用する。catalogにないfield、架空のCFn型、実行時の`clientToken`、生成された`jobArn`を追加しない。
- 選択単位はAPIのroot propertyとする。`s3JobDefinition`、`scheduleFrequency`、`tags`はJSON object、識別子の配列はJSON arrayとしてValueへ記載する。長いobjectは既存のservice配下JSON artifactへのlinkを使用できる。配列要素の所属を失うleaf rowへの分解や、JSON内部へのMarkdown link埋込みは行わない。関連resourceへの説明上の参照には通常のrelative Markdown linkを使用する。
- 固定bucketを列挙する`bucketDefinitions`型Jobでは、`s3JobDefinition` rowを同service配下JSON artifactへのlinkとし、そのJobの設定表の後に`#### 対象S3 bucket`と3列の対応表を置く。この表はmodelの`desired.row.*.document`にあるbucketDefinitionsから生成する。1 bucketを1行とし、Job cellはそのJobへのsame-file link、account cellは確定済み12桁ID、Bucket cellは同targetのS3設計へのrelative linkまたは外部bucket名のliteralとする。S3 linkの表示名はlink先BucketNameに一致させ、同じaccountの行を連続させる。重複bucket、別Jobへのlink、空表を拒否する。

[Macie bucket対応表の例](detailed-design-samples.md#macie-bucket-mapping)

- `framework/scripts/sync-model.py --write`は対応表の行順からmodelの`desired.row.*.document`からJSON artifactと対応表を生成し、選択済み`scoping`も保持する。local validationは表とJSONのaccount、bucket、順序を照合する。`bucketCriteria`型Jobには固定bucket対応表を置かず、model rowのJSON objectを正本とする。
- `name`、`jobType`、`s3JobDefinition`を必須とし、未知のproperty、型、enum、長さ、範囲、nested object/arrayも検証する。未使用のoptional配列は空配列でなくrowを省略する。
- `SCHEDULED`は実行周期を正確に一つ指定する。`ONE_TIME`は`scheduleFrequency`と`initialRun`を省略する。S3対象は`bucketDefinitions`または`bucketCriteria`のどちらか一つにする。managed data identifierの選択方式とID配列、custom data identifierの必須関係も検証する。
- `Macie.ClassificationJob.jobId`は`IDENTIFIER_OUTPUT`としてcatalog順に記載する。未作成は既存の`PENDING_DEPLOY`、取得済みは非ARNの実IDとする。この値はCFnでの作成予定を意味しない。
- 既存Jobの取得がactive taskで許可されている場合、`ListClassificationJobs`で候補を提示し、humanの選択後に`DescribeClassificationJob`で選択済みroot propertyと必要な`jobId`だけを取得する。Cloud Control API用の型は生成しない。optional fieldが欠落またはnullならrowを省略し、response全体、統計、実行状態、生成ARNを保存しない。
- API catalogを使用しても`design` taskのAWS mutation禁止とlocal validation後の終了を維持する。設計書の作成はJob作成の自動化、Custom Resource、Terraform導入を許可しない。

## Related resource display

`framework/rules/resource-layout.json`は全catalog resourceの詳細blockについて、`independent`または親へ統合する関係を明示する。独立した詳細blockを持つresourceでも、Resource overviewで定める条件に従って一覧rowへまとめられる。表示上のまとまりとAWS/IaC resourceの識別・lifecycleを分離する。

- 統合定義の`parent`は包含するresource type、`parentProperty`は子から親への正式property、`maxCount`は親あたりの子の最大数（`null`は複数可）、`identityProperty`は子を識別する先頭propertyとする。`display: rule-table`はSecurity GroupのDirection付き横書き表を指定する。
- 通常の統合では親の全rowの後に子のrowを同じtableへ置き、No.はtable全体で連番にする。`display: rule-table`では後述の単一rule tableへ1 ruleを1 rowで置く。どちらも子ごとの独立heading・table・一覧は作らない。独立resourceとして設計する子のresource typeも`Owned catalog resource types`へ含める。
- `parentProperty`のrowは省略し、包含する親へのlogical referenceとして解決する。外部の既存親を参照する子だけの設計はこの形式では表現せず、対応する親の設計または別の表示contractが必要であることを報告する。
- `identityProperty`がない単一の子は親のmodelへrowを保持する。既存のS3 BucketPolicyはこの形式を維持する。
- `identityProperty`がある子は、そのpropertyのrowから次の子のidentity rowまでを一つのinstanceとする。identity rowの`Source / Comment`先頭に`<a id="<resource-name由来のanchor>"></a><!-- logical-id: <logical-id> -->`を置き、その後に日本語で属性の意味を記載する。`KMS.Alias`のanchorはAliasNameから共通規則で生成する。`display: rule-table`のruleには名称propertyがないため、従来の内部identity markerとcurrent IDの非表示markerを各rule rowの`Direction` cellへ維持し、表示用linkを作らない。この非表示markerは参照・識別用の構造情報であり、説明文やAWS propertyではない。
- 子のlogical IDは既存の確定値を保持する。新規で未確定ならhumanへ確認し、順番やAliasNameから推測して作らない。親子を通じてanchorとlogical IDを重複させず、同じ子のidentity valueを複数の親へ重複配置しない。ただし未作成のSecurity Group ruleのIdは複数rowで`PENDING_DEPLOY`となるため、確定済みlogical IDとanchorで区別する。
- 外部からの参照は子のanchorへ維持する。親へのlinkに置換したり、先頭の子を代表として選んだりしない。
- 各子のpropertyはその子自身のprovider schemaで検証する。所属親が異なる型、独立heading、欠落した識別情報、子の個数超過、重複、参照切れをlocal loopで拒否する。

KMSは`KMS.Key`のtable内に0個以上の`KMS.Alias`をまとめる。`KMS.Alias.TargetKeyId` rowは省略する。KeyId、Keyの設定、AliasNameの順とし、複数AliasではAliasName rowと識別markerをそれぞれ保持する。Key一覧の`AliasNames`列には対応するalias名を表示できる。

[KMS Aliasの例](detailed-design-samples.md#kms-alias)

S3の`KMSMasterKeyID`は引き続き`[alias/venus-dev-s3-file-transfer](kms.md#kms-s3filetransferkeyalias01)`とし、AliasNameを表示する。

`EC2.SubnetRouteTableAssociation`は`EC2.Subnet`に属するidentityなしの単一childとする。Subnet自身の全rowの後へMarkdown表示用の`EC2.RouteTableId`だけを置き、正式property `EC2.SubnetRouteTableAssociation.RouteTableId`として扱う。`Id`と`SubnetId`、Associationの独立anchor・heading・table・一覧は作らない。所属Subnetは包含するtableから解決し、Associationを設計しないSubnetではRouteTableId row自体を省略する。

新規catalog resourceの保守時には、同一service内の所属先、一対多、共有・複数対象、外部参照を確認して表示方針も登録する。schemaの型名や参照propertyだけから親子を自動推測しない。SQS/SNSの複数対象policy、IAM共有policy、共有・複数対象のassociationを一つの親へ無条件に統合しない。条件付き統合が必要な場合は判定条件と検証を先に実装する。既存の統合対象以外の詳細blockは独立表示を維持し、方針変更は明示scopeのframework taskで行う。

## Security Group rules tables

Security Groupも一覧は3列とし、SGのId、GroupDescription、選択済みGroupName、VpcIdを各resourceの4列詳細表に置く。ruleが0件でもanchor、heading、基本設定表を置く。ruleが1件以上あるSGだけ、基本設定表の後にInbound／Outboundをまとめた一つの横書きrule tableを置く。方向別の分割表、Ingress/Egressの全体一覧、ruleごとの縦書き4列表は作らない。

- 詳細表の`Id`はSGのcurrent IDまたは`PENDING_DEPLOY`、`VpcId`は所属VPCのidentifier参照、`GroupDescription`は正式property値とし、いずれも省略しない。`VpcId`のlinkは同じtargetのVPC設計を指し、表示textにVPCのcurrent IDまたは`PENDING_DEPLOY`を使う。所属VPCが未確定なら確認し、default VPCを推測しない。未選択の`GroupName`行は省略する。
- 選択済みタグは所属SGのH3 headingの直後に`<!-- security-group-tags: [{"Key":"...","Value":"..."}] -->`を1行だけ置いて保持する。表へのTags列追加や別のタグ表は作らない。未選択ならmetadata自体を省略する。JSONの各要素は文字列のKeyとValueだけを持ち、modelの`Tags[].Key`／`Tags[].Value`へ配列順を保って展開する。commentの区切りになる文字列はJSONのUnicode escapeで表す。metadataを一覧・別resource配下へ置かず、タグ値を推測・追加・削除しない。
- rule tableは1 ruleを1 rowとし、先頭columnを`Direction`とする。表示値は頭文字を大文字にした`Inbound`または`Outbound`だけを使用し、正式resource typeのIngress／Egressへ対応させる。`SecurityGroupRuleId`や`Id`のcolumnは作らない。
- 続くcolumnは`IpProtocol`と`Port`を必須とし、`CidrIp`、`CidrIpv6`、`Description`、`SourcePrefixListId`、`SourceSecurityGroupOwnerId`、`DestinationPrefixListId`から選択済みのpropertyを載せる。`SourceSecurityGroupId`と`DestinationSecurityGroupId`のcolumnは作らない。Inbound rowのDestination系、Outbound rowのSource系cellは`—`とする。`GroupId`や未登録columnは追加しない。
- Security Groupを送信元／宛先に選択したruleは、Direction cellの末尾へ`<!-- security-group-id: <SourceSecurityGroupIdまたはDestinationSecurityGroupIdのValue> -->`を置く。DirectionがInboundなら`SourceSecurityGroupId`、Outboundなら`DestinationSecurityGroupId`へ展開し、参照linkを含むValueをlosslessに保持する。表示columnや別の説明文へ値を重複させない。
- port表示は`Port`の1列にまとめ、`FromPort`／`ToPort`のcolumnを作らない。単一portは`443`、範囲は`1000-2000`の形式にし、正式propertyのFromPort／ToPortへ同値／開始・終了値として展開する。ICMP／ICMPv6（protocol番号1／58を含む）は同じPort cellに`Type=8, Code=0`の形式でtype/codeを保持し、port範囲として解釈しない。TCP／UDPは0〜65535の範囲、ICMP type/codeは-1〜255とし、type=-1ではcodeも-1とする。FromPort／ToPortの両方を未選択なら`—`とし、値を補完しない。`All`や複数の離れたportを一つの範囲へ読み替えない。Portは表示上のcolumn名であり、catalog propertyを追加しない。
- SG一覧と基本設定表の`No.`だけを`---:`、他のcolumnとrule tableの全columnを`---`で揃える。rule tableでは未選択のoptional propertyを表示だけの`—`とし、modelへsentinelを生成しない。片方向だけでも同じtableを使い、両方向のruleが0件ならrule tableだけを省略する。SGのanchorは一覧や他resourceからの参照先として維持する。未設計をdeny設定やAWSのdefault ruleと読み替えず、ruleを自動補完しない。
- 各ruleはIPv4 CIDR、IPv6 CIDR、Prefix List、Security Groupのいずれか一つを送信元／宛先に持つ。`SourceSecurityGroupOwnerId`は`SourceSecurityGroupId`に付随させる。値、参照先、`-1`、Port内の範囲・ICMP type/codeを保持し、`All`や推測したservice名へ書き換えない。RegionやHTTP/HTTPSなどのTypeを表示目的で追加しない。
- 独立した`EC2.SecurityGroupIngress`／`EC2.SecurityGroupEgress`のDirection cellは`Inbound <a id="<service-id>-<logical-idのlowercase>"></a><!-- logical-id: <logical-id> --><!-- rule-id: <IdのValue> -->`とし、Egressでは先頭を`Outbound`とする。Security Group参照を持つ場合だけ、その後へ上記`security-group-id` markerを続ける。表にはDirectionだけを表示し、logical ID・anchor・取得済みcurrent IDまたは`PENDING_DEPLOY`を非表示の構造情報として保持する。Idを画面上のcolumnや説明文へ重複表示せず、modelの正式property `Id`は維持する。`GroupId`は包含するSGから解決し、他SGへの所属を出現順やphysical IDで推測しない。外部SGだけを参照して包含するSGの設計がない場合は停止する。
- SG自身の`SecurityGroupIngress[]`／`SecurityGroupEgress[]`として設計したinline ruleは、Direction cellを`Inbound`または`Outbound`だけとし、identityやrule-idのmarkerを付けない。Security Group参照を持つ場合だけ上記`security-group-id` markerを続ける。catalogに存在しないinline rule IDを作らず、独立ruleへの変換もしない。inlineと独立ruleは同じtable内でも区別を保持する。
- model propertiesのSG属性・inline rule・独立rule・親参照を設計の正本とし、SG基本設定表とrule table、Direction／所属SGの非表示metadataを生成する。共通parserは表示の検証・明示migration時だけ正式catalog propertyへ展開し、SG属性・inline rule・独立ruleを保持する。元Markdownを書き換えたり、設定値を一覧へ重複保存したりしない。

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

設定表のpolicy JSONリンクだけでなく、所有resourceの設定表直後にJSON本文の派生表示を生成する。resource設定はmodel propertiesの正式row、policy本文はそのrowの`document`を正本とし、派生表示を独立した設計入力にしない。

### 対象と形式

表示方式の機械可読な定義は`framework/scripts/policy_tables.py`の`POLICY_FORMATS`とする。正式なcatalog propertyを完全一致で登録し、provider schemaで型を確認する。property名の末尾だけでpolicy documentと判定しない。catalogへdocument形式のpolicy propertyを追加する場合は、表示方式の登録とfocused checkも同じ明示scopeのtaskで更新する。

| 形式 | 対象 |
| --- | --- |
| Statement表 | IAM Roleのtrust／inline、IAM ManagedPolicy、S3 BucketPolicy、KMS KeyPolicy、VPC endpoint、SQS／SNS、ECR repository、Secrets Manager、CloudWatch Logsのresource policy、API Gateway、EventBridge、SSO PermissionSet inline、DynamoDBのtable／stream／replica policy |
| 内包するStatement表 | `DynamoDB.Table.ResourcePolicy`のJSON object内の`PolicyDocument`。外側の構造を保持し、未知のwrapper keyは省略せず停止する |
| 設定表 | SNSのdelivery／filter／redrive／replay／archive／data protection、SQSのredrive／redrive allow、CloudWatch Logsのdata protection、ECR lifecycle、Organizations PolicyのContent（SCPを含む各policy typeのJSON構造を保持） |

`SecurityPolicy`、`SslPolicy`、policy名、ARN、booleanなどのscalar／referenceは通常の設定行を維持する。CloudFrontやNetwork Firewall、Auto Scaling等のcatalogで個別propertyへ展開されているpolicy設定も既存の4列表へ記載する。選択していないpolicy、policy名、権限を表示のために作成・補完しない。

### 所属と派生表示

- IAM Roleは下記の表・markerを維持する。それ以外は所有resourceの設定表直後を`<!-- policy-tables:start -->`と`<!-- policy-tables:end -->`で囲み、所有するpolicyを設定行の順に生成する。
- S3 BucketPolicyは引き続きBucketの設定表内へ置き、派生policy表もBucketに所属させる。KMSのAliasはKeyと同じ設定表内の既存groupingを維持する。SQS/SNSなど複数resourceを対象とする独立policyを、一つの対象へ勝手に統合しない。
- IAM Role以外の表示名はJSONリンクの表示text、anchorは`<resource-anchor>-policy-<artifact-id>`とする。artifact IDは既存のlower-kebab-case filename stemを使用する。同一resource内の複数policyには異なるartifactを使用し、anchor衝突は停止する。配列の各対象へ設定するpolicyも各JSONリンクから識別できるようにする。
- 見出しは`#### ポリシー：<表示名>`または`#### ポリシー設定：<表示名>`とし、全serviceで設定rowにある正式な`Property`と元の`JSON`リンクを派生表示へ再表示しない。派生表示はanchor、見出し、Statement表または設定表で構成する。IAM信頼ポリシーでは下記のVersion表も含める。表示名を架空のresource propertyとして追加しない。
- policy表は所有resourceの詳細block内に生成し、一覧にはpolicy列を追加しない。
- Statement表の連番、列、Principal展開、Condition、escape、省略禁止、未知要素の拒否は下記のIAMと同じ方式を使用する。IAMを含む全serviceで独立metadata行の`Version：`と`Id：`を省略し、JSON本文のVersion/Idは保持する。権限policy以外のJSONをStatement形式と推測しない。
- 設定表は`Property | Type | Value`とし、PropertyはJSON Pointer、Typeは`object`／`array`／`string`／`number`／`boolean`／`null`を表示する。root pointerは空文字列、object keyは文字列順、配列は0始まりのindexと元の順序を保持する。`~`と`/`はpointer内で`~0`と`~1`へescapeする。子を持つcontainerのValueは表示だけを`—`、空object／arrayは`{}`／`[]`とする。全要素を表示し、構造や型を変換しない。設定表のProperty列やJSON内のVersion/Idというkeyは独立metadata行ではないため省略しない。
- `ECR.Repository.LifecyclePolicy`はwrapperの全設定を表示したうえで、`LifecyclePolicyText`がある場合はJSON文字列をparseした内容も設定表で表示する。JSON文字列以外や不正なJSONは停止する。表示からJSON本文を書き戻さない。
- 全形式で重複JSON key、不正なJSON定数、JSON object以外のartifact、他service配下のartifact参照を拒否する。marker欠落・重複・不正な所属、表や一覧リンクと正本との不一致をlocal loopでFAILとする。
- 生成は指定したMarkdown一件の派生policy表だけを更新する。modelには派生表示を重複保持せず、既存のJSONリンクとcanonical hashを維持する。

通常の設計保存ではmodel更新後の`sync-model.py --write`がこの表示処理を呼ぶ。以下は生成済みpolicy表示だけを検査する補助commandとする。`--write`なしはread-onlyの一致検証になる。

```console
python3 framework/scripts/policy_tables.py docs/designs/<environment>/<target-directory>/<service-id>.md --write
```

### IAM Role policy tables

IAM Roleの4列のresource-detail tableと独立policy JSON artifactを維持し、各Roleの設定表の直後に信頼ポリシーとinline policyのStatement表を生成する。Roleの設定はmodel propertiesの正式row、policy本文はそのrowの`document`を正本とする。Statement表はJSONの派生表示であり、独立した設計入力にしない。

- `## リソース一覧`内の`### IAM.Role`も共通の3列形式とし、ResourceNameにはRole詳細headingのidentifierを表示する。RoleNameとpolicy名・linkは詳細blockに保持し、一覧へ複製しない。`Comment`はRoleの用途説明を保持する。
- `Path`、`ManagedPolicyArns`、`PermissionsBoundary`など選択済みの他のRole設定は既存の4列表に保持する。IAM.ManagedPolicyとIAM.InstanceProfileの独立resource表示も維持する。
- 信頼ポリシーの表示名は`AssumeRolePolicyDocument`のJSONリンクの表示textを使用する。`FlowLogsTrust`は文書上の表示名であり、架空の`TrustPolicyName` propertyや独立IAM resourceを追加しない。inline policyの表示名は直前の`Policies[].PolicyName`を使用する。
- policy anchorは`<role-anchor>-trust`、`<role-anchor>-inline-<policy-name-artifact-id>`とする。inline suffixの正規化は既存のartifact命名と同じ処理を使い、別Roleの同名policyを混同しない。同一Roleで正規化後のanchorが衝突する場合は停止する。
- 見出しは`#### 信頼ポリシー：<表示名>`または`#### インラインポリシー：<PolicyName>`とする。共通ルールに従いProperty、JSON、Version、Idの独立metadata行を表示しない。信頼ポリシーのJSONにVersionがある場合は、見出し直後に`Version`の1列表を置き、値を1行で表示してからStatement表を続ける。Versionがない場合は表も値も補完しない。JSON本文は変更しない。
- IAM inline policy（`IAM.Role.Policies[].PolicyDocument`）のStatementに`Sid`がある場合は文字列かつ16文字以内とする。超過は検証エラーとし、自動で切り詰め・改名しない。SidがないStatementへ補完しない。この制限を信頼ポリシーや他policyのSid、JSON最上位のId、PolicyName、artifact ID、anchorへ適用しない。
- 表は1 Statementを1行とし、先頭列は`No.`の1始まりの連番とする。JSONのStatement配列順を維持し、Statementが単一objectの場合は1行にする。表の番号と任意の`Sid`は別物とし、`Sid`を発明・変更しない。
- 列は`No.`に続き、JSONに存在する`Sid`、`Effect`、`Principal`、`NotPrincipal`、`Action`、`NotAction`、`Resource`、`NotResource`、`Condition`をこの順序で掲載する。Principalがobjectなら`Principal.Service`、`Principal.AWS`、`Principal.Federated`、`Principal.CanonicalUser`のように種別ごとに展開する。NotPrincipalも同様とし、種別の列順は文字列順とする。Statement間で存在しない列のcellは表示だけを`—`にする。
- 複数Action・Resource・Principal値はcell内で`<br>`区切りにする。Conditionは演算子、context key、値を省略せず、演算子とkeyの文字列順で同じcellへ表示する。複数の条件値はJSON配列として表示し、条件の演算子や配列構造を変えない。Conditionを理由にStatementを分割・統合しない。
- JSON object key順やindentだけの変更では表を変えない。文字列内のMarkdown/HTML特殊文字をescapeし、表示上のescapeをJSON値へ書き戻さない。空配列も省略せず表示する。未知のpolicy/Statement要素、重複JSON key、解釈できない構造は黙って省略せず停止する。
- Roleごとの生成範囲は`<!-- iam-policy-tables:start -->`と`<!-- iam-policy-tables:end -->`で囲む。marker内にはそのRoleのpolicy anchor、見出し、信頼ポリシーのVersion表、Statement表だけを置く。設定表や手動のimplementation noteを入れない。markerの欠落・重複・不正な所属も検証対象とする。
- 生成処理は明示したMarkdown一件のmarker内だけを更新する。policy JSON、Role設定、resource一覧を変更しない。表の内容やJSONを自動的に正しい権限へ修正しない。

通常の設計保存ではmodel更新後の`sync-model.py --write`がこの表示処理を呼ぶ。以下は生成済みpolicy表示だけを検査する補助commandとする。`--write`を省略するとread-onlyの一致検証になる。

```console
python3 framework/scripts/policy_tables.py docs/designs/<environment>/<target-directory>/iam.md --write
```

生成される信頼ポリシー表の形式例（値は対象設計のJSONに従う）: [IAM信頼ポリシー表の例](detailed-design-samples.md#iam-trust-policy)

local loopは同じ生成処理で期待する一覧と表を計算し、保存済みMarkdownとの不一致をFAILにする。policy JSONの構造・表示整合性の検証であり、AWSの実効権限判定やActionごとのResource適合性を検証したという意味ではない。設計入力のResource ARN/ARNパターンは保持し、generated ARNの永続化禁止を緩和しない。

## Links and anchors

- 関連 resource は `Value` column の Markdown link で表す。
- link は relative path を使う。
- renderer 自動生成だけに依存せず、resource heading の直前に explicit HTML anchor を置く。
- anchorはService IDとlowercase resource表示名を`-`で結ぶ。表示名内の`[a-z0-9_.-]`以外の連続文字を`-`へ置き換え、表示名部分の前後の`-`を除く。正規化後のanchor衝突は停止し、内部IDで補正しない。内部logical IDを表示用linkのanchor生成元にしない。
- `EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`、`EC2.FlowLog`では`.Name` valueをlogical IDとし、anchorにも同じvalueをlowercaseで使用する。
- 別fileの例: `[role-app-dev-flow-logs](iam.md#iam-role-app-dev-flow-logs)`。
- 同じfileの例: `[flow-log-app-dev-vpc](#vpc-flow-log-app-dev-vpc)`。
- file と anchor の存在を local loop で検証する。
- catalogのidentifier outputを参照するpropertyは、link先anchorをlogical referenceの正本とし、表示textへ参照先のcurrent physical IDを記載する。deploy前とdestroy後は`[PENDING_DEPLOY](#vpc-vpc-app-dev)`、deploy成功後は`[vpc-0123456789abcdef0](#vpc-vpc-app-dev)`とする。
- IaC生成は表示textのphysical IDを使用せず、link先anchorに対応する非表示metadataのlogical IDを解決する。markerを省略したresourceはheadingの確定済みresource名を内部identityとして使う。CloudFormationは`!Ref`、Terraformはresource attribute referenceを使用し、physical IDを直書きしない。

## Generated values and deployment state

- 必要なnon-ARN generated current identifierは独立sectionではなく、`framework/materials/aws/*.properties`で`IDENTIFIER_OUTPUT`と指定された正式なcatalog propertyを該当resource tableのcatalog順の位置へ記載する。`VPC ID`や`Subnet ID`などの合成labelを作らない。
- 未作成resourceのdeploy前はidentifier output rowの値を`PENDING_DEPLOY`とする。例えば`EC2.VPC.VpcId`の`Source / Comment`はprefixや取得元ではなく属性の意味だけを表す`一意に識別するID`とする。
- current identifierは、infrastructure taskのdeploy/apply成功後、またはdesign taskが選択済み既存resourceをread-only取得した場合だけ実値へ更新する。同じidentifierを参照する全propertyのMarkdown link表示textも同じphysical IDへ更新し、`Source / Comment`は属性の意味を維持する。
- replacement後はidentifier output rowと全参照元を新しいphysical IDへ同じ変更で更新する。destroy後はidentifier output rowを`PENDING_DEPLOY`へ戻し、全参照元のlink表示textも`PENDING_DEPLOY`へ戻す。
- human-selected nameなど通常のcatalog propertyがcurrent identifierになるresourceは、そのpropertyを使用し、`IDENTIFIER_OUTPUT`でない重複rowを作らない。
- generated ARNは詳細設計にも`model/**`にも永続化しない。
- old physical valueはGit履歴とAWS/IaC deployment historyで追跡し、詳細設計やscenario evidenceへ保存しない。
- `model/**`はidentifier output rowとidentifier参照rowの同じrow keyに、anchorから解決したlogical referenceを`desired.*`、Markdownの表示textまたはidentifier output valueを`observed.*`として保持する。

[Deploy前の参照例](detailed-design-samples.md#pending-reference)

[Deploy後の参照例](detailed-design-samples.md#deployed-reference)

[Resource自身のidentifier output例](detailed-design-samples.md#identifier-output)

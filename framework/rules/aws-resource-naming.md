# AWS Resource Naming Rules

## Scope

このruleのframework命名convention・coverage・mandatory Name policyはCREATE（resourceMode未指定を含む）に適用する。IMPORTはAWS actual/currentの名称・設定・Name tagの有無を維持し、convention不一致やName tag不存在をerror／blockerにしない。rename、Name tagの追加・変更、仮値の補完は禁止する。provider schema等のAWS制約、構造・確定値・参照の検証は両modeで維持する。表示labelはAWS propertyと区別する。区分の正本は`model-information.md`に従う。

このruleは、詳細設計でhuman-selectedなAWS resource name、identifier、または`Name` tagを決定するときのdefault naming conventionとする。

- AWS生成のphysical ID、ARN、DNS name、IP addressには適用しない。
- `IAM.ManagedPolicy.ManagedPolicyName`、`IAM.User.UserName`、`IAM.InstanceProfile.InstanceProfileName`は命名conventionと命名ルールcoverage checkの対象外とする。名称値の欠落・未確定値やprovider schemaの型・pattern・lengthなどの検証は対象外にしない。
- `Config.ConfigurationRecorder.Name`、`Config.DeliveryChannel.Name`、`Glue.Connection.ConnectionInput.Name`、`GuardDuty.Detector.Name`、`Route53.HostedZone.Name`、`Route53.RecordSet.Name`は命名ルールcoverage checkの対象外とする。名称値の欠落・未確定値やprovider schemaの型・pattern・lengthなどの検証は維持する。`GuardDuty.Detector.Name`の除外はcatalogにないpropertyの追加・使用を許可するものではない。Name tagや他のName propertyへ除外を拡張しない。
- `SecretsManager.Secret.Name`、`Glue.Database.DatabaseInput.Name`、`Glue.Table.TableInput.Name`は命名conventionと命名ルールcoverage checkの対象外とする。Secrets Managerの`{{application}}-{{environment}}-{{purpose}}`、Glue Databaseの`{{application}}*{{environment}}*{{purpose}}`、Glue Tableの`{{purpose}}`は名称形式の参考として保持し、Glue Tableは業務上のtable名を維持する。これらの形式への適合はチェックしない。名称値の欠落・未確定値やprovider schemaの型・pattern・lengthなどの検証は維持し、Name tagや他のName propertyへ除外を拡張しない。
- `CodeBuild.Project.Name`は詳細設計で必須とし、確定済みnon-empty literalをresourceごとに1 row保持する。Name tagや表示labelで代替せず、未確定なら停止する。
- root-levelの`Tags`または`HostedZoneTags`はtag設定能力を示すだけで、`Name` tagの必須性を意味しない。`Name` tagはdefaultでoptionalとする。
- `Name` tagを必須とするcatalog resource typeは`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`、`EC2.FlowLog`と`EC2.VPCEndpoint`とする。前4種類は詳細設計でそれぞれ`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`、`EC2.FlowLog.Name`の1 rowで表す。
- `EC2.VPCEndpoint`は正式な`Tags[].Key=Name`と直後の対応する`Tags[].Value`で必須tagを保持する。設計専用`.Name`を追加せず、一覧・heading・通常の参照linkにはこのValueを使用する。display labelで欠落を代替しない。
- その他のresourceでは、humanが`Name` tagを明示した場合だけ設計する。taggableであることを理由に質問、追加、blocker判定をしない。
- 上記4種類の`.Name`は詳細設計専用propertyとし、IaCではcase-sensitiveな`Name` keyを持つtagへ変換する。`Tags[].Key`と`Tags[].Value`の2 rowでは表さない。
- その他のresourceでhuman-selectedな`Name` tagを使用する場合は、array形式では`Tags[].Key`と直後の`Tags[].Value`、object形式では`Tags` JSON objectで表す。
- `Name` tagのkeyはcase-sensitiveな`Name`を正確に使用し、valueを空にしない。
- 上記4種類のresource heading identifierは`.Name` valueと完全一致させ、anchorはService IDとそのvalueをlowercaseで結ぶ。
- 既存resourceと既存詳細設計の確定済み名称を自動変更しない。renameまたはreplacementは別の明示依頼がある場合だけ扱う。
- CREATEとして扱う既存resourceに必須の`Name` tagが存在しない場合は値を発明せず、設計保存やIaC変更へ進まずblockerとして報告する。
- CloudFormation logical ID、詳細設計のlogical ID、JSON artifact filenameには、それぞれの既存ruleを適用する。

## Naming rule coverage check

- 設計開始前の必須gateとする。対象catalog resource typeとCREATE／IMPORTを確定した直後、名称・parameter・policyなどの設計質問へ進む前に、`python3 framework/scripts/check-design-naming.py --resource-type <Catalog.ResourceType> --mode <CREATE|IMPORT>`を対象resourceごとに実行する。CREATEはcatalogの名称propertyと必須Nameを値未確定でも検査し、human-selectedなoptional Name tagがある場合だけ`--name-tag`を追加する。IMPORT、Scopeの明示除外、名称を持たない型は従来の適用範囲を維持する。
- 未登録rule、空pattern、rule fileの読込失敗、未知resource type、preflightの未実行・失敗では設計を開始・継続しない。不足するresource type／propertyと原因を示して停止し、名称候補・代替patternを推測せず、modelやMarkdown／JSONを保存しない。命名ルールの追加を同じdesign taskで行わない。
- 再開時、resource type／modeの追加・変更時、optional Name tagの選択時、design契約の登録前と保存前にも再実行する。対象・管理区分・optional Name tagの選択に必要な確認だけはgate前に行える。対象全件が通過するまで通常の設計質問へ進まない。
- Scopeで対象外としたpropertyを除き、作成対象の選択済み名称property、必須`.Name`、human-selectedな`Name` tagについて、対象service fileのcatalog resource typeとNaming targetが対応する行を保存前に確認する。未登録の場合は対象type／propertyを明示して停止し、patternを推測しない。
- 名称propertyを選択していないresourceと、名称を持たない型（例：`SecurityHub.Hub` / Security Hub CSPM）は対象外とする。表示用label、内部logical ID、AWS生成identifierに命名patternを要求しない。taggableだけでName tagを追加しない。
- 既存resourceの確定済み名称は変更しない。このcheckはruleの有無を確認し、patternへの自動renameはしない。

## General rules

- service固有要件がない名称はlower-kebab-caseとし、区切りにはASCIIの`-`を使う。
- patternのplaceholderは`{{lower_snake_case}}`、optional componentは`[-{{component}}]`で表す。
- `application`、`purpose`、`service`、`subnet_type`、`route_type`などの意味を持つcomponentはhumanが確認した値だけを使う。値を推測せず、未確定なら停止して一項目ずつ確認する。
- `environment`、`target_alias`、`account_id`、`region`は`project.json`の選択targetと一致する値だけを使う。aliasがないtargetにaliasを発明しない。
- `account_id`は選択targetの`awsAccountId`を使用する。
- `number`は2桁の`01`から始める。同じ役割のresourceが複数存在する場合にだけ連番を使う。
- `zone`、`requester_vpc`、`accepter_vpc`、`resource_token`、`target_token`はhuman-confirmedなstable tokenを使い、generated IDやARNを埋め込まない。
- `source`、`destination`、`condition`など変更され得るcomponentは、その値を名称へ固定することをhumanが明示した場合だけ使う。
- 組織固有tokenの`ISZPF`、`ISZ`、`PF`、`isuzu`、`isuzucojp`はgeneric patternまたはexampleに使用しない。
- final nameは対象propertyのprovider schemaにあるtype、pattern、lengthとAWSのuniqueness scopeを満たすことを確認する。超過時に自動truncate、hash付与、略語化をせず、短い値をhumanへ確認する。
- explicit nameの変更がreplacementを伴う場合は、design taskでrenameを確定するだけとし、IaC変更やreplacement実行へ進まない。
- `Naming target`が`.Name`または`Name tag`のrowは、必須またはhuman-selectedな`Name` tag valueへpatternを適用する。
- 必須またはhuman-selectedな`Name` tagのpatternが対象service fileのtableにない場合は、nameを推測せずhumanへ一つ質問する。

## Name tag policy

| Policy | AWS resource | Rule |
| --- | --- | --- |
| Required | VPC (`EC2.VPC.Name`)、Subnet (`EC2.Subnet.Name`)、Route table (`EC2.RouteTable.Name`)、Flow Log (`EC2.FlowLog.Name`)、VPC endpoint (`EC2.VPCEndpoint`のName tag)、詳細設計するEC2 Instance (`EC2.Instance`のName tag) | AWS生成IDだけでは用途を識別しにくく、VPC consoleで継続的に選択するため必須とする |
| Conditional | VPC peering connection、NAT gateway、Transit gateway／attachment／route table、Customer gateway、Site-to-Site VPN connection | 同種resourceが複数、cross-account／central networking、またはconsoleで頻繁に手動選択する場合にhumanが使用を決定する |
| Optional by default | Internet gateway、Elastic IP address、Security group、固有のname／identifier propertyを持つresource | 関連先または正式なname／identifierで識別できるため、自動追加しない |

個別に`EC2.Instance`として詳細設計するresourceはName tagを表示名とする。Auto Scalingなどが作成し、個別の詳細設計resourceとして扱わない一時的なEC2 Instanceへ同一の`Name` tagを必須化しない。Security groupは必須の`GroupName`を使用し、`Name` tagを重複要求しない。

## Service rule lookup

共通ルールを読んだ後、対象resource typeの`.`より前のcatalog namespaceに対応するfileだけを読む。例：`S3.Bucket`は`S3.md`、VPC・Subnet・EC2 Instance・Security groupは`EC2.md`。複数serviceを扱う場合も対象namespaceだけを読み、directory全体を一括で読まない。対象ruleがない場合はcoverage checkに従い、命名patternを推測しない。

| Catalog namespace | Rule file |
| --- | --- |
| `ApiGateway` | [ApiGateway](aws-resource-naming/ApiGateway.md) |
| `ApiGatewayV2` | [ApiGatewayV2](aws-resource-naming/ApiGatewayV2.md) |
| `Athena` | [Athena](aws-resource-naming/Athena.md) |
| `AutoScaling` | [AutoScaling](aws-resource-naming/AutoScaling.md) |
| `Backup` | [Backup](aws-resource-naming/Backup.md) |
| `CloudFormation` | [CloudFormation](aws-resource-naming/CloudFormation.md) |
| `CloudTrail` | [CloudTrail](aws-resource-naming/CloudTrail.md) |
| `CloudWatch` | [CloudWatch](aws-resource-naming/CloudWatch.md) |
| `CodeBuild` | [CodeBuild](aws-resource-naming/CodeBuild.md) |
| `CodeCommit` | [CodeCommit](aws-resource-naming/CodeCommit.md) |
| `CodePipeline` | [CodePipeline](aws-resource-naming/CodePipeline.md) |
| `Config` | [Config](aws-resource-naming/Config.md) |
| `EC2` | [EC2](aws-resource-naming/EC2.md) |
| `ElasticLoadBalancingV2` | [ElasticLoadBalancingV2](aws-resource-naming/ElasticLoadBalancingV2.md) |
| `Events` | [Events](aws-resource-naming/Events.md) |
| `FMS` | [FMS](aws-resource-naming/FMS.md) |
| `Glue` | [Glue](aws-resource-naming/Glue.md) |
| `IAM` | [IAM](aws-resource-naming/IAM.md) |
| `KMS` | [KMS](aws-resource-naming/KMS.md) |
| `Kinesis` | [Kinesis](aws-resource-naming/Kinesis.md) |
| `KinesisFirehose` | [KinesisFirehose](aws-resource-naming/KinesisFirehose.md) |
| `Lambda` | [Lambda](aws-resource-naming/Lambda.md) |
| `Logs` | [Logs](aws-resource-naming/Logs.md) |
| `MWAA` | [MWAA](aws-resource-naming/MWAA.md) |
| `Macie` | [Macie](aws-resource-naming/Macie.md) |
| `NetworkFirewall` | [NetworkFirewall](aws-resource-naming/NetworkFirewall.md) |
| `Organizations` | [Organizations](aws-resource-naming/Organizations.md) |
| `QuickSight` | [QuickSight](aws-resource-naming/QuickSight.md) |
| `RAM` | [RAM](aws-resource-naming/RAM.md) |
| `RDS` | [RDS](aws-resource-naming/RDS.md) |
| `Route53Profiles` | [Route53Profiles](aws-resource-naming/Route53Profiles.md) |
| `Route53Resolver` | [Route53Resolver](aws-resource-naming/Route53Resolver.md) |
| `S3` | [S3](aws-resource-naming/S3.md) |
| `SNS` | [SNS](aws-resource-naming/SNS.md) |
| `SQS` | [SQS](aws-resource-naming/SQS.md) |
| `SSM` | [SSM](aws-resource-naming/SSM.md) |
| `Scheduler` | [Scheduler](aws-resource-naming/Scheduler.md) |
| `WAFv2` | [WAFv2](aws-resource-naming/WAFv2.md) |

provider schemaまたはAWS serviceの現在の制約が対象service fileの制約より厳しい場合は、厳しい方を適用する。制約を満たせない場合は名称を推測して補正せず、humanへ確認して停止する。

## 設定表の表示順

- 通常propertyの表示順はmaterialsのproperties行順に従う。Name tagの必須性、design-only .Nameの1行表示・heading・anchorの契約は維持し、表示位置は`framework/rules/detailed-design.md`に従う。

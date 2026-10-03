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

- Scopeで対象外としたpropertyを除き、作成対象の選択済み名称property、必須`.Name`、human-selectedな`Name` tagについて、下表のcatalog resource typeとNaming targetが対応する行を保存前に確認する。未登録の場合は対象type／propertyを明示して停止し、patternを推測しない。
- 名称propertyを選択していないresourceと、名称を持たない型（例：`SecurityHub.Hub` / Security Hub CSPM）は対象外とする。表示用label、内部logical ID、AWS生成identifierに命名patternを要求しない。taggableだけでName tagを追加しない。
- 既存resourceの確定済み名称は変更しない。このcheckはruleの有無を確認し、patternへの自動renameはしない。

## General rules

- service固有要件がない名称はlower-kebab-caseとし、区切りにはASCIIの`-`を使う。
- patternのplaceholderは`{{lower_snake_case}}`、optional componentは`[-{{component}}]`で表す。
- `application`、`purpose`、`service`、`subnet_type`、`route_type`などの意味を持つcomponentはhumanが確認した値だけを使う。値を推測せず、未確定なら停止して一項目ずつ確認する。
- `environment`、`target_alias`、`account_id`、`region`は`project.json`の選択targetと一致する値だけを使う。aliasがないtargetにaliasを発明しない。
- `number`は2桁の`01`から始める。同じ役割のresourceが複数存在する場合にだけ連番を使う。
- `zone`、`requester_vpc`、`accepter_vpc`、`resource_token`、`target_token`はhuman-confirmedなstable tokenを使い、generated IDやARNを埋め込まない。
- `source`、`destination`、`condition`など変更され得るcomponentは、その値を名称へ固定することをhumanが明示した場合だけ使う。
- 組織固有tokenの`ISZPF`、`ISZ`、`PF`、`isuzu`、`isuzucojp`はgeneric patternまたはexampleに使用しない。
- final nameは対象propertyのprovider schemaにあるtype、pattern、lengthとAWSのuniqueness scopeを満たすことを確認する。超過時に自動truncate、hash付与、略語化をせず、短い値をhumanへ確認する。
- explicit nameの変更がreplacementを伴う場合は、design taskでrenameを確定するだけとし、IaC変更やreplacement実行へ進まない。
- `Naming target`が`.Name`または`Name tag`のrowは、必須またはhuman-selectedな`Name` tag valueへpatternを適用する。
- 必須またはhuman-selectedな`Name` tagのpatternがこのtableにない場合は、nameを推測せずhumanへ一つ質問する。

## Name tag policy

| Policy | AWS resource | Rule |
| --- | --- | --- |
| Required | VPC (`EC2.VPC.Name`)、Subnet (`EC2.Subnet.Name`)、Route table (`EC2.RouteTable.Name`)、Flow Log (`EC2.FlowLog.Name`)、VPC endpoint (`EC2.VPCEndpoint`のName tag)、詳細設計するEC2 Instance (`EC2.Instance`のName tag) | AWS生成IDだけでは用途を識別しにくく、VPC consoleで継続的に選択するため必須とする |
| Conditional | VPC peering connection、NAT gateway、Transit gateway／attachment／route table、Customer gateway、Site-to-Site VPN connection | 同種resourceが複数、cross-account／central networking、またはconsoleで頻繁に手動選択する場合にhumanが使用を決定する |
| Optional by default | Internet gateway、Elastic IP address、Security group、固有のname／identifier propertyを持つresource | 関連先または正式なname／identifierで識別できるため、自動追加しない |

個別に`EC2.Instance`として詳細設計するresourceはName tagを表示名とする。Auto Scalingなどが作成し、個別の詳細設計resourceとして扱わない一時的なEC2 Instanceへ同一の`Name` tagを必須化しない。Security groupは必須の`GroupName`を使用し、`Name` tagを重複要求しない。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon VPC | VPC | `EC2.VPC` | `EC2.VPC.Name` | `vpc-{{application}}-{{environment}}` |
| Amazon VPC | Subnet | `EC2.Subnet` | `EC2.Subnet.Name` | `sbnt-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}-{{zone}}-{{number}}` |
| Amazon VPC | Route table | `EC2.RouteTable` | `EC2.RouteTable.Name` | `rtb-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}[-{{zone}}]-{{number}}` |
| Amazon VPC | Flow Log | `EC2.FlowLog` | `EC2.FlowLog.Name` | `flowlog-{{application}}-{{environment}}[-{{target_alias}}]` |
| Amazon VPC | VPC peering connection | `EC2.VPCPeeringConnection` | Name tag | `pcx-{{requester_vpc}}-to-{{accepter_vpc}}-{{number}}` |
| Amazon VPC | Internet gateway | `EC2.InternetGateway` | Name tag | `igw-{{application}}-{{environment}}` |
| Amazon VPC | VPC endpoint | `EC2.VPCEndpoint` | Name tag | `vpce-{{application}}-{{environment}}-{{service}}` |
| Amazon VPC | Block Public Access exclusion | `EC2.VPCBlockPublicAccessExclusion` | Name tag | `vbpe-{{application}}-{{environment}}-{{purpose}}` |
| Amazon VPC | NAT gateway | `EC2.NatGateway` | Name tag | `natgw-{{application}}-{{environment}}-{{zone}}` |
| Amazon VPC | Elastic IP address | `EC2.EIP` | Name tag | `eip-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Transit gateway | `EC2.TransitGateway` | Name tag | `tgw-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Transit gateway attachment | `EC2.TransitGatewayVpcAttachment` | Name tag | `tgwa-{{application}}-{{environment}}-{{vpc_token}}-{{number}}` |
| Amazon VPC | Transit gateway route table | `EC2.TransitGatewayRouteTable` | Name tag | `tgwrtb-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Workload transit gateway attachment | `EC2.TransitGatewayVpcAttachment` | Name tag | `tgwa-{{account_id}}-{{target_alias}}` |
| Amazon VPC | Workload transit gateway route table | `EC2.TransitGatewayRouteTable` | Name tag | `tgwrtb-{{account_id}}-{{target_alias}}` |
| Amazon VPC | Customer gateway | `EC2.CustomerGateway` | Name tag | `cgw-{{dc_location}}-{{number}}` |
| Amazon VPC | Site-to-Site VPN connection | `EC2.VPNConnection` | Name tag | `s2s-{{dc_location}}-{{number}}` |
| Amazon S3 | General purpose bucket | `S3.Bucket` | `BucketName` | `{{application}}-{{environment}}-{{purpose}}-{{account_id}}-{{region}}` |
| Amazon S3 | Lifecycle rule | `S3.Bucket` | `LifecycleConfiguration.Rules[].Id` | `{{purpose}}-{{lifecycle_action}}` |
| Amazon RDS | DB instance | `RDS.DBInstance` | `DBInstanceIdentifier` | `rds-{{application}}-{{environment}}-{{engine}}-{{number}}` |
| Amazon RDS | DB subnet group | `RDS.DBSubnetGroup` | `DBSubnetGroupName` | `rdbsg-{{application}}-{{environment}}-{{number}}` |
| Amazon RDS | DB parameter group | `RDS.DBParameterGroup` | `DBParameterGroupName` | `rdbpg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon RDS | DB cluster parameter group | `RDS.DBClusterParameterGroup` | `DBClusterParameterGroupName` | `rdbcpg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon RDS | Option group | `RDS.OptionGroup` | `OptionGroupName` | `rdbog-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon EC2 | Instance | `EC2.Instance` | Name tag | `{{environment}}-{{application}}-{{purpose}}-{{number}}` |
| Amazon EC2 | Security group | `EC2.SecurityGroup` | `GroupName` | `{{environment}}-{{application}}-{{service}}-{{purpose}}-{{number}}-sg` |
| Amazon EC2 | Security group | `EC2.SecurityGroup` | Name tag | `{{environment}}-{{application}}-{{service}}-{{purpose}}-{{number}}-sg` |
| Amazon EC2 | Launch template | `EC2.LaunchTemplate` | `LaunchTemplateName` | `aslt-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Elastic Load Balancing | Load balancer | `ElasticLoadBalancingV2.LoadBalancer` | `Name` | `{{load_balancer_type}}-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Elastic Load Balancing | Target group | `ElasticLoadBalancingV2.TargetGroup` | `Name` | `tgp-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| EC2 Auto Scaling | Auto Scaling group | `AutoScaling.AutoScalingGroup` | `AutoScalingGroupName` | `asg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon CloudWatch | Alarm | `CloudWatch.Alarm` | `AlarmName` | `{{account_id}}:{{environment}}:{{resource_token}}:{{aws_service}}.{{metric_name}}[.{{statistic}}][.{{condition}}][.{{severity}}]` |
| Amazon CloudWatch Logs | Log group | `Logs.LogGroup` | `LogGroupName` | `cwlogs-{{application}}-{{environment}}-{{purpose}}` |
| Amazon Athena | Workgroup | `Athena.WorkGroup` | `Name` | `athwg-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Job | `Glue.Job` | `Name` | `glue-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Security configuration | `Glue.SecurityConfiguration` | `Name` | `glsc-{{application}}-{{environment}}-{{purpose}}` |
| AWS Glue | Catalog | `Glue.Catalog` | `Name` | `glct-{{application}}-{{environment}}-{{purpose}}` |
| Amazon QuickSight | Data source | `QuickSight.DataSource` | `Name` | `qsds-{{application}}-{{environment}}-{{source_type}}-{{purpose}}` |
| Amazon QuickSight | VPC connection | `QuickSight.VPCConnection` | `Name` | `qsvc-{{application}}-{{environment}}-{{purpose}}` |
| Amazon MWAA | Environment | `MWAA.Environment` | `Name` | `mwaa-{{application}}-{{environment}}[-{{purpose}}]` |
| Amazon Macie | Classification job | `Macie.ClassificationJob` | `name` | `macie-{{application}}-{{environment}}-{{purpose}}` |
| AWS CloudTrail | Trail | `CloudTrail.Trail` | `TrailName` | `ctrail-{{application}}-{{environment}}-{{purpose}}` |
| AWS CloudFormation | Stack | `CloudFormation.Stack` | `StackName` | `cfn-stack-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| AWS CloudFormation | StackSet | `CloudFormation.StackSet` | `StackSetName` | `cfn-{{application}}-{{environment}}-{{purpose}}-{{deployment_scope}}` |
| AWS CloudFormation | Change set | `CloudFormation.ChangeSet` | `ChangeSetName` | `cfn-cset-{{purpose}}-{{revision}}` |
| AWS CodeBuild | Project | `CodeBuild.Project` | `Name` | `cbld-{{application}}-{{environment}}-{{purpose}}` |
| AWS CodePipeline | Pipeline | `CodePipeline.Pipeline` | `Name` | `cpln-{{application}}-{{environment}}-{{purpose}}` |
| AWS CodeCommit | Repository | `CodeCommit.Repository` | `RepositoryName` | `ccmt-{{application}}[-{{environment}}]-{{purpose}}` |
| AWS KMS | Customer managed key alias | `KMS.Alias` | `AliasName` | `alias/{{application}}-{{environment}}-{{service}}-{{purpose}}` |
| Amazon Data Firehose | Delivery stream | `KinesisFirehose.DeliveryStream` | `DeliveryStreamName` | `kdf-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |
| Amazon Kinesis Data Streams | Data stream | `Kinesis.Stream` | `StreamName` | `kds-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |
| Amazon EventBridge | Rule | `Events.Rule` | `Name` | `ebr-{{rule_type}}-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |
| Amazon EventBridge Scheduler | Schedule | `Scheduler.Schedule` | `Name` | `ebs-{{application}}-{{environment}}-{{purpose}}-{{pattern}}-{{timeslot}}` |
| Amazon SNS | Topic | `SNS.Topic` | `TopicName` | `sns-{{application}}-{{environment}}-{{purpose}}[.fifo]` |
| Amazon SQS | Queue | `SQS.Queue` | `QueueName` | `sqs-{{application}}-{{environment}}-{{purpose}}[.fifo]` |
| AWS Lambda | Function | `Lambda.Function` | `FunctionName` | `lmda-{{application}}-{{environment}}-{{purpose}}` |
| AWS IAM | Role | `IAM.Role` | `RoleName` | `{{application}}-{{environment}}-{{purpose}}-role` |
| AWS RAM | Resource share | `RAM.ResourceShare` | `Name` | `ram-{{service}}-{{application}}-{{environment}}-share-with-{{target_type}}-{{target_token}}` |
| Amazon Route 53 Resolver | Resolver endpoint | `Route53Resolver.ResolverEndpoint` | `Name` | `rslv-{{endpoint_type}}-{{application}}-{{environment}}-{{purpose}}` |
| Amazon Route 53 Resolver | Resolver rule | `Route53Resolver.ResolverRule` | `Name` | `rslvr-{{application}}-{{environment}}-{{from}}-to-{{to}}-{{domain_token}}` |
| Amazon Route 53 Profiles | Profile | `Route53Profiles.Profile` | `Name` | `rpf-{{application}}-{{environment}}-{{region}}` |
| AWS Backup | Backup vault | `Backup.BackupVault` | `BackupVaultName` | `backup-vault-{{application}}-{{environment}}-{{purpose}}` |
| AWS Backup | Backup plan | `Backup.BackupPlan` | `BackupPlanName` | `backup-plan-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon API Gateway | REST, HTTP, or WebSocket API | `ApiGateway.RestApi`, `ApiGatewayV2.Api` | `Name` | `apigw-{{protocol}}-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | Web ACL | `WAFv2.WebACL` | `Name` | `wafacl-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | Rule group | `WAFv2.RuleGroup` | `Name` | `wafrg-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | IP set | `WAFv2.IPSet` | `Name` | `wafip-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Firewall | `NetworkFirewall.Firewall` | `FirewallName` | `nfwl-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Firewall policy | `NetworkFirewall.FirewallPolicy` | `FirewallPolicyName` | `nfwp-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Rule group | `NetworkFirewall.RuleGroup` | `RuleGroupName` | `nfwr-{{application}}-{{environment}}-{{purpose}}` |
| AWS Organizations | Service control policy | `Organizations.Policy` | `Name` | `scp-{{application}}[-{{environment}}]-{{purpose}}` |
| AWS Firewall Manager | Policy | `FMS.Policy` | `PolicyName` | `fmsp-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Patch baseline | `SSM.PatchBaseline` | `Name` | `sspb-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Association | `SSM.Association` | `AssociationName` | `ssma-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window | `SSM.MaintenanceWindow` | `Name` | `ssmw-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window target | `SSM.MaintenanceWindowTarget` | `Name` | `mwtg-{{application}}-{{environment}}-{{purpose}}` |
| AWS Systems Manager | Maintenance window task | `SSM.MaintenanceWindowTask` | `Name` | `mwts-{{application}}-{{environment}}-{{purpose}}` |
| AWS Config | Config rule | `Config.ConfigRule` | `ConfigRuleName` | `cfgr-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS WAFのWebACL／RuleGroup／IPSetのprefixはそれぞれ`wafacl`／`wafrg`／`wafip`とし、すべて`waf`を含める。
- AWS Organizations Policyの`scp` patternは`Type=SERVICE_CONTROL_POLICY`のSCPに使用する。環境間で同じSCPを共有する場合は`environment`を省略し、環境別に分ける場合は含める。他のpolicy typeへ`scp` prefixを自動適用しない。
- AWS Systems Manager Association自身の名称は`AssociationName`を対象とする。`Name`は参照するSSM document名（例：`AWS-RunPatchBaseline`）であり、この命名patternで変更しない。
- VPC Block Public Access Optionsは名称propertyを持たないため命名patternを要求しない。Exclusionの`Name` tagはhumanが選択した場合だけ`vbpe` patternを適用し、必須化しない。
- AWS Glue JobとSecurityConfigurationの`Name`はlower-kebab-case・1〜255文字とし、`purpose`は用途を識別するhuman-confirmedなtokenを使用する。SecurityConfigurationのprefixは`glsc`（Glue Security Configuration）とし、prefix内にhyphenを含めない。
- Amazon QuickSight DataSourceの`source_type`は`athena`、`snowflake`などの接続種別をlowercaseで表し、`purpose`は部署・情報区分などデータソースの用途を識別するhuman-confirmedな値とする。DataSourceとVPCConnectionの`Name`は1〜128文字の表示名とし、`DataSourceId`／`VPCConnectionId`とは別に扱う。
- Amazon MWAA Environmentの`purpose`は用途別にenvironmentを分ける場合だけ含める。`Name`は英字で開始し、英数字、hyphen、underscoreだけを使い、1〜80文字とする。この命名patternではlower-kebab-caseを使用する。
- Amazon Macie ClassificationJobの`purpose`は検出内容を識別するhuman-confirmedな値とし、`name`はnon-emptyかつ500文字以内とする。
- AWS CodeCommit repositoryの`environment`は、環境間で同じrepositoryを共有する場合は省略し、環境ごとにrepositoryを分ける場合は含める。
- Amazon S3 bucket nameはlowercaseの3〜63文字とし、partition内でglobalに一意にする。patternの全componentを含めたfinal nameを検証する。
- Elastic Load Balancingのload balancerとtarget groupは32文字以内とする。
- AWS IAM Roleは64文字以内、customer managed policyは128文字以内とし、caseだけが異なる名前を作らない。
- AWS Lambda function、Amazon Data Firehose delivery stream、Amazon EventBridge rule／schedule、Route 53 Resolver endpoint／rule／profileは64文字以内とする。
- Amazon SQS queueは80文字以内とし、FIFO queueは`.fifo`で終える。Amazon SNS FIFO topicも`.fifo`で終える。
- AWS Backup vaultとconsoleで作成するbackup planは50文字以内とする。
- AWS CloudFormation stack、StackSet、change setは英字で開始し、英数字とhyphenだけを使い、128文字以内とする。Change setはdeployment operationの名前であり、詳細設計resourceとして追加しない。
- AWS KMS aliasは`alias/`で開始し、AWS reservedの`alias/aws/`を使用しない。
- Amazon EC2 security groupの`GroupName`は`sg-`で開始できないため、このruleでは`-sg` suffixを使う。

provider schemaまたはAWS serviceの現在の制約がこのsectionより厳しい場合は、厳しい方を適用する。制約を満たせない場合は名称を推測して補正せず、humanへ確認して停止する。

## 設定表の表示順

- 通常propertyの表示順はmaterialsのproperties行順に従う。Name tagの必須性、design-only .Nameの1行表示・heading・anchorの契約は維持し、表示位置は`framework/rules/detailed-design.md`に従う。

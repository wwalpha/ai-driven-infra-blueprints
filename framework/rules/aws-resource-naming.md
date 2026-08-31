# AWS Resource Naming Rules

## Scope

このruleは、詳細設計でhuman-selectedなAWS resource name、identifier、または`Name` tagを決定するときのdefault naming conventionとする。

- AWS生成のphysical ID、ARN、DNS name、IP addressには適用しない。
- root-levelの`Tags`または`HostedZoneTags`はtag設定能力を示すだけで、`Name` tagの必須性を意味しない。`Name` tagはdefaultでoptionalとする。
- `Name` tagを必須とするcatalog resource typeは`EC2.VPC`、`EC2.Subnet`、`EC2.RouteTable`だけとし、詳細設計ではそれぞれ`EC2.VPC.Name`、`EC2.Subnet.Name`、`EC2.RouteTable.Name`の1 rowで表す。
- その他のresourceでは、humanが`Name` tagを明示した場合だけ設計する。taggableであることを理由に質問、追加、blocker判定をしない。
- 上記3種類の`.Name`は詳細設計専用propertyとし、IaCではcase-sensitiveな`Name` keyを持つtagへ変換する。`Tags[].Key`と`Tags[].Value`の2 rowでは表さない。
- その他のresourceでhuman-selectedな`Name` tagを使用する場合は、array形式では`Tags[].Key`と直後の`Tags[].Value`、object形式では`Tags` JSON objectで表す。
- `Name` tagのkeyはcase-sensitiveな`Name`を正確に使用し、valueを空にしない。
- 上記3種類のresource heading identifierは`.Name` valueと完全一致させ、anchorはService IDとそのvalueをlowercaseで結ぶ。
- 既存resourceと既存詳細設計の確定済み名称を自動変更しない。renameまたはreplacementは別の明示依頼がある場合だけ扱う。
- 既存resourceに必須の`Name` tagが存在しない場合は値を発明せず、設計保存やIaC変更へ進まずblockerとして報告する。
- CloudFormation logical ID、詳細設計のlogical ID、JSON artifact filenameには、それぞれの既存ruleを適用する。

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
| Required | VPC (`EC2.VPC.Name`)、Subnet (`EC2.Subnet.Name`)、Route table (`EC2.RouteTable.Name`) | AWS生成IDだけでは用途を識別しにくく、VPC consoleで継続的に選択するため必須とする |
| Conditional | 長期運用するEC2 Instance、VPC peering connection、VPC endpoint、NAT gateway、Transit gateway／attachment／route table、Customer gateway、Site-to-Site VPN connection | 同種resourceが複数、cross-account／central networking、またはconsoleで頻繁に手動選択する場合にhumanが使用を決定する |
| Optional by default | Internet gateway、Elastic IP address、Security group、固有のname／identifier propertyを持つresource | 関連先または正式なname／identifierで識別できるため、自動追加しない |

Auto Scalingなどが作成する一時的なEC2 Instanceへ同一の`Name` tagを必須化しない。Security groupは必須の`GroupName`を使用し、`Name` tagを重複要求しない。

## Naming patterns

| AWS service | AWS resource | Naming target | Pattern |
| --- | --- | --- | --- |
| Amazon VPC | VPC | `EC2.VPC.Name` | `vpc-{{application}}-{{environment}}` |
| Amazon VPC | Subnet | `EC2.Subnet.Name` | `sbnt-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}-{{zone}}-{{number}}` |
| Amazon VPC | Route table | `EC2.RouteTable.Name` | `rtb-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}[-{{zone}}]-{{number}}` |
| Amazon VPC | VPC peering connection | Name tag | `pcx-{{requester_vpc}}-to-{{accepter_vpc}}-{{number}}` |
| Amazon VPC | Internet gateway | Name tag | `igw-{{application}}-{{environment}}` |
| Amazon VPC | VPC endpoint | Name tag | `vpce-{{application}}-{{environment}}-{{service}}` |
| Amazon VPC | NAT gateway | Name tag | `natgw-{{application}}-{{environment}}-{{zone}}` |
| Amazon VPC | Elastic IP address | Name tag | `eip-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Transit gateway | Name tag | `tgw-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Transit gateway attachment | Name tag | `tgwa-{{application}}-{{environment}}-{{vpc_token}}-{{number}}` |
| Amazon VPC | Transit gateway route table | Name tag | `tgwrtb-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Workload transit gateway attachment | Name tag | `tgwa-{{account_id}}-{{target_alias}}` |
| Amazon VPC | Workload transit gateway route table | Name tag | `tgwrtb-{{account_id}}-{{target_alias}}` |
| Amazon VPC | Customer gateway | Name tag | `cgw-{{dc_location}}-{{number}}` |
| Amazon VPC | Site-to-Site VPN connection | Name tag | `s2s-{{dc_location}}-{{number}}` |
| Amazon S3 | General purpose bucket | `BucketName` | `{{application}}-{{environment}}-{{purpose}}-{{account_id}}-{{region}}` |
| Amazon S3 | Lifecycle rule | `LifecycleConfiguration.Rules[].Id` | `{{purpose}}-{{lifecycle_action}}` |
| Amazon RDS | DB instance | `DBInstanceIdentifier` | `rds-{{application}}-{{environment}}-{{engine}}-{{number}}` |
| Amazon RDS | DB subnet group | `DBSubnetGroupName` | `rdbsg-{{application}}-{{environment}}-{{number}}` |
| Amazon RDS | DB parameter group | `DBParameterGroupName` | `rdbpg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon RDS | DB cluster parameter group | `DBClusterParameterGroupName` | `rdbcpg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon RDS | Option group | `OptionGroupName` | `rdbog-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon EC2 | Instance | Name tag | `{{environment}}-{{application}}-{{purpose}}-{{number}}` |
| Amazon EC2 | Security group | `GroupName` | `{{environment}}-{{application}}-{{service}}-{{purpose}}-{{number}}-sg` |
| Amazon EC2 | Launch template | `LaunchTemplateName` | `aslt-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Elastic Load Balancing | Load balancer | `Name` | `{{load_balancer_type}}-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Elastic Load Balancing | Target group | `Name` | `tgp-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| EC2 Auto Scaling | Auto Scaling group | `AutoScalingGroupName` | `asg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon CloudWatch | Alarm | `AlarmName` | `{{account_id}}:{{environment}}:{{resource_token}}:{{aws_service}}.{{metric_name}}[.{{statistic}}][.{{condition}}][.{{severity}}]` |
| Amazon CloudWatch Logs | Log group | `LogGroupName` | `cwlogs-{{application}}-{{environment}}-{{purpose}}` |
| AWS CloudFormation | Stack | `StackName` | `cfn-stack-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| AWS CloudFormation | StackSet | `StackSetName` | `cfn-{{application}}-{{environment}}-{{purpose}}-{{deployment_scope}}` |
| AWS CloudFormation | Change set | `ChangeSetName` | `cfn-cset-{{purpose}}-{{revision}}` |
| AWS KMS | Customer managed key alias | `AliasName` | `alias/{{application}}-{{environment}}-{{service}}-{{purpose}}` |
| Amazon Data Firehose | Delivery stream | `DeliveryStreamName` | `kdf-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |
| Amazon Kinesis Data Streams | Data stream | `StreamName` | `kds-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |
| Amazon EventBridge | Rule | `Name` | `ebr-{{rule_type}}-{{application}}-{{environment}}-{{purpose}}[-{{source}}-to-{{destination}}]` |
| Amazon EventBridge Scheduler | Schedule | `Name` | `ebs-{{application}}-{{environment}}-{{purpose}}-{{pattern}}-{{timeslot}}` |
| Amazon SNS | Topic | `TopicName` | `sns-{{application}}-{{environment}}-{{purpose}}[.fifo]` |
| Amazon SQS | Queue | `QueueName` | `sqs-{{application}}-{{environment}}-{{purpose}}[.fifo]` |
| AWS Lambda | Function | `FunctionName` | `lmda-{{application}}-{{environment}}-{{purpose}}` |
| AWS IAM | Role | `RoleName` | `{{application}}-{{environment}}-{{purpose}}-role` |
| AWS IAM | Customer managed policy | `PolicyName` | `{{application}}-{{environment}}-{{purpose}}-policy` |
| AWS RAM | Resource share | `Name` | `ram-{{service}}-{{application}}-{{environment}}-share-with-{{target_type}}-{{target_token}}` |
| Amazon Route 53 Resolver | Resolver endpoint | `Name` | `rslv-{{endpoint_type}}-{{application}}-{{environment}}-{{purpose}}` |
| Amazon Route 53 Resolver | Resolver rule | `Name` | `rslvr-{{application}}-{{environment}}-{{from}}-to-{{to}}-{{domain_token}}` |
| Amazon Route 53 Profiles | Profile | `Name` | `rpf-{{application}}-{{environment}}-{{region}}` |
| AWS Backup | Backup vault | `BackupVaultName` | `backup-vault-{{application}}-{{environment}}-{{purpose}}` |
| AWS Backup | Backup plan | `BackupPlanName` | `backup-plan-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon API Gateway | REST, HTTP, or WebSocket API | `Name` | `apigw-{{protocol}}-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

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

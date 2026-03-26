# AWS Resource Naming Rules

## 1. このファイルの目的

このファイルは、このリポジトリにおける AWS リソース命名規則の正本です。  
人間が設計書を読むとき、Copilot が設計書や CloudFormation を読むとき、どちらも同じルールを参照できるようにすることを目的とします。

今後、新規に AWS リソースを追加する場合は、各サービス設計書、CloudFormation 実装、必要に応じてシナリオテストや結果記録も、このファイルの命名規則に従います。

`docs/designs/_llm/naming-rules.properties` が存在する場合、それはこの markdown の補助ファイルです。  
意味の正本はこの markdown にあり、補助ファイルは機械可読な同期表現として扱います。

---

## 2. 命名規則の基本方針

このリポジトリでは、AWS リソース名はできるだけ一貫した形式で管理します。  
目的は、単に名前を揃えることではなく、環境、用途、経路、接続先、番号などを名前から追えるようにすることです。

基本方針は次のとおりです。

- 区切り文字は ASCII の `-` を使います
- 原則として lowercase-kebab-case を使います
- `number` は原則として 2 桁ゼロ埋めを使います
- `zone` は Availability Zone suffix を使います
- 例: `a`, `c`, `d`
- AWS サービス仕様上、明示的な Resource Name を持たないリソースについては、この命名規則を `Name` tag に適用します
- CloudFormation の logical ID はこの命名規則の対象外です。logical ID は可読性と変更安全性を優先して別途定義して構いません

ただし、すべての AWS サービスで完全に同じ記法が使えるとは限りません。  
S3 bucket 名、IAM 名称、CloudWatch Alarm 名などには固有制約があるため、サービス仕様上必要な例外は許容します。  
その場合は、なぜその例外が必要かを各設計書に残してください。

---

## 3. 例外として維持する表記

原則は lowercase-kebab-case ですが、以下のように、すでに意味を持つ既存規約は例外としてそのまま維持します。

- `ISZ/`

これらはこのファイル内でも例外扱いとし、無理に lowercase へ変換しません。

---

## 4. プレースホルダの考え方

命名規則では、具体値の代わりにプレースホルダを使います。  
各サービス設計書では、これらのプレースホルダを実際の環境値に置き換えて使います。

### 主なプレースホルダ

| Placeholder        | Meaning                        | Example                                    |
| ------------------ | ------------------------------ | ------------------------------------------ |
| `application`      | アプリケーション名             | `billing`                                  |
| `env`              | 環境名                         | `prod`, `dev`, `stg`                       |
| `vpcName`          | VPC を識別する短縮名           | `core-prod`                                |
| `subnetType`       | subnet の役割                  | `app`, `db`, `web`, `mgmt`                 |
| `routeType`        | 経路種別                       | `public`, `private`, `isolated`, `transit` |
| `zone`             | AZ suffix                      | `a`, `c`                                   |
| `number`           | 連番                           | `01`, `02`                                 |
| `purpose`          | 用途                           | `app`, `logs`, `backup`, `egress`          |
| `service`          | AWS サービス名や接続先         | `s3`, `ssm`, `logs`                        |
| `companyName`      | 会社識別名                     | `acme`                                     |
| `dbType`           | DB 種別                        | `mysql`, `postgres`, `aurora-mysql`        |
| `serviceName`      | サービス名                     | `ec2`, `rds`, `ssm`                        |
| `loadBalancerType` | LB 種別                        | `alb`, `nlb`                               |
| `ruleType`         | EventBridge ルール種別         | `schedule`, `event`                        |
| `source`           | 送信元                         | `app`, `cloudwatch`, `s3`                  |
| `destination`      | 送信先                         | `s3`, `logs`, `sns`                        |
| `targetRegion`     | 対象リージョン                 | `ap-northeast-1`                           |
| `accountId`        | AWS アカウント ID              | `123456789012`                             |
| `accountName`      | AWS アカウント短縮名           | `shared-prod`                              |
| `dcLocation`       | データセンター拠点名           | `tokyo-dc1`                                |
| `protocol`         | API プロトコル                 | `rest`, `http`, `websocket`                |
| `timeslot`         | スケジュール表現               | `daily-0900`                               |
| `metricName`       | CloudWatch メトリクス名        | `CPUUtilization`                           |
| `resourceName`     | 監視対象名                     | `ec2-app01`                                |
| `nameTag`          | 補助識別子                     | `critical`                                 |
| `targetType`       | RAM 共有先種別                 | `account`, `ou`                            |
| `targetId`         | RAM 共有先 ID                  | `123456789012`                             |
| `from`             | Route53 Resolver Rule の送信元 | `onprem`                                   |
| `to`               | Route53 Resolver Rule の宛先   | `aws`                                      |
| `domain`           | 対象ドメイン                   | `corp.local`                               |

---

## 5. 命名ルールの適用方法

命名規則を適用する際は、まずその AWS リソースが「実際のリソース名を持つか」を確認してください。

- 実リソース名を持つもの  
  例: S3 bucket, RDS instance, Security Group, CloudWatch Log Group  
  → その実名に適用します

- 実リソース名を持たず、タグで識別するもの  
  例: VPC, subnet, route table, internet gateway など  
  → `Name` tag に適用します

この違いを設計書と CloudFormation の両方で明示し、実名なのか `Name` tag なのかを曖昧にしないでください。

---

## 6. サービス別の命名ルール

### 6.1 VPC 関連

VPC 関連リソースでは、ネットワークの役割や接続先が名前から読み取れることを重視します。  
多くのリソースは実名よりも `Name` tag が主になるため、`Name` tag にこの規則を適用します。

| AWS Resource                                | Naming Rule                                                                         | Note              |
| ------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------- |
| VPCs                                        | `vpc-{{application}}-{{env}}`                                                       | `Name` tag に適用 |
| Subnets                                     | `sbnt-{{vpcName}}-{{subnetType}}-{{routeType}}-{{zone}}-{{number}}`                 | `Name` tag に適用 |
| Route Tables                                | `rtb-{{vpcName}}-{{subnetType}}-{{routeType}}[-{{zone}}]-{{number}}`                | `Name` tag に適用 |
| Peering Connections                         | `pcx-{{sourceVpcName}}-{{sourceEnv}}-to-{{targetVpcName}}-{{targetEnv}}-{{number}}` | `Name` tag に適用 |
| Internet Gateways                           | `igw-{{vpcName}}`                                                                   | `Name` tag に適用 |
| Endpoints                                   | `vpce-{{vpcName}}-{{service}}`                                                      | `Name` tag に適用 |
| NAT Gateways                                | `natgw-{{vpcName}}-{{zone}}`                                                        | `Name` tag に適用 |
| Elastic IP Addresses                        | `eip-{{vpcName}}-{{purpose}}-{{number}}`                                            | `Name` tag に適用 |
| Transit Gateways                            | `tgw-{{purpose}}-{{env}}-{{number}}`                                                | `Name` tag に適用 |
| Transit Gateway Attachments                 | `tgwa-{{vpcName}}-{{number}}`                                                       | `Name` tag に適用 |
| Transit Gateway Route Tables                | `tgwrtb-{{vpcName}}-{{number}}`                                                     | `Name` tag に適用 |
| Transit Gateway Attachments (for Workload)  | `tgwa-{{accountId}}-{{accountName}}`                                                | `Name` tag に適用 |
| Transit Gateway Route Tables (for Workload) | `tgwrtb-{{accountId}}-{{accountName}}`                                              | `Name` tag に適用 |
| Customer Gateways                           | `cgw-{{dcLocation}}-{{number}}`                                                     | `Name` tag に適用 |
| Site-to-Site VPN                            | `s2s-{{dcLocation}}-{{number}}`                                                     | `Name` tag に適用 |

---

### 6.2 S3 関連

S3 bucket 名はグローバル一意制約があるため、他サービスより制約が強いリソースです。  
そのため、会社識別名、環境、用途、リージョンを含めて衝突しにくい形にします。

| AWS Resource    | Naming Rule                                           | Note               |
| --------------- | ----------------------------------------------------- | ------------------ |
| Buckets         | `bckt-{{companyName}}-{{env}}-{{purpose}}-{{region}}` | 実バケット名に適用 |
| Lifecycle Rules | `{{purpose}}-{{lifecycleRuleAction}}`                 | ルール名に適用     |

---

### 6.3 RDS 関連

RDS では DB 種別、環境、連番が追えることを重視します。  
インスタンスだけでなく、subnet group や parameter group も同じ思想で揃えます。

| AWS Resource             | Naming Rule                         | Note       |
| ------------------------ | ----------------------------------- | ---------- |
| Instances                | `rds-{{dbType}}-{{env}}-{{number}}` | 実名に適用 |
| Subnet Groups            | `rdbsg-{{env}}-{{number}}`          | 実名に適用 |
| Parameter Groups         | `rdbpg-{{env}}-db{{number}}`        | 実名に適用 |
| Cluster Parameter Groups | `rdbcpg-{{env}}-db{{number}}`       | 実名に適用 |
| Option Groups            | `rdbog-{{env}}-db{{number}}`        | 実名に適用 |

---

### 6.4 EC2 関連

EC2 では、用途と連番を短く扱えることを重視します。  
ただし、EC2 instance 自体は `Name` tag を主に使うケースが多いため、実装時に実名とタグの使い分けを明確にしてください。

| AWS Resource           | Naming Rule                                          | Note                     |
| ---------------------- | ---------------------------------------------------- | ------------------------ |
| Instances              | `{{env}}-{{purpose}}{{number}}`                      | 通常は `Name` tag に適用 |
| Security Groups        | `{{env}}-{{serviceName}}-{{purpose}}{{number}}-sg`   | 実名に適用               |
| Launch Templates       | `aslt-{{env}}-{{purpose}}{{number}}`                 | 実名に適用               |
| Elastic Load Balancers | `{{loadBalancerType}}-{{env}}-{{purpose}}{{number}}` | 実名に適用               |
| ELB Target Groups      | `tgp-{{env}}-{{purpose}}{{number}}`                  | 実名に適用               |
| Auto Scaling Groups    | `asg-{{env}}-{{purpose}}{{number}}`                  | 実名に適用               |

---

### 6.5 CloudWatch 関連

CloudWatch はメトリクスや監視対象が名前から追えることが重要です。  
特に Alarm は情報量が多くなるため、既存ルールを維持します。

| AWS Resource | Naming Rule                                                                                                                             | Note       |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Alarms       | `{{accountId}}:{{env}}:{{resourceName}}:ISZ/{{awsService}}.{{metricName}}[[.Max/Min]][[.condition+threshold]][[.severity]][[:nameTag]]` | 実名に適用 |
| Log Groups   | `cwlogs-{{env}}-{{purpose}}`                                                                                                            | 実名に適用 |

---

### 6.6 CloudFormation 関連

CloudFormation では stack, stack set, change set の役割が名前から分かるようにします。

| AWS Resource | Naming Rule                                          | Note       |
| ------------ | ---------------------------------------------------- | ---------- |
| Stacks       | `cfn-stack-{{env}}-{{purpose}}{{number}}`            | 実名に適用 |
| StackSets    | `cfn-{{env}}-{{purpose}}{{number}}-{{targetRegion}}` | 実名に適用 |
| ChangeSets   | `cfn-cset-{{env}}-{{purpose}}{{number}}`             | 実名に適用 |

---

### 6.7 KMS 関連

KMS は alias 名で管理する前提とし、環境と用途を明示します。

| AWS Resource   | Naming Rule                               | Note           |
| -------------- | ----------------------------------------- | -------------- |
| Keys / Aliases | `kms-{{env}}-{{serviceName}}-{{purpose}}` | alias 名に適用 |

---

### 6.8 Kinesis 関連

送信元と送信先の流れが名前から読めるようにします。

| AWS Resource          | Naming Rule                                             | Note       |
| --------------------- | ------------------------------------------------------- | ---------- |
| Kinesis Data Firehose | `kdf-{{env}}-{{purpose}}-{{source}}-to-{{destination}}` | 実名に適用 |
| Kinesis Data Streams  | `kds-{{env}}-{{purpose}}-{{source}}-to-{{destination}}` | 実名に適用 |

---

### 6.9 EventBridge 関連

ルール種別、用途、送信元、送信先を名前に含めます。

| AWS Resource | Naming Rule                                                          | Note       |
| ------------ | -------------------------------------------------------------------- | ---------- |
| Rules        | `ebr-{{ruleType}}-{{env}}-{{purpose}}-{{source}}-to-{{destination}}` | 実名に適用 |
| Schedulers   | `ebs-{{env}}-{{purpose}}-{{pattern}}-{{timeslot}}`                   | 実名に適用 |

---

### 6.10 SNS / SQS / Lambda 関連

これらは比較的短く、環境と用途が分かることを優先します。

| AWS Resource     | Naming Rule                | Note       |
| ---------------- | -------------------------- | ---------- |
| SNS Topics       | `sns-{{env}}-{{purpose}}`  | 実名に適用 |
| SQS Queues       | `sqs-{{env}}-{{purpose}}`  | 実名に適用 |
| Lambda Functions | `lmda-{{env}}-{{purpose}}` | 実名に適用 |

---

### 6.11 IAM 関連

IAM は用途またはアプリ名とサービス名を組み合わせます。

| AWS Resource | Naming Rule                                 | Note       |
| ------------ | ------------------------------------------- | ---------- |
| Roles        | `{{purposeOrAppName}}{{serviceName}}Role`   | 実名に適用 |
| Policies     | `{{purposeOrAppName}}{{serviceName}}Policy` | 実名に適用 |

---

### 6.12 RAM 関連

共有対象が分かるよう、共有元サービスと共有先を含めます。

| AWS Resource    | Naming Rule                                                         | Note       |
| --------------- | ------------------------------------------------------------------- | ---------- |
| Resource Shares | `ram-{{serviceName}}-{{env}}-sharewith-{{targetType}}-{{targetId}}` | 実名に適用 |

---

### 6.13 Route53 関連

Resolver endpoint や rule は、方向と用途が読めることを重視します。

| AWS Resource       | Naming Rule                                 | Note       |
| ------------------ | ------------------------------------------- | ---------- |
| Resolver Endpoints | `rslv-{{endpointType}}-{{purpose}}-{{env}}` | 実名に適用 |
| Resolver Rules     | `rslvr-{{from}}-{{to}}-{{domain}}-{{env}}`  | 実名に適用 |
| Profiles           | `rpf-{{env}}-{{region}}`                    | 実名に適用 |

---

### 6.14 Backup 関連

Backup はサービス種別と連番が分かる形を維持します。

| AWS Resource | Naming Rule            | Note       |
| ------------ | ---------------------- | ---------- |
| Vaults       | `BackupVault`          | 実名に適用 |
| Plans        | `BackupPlan{{number}}` | 実名に適用 |

---

### 6.15 API Gateway 関連

API の種類、環境、用途が分かる構成にします。

| AWS Resource | Naming Rule                              | Note       |
| ------------ | ---------------------------------------- | ---------- |
| APIs         | `apigw-{{protocol}}-{{env}}-{{purpose}}` | 実名に適用 |

---

## 7. 設計書での使い方

各サービス設計書では、このファイルのプレースホルダを具体値に置き換えて利用します。  
その際、単にパターンだけを書くのではなく、必要に応じて実際の採用名も記載してください。

たとえば VPC なら、設計書で以下のように具体化します。

- naming rule: `vpc-{{application}}-{{env}}`
- actual value: `vpc-billing-prod`

また、subnet や route table のように `Name` tag へ適用するものは、そのことを明示してください。

---

## 8. 既存リソースとの差分の扱い

既存環境に、この命名規則と一致しないリソースが存在することはありえます。  
その場合でも、勝手に即時一括リネームは行いません。

既存差分を見つけた場合は、次のどちらかを設計書や結果記録に残してください。

- 今回は据え置く
- 今後の移行対象として扱う

特に、既存スタック変更時の rename は置換、参照切れ、運用手順変更のリスクがあるため、影響評価なしに行ってはいけません。

---

## 9. 補助ファイルとの関係

`docs/designs/_llm/naming-rules.properties` が存在する場合、それはこのファイルの補助表現です。  
Copilot や LLM が機械的に読みやすいようにするためのものであり、意味の正本はこの markdown にあります。

命名規則を更新する場合は、markdown と `_llm` を同一変更で同期してください。

---

## 10. このファイルを更新するときの注意

このファイルを更新した場合、必要に応じて以下も確認してください。

- 各サービスの `docs/designs/*.md`
- `docs/designs/_llm/*.properties`
- `infra/cloudformation/*`
- `tests/scenarios/*`
- `docs/test-results/results.md`
- `.github/copilot-instructions.md`
- `.github/prompts/*`

命名規則は単独では完結せず、設計・実装・テスト・運用に影響します。  
そのため、ルール変更時は影響範囲を意識して更新してください。

---

## 11. 変更履歴

- 2026-03-26: 初版作成

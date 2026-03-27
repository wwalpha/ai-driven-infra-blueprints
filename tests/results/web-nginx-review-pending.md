# web-nginx Review Checkpoint

## Phase

- phase: COMPLETED_AND_TORN_DOWN
- review approval: REVIEW APPROVED
- last successful step: CloudFormation stack teardown
- next action: none

## Target Service

- systemName: web-nginx
- env: dev
- region: ap-northeast-1
- scope: VPC, subnet, route table, NAT Gateway, security group, internet-facing ALB, Amazon Linux 2023 EC2, NGINX bootstrap

## Read Design Markdown

- docs/designs/naming-rules.md
- docs/designs/post-deploy-actual-values.md

## Read `_llm` Helper Files

- docs/designs/\_llm/naming-rules.properties
- docs/designs/\_llm/post-deploy-actual-values.properties

## Read Instruction Files

- .github/instructions/cloudformation.instructions.md
- .github/instructions/designs.instructions.md
- .github/instructions/designs-llm.instructions.md
- .github/instructions/scenario-tests.instructions.md

## Updated Design Markdown

- docs/designs/vpc.md
- docs/designs/subnet.md
- docs/designs/security-group.md
- docs/designs/alb.md
- docs/designs/ec2.md

## Updated `_llm` Helper Files

- docs/designs/\_llm/vpc.properties
- docs/designs/\_llm/subnet.properties
- docs/designs/\_llm/security-group.properties
- docs/designs/\_llm/alb.properties
- docs/designs/\_llm/ec2.properties

## Changed CloudFormation Files

- infra/cloudformation/templates/network.yaml
- infra/cloudformation/templates/security.yaml
- infra/cloudformation/templates/app.yaml
- infra/cloudformation/parameters/network-dev.json
- infra/cloudformation/parameters/security-dev.json
- infra/cloudformation/parameters/app-dev.json

## Added Scenario Tests

- tests/scenarios/sh/web-nginx-scenario.sh
- tests/scenarios/ps1/web-nginx-scenario.ps1

## Added Result Files

- tests/results/web-nginx-review-pending.md
- tests/results/web-nginx-scenario.md

## Current Environment Understanding

- network stack provides stable IDs for VPC and subnets only
- security stack provides ALB SG and EC2 SG IDs only
- app stack owns IAM role/profile, ALB, target group, listener, and two EC2 instances
- EC2 management path is Session Manager through outbound 443 via NAT Gateway
- HTTPS, Auto Scaling, CloudWatch Agent, and SSM VPC endpoints are intentionally out of scope for this change

## Template Boundary Decision

- network.yaml: deploy責務は VPC, IGW, subnets, route tables, EIPs, NAT Gateways
- security.yaml: deploy責務は ALB SG と EC2 SG のみ
- app.yaml: deploy責務は IAM role/profile, ALB, target group, listener, EC2, UserData
- dependency direction: network -> security -> app
- cross-stack references are limited to VPC ID, subnet IDs, security group IDs

## Naming Rule Alignment

- VPC, subnets, route tables, IGW, NAT Gateway, EIP, EC2 instance は `Name` tag に naming rules を適用した
- Security Group, ALB, Target Group, IAM Role, Instance Profile は実名へ naming rules または service-specific naming を適用した
- CMD の命名案と差分がある主な項目:
  - VPC: `web-nginx-dev-vpc` ではなく `vpc-web-nginx-dev`
  - ALB: `web-nginx-dev-alb` ではなく `alb-dev-web01`
  - Target Group: `web-nginx-dev-tg` ではなく `tgp-dev-web01`
  - Security Group: `web-nginx-dev-alb-sg` / `web-nginx-dev-ec2-sg` ではなく `dev-alb-web01-sg` / `dev-ec2-app01-sg`
  - IAM Role/Profile: `web-nginx-dev-ec2-role` / `web-nginx-dev-ec2-profile` ではなく `webNginxEc2Role` / `webNginxEc2Profile`

## Added Stack List

- cfn-stack-dev-webnginx-network01
- cfn-stack-dev-webnginx-security01
- cfn-stack-dev-webnginx-app01

## Stack Dependencies

- cfn-stack-dev-webnginx-network01: no stack dependency
- cfn-stack-dev-webnginx-security01: imports `${NetworkStackName}-VpcId`
- cfn-stack-dev-webnginx-app01: imports `${NetworkStackName}-VpcId`, `${NetworkStackName}-PublicSubnetAz1Id`, `${NetworkStackName}-PublicSubnetAz2Id`, `${NetworkStackName}-PrivateAppSubnetAz1Id`, `${NetworkStackName}-PrivateAppSubnetAz2Id`, `${SecurityStackName}-AlbSecurityGroupId`, `${SecurityStackName}-Ec2SecurityGroupId`

## Deploy Order

1. cfn-stack-dev-webnginx-network01
2. cfn-stack-dev-webnginx-security01
3. cfn-stack-dev-webnginx-app01

## Expected Parameters

### network stack

| ParameterKey            | Value           |
| ----------------------- | --------------- |
| SystemName              | web-nginx       |
| Env                     | dev             |
| AvailabilityZone1       | ap-northeast-1a |
| AvailabilityZone2       | ap-northeast-1c |
| VpcCidr                 | 10.0.0.0/16     |
| PublicSubnetAz1Cidr     | 10.0.0.0/24     |
| PublicSubnetAz2Cidr     | 10.0.1.0/24     |
| PrivateAppSubnetAz1Cidr | 10.0.10.0/24    |
| PrivateAppSubnetAz2Cidr | 10.0.11.0/24    |

### security stack

| ParameterKey     | Value                            |
| ---------------- | -------------------------------- |
| SystemName       | web-nginx                        |
| Env              | dev                              |
| NetworkStackName | cfn-stack-dev-webnginx-network01 |

### app stack

| ParameterKey      | Value                                                                 |
| ----------------- | --------------------------------------------------------------------- |
| SystemName        | web-nginx                                                             |
| Env               | dev                                                                   |
| NetworkStackName  | cfn-stack-dev-webnginx-network01                                      |
| SecurityStackName | cfn-stack-dev-webnginx-security01                                     |
| InstanceType      | t3.small                                                              |
| AmiSsmParameter   | /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 |

## Validate Commands

```bash
aws cloudformation validate-template --no-cli-pager --region ap-northeast-1 --template-body file://infra/cloudformation/templates/network.yaml
aws cloudformation validate-template --no-cli-pager --region ap-northeast-1 --template-body file://infra/cloudformation/templates/security.yaml
aws cloudformation validate-template --no-cli-pager --region ap-northeast-1 --template-body file://infra/cloudformation/templates/app.yaml
bash -n tests/scenarios/sh/web-nginx-scenario.sh
```

## Validate Results

| Item                       | Result  | Detail                                                              |
| -------------------------- | ------- | ------------------------------------------------------------------- |
| network.yaml               | PASS    | validate-template succeeded                                         |
| security.yaml              | PASS    | validate-template succeeded                                         |
| app.yaml                   | PASS    | validate-template succeeded; deploy requires `CAPABILITY_NAMED_IAM` |
| shell scenario syntax      | PASS    | `bash -n tests/scenarios/sh/web-nginx-scenario.sh`                  |
| PowerShell scenario syntax | PASS    | editor diagnostics reported no errors                               |
| PowerShell runtime check   | NOT RUN | `pwsh` command is not installed in this environment                 |

## Deploy Results

| Stack                             | Result | Detail            |
| --------------------------------- | ------ | ----------------- |
| cfn-stack-dev-webnginx-network01  | PASS   | `CREATE_COMPLETE` |
| cfn-stack-dev-webnginx-security01 | PASS   | `CREATE_COMPLETE` |
| cfn-stack-dev-webnginx-app01      | PASS   | `CREATE_COMPLETE` |

## Executed Deploy Commands

```bash
aws cloudformation deploy \
  --no-cli-pager \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-webnginx-network01 \
  --template-file infra/cloudformation/templates/network.yaml \
  --parameter-overrides \
    SystemName=web-nginx \
    Env=dev \
    AvailabilityZone1=ap-northeast-1a \
    AvailabilityZone2=ap-northeast-1c \
    VpcCidr=10.0.0.0/16 \
    PublicSubnetAz1Cidr=10.0.0.0/24 \
    PublicSubnetAz2Cidr=10.0.1.0/24 \
    PrivateAppSubnetAz1Cidr=10.0.10.0/24 \
    PrivateAppSubnetAz2Cidr=10.0.11.0/24

aws cloudformation deploy \
  --no-cli-pager \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-webnginx-security01 \
  --template-file infra/cloudformation/templates/security.yaml \
  --parameter-overrides \
    SystemName=web-nginx \
    Env=dev \
    NetworkStackName=cfn-stack-dev-webnginx-network01

aws cloudformation deploy \
  --no-cli-pager \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-webnginx-app01 \
  --template-file infra/cloudformation/templates/app.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    SystemName=web-nginx \
    Env=dev \
    NetworkStackName=cfn-stack-dev-webnginx-network01 \
    SecurityStackName=cfn-stack-dev-webnginx-security01 \
    InstanceType=t3.small \
    AmiSsmParameter=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
```

## Scenario Execution Result

| Item                       | Result | Detail                                                                                                                                          |
| -------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Shell scenario             | PASS   | `bash tests/scenarios/sh/web-nginx-scenario.sh cfn-stack-dev-webnginx-network01 cfn-stack-dev-webnginx-security01 cfn-stack-dev-webnginx-app01` |
| HTTP status                | PASS   | `200`                                                                                                                                           |
| Healthy targets            | PASS   | `2`                                                                                                                                             |
| EC2 public IP count        | PASS   | `0`                                                                                                                                             |
| Distinct AZ count          | PASS   | `2`                                                                                                                                             |
| IAM instance profile count | PASS   | `2`                                                                                                                                             |

## Teardown Commands

```bash
aws cloudformation delete-stack --no-cli-pager --region ap-northeast-1 --stack-name cfn-stack-dev-webnginx-app01
aws cloudformation wait stack-delete-complete --region ap-northeast-1 --stack-name cfn-stack-dev-webnginx-app01

aws cloudformation delete-stack --no-cli-pager --region ap-northeast-1 --stack-name cfn-stack-dev-webnginx-security01
aws cloudformation wait stack-delete-complete --region ap-northeast-1 --stack-name cfn-stack-dev-webnginx-security01

aws cloudformation delete-stack --no-cli-pager --region ap-northeast-1 --stack-name cfn-stack-dev-webnginx-network01
aws cloudformation wait stack-delete-complete --region ap-northeast-1 --stack-name cfn-stack-dev-webnginx-network01
```

## Teardown Results

| Stack                             | Result | Detail            |
| --------------------------------- | ------ | ----------------- |
| cfn-stack-dev-webnginx-app01      | PASS   | `DELETE_COMPLETE` |
| cfn-stack-dev-webnginx-security01 | PASS   | `DELETE_COMPLETE` |
| cfn-stack-dev-webnginx-network01  | PASS   | `DELETE_COMPLETE` |

## AWS CLI Deploy Plan

```bash
aws cloudformation deploy \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-webnginx-network01 \
  --template-file infra/cloudformation/templates/network.yaml \
  --parameter-overrides \
    SystemName=web-nginx \
    Env=dev \
    AvailabilityZone1=ap-northeast-1a \
    AvailabilityZone2=ap-northeast-1c \
    VpcCidr=10.0.0.0/16 \
    PublicSubnetAz1Cidr=10.0.0.0/24 \
    PublicSubnetAz2Cidr=10.0.1.0/24 \
    PrivateAppSubnetAz1Cidr=10.0.10.0/24 \
    PrivateAppSubnetAz2Cidr=10.0.11.0/24

aws cloudformation deploy \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-webnginx-security01 \
  --template-file infra/cloudformation/templates/security.yaml \
  --parameter-overrides \
    SystemName=web-nginx \
    Env=dev \
    NetworkStackName=cfn-stack-dev-webnginx-network01

aws cloudformation deploy \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-webnginx-app01 \
  --template-file infra/cloudformation/templates/app.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    SystemName=web-nginx \
    Env=dev \
    NetworkStackName=cfn-stack-dev-webnginx-network01 \
    SecurityStackName=cfn-stack-dev-webnginx-security01 \
    InstanceType=t3.small \
    AmiSsmParameter=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
```

## Risks And Unresolved Items

- NAT Gateway を各 AZ に 1 台ずつ作るためコストが継続発生する
- app stack は Named IAM を含むため deploy 時に `CAPABILITY_NAMED_IAM` が必要
- shell scenario は deploy 後の ALB 応答待ちを 30 回まで再試行するが、初回 bootstrap が遅い場合は retry 回数の調整が必要な可能性がある
- PowerShell script の構文は editor で確認したが、この macOS 環境では `pwsh` 未導入のため runtime 実行は未確認
- `docs/test-results/results.md` は worktree で削除済みだが、今回の証跡は user 指示に従い tests/results 配下へ統一した

## Review Points For Humans

- naming rules 優先により CMD 命名案との差分を受け入れるか
- stack 境界を network / security / app の 3 分割とした判断が運用単位に合うか
- private subnet からの SSM 利用を NAT outbound 前提でよいか
- ALB を HTTP 80 のみで開始し、HTTPS を後続変更に分ける方針でよいか
- IAM Role と Instance Profile の命名を `webNginxEc2Role` / `webNginxEc2Profile` とした判断でよいか

## Result

- design markdown を先に作成し、対応する `_llm` properties を同期した
- network / security / app の 3 stack を CloudFormation で deploy した
- shell script と PowerShell script の両シナリオテストを追加した
- validate-template は 3 templates とも成功した
- shell scenario test を実行し成功した
- Post-Deploy Actual Values を各設計書へ反映した
- deploy 済み 3 stack を app -> security -> network の順に削除し、すべて `DELETE_COMPLETE` を確認した
- PowerShell runtime 実行のみ `pwsh` 未導入のため未確認

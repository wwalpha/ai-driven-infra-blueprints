# Implementation Results

## Target Service

- Multi-AZ web baseline
- Scope: VPC, subnet, route, NAT Gateway, Security Group, public ALB, Amazon Linux EC2, NGINX bootstrap

## Read Design Markdown

- `docs/designs/naming-rules.md`

## Read `_llm` Helper Files

- `docs/designs/_llm/naming-rules.properties`

## Read Instruction Files

- `.github/instructions/cloudformation.instructions.md`
- `.github/instructions/designs.instructions.md`
- `.github/instructions/designs-llm.instructions.md`
- `.github/instructions/scenario-tests.instructions.md`

## Updated Design Markdown

- `docs/designs/vpc.md`
- `docs/designs/subnet.md`
- `docs/designs/security-group.md`
- `docs/designs/alb.md`
- `docs/designs/ec2.md`

## Updated `_llm` Helper Files

- `docs/designs/_llm/vpc.properties`
- `docs/designs/_llm/subnet.properties`
- `docs/designs/_llm/security-group.properties`
- `docs/designs/_llm/alb.properties`
- `docs/designs/_llm/ec2.properties`

## Changed CloudFormation Files

- `infra/cloudformation/templates/network-base.yaml`
- `infra/cloudformation/templates/web-service.yaml`
- `infra/cloudformation/parameters/network-dev.json`
- `infra/cloudformation/parameters/web-dev.json`

## Added Scenario Test

- `tests/scenarios/sh/multi-az-web-scenario.sh`
- public IP 集計 query を `length(Reservations[].Instances[?PublicIpAddress!=null][])` に修正

## Template Boundary Decision

- `network-base.yaml`: VPC、subnet、route、IGW、EIP、NAT Gateway を deploy する network 基盤 stack
- `web-service.yaml`: Security Group、IAM、ALB、Target Group、Listener、EC2、UserData bootstrap を deploy する web 配信 stack
- stack 間連携は cross-stack reference を使い、`VpcId` と subnet ID のみを export / import する

## AWS CLI Validation Commands

```bash
aws cloudformation validate-template --no-cli-pager --region ap-northeast-1 --template-body file://infra/cloudformation/templates/network-base.yaml
aws cloudformation validate-template --no-cli-pager --region ap-northeast-1 --template-body file://infra/cloudformation/templates/web-service.yaml
bash -n tests/scenarios/sh/multi-az-web-scenario.sh
```

## AWS CLI Deploy Commands

```bash
aws cloudformation deploy \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-network01 \
  --template-file infra/cloudformation/templates/network-base.yaml \
  --parameter-overrides \
    Application=web \
    Environment=dev \
    VpcName=web-dev \
    ExportPrefix=dev-web \
    AvailabilityZone1=ap-northeast-1a \
    AvailabilityZone2=ap-northeast-1c \
    ZoneCode1=a \
    ZoneCode2=c \
    VpcCidr=10.10.0.0/16 \
    PublicSubnetAz1Cidr=10.10.0.0/24 \
    PublicSubnetAz2Cidr=10.10.1.0/24 \
    PrivateSubnetAz1Cidr=10.10.10.0/24 \
    PrivateSubnetAz2Cidr=10.10.11.0/24

aws cloudformation deploy \
  --region ap-northeast-1 \
  --stack-name cfn-stack-dev-web01 \
  --template-file infra/cloudformation/templates/web-service.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    Environment=dev \
    Purpose=web \
    NetworkExportPrefix=dev-web \
    AlbIngressCidr=0.0.0.0/0 \
    InstanceType=t3.micro \
    AmiId=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    KeyPairName= \
    HealthCheckPath=/ \
    WebContentTitle='Hello from NGINX' \
    WebContentBody='Served via public ALB'
```

## Scenario Test Command

```bash
bash tests/scenarios/sh/multi-az-web-scenario.sh cfn-stack-dev-web01
```

## Result

- design markdown と `_llm` helper の初版を追加した
- CloudFormation の network / web 2 stack 構成を追加した
- CloudFormation validate-template は 2 template とも成功した
- shell script の構文チェックは成功した
- 一度は Elastic IP quota 超過で network stack deploy に失敗したが、EIP 解放後に再実行した
- `cfn-stack-dev-network01` の deploy は成功した
- `cfn-stack-dev-web01` の deploy は成功した
- `bash tests/scenarios/sh/multi-az-web-scenario.sh cfn-stack-dev-web01` を実行し成功した
- Scenario test の確認結果:
  - HTTP status: `200`
  - Healthy targets: `2`
  - Public IP count on instances: `0`
- web instance は private subnet に配置され、public IP を持たないことを AWS CLI で確認した

## Unresolved Items

- HTTPS 化する場合は ACM と Route53 の設計が別途必要
- SSM patching、CloudWatch alarm、Auto Scaling はまだ未実装
- scenario test スクリプトの実行権付与はツール制約で未実施。ただし `bash` 実行は可能

## Next Candidates

- HTTPS 化する場合は ACM、Route53、80 から 443 への redirect listener を追加する
- Auto Scaling Group と Launch Template に置き換えて EC2 の運用性を上げる
- CloudWatch alarm と SSM patching を追加する

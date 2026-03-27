# ALB Design

## Purpose

public subnet の internet-facing ALB で HTTP 80 を受け、private EC2 上の NGINX へ転送する。

## Naming Decision

- ALB と Target Group は実リソース名を持つため naming rules の実名ルールを適用する
- CMD の `web-nginx-dev-alb` / `web-nginx-dev-tg` ではなく、repo ルール優先で `alb-dev-web01` / `tgp-dev-web01` を採用する

## Load Balancer: ALB01

| Property Name     | Value                                   | Comment                                                                 |
| ----------------- | --------------------------------------- | ----------------------------------------------------------------------- |
| loadBalancerName  | alb-dev-web01                           | naming rule `{{loadBalancerType}}-{{env}}-{{purpose}}{{number}}` を適用 |
| scheme            | internet-facing                         | public ALB                                                              |
| type              | application                             | ALB を利用                                                              |
| ipAddressType     | ipv4                                    | 今回は IPv4 のみ                                                        |
| subnets           | PUBLICAZ1,PUBLICAZ2                     | 2 つの public subnet へ配置                                             |
| securityGroup     | ALBSG01                                 | HTTP 80 を internet から受ける                                          |
| accessLogsEnabled | false                                   | 今回は disabled                                                         |
| template          | infra/cloudformation/templates/app.yaml | app stack で管理                                                        |

## Target Group: TG01

| Property Name              | Value                                   | Comment                                                |
| -------------------------- | --------------------------------------- | ------------------------------------------------------ |
| targetGroupName            | tgp-dev-web01                           | naming rule `tgp-{{env}}-{{purpose}}{{number}}` を適用 |
| targetType                 | instance                                | EC2 instance を登録                                    |
| protocol                   | HTTP                                    | HTTP 80 で転送                                         |
| port                       | 80                                      | NGINX の待受ポート                                     |
| healthCheckProtocol        | HTTP                                    | health check は HTTP                                   |
| healthCheckPath            | /                                       | index.html を確認                                      |
| healthCheckMatcher         | 200-399                                 | healthy 判定                                           |
| deregistrationDelaySeconds | 60                                      | 固定値どおり                                           |
| targets                    | EC2AZ1,EC2AZ2                           | 2 台とも登録                                           |
| template                   | infra/cloudformation/templates/app.yaml | app stack で管理                                       |

## Listener: HTTP80

| Property Name | Value                                   | Comment                       |
| ------------- | --------------------------------------- | ----------------------------- |
| protocol      | HTTP                                    | 初回は HTTP のみ              |
| port          | 80                                      | public listener               |
| defaultAction | forward to TG01                         | 80/tcp で target group へ転送 |
| template      | infra/cloudformation/templates/app.yaml | app stack で管理              |

## Preconditions And Dependencies

- VPC と subnet は [docs/designs/vpc.md](docs/designs/vpc.md) と [docs/designs/subnet.md](docs/designs/subnet.md) を参照する
- Security Group は [docs/designs/security-group.md](docs/designs/security-group.md) を参照する
- backend EC2 は [docs/designs/ec2.md](docs/designs/ec2.md) を参照する

## CloudFormation Implementation

- template: infra/cloudformation/templates/app.yaml
- deploy責務: ALB、Target Group、Listener を IAM/EC2 と同一 app stack に置く
- import 一覧:
  - `${NetworkStackName}-VpcId`
  - `${NetworkStackName}-PublicSubnetAz1Id`
  - `${NetworkStackName}-PublicSubnetAz2Id`
  - `${SecurityStackName}-AlbSecurityGroupId`
- template 境界の理由: ALB と target 登録対象の EC2 を同じ rollback 単位で扱うため app stack に同居させる

## Scenario Test Viewpoints

- ALB DNS 名へ HTTP GET して 200 を返すこと
- 返却 HTML に systemName、env、hostname、instance-id、availability zone のいずれかが含まれること
- Target Group の healthy target が 2 台であること

## Post-Deploy Actual Values

### Application Load Balancer: ALB01

| Property Name         | Value                                                                                                    | Comment      |
| --------------------- | -------------------------------------------------------------------------------------------------------- | ------------ |
| loadBalancerArn       | arn:aws:elasticloadbalancing:ap-northeast-1:334678299258:loadbalancer/app/alb-dev-web01/93e070703b11c5ce | actual value |
| loadBalancerName      | alb-dev-web01                                                                                            | actual value |
| dnsName               | alb-dev-web01-1082823635.ap-northeast-1.elb.amazonaws.com                                                | actual value |
| canonicalHostedZoneId | Z14GRHDCWA56QT                                                                                           | actual value |
| scheme                | internet-facing                                                                                          | actual value |
| ipAddressType         | ipv4                                                                                                     | actual value |
| subnetIds             | subnet-04b8e39bf5928b306,subnet-0e91f32417238ddb7                                                        | actual value |
| securityGroupIds      | sg-016e241a2c348b10d                                                                                     | actual value |
| vpcId                 | vpc-09da1a2c741c6c664                                                                                    | actual value |
| state                 | active                                                                                                   | actual value |

### Post-Deploy Target Group: TG01

| Property Name       | Value                                                                                               | Comment      |
| ------------------- | --------------------------------------------------------------------------------------------------- | ------------ |
| targetGroupArn      | arn:aws:elasticloadbalancing:ap-northeast-1:334678299258:targetgroup/tgp-dev-web01/3ecb7b0d34636b99 | actual value |
| targetGroupName     | tgp-dev-web01                                                                                       | actual value |
| targetType          | instance                                                                                            | actual value |
| protocol            | HTTP                                                                                                | actual value |
| port                | 80                                                                                                  | actual value |
| vpcId               | vpc-09da1a2c741c6c664                                                                               | actual value |
| healthCheckPath     | /                                                                                                   | actual value |
| matcher             | 200-399                                                                                             | actual value |
| registeredTargetIds | i-0c91877e97777e9d9,i-07724d16c58b825b2                                                             | actual value |

## Change History

- 2026-03-27: web-nginx dev の internet-facing ALB 設計を追加

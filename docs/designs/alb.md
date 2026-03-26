# ALB Design

## Purpose

internet-facing な public ALB から private EC2 上の NGINX を公開する。

## Load Balancer: ALB01

| Property Name    | Value                                           | Comment                     |
| ---------------- | ----------------------------------------------- | --------------------------- |
| loadBalancerName | alb-dev-web01                                   | ALB 実名                    |
| scheme           | internet-facing                                 | public ALB                  |
| type             | application                                     | ALB を使用                  |
| ipAddressType    | ipv4                                            | 最小構成                    |
| subnets          | PUBAZ1,PUBAZ2                                   | 2 つの public subnet に配置 |
| securityGroup    | ALBSG01                                         | internet から HTTP を受ける |
| template         | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理       |

## Target Group: TGP01

| Property Name   | Value                                           | Comment                  |
| --------------- | ----------------------------------------------- | ------------------------ |
| targetGroupName | tgp-dev-web01                                   | Target Group 実名        |
| targetType      | instance                                        | EC2 instance を登録      |
| protocol        | HTTP                                            | NGINX への HTTP 接続     |
| port            | 80                                              | EC2 側待受ポート         |
| healthCheckPath | /                                               | NGINX トップページで確認 |
| matcher         | 200                                             | 正常系の期待ステータス   |
| targets         | WEB01,WEB02                                     | 各 AZ の EC2 を登録      |
| template        | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理    |

## Listener: HTTP80

| Property Name | Value                                           | Comment               |
| ------------- | ----------------------------------------------- | --------------------- |
| protocol      | HTTP                                            | 今回は HTTP 最小構成  |
| port          | 80                                              | public listener       |
| defaultAction | forward to TGP01                                | EC2 へ転送            |
| template      | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理 |

## Preconditions And Dependencies

- VPC と subnet は [docs/designs/vpc.md](docs/designs/vpc.md) と [docs/designs/subnet.md](docs/designs/subnet.md) を参照する
- Security Group は [docs/designs/security-group.md](docs/designs/security-group.md) を参照する
- backend EC2 は [docs/designs/ec2.md](docs/designs/ec2.md) を参照する

## CloudFormation Implementation

- template: `infra/cloudformation/templates/web-service.yaml`
- deploy責務: ALB、Target Group、Listener を管理する
- import 一覧:
  - `dev-web-VpcId`
  - `dev-web-PublicSubnetAz1Id`
  - `dev-web-PublicSubnetAz2Id`

## Scenario Test Viewpoints

- ALB DNS 名へ HTTP GET して 200 を返すこと
- Target Group の healthy target が 2 台であること
- expected response text を返すこと

## Change History

- 2026-03-26: public ALB、Target Group、HTTP listener の初版を追加

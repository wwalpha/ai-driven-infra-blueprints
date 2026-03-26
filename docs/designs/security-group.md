# Security Group Design

## Purpose

public ALB と private EC2 の通信経路を Security Group で制御する。

## Security Group: ALBSG01

| Property Name | Value                                           | Comment                     |
| ------------- | ----------------------------------------------- | --------------------------- |
| groupName     | dev-alb-web01-sg                                | ALB 用 Security Group 実名  |
| attachedTo    | ALB01                                           | public ALB に適用           |
| ingress       | tcp/80 from 0.0.0.0/0                           | internet から HTTP を受ける |
| egress        | all to 0.0.0.0/0                                | target への接続を許可       |
| template      | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理       |

## Security Group: EC2SG01

| Property Name         | Value                                           | Comment                          |
| --------------------- | ----------------------------------------------- | -------------------------------- |
| groupName             | dev-ec2-web01-sg                                | EC2 用 Security Group 実名       |
| attachedTo            | WEB01,WEB02                                     | private EC2 に適用               |
| ingress               | tcp/80 from ALBSG01                             | ALB 経由 HTTP のみ許可           |
| egress                | all to 0.0.0.0/0                                | NAT Gateway 経由 outbound を許可 |
| directInternetIngress | denied                                          | internet からの直接到達は不可    |
| template              | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理            |

## Preconditions And Dependencies

- VPC は [docs/designs/vpc.md](docs/designs/vpc.md) の export を利用する
- ALB と EC2 の詳細は [docs/designs/alb.md](docs/designs/alb.md) と [docs/designs/ec2.md](docs/designs/ec2.md) を参照する

## CloudFormation Implementation

- template: `infra/cloudformation/templates/web-service.yaml`
- deploy責務: web 配信に必要な Security Group を管理する
- import 一覧:
  - `dev-web-VpcId`

## Scenario Test Viewpoints

- ALB 経由の HTTP だけが通ること
- EC2 に public IP がなく、直接公開されないこと

## Change History

- 2026-03-26: ALB 用と EC2 用 Security Group の初版を追加

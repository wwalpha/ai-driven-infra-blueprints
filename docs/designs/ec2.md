# EC2 Design

## Purpose

private subnet に Amazon Linux EC2 を 2 台配置し、UserData で NGINX を導入して ALB 配下で応答させる。

## IAM Role: WEBEC2ROLE01

| Property Name | Value                                                | Comment               |
| ------------- | ---------------------------------------------------- | --------------------- |
| managedPolicy | arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore | SSM 接続を有効化      |
| purpose       | ec2 bootstrap and session management                 | SSH なし運用の前提    |
| template      | infra/cloudformation/templates/web-service.yaml      | web 配信 stack で管理 |

## Instance Profile: WEBEC2PROFILE01

| Property Name | Value                                           | Comment               |
| ------------- | ----------------------------------------------- | --------------------- |
| role          | WEBEC2ROLE01                                    | EC2 に割り当てる role |
| template      | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理 |

## EC2: WEB01

| Property Name            | Value                                                                 | Comment                  |
| ------------------------ | --------------------------------------------------------------------- | ------------------------ |
| nameTag                  | dev-web01                                                             | EC2 `Name` tag           |
| availabilityZone         | ap-northeast-1a                                                       | 配置 AZ                  |
| subnet                   | PRVAZ1                                                                | private subnet AZ1       |
| instanceType             | t3.micro                                                              | 最小構成の参考値         |
| ami                      | /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 | Amazon Linux 2023        |
| associatePublicIpAddress | false                                                                 | private EC2 のため無効   |
| securityGroup            | EC2SG01                                                               | ALB からの HTTP のみ許可 |
| instanceProfile          | WEBEC2PROFILE01                                                       | SSM 接続と bootstrap 用  |
| userData                 | install nginx and write index page                                    | NGINX 初期化を行う       |
| template                 | infra/cloudformation/templates/web-service.yaml                       | web 配信 stack で管理    |

## EC2: WEB02

| Property Name            | Value                                                                 | Comment                  |
| ------------------------ | --------------------------------------------------------------------- | ------------------------ |
| nameTag                  | dev-web02                                                             | EC2 `Name` tag           |
| availabilityZone         | ap-northeast-1c                                                       | 配置 AZ                  |
| subnet                   | PRVAZ2                                                                | private subnet AZ2       |
| instanceType             | t3.micro                                                              | 最小構成の参考値         |
| ami                      | /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 | Amazon Linux 2023        |
| associatePublicIpAddress | false                                                                 | private EC2 のため無効   |
| securityGroup            | EC2SG01                                                               | ALB からの HTTP のみ許可 |
| instanceProfile          | WEBEC2PROFILE01                                                       | SSM 接続と bootstrap 用  |
| userData                 | install nginx and write index page                                    | NGINX 初期化を行う       |
| template                 | infra/cloudformation/templates/web-service.yaml                       | web 配信 stack で管理    |

## UserData: NGINXBOOTSTRAP01

| Property Name  | Value                                           | Comment                  |
| -------------- | ----------------------------------------------- | ------------------------ |
| packageManager | dnf                                             | Amazon Linux 2023 を前提 |
| installPackage | nginx                                           | Web server               |
| listenPort     | 80                                              | NGINX 待受ポート         |
| title          | Hello from NGINX                                | 画面タイトル             |
| body           | Served via public ALB                           | 疎通確認用の本文         |
| systemdEnable  | true                                            | 再起動後も自動起動       |
| template       | infra/cloudformation/templates/web-service.yaml | web 配信 stack で管理    |

## Preconditions And Dependencies

- VPC と subnet は [docs/designs/vpc.md](docs/designs/vpc.md) と [docs/designs/subnet.md](docs/designs/subnet.md) を参照する
- Security Group は [docs/designs/security-group.md](docs/designs/security-group.md) を参照する
- ALB は [docs/designs/alb.md](docs/designs/alb.md) を参照する

## CloudFormation Implementation

- template: `infra/cloudformation/templates/web-service.yaml`
- deploy責務: IAM Role、Instance Profile、EC2、UserData bootstrap を管理する
- import 一覧:
  - `dev-web-PrivateSubnetAz1Id`
  - `dev-web-PrivateSubnetAz2Id`

## Scenario Test Viewpoints

- ALB 経由で NGINX の HTML を返すこと
- 2 台とも Target Group で healthy になること
- EC2 に public IP が付与されないこと

## Change History

- 2026-03-26: Amazon Linux 2023 EC2 と NGINX bootstrap の初版を追加

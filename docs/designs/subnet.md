# Subnet Design

## Purpose

web-nginx の public ALB 用 subnet と private app subnet、および route table を定義する。

## Subnet: PUBLICAZ1

| Property Name       | Value                                       | Comment                                                                                |
| ------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------- |
| nameTag             | sbnt-web-nginx-dev-public-public-a-01       | naming rule `sbnt-{{vpcName}}-{{subnetType}}-{{routeType}}-{{zone}}-{{number}}` を適用 |
| availabilityZone    | ap-northeast-1a                             | ALB と NAT Gateway 用                                                                  |
| cidrBlock           | 10.0.0.0/24                                 | public subnet AZ1                                                                      |
| subnetType          | public                                      | naming rule 上の subnet type                                                           |
| routeType           | public                                      | IGW へ出る                                                                             |
| mapPublicIpOnLaunch | true                                        | public subnet として有効                                                               |
| template            | infra/cloudformation/templates/network.yaml | network stack で管理                                                                   |

## Subnet: PUBLICAZ2

| Property Name       | Value                                       | Comment                      |
| ------------------- | ------------------------------------------- | ---------------------------- |
| nameTag             | sbnt-web-nginx-dev-public-public-c-02       | naming rule を適用           |
| availabilityZone    | ap-northeast-1c                             | ALB と NAT Gateway 用        |
| cidrBlock           | 10.0.1.0/24                                 | public subnet AZ2            |
| subnetType          | public                                      | naming rule 上の subnet type |
| routeType           | public                                      | IGW へ出る                   |
| mapPublicIpOnLaunch | true                                        | public subnet として有効     |
| template            | infra/cloudformation/templates/network.yaml | network stack で管理         |

## Subnet: PRIVATEAPPAZ1

| Property Name       | Value                                       | Comment                      |
| ------------------- | ------------------------------------------- | ---------------------------- |
| nameTag             | sbnt-web-nginx-dev-app-private-a-01         | naming rule を適用           |
| availabilityZone    | ap-northeast-1a                             | EC2 AZ1 を配置               |
| cidrBlock           | 10.0.10.0/24                                | private app subnet AZ1       |
| subnetType          | app                                         | naming rule 上の subnet type |
| routeType           | private                                     | NAT Gateway 経由 outbound    |
| mapPublicIpOnLaunch | false                                       | private subnet のため無効    |
| template            | infra/cloudformation/templates/network.yaml | network stack で管理         |

## Subnet: PRIVATEAPPAZ2

| Property Name       | Value                                       | Comment                      |
| ------------------- | ------------------------------------------- | ---------------------------- |
| nameTag             | sbnt-web-nginx-dev-app-private-c-02         | naming rule を適用           |
| availabilityZone    | ap-northeast-1c                             | EC2 AZ2 を配置               |
| cidrBlock           | 10.0.11.0/24                                | private app subnet AZ2       |
| subnetType          | app                                         | naming rule 上の subnet type |
| routeType           | private                                     | NAT Gateway 経由 outbound    |
| mapPublicIpOnLaunch | false                                       | private subnet のため無効    |
| template            | infra/cloudformation/templates/network.yaml | network stack で管理         |

## Route Table: PUBLICRT01

| Property Name     | Value                                       | Comment                                                                                 |
| ----------------- | ------------------------------------------- | --------------------------------------------------------------------------------------- |
| nameTag           | rtb-web-nginx-dev-public-public-01          | naming rule `rtb-{{vpcName}}-{{subnetType}}-{{routeType}}[-{{zone}}]-{{number}}` を適用 |
| associatedSubnets | PUBLICAZ1,PUBLICAZ2                         | public subnet 共通                                                                      |
| defaultRoute      | 0.0.0.0/0 -> WEBNGINXIGW                    | internet-facing 用                                                                      |
| template          | infra/cloudformation/templates/network.yaml | network stack で管理                                                                    |

## Route Table: PRIVATEAPPARTA01

| Property Name     | Value                                       | Comment                       |
| ----------------- | ------------------------------------------- | ----------------------------- |
| nameTag           | rtb-web-nginx-dev-app-private-a-01          | naming rule を適用            |
| associatedSubnets | PRIVATEAPPAZ1                               | AZ1 private subnet 専用       |
| defaultRoute      | 0.0.0.0/0 -> NATA01                         | 同一 AZ の NAT Gateway を使う |
| template          | infra/cloudformation/templates/network.yaml | network stack で管理          |

## Route Table: PRIVATEAPPCRT02

| Property Name     | Value                                       | Comment                       |
| ----------------- | ------------------------------------------- | ----------------------------- |
| nameTag           | rtb-web-nginx-dev-app-private-c-02          | naming rule を適用            |
| associatedSubnets | PRIVATEAPPAZ2                               | AZ2 private subnet 専用       |
| defaultRoute      | 0.0.0.0/0 -> NATC01                         | 同一 AZ の NAT Gateway を使う |
| template          | infra/cloudformation/templates/network.yaml | network stack で管理          |

## Preconditions And Dependencies

- VPC、IGW、NAT Gateway は [docs/designs/vpc.md](docs/designs/vpc.md) を参照する
- ALB は public subnet、EC2 は private app subnet を利用する
- SSM 用 VPC endpoint は作らないため、private subnet の outbound は NAT Gateway 前提とする

## CloudFormation Implementation

- template: infra/cloudformation/templates/network.yaml
- deploy責務: subnet、route table、route、association を network stack に集約する
- rollback 単位: VPC と routable network を同じ stack で rollback できるようにする

## Scenario Test Viewpoints

- ALB が public subnet 2 本に接続されること
- EC2 が private subnet 2 本に分散配置されること
- private subnet の route table が各 AZ の NAT Gateway を使うこと

## Post-Deploy Actual Values

### Post-Deploy Subnet: PUBLICAZ1

| Property Name       | Value                    | Comment      |
| ------------------- | ------------------------ | ------------ |
| subnetId            | subnet-04b8e39bf5928b306 | actual value |
| vpcId               | vpc-09da1a2c741c6c664    | actual value |
| availabilityZone    | ap-northeast-1a          | actual value |
| availabilityZoneId  | apne1-az4                | actual value |
| cidrBlock           | 10.0.0.0/24              | actual value |
| routeTableId        | rtb-0e94bcdb76e9eca07    | actual value |
| networkAclId        | acl-01377293865d99f0f    | actual value |
| mapPublicIpOnLaunch | true                     | actual value |

### Post-Deploy Subnet: PUBLICAZ2

| Property Name       | Value                    | Comment      |
| ------------------- | ------------------------ | ------------ |
| subnetId            | subnet-0e91f32417238ddb7 | actual value |
| vpcId               | vpc-09da1a2c741c6c664    | actual value |
| availabilityZone    | ap-northeast-1c          | actual value |
| availabilityZoneId  | apne1-az1                | actual value |
| cidrBlock           | 10.0.1.0/24              | actual value |
| routeTableId        | rtb-0e94bcdb76e9eca07    | actual value |
| networkAclId        | acl-01377293865d99f0f    | actual value |
| mapPublicIpOnLaunch | true                     | actual value |

### Post-Deploy Subnet: PRIVATEAPPAZ1

| Property Name       | Value                    | Comment      |
| ------------------- | ------------------------ | ------------ |
| subnetId            | subnet-0a60ddd215eee3532 | actual value |
| vpcId               | vpc-09da1a2c741c6c664    | actual value |
| availabilityZone    | ap-northeast-1a          | actual value |
| availabilityZoneId  | apne1-az4                | actual value |
| cidrBlock           | 10.0.10.0/24             | actual value |
| routeTableId        | rtb-022b833167a44e9d2    | actual value |
| networkAclId        | acl-01377293865d99f0f    | actual value |
| mapPublicIpOnLaunch | false                    | actual value |

### Post-Deploy Subnet: PRIVATEAPPAZ2

| Property Name       | Value                    | Comment      |
| ------------------- | ------------------------ | ------------ |
| subnetId            | subnet-089a21093d6eb8a28 | actual value |
| vpcId               | vpc-09da1a2c741c6c664    | actual value |
| availabilityZone    | ap-northeast-1c          | actual value |
| availabilityZoneId  | apne1-az1                | actual value |
| cidrBlock           | 10.0.11.0/24             | actual value |
| routeTableId        | rtb-05a5a0e426d3efb3c    | actual value |
| networkAclId        | acl-01377293865d99f0f    | actual value |
| mapPublicIpOnLaunch | false                    | actual value |

## Change History

- 2026-03-27: web-nginx dev の public/private subnet と route table 設計を追加

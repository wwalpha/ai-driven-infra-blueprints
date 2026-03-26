# Subnet Design

## Purpose

public ALB 用と private EC2 用の Multi-AZ subnet、および route table 構成を定義する。

## Subnet: PUBAZ1

| Property Name       | Value                                            | Comment                         |
| ------------------- | ------------------------------------------------ | ------------------------------- |
| nameTag             | sbnt-web-dev-web-public-a-01                     | public subnet AZ1 の `Name` tag |
| availabilityZone    | ap-northeast-1a                                  | 配置 AZ                         |
| cidrBlock           | 10.10.0.0/24                                     | ALB と NAT Gateway 用           |
| subnetType          | web                                              | 命名規則上の subnet type        |
| routeType           | public                                           | internet 公開用                 |
| mapPublicIpOnLaunch | true                                             | public subnet のため有効        |
| template            | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理       |

## Subnet: PUBAZ2

| Property Name       | Value                                            | Comment                         |
| ------------------- | ------------------------------------------------ | ------------------------------- |
| nameTag             | sbnt-web-dev-web-public-c-02                     | public subnet AZ2 の `Name` tag |
| availabilityZone    | ap-northeast-1c                                  | 配置 AZ                         |
| cidrBlock           | 10.10.1.0/24                                     | ALB と NAT Gateway 用           |
| subnetType          | web                                              | 命名規則上の subnet type        |
| routeType           | public                                           | internet 公開用                 |
| mapPublicIpOnLaunch | true                                             | public subnet のため有効        |
| template            | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理       |

## Subnet: PRVAZ1

| Property Name       | Value                                            | Comment                          |
| ------------------- | ------------------------------------------------ | -------------------------------- |
| nameTag             | sbnt-web-dev-app-private-a-01                    | private subnet AZ1 の `Name` tag |
| availabilityZone    | ap-northeast-1a                                  | 配置 AZ                          |
| cidrBlock           | 10.10.10.0/24                                    | EC2 用 private subnet            |
| subnetType          | app                                              | 命名規則上の subnet type         |
| routeType           | private                                          | NAT 経由 outbound 用             |
| mapPublicIpOnLaunch | false                                            | private subnet のため無効        |
| template            | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理        |

## Subnet: PRVAZ2

| Property Name       | Value                                            | Comment                          |
| ------------------- | ------------------------------------------------ | -------------------------------- |
| nameTag             | sbnt-web-dev-app-private-c-02                    | private subnet AZ2 の `Name` tag |
| availabilityZone    | ap-northeast-1c                                  | 配置 AZ                          |
| cidrBlock           | 10.10.11.0/24                                    | EC2 用 private subnet            |
| subnetType          | app                                              | 命名規則上の subnet type         |
| routeType           | private                                          | NAT 経由 outbound 用             |
| mapPublicIpOnLaunch | false                                            | private subnet のため無効        |
| template            | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理        |

## Route Table: PUBLICRT01

| Property Name     | Value                                            | Comment                           |
| ----------------- | ------------------------------------------------ | --------------------------------- |
| nameTag           | rtb-web-dev-web-public-01                        | public subnet 共通 route table    |
| associatedSubnets | PUBAZ1,PUBAZ2                                    | 2 つの public subnet に関連付ける |
| defaultRoute      | 0.0.0.0/0 -> Internet Gateway                    | internet 公開経路                 |
| template          | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理         |

## Route Table: PRIVRTAZ1

| Property Name     | Value                                            | Comment                           |
| ----------------- | ------------------------------------------------ | --------------------------------- |
| nameTag           | rtb-web-dev-app-private-a-01                     | private subnet AZ1 用 route table |
| associatedSubnets | PRVAZ1                                           | AZ1 private subnet に関連付ける   |
| defaultRoute      | 0.0.0.0/0 -> NATAZ1                              | AZ ローカルの NAT Gateway を使う  |
| template          | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理         |

## Route Table: PRIVRTAZ2

| Property Name     | Value                                            | Comment                           |
| ----------------- | ------------------------------------------------ | --------------------------------- |
| nameTag           | rtb-web-dev-app-private-c-02                     | private subnet AZ2 用 route table |
| associatedSubnets | PRVAZ2                                           | AZ2 private subnet に関連付ける   |
| defaultRoute      | 0.0.0.0/0 -> NATAZ2                              | AZ ローカルの NAT Gateway を使う  |
| template          | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理         |

## Preconditions And Dependencies

- VPC、IGW、NAT Gateway は [docs/designs/vpc.md](docs/designs/vpc.md) を参照する
- ALB は public subnet、EC2 は private subnet を利用する

## CloudFormation Implementation

- template: `infra/cloudformation/templates/network-base.yaml`
- deploy責務: subnet、route table、route、association を管理する
- rollback 単位: network 基盤全体として扱う

## Scenario Test Viewpoints

- ALB が両方の public subnet にアタッチされていること
- EC2 が private subnet に存在し、public IP を持たないこと
- private subnet の outbound が各 AZ の NAT Gateway を使って成立すること

## Change History

- 2026-03-26: public/private subnet と route table の初版を追加

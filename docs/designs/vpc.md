# VPC Design

## Purpose

public ALB と private EC2 を収容する Multi-AZ のネットワーク基盤を定義する。

## VPC: WEBCORE

| Property Name      | Value                                            | Comment                                |
| ------------------ | ------------------------------------------------ | -------------------------------------- |
| nameTag            | vpc-web-dev                                      | `Name` tag に適用する VPC 名           |
| cidrBlock          | 10.10.0.0/16                                     | VPC CIDR                               |
| enableDnsSupport   | true                                             | DNS 解決を有効化                       |
| enableDnsHostnames | true                                             | DNS hostname を有効化                  |
| template           | infra/cloudformation/templates/network-base.yaml | deploy責務は network 基盤              |
| exportPrefix       | dev-web                                          | web stack が import する export prefix |

## Internet Gateway: WEBIGW01

| Property Name | Value                                            | Comment                                   |
| ------------- | ------------------------------------------------ | ----------------------------------------- |
| nameTag       | igw-web-dev                                      | `Name` tag に適用する Internet Gateway 名 |
| attachedVpc   | WEBCORE                                          | VPC にアタッチする                        |
| template      | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理                 |

## Elastic IP: NATAZ1EIP

| Property Name        | Value                                            | Comment                                                  |
| -------------------- | ------------------------------------------------ | -------------------------------------------------------- |
| nameTag              | eip-web-dev-egress-01                            | NAT Gateway AZ1 用 EIP                                   |
| domain               | vpc                                              | VPC domain の EIP                                        |
| purpose              | egress                                           | outbound 通信用途                                        |
| allocationSource     | parameterized                                    | quota に応じて新規確保または既存未使用 allocation を指定 |
| existingAllocationId | TBD                                              | 既存 EIP を再利用する場合のみ設定                        |
| template             | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理                                |

## Elastic IP: NATAZ2EIP

| Property Name        | Value                                            | Comment                                                  |
| -------------------- | ------------------------------------------------ | -------------------------------------------------------- |
| nameTag              | eip-web-dev-egress-02                            | NAT Gateway AZ2 用 EIP                                   |
| domain               | vpc                                              | VPC domain の EIP                                        |
| purpose              | egress                                           | outbound 通信用途                                        |
| allocationSource     | parameterized                                    | quota に応じて新規確保または既存未使用 allocation を指定 |
| existingAllocationId | TBD                                              | 既存 EIP を再利用する場合のみ設定                        |
| template             | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理                                |

## NAT Gateway: NATAZ1

| Property Name    | Value                                            | Comment                              |
| ---------------- | ------------------------------------------------ | ------------------------------------ |
| nameTag          | natgw-web-dev-a                                  | `Name` tag に適用する NAT Gateway 名 |
| subnet           | PUBAZ1                                           | public subnet に配置                 |
| elasticIp        | NATAZ1EIP                                        | AZ1 EIP を割り当てる                 |
| connectivityType | public                                           | internet egress 用                   |
| template         | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理            |

## NAT Gateway: NATAZ2

| Property Name    | Value                                            | Comment                              |
| ---------------- | ------------------------------------------------ | ------------------------------------ |
| nameTag          | natgw-web-dev-c                                  | `Name` tag に適用する NAT Gateway 名 |
| subnet           | PUBAZ2                                           | public subnet に配置                 |
| elasticIp        | NATAZ2EIP                                        | AZ2 EIP を割り当てる                 |
| connectivityType | public                                           | internet egress 用                   |
| template         | infra/cloudformation/templates/network-base.yaml | network 基盤 stack で管理            |

## Preconditions And Dependencies

- region は `ap-northeast-1` を前提とする
- AZ は `ap-northeast-1a` と `ap-northeast-1c` を使う
- subnet と route table は [docs/designs/subnet.md](docs/designs/subnet.md) を参照する
- ALB と EC2 はこの VPC を前提とし、詳細は [docs/designs/alb.md](docs/designs/alb.md) と [docs/designs/ec2.md](docs/designs/ec2.md) を参照する

## CloudFormation Implementation

- template: `infra/cloudformation/templates/network-base.yaml`
- deploy責務: VPC、subnet、route、IGW、EIP、NAT Gateway を管理する
- deploy 順序: network stack を先に deploy し、その export を web stack が import する
- EIP quota により新規 EIP を確保できない場合は、未関連付けの既存 allocation ID を parameter で渡して NAT Gateway に再利用する
- export 一覧:
  - `dev-web-VpcId`
  - `dev-web-PublicSubnetAz1Id`
  - `dev-web-PublicSubnetAz2Id`
  - `dev-web-PrivateSubnetAz1Id`
  - `dev-web-PrivateSubnetAz2Id`

## Scenario Test Viewpoints

- private subnet の EC2 が NAT Gateway 経由で package install できること
- public ALB 経由で private EC2 上の NGINX に到達できること
- EC2 に public IP が付与されていないこと

## Change History

- 2026-03-26: VPC、IGW、EIP、NAT Gateway の初版を追加

# VPC Design

## Purpose

public ALB と private EC2 を収容する web-nginx の Multi-AZ VPC 基盤を定義する。

## Naming Decision

- repo 正本の [docs/designs/naming-rules.md](docs/designs/naming-rules.md) を優先し、VPC と NAT などは実名ではなく `Name` tag に命名規則を適用する
- CMD の命名案 `web-nginx-dev-vpc` などとは形式差分があるが、今回は naming rules 準拠の `vpc-web-nginx-dev` などを採用する

## VPC: WEBNGINXVPC

| Property Name      | Value                                       | Comment                                                         |
| ------------------ | ------------------------------------------- | --------------------------------------------------------------- |
| nameTag            | vpc-web-nginx-dev                           | naming rule `vpc-{{application}}-{{env}}` を適用した `Name` tag |
| cidrBlock          | 10.0.0.0/16                                 | VPC CIDR                                                        |
| enableDnsSupport   | true                                        | DNS 解決を有効化                                                |
| enableDnsHostnames | true                                        | DNS hostname を有効化                                           |
| ipAddressFamily    | ipv4                                        | 今回は IPv4 のみ                                                |
| template           | infra/cloudformation/templates/network.yaml | network stack で管理                                            |

## Internet Gateway: WEBNGINXIGW

| Property Name | Value                                       | Comment                                             |
| ------------- | ------------------------------------------- | --------------------------------------------------- |
| nameTag       | igw-web-nginx-dev                           | naming rule `igw-{{vpcName}}` を適用した `Name` tag |
| attachedVpc   | WEBNGINXVPC                                 | VPC にアタッチする                                  |
| template      | infra/cloudformation/templates/network.yaml | network stack で管理                                |

## Elastic IP: NATA01EIP

| Property Name      | Value                                       | Comment                                       |
| ------------------ | ------------------------------------------- | --------------------------------------------- |
| nameTag            | eip-web-nginx-dev-nat-a-01                  | NAT Gateway AZ1 用の `Name` tag               |
| domain             | vpc                                         | VPC domain を使う                             |
| purpose            | nat-a                                       | naming rule の purpose に AZ を含めて区別する |
| allocationStrategy | create in stack                             | 初回は template 内で確保する                  |
| template           | infra/cloudformation/templates/network.yaml | network stack で管理                          |

## Elastic IP: NATC02EIP

| Property Name      | Value                                       | Comment                                       |
| ------------------ | ------------------------------------------- | --------------------------------------------- |
| nameTag            | eip-web-nginx-dev-nat-c-02                  | NAT Gateway AZ2 用の `Name` tag               |
| domain             | vpc                                         | VPC domain を使う                             |
| purpose            | nat-c                                       | naming rule の purpose に AZ を含めて区別する |
| allocationStrategy | create in stack                             | 初回は template 内で確保する                  |
| template           | infra/cloudformation/templates/network.yaml | network stack で管理                          |

## NAT Gateway: NATA01

| Property Name    | Value                                       | Comment                                                        |
| ---------------- | ------------------------------------------- | -------------------------------------------------------------- |
| nameTag          | natgw-web-nginx-dev-a                       | naming rule `natgw-{{vpcName}}-{{zone}}` を適用した `Name` tag |
| subnet           | PUBLICAZ1                                   | public subnet AZ1 に配置                                       |
| elasticIp        | NATA01EIP                                   | AZ1 の EIP を割り当てる                                        |
| connectivityType | public                                      | private subnet の outbound 用                                  |
| template         | infra/cloudformation/templates/network.yaml | network stack で管理                                           |

## NAT Gateway: NATC01

| Property Name    | Value                                       | Comment                                                        |
| ---------------- | ------------------------------------------- | -------------------------------------------------------------- |
| nameTag          | natgw-web-nginx-dev-c                       | naming rule `natgw-{{vpcName}}-{{zone}}` を適用した `Name` tag |
| subnet           | PUBLICAZ2                                   | public subnet AZ2 に配置                                       |
| elasticIp        | NATC02EIP                                   | AZ2 の EIP を割り当てる                                        |
| connectivityType | public                                      | private subnet の outbound 用                                  |
| template         | infra/cloudformation/templates/network.yaml | network stack で管理                                           |

## Preconditions And Constraints

- region は ap-northeast-1 を前提とする
- Availability Zone は ap-northeast-1a と ap-northeast-1c を固定で使う
- createSsmVpcEndpoints は false とし、private EC2 の outbound は NAT Gateway 経由で SSM public endpoint と package repository へ到達させる
- HTTPS は createHttpsNow=false のため対象外とし、ALB は HTTP 80 のみ実装する

## CloudFormation Implementation

- template: infra/cloudformation/templates/network.yaml
- deploy責務: VPC、IGW、subnet、route table、EIP、NAT Gateway の基盤ネットワークを deploy する
- deploy 順序: network stack を最初に deploy し、その export を security stack と app stack が import する
- export 一覧:
  - `${NetworkStackName}-VpcId`
  - `${NetworkStackName}-PublicSubnetAz1Id`
  - `${NetworkStackName}-PublicSubnetAz2Id`
  - `${NetworkStackName}-PrivateAppSubnetAz1Id`
  - `${NetworkStackName}-PrivateAppSubnetAz2Id`
  - `${NetworkStackName}-PublicSubnetIds`
  - `${NetworkStackName}-PrivateAppSubnetIds`
- template 境界の理由: network は他 stack が参照する安定した ID を提供する責務に限定し、security と app の rollback と分離する

## Scenario Test Viewpoints

- private subnet の default route が同一 AZ の NAT Gateway を向くこと
- EC2 が private subnet に配置され、public IP を持たないこと
- ALB が public subnet 2 本へ配置されること

## Post-Deploy Actual Values

### VPC

| Property Name          | Value                 | Comment                                   |
| ---------------------- | --------------------- | ----------------------------------------- |
| vpcId                  | vpc-09da1a2c741c6c664 | post-deploy-actual-values.md に従って反映 |
| cidrBlock              | 10.0.0.0/16           | actual value                              |
| mainRouteTableId       | rtb-08812b7f7e4b80142 | actual value                              |
| defaultNetworkAclId    | acl-01377293865d99f0f | actual value                              |
| defaultSecurityGroupId | sg-062519f3ecc86fb66  | actual value                              |
| dhcpOptionsId          | dopt-46978c21         | actual value                              |
| enableDnsSupport       | true                  | actual value                              |
| enableDnsHostnames     | true                  | actual value                              |

### Post-Deploy NAT Gateway: NATA01

| Property Name | Value                      | Comment      |
| ------------- | -------------------------- | ------------ |
| natGatewayId  | nat-0f669f40f1aeb57f3      | actual value |
| subnetId      | subnet-04b8e39bf5928b306   | actual value |
| allocationId  | eipalloc-05a48d0a0ee5586f5 | actual value |
| publicIp      | 52.197.44.226              | actual value |
| privateIp     | 10.0.0.129                 | actual value |
| state         | available                  | actual value |

### Post-Deploy NAT Gateway: NATC01

| Property Name | Value                      | Comment      |
| ------------- | -------------------------- | ------------ |
| natGatewayId  | nat-0324eef4e6ce759e4      | actual value |
| subnetId      | subnet-0e91f32417238ddb7   | actual value |
| allocationId  | eipalloc-0efa6d13b8dd12d37 | actual value |
| publicIp      | 54.250.52.35               | actual value |
| privateIp     | 10.0.1.39                  | actual value |
| state         | available                  | actual value |

## Change History

- 2026-03-27: web-nginx dev の VPC、IGW、EIP、NAT Gateway 設計を追加

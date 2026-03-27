# Security Group Design

## Purpose

internet-facing ALB と private EC2 間の通信を最小権限で制御する。

## Naming Decision

- Security Group は naming rules 上で実リソース名を持つため、`GroupName` に命名規則を適用する
- CMD の `web-nginx-dev-alb-sg` / `web-nginx-dev-ec2-sg` ではなく、repo ルール優先で `dev-alb-web01-sg` / `dev-ec2-app01-sg` を採用する

## Security Group: ALBSG01

| Property Name | Value                                        | Comment                                                               |
| ------------- | -------------------------------------------- | --------------------------------------------------------------------- |
| groupName     | dev-alb-web01-sg                             | naming rule `{{env}}-{{serviceName}}-{{purpose}}{{number}}-sg` を適用 |
| attachedTo    | ALB01                                        | public ALB に適用                                                     |
| ingress       | tcp/80 from 0.0.0.0/0                        | HTTP のみ許可                                                         |
| egress        | tcp/80 to EC2SG01                            | target group 接続のみ許可                                             |
| template      | infra/cloudformation/templates/security.yaml | security stack で管理                                                 |

## Security Group: EC2SG01

| Property Name | Value                                        | Comment                                  |
| ------------- | -------------------------------------------- | ---------------------------------------- |
| groupName     | dev-ec2-app01-sg                             | naming rule を適用                       |
| attachedTo    | EC2AZ1,EC2AZ2                                | private EC2 に適用                       |
| ingress       | tcp/80 from ALBSG01                          | ALB からの HTTP のみ許可                 |
| egress80      | tcp/80 to 0.0.0.0/0                          | package mirror などの HTTP outbound      |
| egress443     | tcp/443 to 0.0.0.0/0                         | SSM public endpoint と package mirror 用 |
| ingress22     | none                                         | SSH は使わない                           |
| template      | infra/cloudformation/templates/security.yaml | security stack で管理                    |

## Preconditions And Dependencies

- VPC は [docs/designs/vpc.md](docs/designs/vpc.md) の export を使う
- ALB と EC2 の詳細は [docs/designs/alb.md](docs/designs/alb.md) と [docs/designs/ec2.md](docs/designs/ec2.md) を参照する

## CloudFormation Implementation

- template: infra/cloudformation/templates/security.yaml
- deploy責務: ALB SG と EC2 SG のみを deploy する
- import 一覧:
  - `${NetworkStackName}-VpcId`
- export 一覧:
  - `${SecurityStackName}-AlbSecurityGroupId`
  - `${SecurityStackName}-Ec2SecurityGroupId`
  - `${SecurityStackName}-SecurityGroupIds`
- template 境界の理由: security rule の更新を network/app から分離し、rollback と review をしやすくする

## Scenario Test Viewpoints

- ALB 経由の HTTP だけが通ること
- EC2 に public IP がなく、直接公開されないこと
- EC2 SG に SSH inbound が存在しないこと

## Post-Deploy Actual Values

### Post-Deploy Security Group: ALBSG01

| Property Name      | Value                          | Comment      |
| ------------------ | ------------------------------ | ------------ |
| securityGroupId    | sg-016e241a2c348b10d           | actual value |
| vpcId              | vpc-09da1a2c741c6c664          | actual value |
| groupName          | dev-alb-web01-sg               | actual value |
| ingressRuleSummary | tcp/80 from 0.0.0.0/0          | actual value |
| egressRuleSummary  | tcp/80 to sg-02279a735ccd14295 | actual value |

### Post-Deploy Security Group: EC2SG01

| Property Name      | Value                                     | Comment      |
| ------------------ | ----------------------------------------- | ------------ |
| securityGroupId    | sg-02279a735ccd14295                      | actual value |
| vpcId              | vpc-09da1a2c741c6c664                     | actual value |
| groupName          | dev-ec2-app01-sg                          | actual value |
| ingressRuleSummary | tcp/80 from sg-016e241a2c348b10d          | actual value |
| egressRuleSummary  | tcp/80 to 0.0.0.0/0, tcp/443 to 0.0.0.0/0 | actual value |

## Change History

- 2026-03-27: web-nginx dev の ALB/EC2 用 Security Group 設計を追加

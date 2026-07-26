# Subnet Design

public ALB/NAT 用 subnet と private application EC2 用 subnet を定義する。

<a id="subnet-publicaz1"></a>
## Subnet: PUBLICAZ1

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | sbnt-web-nginx-dev-public-public-a-01 | `Key=Name` |
| 3 | AvailabilityZone | ap-northeast-1a | ALB and NAT AZ1 |
| 4 | CidrBlock | 10.0.0.0/24 | public subnet AZ1 |
| 5 | MapPublicIpOnLaunch | true | public subnet behavior |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 7 | SubnetId | PENDING_DEPLOY | generated current value |

<a id="subnet-publicaz2"></a>
## Subnet: PUBLICAZ2

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | sbnt-web-nginx-dev-public-public-c-02 | `Key=Name` |
| 3 | AvailabilityZone | ap-northeast-1c | ALB and NAT AZ2 |
| 4 | CidrBlock | 10.0.1.0/24 | public subnet AZ2 |
| 5 | MapPublicIpOnLaunch | true | public subnet behavior |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 7 | SubnetId | PENDING_DEPLOY | generated current value |

<a id="subnet-privateappaz1"></a>
## Subnet: PRIVATEAPPAZ1

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | sbnt-web-nginx-dev-app-private-a-01 | `Key=Name` |
| 3 | AvailabilityZone | ap-northeast-1a | EC2 AZ1 |
| 4 | CidrBlock | 10.0.10.0/24 | private app subnet AZ1 |
| 5 | MapPublicIpOnLaunch | false | no public IP assignment |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 7 | SubnetId | PENDING_DEPLOY | generated current value |

<a id="subnet-privateappaz2"></a>
## Subnet: PRIVATEAPPAZ2

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | sbnt-web-nginx-dev-app-private-c-02 | `Key=Name` |
| 3 | AvailabilityZone | ap-northeast-1c | EC2 AZ2 |
| 4 | CidrBlock | 10.0.11.0/24 | private app subnet AZ2 |
| 5 | MapPublicIpOnLaunch | false | no public IP assignment |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 7 | SubnetId | PENDING_DEPLOY | generated current value |

## CloudFormation implementation

All subnets are owned by `infra/cloudformation/templates/network.yaml`. Route tables, routes, and associations are separated into [route-table.md](route-table.md#route-table-publicrt01).

## Scenario test viewpoints

- ALB connects to both public subnets.
- EC2 instances are distributed across both private subnets.

## Change history

- 2026-03-27: public/private subnet design created.
- 2026-07-26: route resources moved to `route-table.md`.

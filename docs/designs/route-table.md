# Route Table Design

Route Table、Route、Subnet Route Table Association を一つの human design resource group として定義する。

<a id="route-table-publicrt01"></a>
## Route Table: PUBLICRT01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | rtb-web-nginx-dev-public-public-01 | `Key=Name` |
| 3 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 4 | RouteTableId | PENDING_DEPLOY | generated current value |

<a id="route-public-default"></a>
### Route: PUBLICDEFAULT

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PUBLICRT01](#route-table-publicrt01) | logical route-table reference |
| 2 | DestinationCidrBlock | 0.0.0.0/0 | public default route |
| 3 | GatewayId | [WEBNGINXIGW](internet-gateway.md#internet-gateway-webnginxigw) | Internet Gateway target |

<a id="route-association-publicaz1"></a>
### Association: PUBLICAZ1ASSOC

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PUBLICRT01](#route-table-publicrt01) | logical route-table reference |
| 2 | SubnetId | [PUBLICAZ1](subnet.md#subnet-publicaz1) | public subnet AZ1 |

<a id="route-association-publicaz2"></a>
### Association: PUBLICAZ2ASSOC

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PUBLICRT01](#route-table-publicrt01) | logical route-table reference |
| 2 | SubnetId | [PUBLICAZ2](subnet.md#subnet-publicaz2) | public subnet AZ2 |

<a id="route-table-privateapparta01"></a>
## Route Table: PRIVATEAPPARTA01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | rtb-web-nginx-dev-app-private-a-01 | `Key=Name` |
| 3 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 4 | RouteTableId | PENDING_DEPLOY | generated current value |

<a id="route-private-az1-default"></a>
### Route: PRIVATEAZ1DEFAULT

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PRIVATEAPPARTA01](#route-table-privateapparta01) | logical route-table reference |
| 2 | DestinationCidrBlock | 0.0.0.0/0 | private default route |
| 3 | NatGatewayId | [NATA01](nat-gateway.md#nat-gateway-nata01) | same-AZ NAT target |

<a id="route-association-privateappaz1"></a>
### Association: PRIVATEAPPAZ1ASSOC

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PRIVATEAPPARTA01](#route-table-privateapparta01) | logical route-table reference |
| 2 | SubnetId | [PRIVATEAPPAZ1](subnet.md#subnet-privateappaz1) | private subnet AZ1 |

<a id="route-table-privateappcrt02"></a>
## Route Table: PRIVATEAPPCRT02

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 2 | Tags[].Value | rtb-web-nginx-dev-app-private-c-02 | `Key=Name` |
| 3 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 4 | RouteTableId | PENDING_DEPLOY | generated current value |

<a id="route-private-az2-default"></a>
### Route: PRIVATEAZ2DEFAULT

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PRIVATEAPPCRT02](#route-table-privateappcrt02) | logical route-table reference |
| 2 | DestinationCidrBlock | 0.0.0.0/0 | private default route |
| 3 | NatGatewayId | [NATC01](nat-gateway.md#nat-gateway-natc01) | same-AZ NAT target |

<a id="route-association-privateappaz2"></a>
### Association: PRIVATEAPPAZ2ASSOC

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RouteTableId | [PRIVATEAPPCRT02](#route-table-privateappcrt02) | logical route-table reference |
| 2 | SubnetId | [PRIVATEAPPAZ2](subnet.md#subnet-privateappaz2) | private subnet AZ2 |

## CloudFormation implementation

`infra/cloudformation/templates/network.yaml` owns all Route Tables, Routes, and Associations so the routable network can roll back with the VPC.

## Scenario test viewpoints

- public subnets share the IGW route.
- each private subnet uses its same-AZ NAT Gateway.

## Change history

- 2026-03-27: route design created.
- 2026-07-26: split from the former subnet document.

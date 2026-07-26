# NAT Gateway Design

private subnet の outbound を AZ-local に提供する public NAT Gateway を定義する。

<a id="nat-gateway-nata01"></a>
## NAT Gateway: NATA01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | natgw-web-nginx-dev-a | `Key=Name`; AZ1 |
| 2 | SubnetId | [PUBLICAZ1](subnet.md#subnet-publicaz1) | public subnet AZ1 |
| 3 | AllocationId | [NATA01EIP](elastic-ip.md#elastic-ip-nata01eip) | AZ1 Elastic IP logical reference |
| 4 | ConnectivityType | public | private subnet outbound |
| 5 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 6 | NatGatewayId | PENDING_DEPLOY | generated current value |
| 7 | PrivateIp | PENDING_DEPLOY | generated current value |

<a id="nat-gateway-natc01"></a>
## NAT Gateway: NATC01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | natgw-web-nginx-dev-c | `Key=Name`; AZ2 |
| 2 | SubnetId | [PUBLICAZ2](subnet.md#subnet-publicaz2) | public subnet AZ2 |
| 3 | AllocationId | [NATC02EIP](elastic-ip.md#elastic-ip-natc02eip) | AZ2 Elastic IP logical reference |
| 4 | ConnectivityType | public | private subnet outbound |
| 5 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 6 | NatGatewayId | PENDING_DEPLOY | generated current value |
| 7 | PrivateIp | PENDING_DEPLOY | generated current value |

## CloudFormation implementation

Both NAT Gateways are owned by `infra/cloudformation/templates/network.yaml`. Private routes are defined in [route-table.md](route-table.md#route-private-az1-default).

## Scenario test viewpoints

- each private route uses the NAT Gateway in the same Availability Zone.

## Change history

- 2026-03-27: two NAT Gateway designs created.
- 2026-07-26: split from the former VPC document.

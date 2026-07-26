# Elastic IP Design

各 public NAT Gateway に割り当てる Elastic IP を定義する。

<a id="elastic-ip-nata01eip"></a>
## Elastic IP: NATA01EIP

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | eip-web-nginx-dev-nat-a-01 | `Key=Name`; NAT AZ1 |
| 2 | Domain | vpc | VPC domain |
| 3 | Allocation strategy | create in stack | network stack responsibility |
| 4 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 5 | AllocationId | PENDING_DEPLOY | generated current value |
| 6 | PublicIp | PENDING_DEPLOY | generated current value |

<a id="elastic-ip-natc02eip"></a>
## Elastic IP: NATC02EIP

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | eip-web-nginx-dev-nat-c-02 | `Key=Name`; NAT AZ2 |
| 2 | Domain | vpc | VPC domain |
| 3 | Allocation strategy | create in stack | network stack responsibility |
| 4 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 5 | AllocationId | PENDING_DEPLOY | generated current value |
| 6 | PublicIp | PENDING_DEPLOY | generated current value |

## CloudFormation implementation

Both EIPs are owned by `infra/cloudformation/templates/network.yaml`.

## Change history

- 2026-03-27: two NAT Elastic IP designs created.
- 2026-07-26: split from the former VPC document.

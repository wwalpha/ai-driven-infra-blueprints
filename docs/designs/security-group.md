# Security Group Design

internet-facing ALB と private EC2 間の通信を最小権限で制御する。

<a id="security-group-albsg01"></a>
## Security Group: ALBSG01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | GroupDescription | Allow inbound HTTP from the internet to the public ALB. | CloudFormation design |
| 2 | GroupName | dev-alb-web01-sg | naming rule |
| 3 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 4 | Attached resource | [ALB01](load-balancer.md#load-balancer-alb01) | public ALB |
| 5 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 6 | SecurityGroupId | PENDING_DEPLOY | generated current value |

<a id="security-group-albsg01-ingress-http"></a>
### Ingress: ALBSG01 HTTP

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IpProtocol | tcp | HTTP |
| 2 | FromPort | 80 | HTTP |
| 3 | ToPort | 80 | HTTP |
| 4 | CidrIp | 0.0.0.0/0 | internet clients |

<a id="security-group-albsg01-egress-http"></a>
### Egress: ALBSG01 to EC2SG01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IpProtocol | tcp | HTTP |
| 2 | FromPort | 80 | target port |
| 3 | ToPort | 80 | target port |
| 4 | DestinationSecurityGroupId | [EC2SG01](#security-group-ec2sg01) | target EC2 group |

<a id="security-group-ec2sg01"></a>
## Security Group: EC2SG01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | GroupDescription | Allow inbound HTTP from the ALB and outbound HTTP/HTTPS for patching and SSM. | CloudFormation design |
| 2 | GroupName | dev-ec2-app01-sg | naming rule |
| 3 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 4 | Attached resources | [EC2AZ1](ec2.md#ec2-ec2az1), [EC2AZ2](ec2.md#ec2-ec2az2) | private EC2 instances |
| 5 | SSH ingress | none | Session Manager only |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 7 | SecurityGroupId | PENDING_DEPLOY | generated current value |

<a id="security-group-ec2sg01-ingress-http"></a>
### Ingress: EC2SG01 from ALBSG01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IpProtocol | tcp | HTTP |
| 2 | FromPort | 80 | NGINX |
| 3 | ToPort | 80 | NGINX |
| 4 | SourceSecurityGroupId | [ALBSG01](#security-group-albsg01) | ALB only |

<a id="security-group-ec2sg01-egress-http"></a>
### Egress: EC2SG01 HTTP

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IpProtocol | tcp | package mirror |
| 2 | FromPort | 80 | HTTP |
| 3 | ToPort | 80 | HTTP |
| 4 | CidrIp | 0.0.0.0/0 | through NAT |

<a id="security-group-ec2sg01-egress-https"></a>
### Egress: EC2SG01 HTTPS

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | IpProtocol | tcp | SSM and package mirror |
| 2 | FromPort | 443 | HTTPS |
| 3 | ToPort | 443 | HTTPS |
| 4 | CidrIp | 0.0.0.0/0 | through NAT |

## CloudFormation implementation

- implementation: `infra/cloudformation/templates/security.yaml`
- responsibility: ALB SG and EC2 SG
- dependency: imports VPC ID from network stack
- exports: both security group IDs
- boundary: security rule rollback is separate from network/app

## Scenario test viewpoints

- ALB経由の HTTP が動作する。
- EC2 は direct public access を持たない。
- SSH ingress が存在しない。

## Change history

- 2026-03-27: ALB/EC2 Security Group design created.
- 2026-07-26: rule tables and deleted deployment state added.

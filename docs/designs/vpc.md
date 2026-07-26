# VPC Design

web-nginx の public ALB と private EC2 を収容する Multi-AZ VPC を定義する。

<a id="vpc-webnginxvpc"></a>
## VPC: WEBNGINXVPC

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | vpc-web-nginx-dev | `Key=Name`; naming rule `vpc-{{application}}-{{env}}` |
| 2 | CidrBlock | 10.0.0.0/16 | VPC CIDR |
| 3 | EnableDnsSupport | true | DNS resolution enabled |
| 4 | EnableDnsHostnames | true | DNS hostname enabled |
| 5 | IP address family | ipv4 | current sample selection |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 7 | VpcId | PENDING_DEPLOY | generated current value |

## Preconditions and constraints

- region は `ap-northeast-1`。
- Availability Zone は `ap-northeast-1a` と `ap-northeast-1c`。
- SSM VPC endpoint は作らず、private EC2 の outbound は NAT Gateway を利用する。
- HTTPS は current sample の対象外で、ALB は HTTP 80 のみ。

## CloudFormation implementation

- implementation: `infra/cloudformation/templates/network.yaml`
- responsibility: VPC、IGW、subnet、route table、EIP、NAT Gateway の基盤 network
- deploy order: network → security → app
- exports: VPC ID、public/private subnet IDs
- boundary: downstream stack に stable network IDs を提供し、security/app の rollback unit と分離する

## Scenario test viewpoints

- private subnet の default route が同一 AZ の NAT Gateway を向く。
- EC2 は private subnet にあり public IP を持たない。
- ALB は2本の public subnet に配置される。

## Change history

- 2026-03-27: web-nginx dev VPC design created.
- 2026-07-26: resource-group migration; deleted deployment state corrected.

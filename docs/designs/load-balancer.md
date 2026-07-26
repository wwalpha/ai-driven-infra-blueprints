# Load Balancer Design

public subnet の internet-facing ALB で HTTP 80 を受け、private EC2 上の NGINX へ転送する。

<a id="load-balancer-alb01"></a>
## Load Balancer: ALB01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | alb-dev-web01 | naming rule |
| 2 | Scheme | internet-facing | public ALB |
| 3 | Type | application | Application Load Balancer |
| 4 | IpAddressType | ipv4 | current sample |
| 5 | Subnets | [PUBLICAZ1](subnet.md#subnet-publicaz1), [PUBLICAZ2](subnet.md#subnet-publicaz2) | two public subnets |
| 6 | SecurityGroups | [ALBSG01](security-group.md#security-group-albsg01) | internet HTTP ingress |
| 7 | Access logs | disabled | current sample selection |
| 8 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 9 | DnsName | PENDING_DEPLOY | generated current value |
| 10 | CanonicalHostedZoneId | PENDING_DEPLOY | generated current value |

<a id="target-group-tg01"></a>
## Target Group: TG01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | tgp-dev-web01 | naming rule |
| 2 | TargetType | instance | EC2 targets |
| 3 | Protocol | HTTP | target protocol |
| 4 | Port | 80 | NGINX |
| 5 | HealthCheckProtocol | HTTP | health check |
| 6 | HealthCheckPath | / | index page |
| 7 | Matcher.HttpCode | 200-399 | healthy response |
| 8 | TargetGroupAttributes | `deregistration_delay.timeout_seconds=60` | fixed sample value |
| 9 | VpcId | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | logical VPC reference |
| 10 | Targets | [EC2AZ1](ec2.md#ec2-ec2az1), [EC2AZ2](ec2.md#ec2-ec2az2) | two instances |
| 11 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |

<a id="listener-http80"></a>
## Listener: HTTP80

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | LoadBalancerArn | [ALB01](#load-balancer-alb01) | logical reference; ARN is resolved transiently by IaC |
| 2 | Protocol | HTTP | current sample |
| 3 | Port | 80 | public listener |
| 4 | DefaultActions | forward to [TG01](#target-group-tg01) | target ARN is resolved transiently by IaC |
| 5 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |

## CloudFormation implementation

- implementation: `infra/cloudformation/templates/app.yaml`
- responsibility: ALB, Target Group, Listener share the app stack with target EC2 instances
- imports: VPC ID, public subnet IDs, ALB security group ID
- boundary: ALB and registered EC2 targets share a rollback unit
- generated load-balancer and target-group ARNs may remain CloudFormation outputs or transient API inputs but are not current actual records

## Scenario test viewpoints

- HTTP GET to the ALB DNS name returns 200 and expected page metadata.
- Target Group has two healthy targets.

## Change history

- 2026-03-27: internet-facing ALB design created.
- 2026-07-26: renamed from `alb.md`; current generated ARNs and stale values removed.

# Internet Gateway Design

web-nginx VPC の public route target を定義する。

<a id="internet-gateway-webnginxigw"></a>
## Internet Gateway: WEBNGINXIGW

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | igw-web-nginx-dev | `Key=Name`; naming rule `igw-{{vpcName}}` |
| 2 | AttachedVpc | [WEBNGINXVPC](vpc.md#vpc-webnginxvpc) | VPC gateway attachment |
| 3 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 4 | InternetGatewayId | PENDING_DEPLOY | generated current value |

## CloudFormation implementation

`infra/cloudformation/templates/network.yaml` owns the Internet Gateway and its VPC attachment. The public default route is defined in [route-table.md](route-table.md#route-public-default).

## Change history

- 2026-03-27: web-nginx dev Internet Gateway design created.
- 2026-07-26: split from the former VPC document.

# ElasticLoadBalancingV2 Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Elastic Load Balancing | Load balancer | `ElasticLoadBalancingV2.LoadBalancer` | `Name` | `{{load_balancer_type}}-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Elastic Load Balancing | Target group | `ElasticLoadBalancingV2.TargetGroup` | `Name` | `tgp-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

## Service-specific constraints

- Elastic Load Balancingのload balancerとtarget groupは32文字以内とする。

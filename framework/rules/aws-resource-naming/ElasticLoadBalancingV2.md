# ElasticLoadBalancingV2 Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Elastic Load Balancing | Load balancer | `ElasticLoadBalancingV2.LoadBalancer` | `Name` | `{{load_balancer_type}}-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Elastic Load Balancing | Target group | `ElasticLoadBalancingV2.TargetGroup` | `Name` | `tgp-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

## Service-specific constraints

- Elastic Load Balancing load balancers and target groups must be at most 32 characters.

# AutoScaling Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| EC2 Auto Scaling | Auto Scaling group | `AutoScaling.AutoScalingGroup` | `AutoScalingGroupName` | `asg-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

# IAM Instance Profile Design

EC2 に IAM Role を付与する Instance Profile を定義する。

<a id="instance-profile-webnginxec2profile01"></a>
## Instance Profile: WEBNGINXEC2PROFILE01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | InstanceProfileName | webNginxEc2Profile | role-aligned explicit name |
| 2 | Roles | [WEBNGINXEC2ROLE01](iam-role.md#iam-role-webnginxec2role01) | logical role reference |
| 3 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |

## CloudFormation implementation

`infra/cloudformation/templates/app.yaml` owns the Instance Profile.

## Scenario test viewpoints

- both EC2 instances have this profile attached after deployment.

## Change history

- 2026-03-27: Instance Profile design created.
- 2026-07-26: split from the former EC2 document; generated profile ARN removed from current design.

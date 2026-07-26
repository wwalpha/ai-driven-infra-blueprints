# IAM Role Design

private EC2 の Session Manager と bootstrap に使用する IAM Role を定義する。

<a id="iam-role-webnginxec2role01"></a>
## IAM Role: WEBNGINXEC2ROLE01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | RoleName | webNginxEc2Role | naming rule `{{purposeOrAppName}}{{serviceName}}Role` |
| 2 | AssumeRolePolicyDocument | EC2 service principal may call `sts:AssumeRole` | trust policy |
| 3 | ManagedPolicyArns | arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore | human-provided AWS managed-policy ARN; design input, not generated actual |
| 4 | Tags[].Value | webNginxEc2Role | `Key=Name` |
| 5 | Purpose | EC2 bootstrap and Session Manager | no SSH management |
| 6 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |

## CloudFormation implementation

`infra/cloudformation/templates/app.yaml` owns the named IAM Role. Deployment requires the named-IAM capability when authorized.

## Change history

- 2026-03-27: EC2 IAM Role design created.
- 2026-07-26: split from the former EC2 document; generated role ARN removed from current design.

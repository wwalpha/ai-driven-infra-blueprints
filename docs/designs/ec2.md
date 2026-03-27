# EC2 Design

## Purpose

private subnet に Amazon Linux 2023 EC2 を 2 台配置し、Session Manager 運用と NGINX bootstrap を定義する。

## Naming Decision

- EC2 instance は naming rules 上で `Name` tag を主に使うため、実名ではなく `Name` tag に `dev-web-a01` / `dev-web-c01` を採用する
- IAM Role は naming rules の IAM 実名ルールを優先し `webNginxEc2Role` を採用する
- Instance Profile は IAM role 名に合わせて `webNginxEc2Profile` を採用し、CMD の `web-nginx-dev-ec2-profile` とは差分を残す

## IAM Role: WEBNGINXEC2ROLE01

| Property Name | Value                                                | Comment                                                          |
| ------------- | ---------------------------------------------------- | ---------------------------------------------------------------- |
| roleName      | webNginxEc2Role                                      | IAM naming rule `{{purposeOrAppName}}{{serviceName}}Role` を適用 |
| managedPolicy | arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore | Session Manager 用                                               |
| purpose       | EC2 bootstrap and session management                 | SSH なし運用                                                     |
| template      | infra/cloudformation/templates/app.yaml              | app stack で管理                                                 |

## Instance Profile: WEBNGINXEC2PROFILE01

| Property Name       | Value                                   | Comment                                 |
| ------------------- | --------------------------------------- | --------------------------------------- |
| instanceProfileName | webNginxEc2Profile                      | Role 名に合わせた instance profile 実名 |
| role                | WEBNGINXEC2ROLE01                       | EC2 に割り当てる                        |
| template            | infra/cloudformation/templates/app.yaml | app stack で管理                        |

## EC2: EC2AZ1

| Property Name            | Value                                                                 | Comment                          |
| ------------------------ | --------------------------------------------------------------------- | -------------------------------- |
| nameTag                  | dev-web-a01                                                           | `Name` tag に naming rule を適用 |
| availabilityZone         | ap-northeast-1a                                                       | AZ1 に配置                       |
| subnet                   | PRIVATEAPPAZ1                                                         | private subnet AZ1               |
| instanceType             | t3.small                                                              | 固定値                           |
| architecture             | x86_64                                                                | AL2023 x86_64                    |
| amiSsmParameter          | /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 | SSM public parameter 参照        |
| associatePublicIpAddress | false                                                                 | private EC2 のため無効           |
| securityGroup            | EC2SG01                                                               | ALB からの HTTP のみ許可         |
| instanceProfile          | WEBNGINXEC2PROFILE01                                                  | SSM 接続と bootstrap 用          |
| rootVolumeType           | gp3                                                                   | 固定値                           |
| rootVolumeSizeGiB        | 8                                                                     | 固定値                           |
| metadataHttpTokens       | required                                                              | IMDSv2 必須                      |
| template                 | infra/cloudformation/templates/app.yaml                               | app stack で管理                 |

## EC2: EC2AZ2

| Property Name            | Value                                                                 | Comment                          |
| ------------------------ | --------------------------------------------------------------------- | -------------------------------- |
| nameTag                  | dev-web-c01                                                           | `Name` tag に naming rule を適用 |
| availabilityZone         | ap-northeast-1c                                                       | AZ2 に配置                       |
| subnet                   | PRIVATEAPPAZ2                                                         | private subnet AZ2               |
| instanceType             | t3.small                                                              | 固定値                           |
| architecture             | x86_64                                                                | AL2023 x86_64                    |
| amiSsmParameter          | /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 | SSM public parameter 参照        |
| associatePublicIpAddress | false                                                                 | private EC2 のため無効           |
| securityGroup            | EC2SG01                                                               | ALB からの HTTP のみ許可         |
| instanceProfile          | WEBNGINXEC2PROFILE01                                                  | SSM 接続と bootstrap 用          |
| rootVolumeType           | gp3                                                                   | 固定値                           |
| rootVolumeSizeGiB        | 8                                                                     | 固定値                           |
| metadataHttpTokens       | required                                                              | IMDSv2 必須                      |
| template                 | infra/cloudformation/templates/app.yaml                               | app stack で管理                 |

## UserData: NGINXBOOTSTRAP01

| Property Name      | Value                                                         | Comment                        |
| ------------------ | ------------------------------------------------------------- | ------------------------------ |
| packageManager     | dnf                                                           | Amazon Linux 2023 を前提とする |
| installPackage     | nginx                                                         | web server を導入する          |
| systemdEnable      | true                                                          | 再起動後も自動起動             |
| indexPageContent   | systemName / env / hostname / instance-id / availability-zone | HTML に必要値を出す            |
| idempotentApproach | rpm query and overwrite index.html                            | 再実行時も壊しにくくする       |
| template           | infra/cloudformation/templates/app.yaml                       | app stack で管理               |

## Preconditions And Dependencies

- VPC と subnet は [docs/designs/vpc.md](docs/designs/vpc.md) と [docs/designs/subnet.md](docs/designs/subnet.md) を参照する
- Security Group は [docs/designs/security-group.md](docs/designs/security-group.md) を参照する
- ALB は [docs/designs/alb.md](docs/designs/alb.md) を参照する
- SSH inbound は作らず、管理接続は Session Manager のみとする

## CloudFormation Implementation

- template: infra/cloudformation/templates/app.yaml
- deploy責務: IAM Role、Instance Profile、EC2、UserData bootstrap を app stack で deploy する
- import 一覧:
  - `${NetworkStackName}-PrivateAppSubnetAz1Id`
  - `${NetworkStackName}-PrivateAppSubnetAz2Id`
  - `${SecurityStackName}-Ec2SecurityGroupId`
- output 一覧:
  - `${AppStackName}-Ec2InstanceIds`
  - `${AppStackName}-Ec2Az1InstanceId`
  - `${AppStackName}-Ec2Az2InstanceId`

## Scenario Test Viewpoints

- ALB 経由で NGINX の HTML を返すこと
- 2 台とも Target Group で healthy になること
- EC2 に public IP が付与されないこと
- 2 台が別 AZ に配置されること
- IAM instance profile が 2 台とも付与されること

## Post-Deploy Actual Values

### Post-Deploy IAM Role: WEBNGINXEC2ROLE01

| Property Name           | Value                                                | Comment      |
| ----------------------- | ---------------------------------------------------- | ------------ |
| roleName                | webNginxEc2Role                                      | actual value |
| roleArn                 | arn:aws:iam::334678299258:role/webNginxEc2Role       | actual value |
| path                    | /                                                    | actual value |
| permissionsBoundary     | none                                                 | actual value |
| attachedManagedPolicies | arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore | actual value |
| inlinePolicyNames       | none                                                 | actual value |

### Post-Deploy Instance Profile: WEBNGINXEC2PROFILE01

| Property Name       | Value                                                         | Comment      |
| ------------------- | ------------------------------------------------------------- | ------------ |
| instanceProfileName | webNginxEc2Profile                                            | actual value |
| instanceProfileArn  | arn:aws:iam::334678299258:instance-profile/webNginxEc2Profile | actual value |
| roleNames           | webNginxEc2Role                                               | actual value |

### Post-Deploy EC2: EC2AZ1

| Property Name         | Value                                                         | Comment      |
| --------------------- | ------------------------------------------------------------- | ------------ |
| instanceId            | i-07724d16c58b825b2                                           | actual value |
| imageId               | ami-088b486f20fab3f0e                                         | actual value |
| instanceType          | t3.small                                                      | actual value |
| subnetId              | subnet-0a60ddd215eee3532                                      | actual value |
| privateIp             | 10.0.10.230                                                   | actual value |
| privateDnsName        | ip-10-0-10-230.ap-northeast-1.compute.internal                | actual value |
| availabilityZone      | ap-northeast-1a                                               | actual value |
| securityGroupIds      | sg-02279a735ccd14295                                          | actual value |
| iamInstanceProfileArn | arn:aws:iam::334678299258:instance-profile/webNginxEc2Profile | actual value |
| keyName               | none                                                          | actual value |
| state                 | running                                                       | actual value |

### Post-Deploy EC2: EC2AZ2

| Property Name         | Value                                                         | Comment      |
| --------------------- | ------------------------------------------------------------- | ------------ |
| instanceId            | i-0c91877e97777e9d9                                           | actual value |
| imageId               | ami-088b486f20fab3f0e                                         | actual value |
| instanceType          | t3.small                                                      | actual value |
| subnetId              | subnet-089a21093d6eb8a28                                      | actual value |
| privateIp             | 10.0.11.178                                                   | actual value |
| privateDnsName        | ip-10-0-11-178.ap-northeast-1.compute.internal                | actual value |
| availabilityZone      | ap-northeast-1c                                               | actual value |
| securityGroupIds      | sg-02279a735ccd14295                                          | actual value |
| iamInstanceProfileArn | arn:aws:iam::334678299258:instance-profile/webNginxEc2Profile | actual value |
| keyName               | none                                                          | actual value |
| state                 | running                                                       | actual value |

## Change History

- 2026-03-27: web-nginx dev の EC2、IAM、UserData 設計を追加

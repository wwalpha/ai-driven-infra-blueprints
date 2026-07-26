# EC2 Design

private subnet に Amazon Linux 2023 EC2 を2台配置し、Session Manager 運用と NGINX bootstrap を定義する。

<a id="ec2-ec2az1"></a>
## EC2 Instance: EC2AZ1

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | dev-web-a01 | `Key=Name`; naming rule |
| 2 | AvailabilityZone | ap-northeast-1a | derived from selected subnet |
| 3 | NetworkInterfaces[].SubnetId | [PRIVATEAPPAZ1](subnet.md#subnet-privateappaz1) | logical subnet reference |
| 4 | InstanceType | t3.small | fixed sample value |
| 5 | ImageId | `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` | resolved through SSM public parameter |
| 6 | NetworkInterfaces[].AssociatePublicIpAddress | false | private instance |
| 7 | NetworkInterfaces[].GroupSet | [EC2SG01](security-group.md#security-group-ec2sg01) | logical security-group reference |
| 8 | IamInstanceProfile | [WEBNGINXEC2PROFILE01](instance-profile.md#instance-profile-webnginxec2profile01) | Session Manager |
| 9 | BlockDeviceMappings[].Ebs.VolumeType | gp3 | root volume |
| 10 | BlockDeviceMappings[].Ebs.VolumeSize | 8 | GiB |
| 11 | MetadataOptions.HttpTokens | required | IMDSv2 |
| 12 | Monitoring | false | detailed monitoring disabled |
| 13 | DisableApiTermination | false | termination protection disabled |
| 14 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 15 | InstanceId | PENDING_DEPLOY | generated current value |
| 16 | PrivateIp | PENDING_DEPLOY | generated current value |
| 17 | PrivateDnsName | PENDING_DEPLOY | generated current value |

<a id="ec2-ec2az2"></a>
## EC2 Instance: EC2AZ2

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Tags[].Value | dev-web-c01 | `Key=Name`; naming rule |
| 2 | AvailabilityZone | ap-northeast-1c | derived from selected subnet |
| 3 | NetworkInterfaces[].SubnetId | [PRIVATEAPPAZ2](subnet.md#subnet-privateappaz2) | logical subnet reference |
| 4 | InstanceType | t3.small | fixed sample value |
| 5 | ImageId | `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` | resolved through SSM public parameter |
| 6 | NetworkInterfaces[].AssociatePublicIpAddress | false | private instance |
| 7 | NetworkInterfaces[].GroupSet | [EC2SG01](security-group.md#security-group-ec2sg01) | logical security-group reference |
| 8 | IamInstanceProfile | [WEBNGINXEC2PROFILE01](instance-profile.md#instance-profile-webnginxec2profile01) | Session Manager |
| 9 | BlockDeviceMappings[].Ebs.VolumeType | gp3 | root volume |
| 10 | BlockDeviceMappings[].Ebs.VolumeSize | 8 | GiB |
| 11 | MetadataOptions.HttpTokens | required | IMDSv2 |
| 12 | Monitoring | false | detailed monitoring disabled |
| 13 | DisableApiTermination | false | termination protection disabled |
| 14 | DeploymentState | NOT_DEPLOYED | 2026-03-27 teardown evidence |
| 15 | InstanceId | PENDING_DEPLOY | generated current value |
| 16 | PrivateIp | PENDING_DEPLOY | generated current value |
| 17 | PrivateDnsName | PENDING_DEPLOY | generated current value |

<a id="ec2-userdata-nginxbootstrap01"></a>
## UserData: NGINXBOOTSTRAP01

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | UserData | install/enable/start NGINX and overwrite `index.html` | Amazon Linux 2023 bootstrap |
| 2 | Package manager | dnf | install only when RPM is absent |
| 3 | Index content | systemName / env / hostname / instance-id / availability-zone | scenario-visible metadata |
| 4 | Idempotency | RPM query plus deterministic page overwrite | repeat-safe approach |

## CloudFormation implementation

- implementation: `infra/cloudformation/templates/app.yaml`
- responsibility: IAM, load balancer components, both EC2 instances, and UserData
- imports: private subnet IDs and EC2 security group ID
- current sample does not create SSH ingress or SSM VPC endpoints

## Scenario test viewpoints

- ALB経由で NGINX HTML を返す。
- both targets become healthy.
- instances have no public IP and occupy distinct Availability Zones.
- both instances have the selected Instance Profile.

## Change history

- 2026-03-27: EC2 and UserData design created.
- 2026-07-26: IAM groups split out; deleted deployment state corrected.

# Post-Deploy Actual Values Catalog

## このファイルの目的

このファイルは、各 AWS サービスの `Post-Deploy Actual Values` を共通定義するための正本です。  
`docs/designs/*.md` に deploy 後の実値を反映するときは、このファイルを参照します。

## 基本ルール

- `Post-Deploy Actual Values` は `docs/designs/*.md` に記載する
- design 時点の intended state と deploy 後の actual state を分けて管理する
- `Post-Deploy Actual Values` には、少なくとも運用・疎通確認・再参照に必要な ID / 実値を残す
- 可能な限り CloudFormation Outputs を使い、足りないものは AWS CLI で取得する

## サービス別定義

### 1. VPC

- vpcId
- cidrBlock
- mainRouteTableId
- defaultNetworkAclId
- defaultSecurityGroupId
- dhcpOptionsId
- enableDnsSupport
- enableDnsHostnames

### 2. Subnet

- subnetId
- vpcId
- availabilityZone
- availabilityZoneId
- cidrBlock
- routeTableId
- networkAclId
- mapPublicIpOnLaunch

### 3. Route Table

- routeTableId
- vpcId
- associatedSubnetIds
- propagatedGatewayIds
- routeSummary

### 4. Internet Gateway

- internetGatewayId
- attachedVpcId

### 5. NAT Gateway

- natGatewayId
- subnetId
- vpcId
- connectivityType
- allocationId
- publicIp
- privateIp
- state

### 6. Security Group

- securityGroupId
- vpcId
- groupName
- ingressRuleSummary
- egressRuleSummary

### 7. EC2 Instance

- instanceId
- imageId
- instanceType
- subnetId
- privateIp
- privateDnsName
- availabilityZone
- securityGroupIds
- iamInstanceProfileArn
- keyName
- state

### 8. EBS Volume

- volumeId
- availabilityZone
- sizeGiB
- volumeType
- iops
- throughput
- encrypted
- kmsKeyId
- attachedInstanceId
- deviceName

### 9. Application Load Balancer

- loadBalancerArn
- loadBalancerName
- dnsName
- canonicalHostedZoneId
- scheme
- ipAddressType
- subnetIds
- securityGroupIds
- vpcId
- state

### 10. Target Group

- targetGroupArn
- targetGroupName
- targetType
- protocol
- port
- vpcId
- healthCheckPath
- matcher
- registeredTargetIds

### 11. Network Load Balancer

- loadBalancerArn
- loadBalancerName
- dnsName
- canonicalHostedZoneId
- scheme
- subnetIds
- vpcId
- state

### 12. Auto Scaling Group

- autoScalingGroupName
- autoScalingGroupArn
- desiredCapacity
- minSize
- maxSize
- availabilityZones
- subnetIds
- launchTemplateIdOrName
- targetGroupArns
- instanceIds

### 13. Launch Template

- launchTemplateId
- launchTemplateName
- latestVersionNumber
- defaultVersionNumber
- imageId
- instanceType
- securityGroupIds
- iamInstanceProfileNameOrArn

### 14. IAM Role

- roleName
- roleArn
- path
- permissionsBoundary
- attachedManagedPolicies
- inlinePolicyNames

### 15. IAM Instance Profile

- instanceProfileName
- instanceProfileArn
- roleNames

### 16. S3 Bucket

- bucketName
- bucketArn
- region
- versioningStatus
- encryptionSummary
- publicAccessBlockSummary
- lifecycleRuleNames

### 17. RDS DB Instance

- dbInstanceIdentifier
- dbInstanceArn
- engine
- engineVersion
- dbInstanceClass
- endpointAddress
- endpointPort
- subnetGroupName
- securityGroupIds
- kmsKeyId
- status

### 18. Aurora / RDS Cluster

- dbClusterIdentifier
- dbClusterArn
- engine
- engineVersion
- writerEndpoint
- readerEndpoint
- port
- subnetGroupName
- securityGroupIds
- kmsKeyId
- memberInstanceIdentifiers
- status

### 19. ElastiCache Replication Group

- replicationGroupId
- replicationGroupArn
- engine
- engineVersion
- primaryEndpointAddress
- readerEndpointAddress
- port
- subnetGroupName
- securityGroupIds
- status

### 20. EFS File System

- fileSystemId
- fileSystemArn
- performanceMode
- throughputMode
- encrypted
- kmsKeyId
- mountTargetIds
- mountTargetIpAddresses

### 21. Lambda Function

- functionName
- functionArn
- runtime
- handler
- roleArn
- timeout
- memorySize
- codeSha256
- latestVersion
- aliasNames
- logGroupName

### 22. API Gateway

- apiId
- apiName
- apiEndpoint
- stageName
- stageInvokeUrl
- deploymentId
- customDomainName
- hostedZoneId

### 23. Route 53 Hosted Zone

- hostedZoneId
- hostedZoneName
- privateZone
- vpcIds
- recordSetSummary

### 24. CloudWatch Alarm

- alarmName
- alarmArn
- metricName
- namespace
- comparisonOperator
- threshold
- evaluationPeriods
- stateValue
- treatMissingData

### 25. CloudWatch Log Group

- logGroupName
- arn
- retentionInDays
- kmsKeyId
- storedBytes

### 26. SNS Topic

- topicName
- topicArn
- kmsMasterKeyId
- subscriptionEndpoints

### 27. SQS Queue

- queueName
- queueUrl
- queueArn
- visibilityTimeout
- messageRetentionPeriod
- kmsKeyId
- deadLetterTargetArn

### 28. KMS Key

- keyId
- keyArn
- keySpec
- keyUsage
- aliasNames
- enabled
- rotationEnabled

### 29. ECS Cluster / Service

- clusterArn
- clusterName
- serviceArn
- serviceName
- taskDefinitionArn
- desiredCount
- runningCount
- subnetIds
- securityGroupIds
- targetGroupArns

### 30. ECR Repository

- repositoryName
- repositoryArn
- repositoryUri
- encryptionType
- imageTagMutability
- lifecyclePolicySummary

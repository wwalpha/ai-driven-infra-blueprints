"""Explicit AWS receiving-property contracts shared by comparison and IMPORT."""

import re
from functools import lru_cache

from design.services.definitions.registry import POLICY_FORMATS

from utils.comparison_rows import put_row

# Returned attributes whose explicit setting has a different property name.
RETURN_ATTRIBUTE_PROPERTIES = {
    ("EC2.SecurityGroup", "GroupId"): "Id",
    ("CodeCommit.Repository", "Name"): "RepositoryName",
    ("Events.Rule", "RuleName"): "Name",
    ("SNS.Topic", "TopicName"): "TopicName",
    ("SQS.Queue", "QueueName"): "QueueName",
    ("Glue.Connection", "Name"): "ConnectionInput.Name",
    ("Glue.Database", "Name"): "DatabaseInput.Name",
    ("Glue.Table", "Name"): "TableInput.Name",
    ("ECS.Service", "Name"): "ServiceName",
}


# Ref semantics are documented on each resource's CloudFormation Return values page.
# Composite/conditional/undocumented returns are deliberately not inferred from primaryIdentifier.
REF_ATTRIBUTES = {
    "S3.Bucket": "BucketName",
    "Logs.LogGroup": "LogGroupName",
    "SQS.Queue": "QueueUrl",
    "SNS.Topic": "TopicArn",
    "KMS.Key": "KeyId",
    "KMS.Alias": "AliasName",
    "IAM.Role": "RoleName",
    "IAM.InstanceProfile": "InstanceProfileName",
    "IAM.ManagedPolicy": "PolicyArn",
    "IAM.User": "UserName",
    "EC2.Subnet": "SubnetId",
    "EC2.VPC": "VpcId",
    "EC2.RouteTable": "RouteTableId",
    "EC2.Instance": "InstanceId",
    "EC2.FlowLog": "Id",
    "EC2.InternetGateway": "InternetGatewayId",
    "EC2.LaunchTemplate": "LaunchTemplateId",
    "EC2.NatGateway": "NatGatewayId",
    "EC2.VPCEndpoint": "Id",
    "EC2.TransitGateway": "Id",
    "CodeBuild.Project": "Name",
    "Lambda.Function": "FunctionName",
    "Lambda.EventSourceMapping": "Id",
    "CodeCommit.Repository": "RepositoryId",
    "CodePipeline.Pipeline": "Name",
    "Route53.HostedZone": "Id",
    "Glue.Connection": "Name",
    "Glue.SecurityConfiguration": "Name",
    "Glue.Job": "Name",
    "Glue.Crawler": "Name",
    "Glue.Database": "Name",
    "Glue.Table": "Name",
    "Glue.Catalog": "ResourceArn",
    "Athena.WorkGroup": "Name",
    "SecretsManager.Secret": "Id",
    "CloudTrail.Trail": "TrailName",
    "CloudWatch.Alarm": "AlarmName",
    "CloudWatch.Dashboard": "DashboardName",
    "ECR.Repository": "RepositoryName",
    "Events.Rule": "RuleName",
    "Events.EventBus": "Name",
    "DynamoDB.Table": "TableName",
    "DynamoDB.GlobalTable": "TableName",
    "ECS.Cluster": "ClusterName",
    "ECS.CapacityProvider": "Name",
    "ECS.Service": "ServiceArn",
    "ECS.TaskDefinition": "TaskDefinitionArn",
    "ElasticLoadBalancingV2.Listener": "ListenerArn",
    "ElasticLoadBalancingV2.ListenerRule": "RuleArn",
    "ElasticLoadBalancingV2.LoadBalancer": "LoadBalancerArn",
    "ElasticLoadBalancingV2.TargetGroup": "TargetGroupArn",
    "KinesisFirehose.DeliveryStream": "DeliveryStreamName",
    "RDS.DBCluster": "DBClusterIdentifier",
    "RDS.DBInstance": "DBInstanceIdentifier",
    "RDS.DBClusterParameterGroup": "DBClusterParameterGroupName",
    "RDS.DBParameterGroup": "DBParameterGroupName",
    "RDS.DBProxy": "DBProxyName",
    "RDS.DBProxyEndpoint": "DBProxyEndpointName",
    "RDS.DBSubnetGroup": "DBSubnetGroupName",
    "RDS.OptionGroup": "OptionGroupName",
    "SageMaker.Domain": "DomainId",
    "Scheduler.Schedule": "Name",
    "SecurityHub.Hub": "ARN",
    "ApiGateway.ApiKey": "APIKeyId",
    "ApiGateway.Authorizer": "AuthorizerId",
    "ApiGateway.Deployment": "DeploymentId",
    "ApiGateway.DomainName": "DomainName",
    "ApiGateway.Model": "Name",
    "ApiGateway.RequestValidator": "RequestValidatorId",
    "ApiGateway.Resource": "ResourceId",
    "ApiGateway.RestApi": "RestApiId",
    "ApiGateway.Stage": "StageName",
    "ApiGateway.UsagePlan": "Id",
    "ApiGateway.UsagePlanKey": "Id",
    "ApiGateway.VpcLink": "VpcLinkId",
    "ApiGatewayV2.Api": "ApiId",
    "ApiGatewayV2.ApiMapping": "ApiMappingId",
    "ApiGatewayV2.Authorizer": "AuthorizerId",
    "ApiGatewayV2.Deployment": "DeploymentId",
    "ApiGatewayV2.DomainName": "DomainName",
    "ApiGatewayV2.Integration": "IntegrationId",
    "ApiGatewayV2.IntegrationResponse": "IntegrationResponseId",
    "ApiGatewayV2.Route": "RouteId",
    "ApiGatewayV2.RouteResponse": "RouteResponseId",
    "ApiGatewayV2.Stage": "StageName",
    "ApiGatewayV2.VpcLink": "VpcLinkId",
    "AutoScaling.AutoScalingGroup": "AutoScalingGroupName",
    "AutoScaling.LifecycleHook": "LifecycleHookName",
    "AutoScaling.ScalingPolicy": "Arn",
    "AutoScaling.ScheduledAction": "ScheduledActionName",
    "CertificateManager.Certificate": "CertificateArn",
    "CloudFront.CachePolicy": "Id",
    "CloudFront.Distribution": "Id",
    "CloudFront.OriginRequestPolicy": "Id",
    "CloudFront.ResponseHeadersPolicy": "Id",
    "Config.ConfigRule": "ConfigRuleName",
    "Config.ConfigurationRecorder": "Name",
    "Config.DeliveryChannel": "Name",
    "DataZone.Domain": "Id",
    "EC2.EIP": "PublicIp",
    "EC2.SubnetRouteTableAssociation": "Id",
    "EC2.TransitGatewayRouteTable": "TransitGatewayRouteTableId",
    "EC2.TransitGatewayVpcAttachment": "Id",
    "EC2.VPCBlockPublicAccessExclusion": "ExclusionId",
    "EC2.VPCBlockPublicAccessOptions": "AccountId",
    "FMS.Policy": "Id",
    "GuardDuty.Detector": "Id",
    "Logs.ResourcePolicy": "PolicyName",
    "Logs.SubscriptionFilter": "FilterName",
    "Macie.Session": "AwsAccountId",
    "NetworkFirewall.Firewall": "FirewallArn",
    "NetworkFirewall.FirewallPolicy": "FirewallPolicyArn",
    "NetworkFirewall.LoggingConfiguration": "FirewallArn",
    "NetworkFirewall.RuleGroup": "RuleGroupArn",
    "Organizations.Policy": "Id",
    "RDS.DBProxyTargetGroup": "TargetGroupArn",
    "Route53Resolver.ResolverRuleAssociation": "ResolverRuleAssociationId",
    "SSM.MaintenanceWindow": "WindowId",
    "SSM.MaintenanceWindowTarget": "WindowTargetId",
    "SSM.MaintenanceWindowTask": "WindowTaskId",
    "SSM.PatchBaseline": "Id",
    "SecretsManager.ResourcePolicy": "Id",
    "SecretsManager.RotationSchedule": "Id",
    "SecurityHub.FindingAggregator": "FindingAggregatorArn",
    "WAFv2.LoggingConfiguration": "ResourceArn",
    "Route53.RecordSet": "Name",
    "EC2.TransitGatewayRouteTablePropagation": "TransitGatewayRouteTableId",
    "ECS.ClusterCapacityProviderAssociations": "ClusterName",
    # Ref is an opaque Framework attribute, never GetAtt or an alias for one component.
    "ApiGateway.Method": "Ref",
    "EC2.Route": "Ref",
    "EC2.SecurityGroupEgress": "Ref",
    "EC2.TransitGatewayRoute": "Ref",
    "EC2.TransitGatewayRouteTableAssociation": "Ref",
    "EC2.VPCGatewayAttachment": "Ref",
    "Lambda.EventInvokeConfig": "Ref",
    "SNS.Subscription": "Ref",
    "DataZone.Connection": "Ref",
    "DataZone.DataSource": "Ref",
    "DataZone.Environment": "Ref",
    "DataZone.EnvironmentBlueprintConfiguration": "Ref",
    "DataZone.EnvironmentProfile": "Ref",
    "DataZone.Owner": "Ref",
    "DataZone.Project": "Ref",
    "DataZone.ProjectMembership": "Ref",
    "DataZone.ProjectProfile": "Ref",
    "LakeFormation.PrincipalPermissions": "Ref",
    "SSO.Assignment": "Ref",
    "SSO.PermissionSet": "Ref",
    "SageMaker.Space": "Ref",
    "SageMaker.UserProfile": "Ref",
    "WAFv2.IPSet": "Ref",
    "WAFv2.RuleGroup": "Ref",
    "WAFv2.WebACL": "Ref",
    "WAFv2.WebACLAssociation": "Ref",
}
# Documented GetAtt attributes omitted from the pinned schema readOnlyProperties.
GETATT_ATTRIBUTES = {
    "SNS.Topic": {"TopicName"},
    "SQS.Queue": {"QueueName"},
    "Events.EventBus": {"Name"},
    "Config.ConfigurationRecorder": {"ResourceARN"},
    "EC2.SecurityGroup": {"VpcId"},
    "EC2.Subnet": {
        "AvailabilityZone",
        "AvailabilityZoneId",
        "CidrBlock",
        "OutpostArn",
        "VpcId",
    },
    "EC2.VPC": {"CidrBlock"},
    "ElasticLoadBalancingV2.LoadBalancer": {"SecurityGroups"},
    "NetworkFirewall.Firewall": {"NumberOfAssociations"},
    "RDS.DBInstance": {"DBSystemId"},
    "RDS.DBParameterGroup": {"DBParameterGroupName"},
    "Route53Resolver.ResolverEndpoint": {"Direction", "Name"},
    "Route53Resolver.ResolverRule": {
        "DomainName",
        "Name",
        "ResolverEndpointId",
        "TargetIps",
    },
    "Route53Resolver.ResolverRuleAssociation": {"Name", "ResolverRuleId", "VPCId"},
}
# Documented output types absent from the pinned provider schema.
RETURN_TYPES = {
    ("Config.ConfigurationRecorder", "ResourceARN"): "string",
    ("NetworkFirewall.Firewall", "NumberOfAssociations"): "integer",
}


def getatt_attribute(kind, attribute, schema):
    return attribute in GETATT_ATTRIBUTES.get(
        kind, ()
    ) or "/properties/" + attribute.replace(".", "/") in schema.get(
        "readOnlyProperties", ()
    )


# Model Arn is a semantic alias only; Fn::GetAtt must still use its formal attribute.
ARN_ATTRIBUTES = {
    "KMS.Alias": "AliasArn",
    "SNS.Topic": "TopicArn",
    "IAM.ManagedPolicy": "PolicyArn",
    "SecretsManager.Secret": "Id",
    "ECS.Service": "ServiceArn",
    "ECS.TaskDefinition": "TaskDefinitionArn",
    "ElasticLoadBalancingV2.Listener": "ListenerArn",
    "ElasticLoadBalancingV2.ListenerRule": "RuleArn",
    "ElasticLoadBalancingV2.LoadBalancer": "LoadBalancerArn",
    "ElasticLoadBalancingV2.TargetGroup": "TargetGroupArn",
    "RDS.DBCluster": "DBClusterArn",
    "RDS.DBInstance": "DBInstanceArn",
    "RDS.DBParameterGroup": "DBParameterGroupArn",
    "RDS.DBSubnetGroup": "DBSubnetGroupArn",
    "RDS.DBProxy": "DBProxyArn",
    "RDS.DBProxyEndpoint": "DBProxyEndpointArn",
    "CloudFront.Function": "FunctionARN",
    "SageMaker.Domain": "DomainArn",
    "SageMaker.Space": "SpaceArn",
    "SageMaker.UserProfile": "UserProfileArn",
    "SecurityHub.Hub": "ARN",
    "Glue.Catalog": "ResourceArn",
    "NetworkFirewall.Firewall": "FirewallArn",
    "NetworkFirewall.FirewallPolicy": "FirewallPolicyArn",
    "NetworkFirewall.RuleGroup": "RuleGroupArn",
    "ApiGateway.DomainName": "DomainNameArn",
    "ApiGatewayV2.DomainName": "DomainNameArn",
    "AutoScaling.AutoScalingGroup": "AutoScalingGroupARN",
    "CertificateManager.Certificate": "CertificateArn",
    "EC2.TransitGateway": "TransitGatewayArn",
    "Lambda.EventSourceMapping": "EventSourceMappingArn",
    "RDS.DBProxyTargetGroup": "TargetGroupArn",
    "SecurityHub.FindingAggregator": "FindingAggregatorArn",
    "SSO.PermissionSet": "PermissionSetArn",
    "Config.ConfigurationRecorder": "ResourceARN",
    "NetworkFirewall.LoggingConfiguration": "FirewallArn",
    "WAFv2.LoggingConfiguration": "ResourceArn",
    "SecretsManager.ResourcePolicy": "Id",
    "SecretsManager.RotationSchedule": "Id",
}


SUBNET_LIST_PROPERTIES = {
    "ApiGatewayV2.VpcLink.SubnetIds[]",
    "CodeBuild.Project.VpcConfig.Subnets",
    "EC2.TransitGatewayVpcAttachment.SubnetIds",
    "EC2.VPCEndpoint.SubnetIds",
    "ECS.CapacityProvider.ManagedInstancesProvider.InstanceLaunchTemplate.NetworkConfiguration.Subnets[]",
    "ECS.Service.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
    "ElasticLoadBalancingV2.LoadBalancer.Subnets[]",
    "Lambda.Function.VpcConfig.SubnetIds",
    "MWAA.Environment.NetworkConfiguration.SubnetIds",
    "QuickSight.VPCConnection.SubnetIds",
    "RDS.DBProxy.VpcSubnetIds[]",
    "RDS.DBProxyEndpoint.VpcSubnetIds[]",
    "RDS.DBSubnetGroup.SubnetIds[]",
    "SageMaker.Domain.SubnetIds[]",
    "Scheduler.Schedule.Target.EcsParameters.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
    "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds",
}


LINKED_LIST_PROPERTIES = dict.fromkeys(SUBNET_LIST_PROPERTIES, "EC2.Subnet") | {
    "CodeBuild.Project.VpcConfig.SecurityGroupIds": "EC2.SecurityGroup",
}


S3_KMS_MASTER_KEY_ID = (
    "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]"
    ".ServerSideEncryptionByDefault.KMSMasterKeyID"
)

# Documented identifier formats absent from the provider schema's string pattern.
# Each entry is a property contract, not permission to erase reference attributes.
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-kms-alias.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cloudtrail-trail.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-athena-workgroup-encryptionconfiguration.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecr-repository-encryptionconfiguration.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-s3-bucket-serversideencryptionbydefault.html
REFERENCE_FORMS = {
    "DynamoDB.Table.SSESpecification.KMSMasterKeyId": {"KeyId", "Arn", "AliasName"},
    "KMS.Alias.TargetKeyId": {"KeyId", "Arn"},
    "CloudTrail.Trail.KMSKeyId": {"KeyId", "Arn", "AliasName"},
    # Framework design/comparison policy: this property requires a key ARN.
    "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": {
        "Arn"
    },
    "ECR.Repository.EncryptionConfiguration.KmsKey": {"KeyId", "Arn", "AliasName"},
    "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID": {
        "KeyId",
        "Arn",
        "AliasName",
    },
    # aws-resource-codecommit-repository.html; aws-properties-ec2-instance-ebs.html
    "CodeCommit.Repository.KmsKeyId": {"KeyId", "Arn", "AliasName"},
    "EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId": {"KeyId", "Arn", "AliasName"},
    # aws-properties-codepipeline-pipeline-encryptionkey.html: alias ARN, not alias name.
    "CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id": {"KeyId", "Arn"},
    # aws-resource-mwaa-environment.html; aws-resource-secretsmanager-secret.html
    "MWAA.Environment.KmsKey": {"KeyId", "Arn", "AliasName"},
    "SecretsManager.Secret.KmsKeyId": {"KeyId", "Arn", "AliasName"},
    # aws-resource-glue-job.html; aws-resource-lambda-permission.html
    "Glue.Job.Role": {"RoleName", "Arn"},
    "Glue.Crawler.Role": {"RoleName", "Arn"},
    "ECS.TaskDefinition.TaskRoleArn": {"RoleName", "Arn"},
    "ECS.Service.Cluster": {"ClusterName", "Arn"},
    "ECS.Service.Role": {"RoleName", "Arn"},
    "CodeBuild.Project.EncryptionKey": {"Arn", "AliasName"},
    "S3.Bucket.ReplicationConfiguration.Rules[].Destination.EncryptionConfiguration.ReplicaKmsKeyID": {
        "Arn"
    },
    "Lambda.Permission.FunctionName": {"FunctionName", "Arn"},
    "Lambda.EventSourceMapping.FunctionName": {"FunctionName", "Arn"},
    # aws-resource-secretsmanager-rotationschedule.html: Ref returns the secret ARN (Id).
    "SecretsManager.RotationSchedule.SecretId": {"Id", "Name"},
    "SecretsManager.ResourcePolicy.SecretId": {"Id", "Name"},
    "RDS.DBCluster.PerformanceInsightsKmsKeyId": {"KeyId", "Arn", "AliasName"},
}

# Explicit receiving-property contracts: target type(s) and the Model link attribute.
# Sources are the named resource/property pages in the CloudFormation TemplateReference.
# No identifier suffix or primaryIdentifier determines a receiving property's meaning.
REFERENCE_PROPERTIES = {
    "S3.Bucket.NotificationConfiguration.LambdaConfigurations[].Function": (
        "Lambda.Function",
        "Arn",
    ),
    "S3.Bucket.NotificationConfiguration.QueueConfigurations[].Queue": (
        "SQS.Queue",
        "Arn",
    ),
    "S3.Bucket.NotificationConfiguration.TopicConfigurations[].Topic": (
        "SNS.Topic",
        "Arn",
    ),
    "SQS.Queue.RedrivePolicy.deadLetterTargetArn": ("SQS.Queue", "Arn"),
    "SNS.Subscription.RedrivePolicy.deadLetterTargetArn": ("SQS.Queue", "Arn"),
    "CloudTrail.Trail.S3BucketName": ("S3.Bucket", "BucketName"),
    "CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName": (
        "Logs.LogGroup",
        "LogGroupName",
    ),
    "CodeBuild.Project.VpcConfig.VpcId": ("EC2.VPC", "VpcId"),
    "CodeBuild.Project.VpcConfig.Subnets[]": ("EC2.Subnet", "SubnetId"),
    "CodeBuild.Project.VpcConfig.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "CodeCommit.Repository.KmsKeyId": (("KMS.Key", "KMS.Alias"), None),
    "CodePipeline.Pipeline.ArtifactStore.Location": ("S3.Bucket", "BucketName"),
    "CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id": (
        ("KMS.Key", "KMS.Alias"),
        None,
    ),
    "EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId": (("KMS.Key", "KMS.Alias"), None),
    "EC2.Instance.IamInstanceProfile": ("IAM.InstanceProfile", "InstanceProfileName"),
    "EC2.Instance.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "EC2.Instance.SubnetId": ("EC2.Subnet", "SubnetId"),
    "EC2.SecurityGroup.SecurityGroupIngress[].SourceSecurityGroupId": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "ECS.Service.NetworkConfiguration.AwsvpcConfiguration.SecurityGroups[]": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "ElasticLoadBalancingV2.LoadBalancer.SecurityGroups[]": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "ElasticLoadBalancingV2.TargetGroup.VpcId": ("EC2.VPC", "VpcId"),
    "RDS.DBInstance.VPCSecurityGroups[]": ("EC2.SecurityGroup", "GroupId"),
    "RDS.DBCluster.VpcSecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "RDS.DBProxy.VpcSecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "RDS.DBProxyEndpoint.VpcSecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "ECS.CapacityProvider.ManagedInstancesProvider.InstanceLaunchTemplate.NetworkConfiguration.SecurityGroups[]": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "EC2.SecurityGroup.VpcId": ("EC2.VPC", "VpcId"),
    "EC2.SecurityGroup.SecurityGroupEgress[].DestinationSecurityGroupId": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "EC2.SecurityGroupIngress.GroupId": ("EC2.SecurityGroup", "GroupId"),
    "EC2.SecurityGroupIngress.SourceSecurityGroupId": ("EC2.SecurityGroup", "GroupId"),
    "EC2.SecurityGroupEgress.GroupId": ("EC2.SecurityGroup", "GroupId"),
    "EC2.SecurityGroupEgress.DestinationSecurityGroupId": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "EC2.Subnet.VpcId": ("EC2.VPC", "VpcId"),
    "EC2.TransitGatewayVpcAttachment.VpcId": ("EC2.VPC", "VpcId"),
    "EC2.SubnetRouteTableAssociation.RouteTableId": ("EC2.RouteTable", "RouteTableId"),
    "EC2.RouteTable.VpcId": ("EC2.VPC", "VpcId"),
    "EC2.FlowLog.LogGroupName": ("Logs.LogGroup", "LogGroupName"),
    "EC2.VPCEndpoint.RouteTableIds[]": ("EC2.RouteTable", "RouteTableId"),
    "EC2.VPCEndpoint.VpcId": ("EC2.VPC", "VpcId"),
    "EC2.VPCEndpoint.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "EC2.VPCEndpoint.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    "Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList[]": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SubnetId": (
        "EC2.Subnet",
        "SubnetId",
    ),
    "Glue.Catalog.FederatedCatalog.ConnectionName": ("Glue.Connection", "Name"),
    "Glue.Job.Connections.Connections[]": ("Glue.Connection", "Name"),
    "Glue.Job.Role": ("IAM.Role", "RoleName"),
    "Glue.Job.SecurityConfiguration": ("Glue.SecurityConfiguration", "Name"),
    "GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName": (
        "S3.Bucket",
        "BucketName",
    ),
    "IAM.ManagedPolicy.Roles[]": ("IAM.Role", "RoleName"),
    "IAM.InstanceProfile.Roles[]": ("IAM.Role", "RoleName"),
    "Lambda.Function.Code.S3Bucket": ("S3.Bucket", "BucketName"),
    "Lambda.Function.LoggingConfig.LogGroup": ("Logs.LogGroup", "LogGroupName"),
    "Lambda.Function.VpcConfig.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "Lambda.Function.VpcConfig.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    "Lambda.Permission.FunctionName": ("Lambda.Function", "FunctionName"),
    "MWAA.Environment.KmsKey": (("KMS.Key", "KMS.Alias"), None),
    "MWAA.Environment.NetworkConfiguration.SecurityGroupIds[]": (
        "EC2.SecurityGroup",
        "GroupId",
    ),
    "MWAA.Environment.NetworkConfiguration.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    "QuickSight.DataSource.Permissions[].Principal": ("QuickSight.Group", "Arn"),
    "QuickSight.VPCConnection.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    "QuickSight.VPCConnection.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    "Route53.HostedZone.VPCs[].VPCId": ("EC2.VPC", "VpcId"),
    "Route53.RecordSet.HostedZoneId": ("Route53.HostedZone", "Id"),
    "SecretsManager.Secret.KmsKeyId": (("KMS.Key", "KMS.Alias"), None),
    "SecretsManager.RotationSchedule.SecretId": ("SecretsManager.Secret", "Id"),
    "SQS.QueuePolicy.Queues[]": ("SQS.Queue", "QueueUrl"),
}


# ARN receiving forms are explicit, not inferred from an Id/Arn suffix.
IMPORT_PROPERTIES = {
    **REFERENCE_PROPERTIES,
    "ECS.Service.CapacityProviderStrategy[].CapacityProvider": (
        "ECS.CapacityProvider",
        "Name",
    ),
    "ECS.Service.TaskDefinition": ("ECS.TaskDefinition", "Arn"),
    "ECS.Service.Cluster": ("ECS.Cluster", "ClusterName"),
    "ECS.Service.LoadBalancers[].TargetGroupArn": (
        "ElasticLoadBalancingV2.TargetGroup",
        "Arn",
    ),
    "EC2.VPCBlockPublicAccessExclusion.VpcId": ("EC2.VPC", "VpcId"),
    "EC2.VPCBlockPublicAccessExclusion.SubnetId": ("EC2.Subnet", "SubnetId"),
    "EC2.VPCGatewayAttachment.VpcId": ("EC2.VPC", "VpcId"),
    "Route53Resolver.ResolverRuleAssociation.VPCId": ("EC2.VPC", "VpcId"),
    "Route53Resolver.ResolverEndpoint.IpAddresses[].SubnetId": (
        "EC2.Subnet",
        "SubnetId",
    ),
    "EC2.Instance.NetworkInterfaces[].SubnetId": ("EC2.Subnet", "SubnetId"),
    "EC2.LaunchTemplate.LaunchTemplateData.NetworkInterfaces[].SubnetId": (
        "EC2.Subnet",
        "SubnetId",
    ),
    "EC2.NatGateway.SubnetId": ("EC2.Subnet", "SubnetId"),
    "EC2.SubnetRouteTableAssociation.SubnetId": ("EC2.Subnet", "SubnetId"),
    "NetworkFirewall.Firewall.SubnetMappings[].SubnetId": ("EC2.Subnet", "SubnetId"),
    "ElasticLoadBalancingV2.LoadBalancer.SubnetMappings[].SubnetId": (
        "EC2.Subnet",
        "SubnetId",
    ),
    "MWAA.Environment.ExecutionRoleArn": ("IAM.Role", "Arn"),
    "MWAA.Environment.SourceBucketArn": ("S3.Bucket", "Arn"),
    "RDS.DBProxy.Auth[].SecretArn": ("SecretsManager.Secret", "Arn"),
    "RDS.DBProxy.RoleArn": ("IAM.Role", "Arn"),
    "Scheduler.Schedule.Target.DeadLetterConfig.Arn": ("SQS.Queue", "Arn"),
    "ECS.Cluster.Configuration.ExecuteCommandConfiguration.LogConfiguration.S3BucketName": (
        "S3.Bucket",
        "BucketName",
    ),
    "CloudFront.Distribution.DistributionConfig.Logging.Bucket": (
        "S3.Bucket",
        "DomainName",
    ),
    "S3.BucketPolicy.Bucket": ("S3.Bucket", "BucketName"),
    "QuickSight.DataSource.DataSourceParameters.S3Parameters.ManifestFileLocation.Bucket": (
        "S3.Bucket",
        "BucketName",
    ),
    "ApiGateway.RestApi.BodyS3Location.Bucket": ("S3.Bucket", "BucketName"),
    "ApiGatewayV2.Api.BodyS3Location.Bucket": ("S3.Bucket", "BucketName"),
    "CodeCommit.Repository.Code.S3.Bucket": ("S3.Bucket", "BucketName"),
    "CodePipeline.Pipeline.ArtifactStores[].ArtifactStore.Location": (
        "S3.Bucket",
        "BucketName",
    ),
    "Config.DeliveryChannel.S3BucketName": ("S3.Bucket", "BucketName"),
    "DynamoDB.Table.ImportSourceSpecification.S3BucketSource.S3Bucket": (
        "S3.Bucket",
        "BucketName",
    ),
    "ApiGatewayV2.Integration.ConnectionId": ("ApiGatewayV2.VpcLink", "VpcLinkId"),
    "AutoScaling.AutoScalingGroup.ServiceLinkedRoleARN": ("IAM.Role", "Arn"),
    "CodePipeline.Pipeline.Stages[].Actions[].RoleArn": ("IAM.Role", "Arn"),
    "ECS.Service.DeploymentConfiguration.LifecycleHooks[].RoleArn": ("IAM.Role", "Arn"),
    "ECS.Service.LoadBalancers[].AdvancedConfiguration.RoleArn": ("IAM.Role", "Arn"),
    "ECS.Service.Role": ("IAM.Role", "RoleName"),
    "RDS.DBCluster.AssociatedRoles[].RoleArn": ("IAM.Role", "Arn"),
    "RDS.DBInstance.AssociatedRoles[].RoleArn": ("IAM.Role", "Arn"),
    "SSM.MaintenanceWindowTask.ServiceRoleArn": ("IAM.Role", "Arn"),
    "SageMaker.Domain.DomainSettings.RStudioServerProDomainSettings.DomainExecutionRoleArn": (
        "IAM.Role",
        "Arn",
    ),
    "AutoScaling.AutoScalingGroup.LifecycleHookSpecificationList[].RoleARN": (
        "IAM.Role",
        "Arn",
    ),
    "AutoScaling.LifecycleHook.RoleARN": ("IAM.Role", "Arn"),
    "DataZone.Connection.Props.IamProperties.RoleArn": ("IAM.Role", "Arn"),
    "EC2.FlowLog.DeliverCrossAccountRole": ("IAM.Role", "Arn"),
    "EC2.FlowLog.DeliverLogsPermissionArn": ("IAM.Role", "Arn"),
    "EC2.Route.VpcEndpointId": ("EC2.VPCEndpoint", "Id"),
    "ECS.ClusterCapacityProviderAssociations.Cluster": ("ECS.Cluster", "ClusterName"),
    "Glue.Crawler.Targets.JdbcTargets[].ConnectionName": ("Glue.Connection", "Name"),
    "Glue.Crawler.Targets.S3Targets[].ConnectionName": ("Glue.Connection", "Name"),
    "LakeFormation.PrincipalPermissions.Resource.Database.Name": (
        "Glue.Database",
        "Name",
    ),
    "LakeFormation.PrincipalPermissions.Resource.Table.DatabaseName": (
        "Glue.Database",
        "Name",
    ),
    "LakeFormation.PrincipalPermissions.Resource.TableWithColumns.DatabaseName": (
        "Glue.Database",
        "Name",
    ),
    "Logs.SubscriptionFilter.RoleArn": ("IAM.Role", "Arn"),
    "RDS.DBCluster.DBInstanceParameterGroupName": (
        "RDS.DBParameterGroup",
        "DBParameterGroupName",
    ),
    "RDS.DBCluster.DomainIAMRoleName": ("IAM.Role", "RoleName"),
    "RDS.DBInstance.DomainIAMRoleName": ("IAM.Role", "RoleName"),
    "RDS.DBCluster.MonitoringRoleArn": ("IAM.Role", "Arn"),
    "RDS.DBInstance.MonitoringRoleArn": ("IAM.Role", "Arn"),
    "S3.Bucket.LoggingConfiguration.DestinationBucketName": ("S3.Bucket", "BucketName"),
    "SecretsManager.ResourcePolicy.SecretId": ("SecretsManager.Secret", "Id"),
    "RDS.DBCluster.PerformanceInsightsKmsKeyId": (("KMS.Key", "KMS.Alias"), None),
    "SecretsManager.RotationSchedule.ExternalSecretRotationRoleArn": (
        "IAM.Role",
        "Arn",
    ),
    "SecretsManager.RotationSchedule.HostedRotationLambda.MasterSecretArn": (
        "SecretsManager.Secret",
        "Arn",
    ),
    "SecretsManager.RotationSchedule.HostedRotationLambda.SuperuserSecretArn": (
        "SecretsManager.Secret",
        "Arn",
    ),
    "Config.DeliveryChannel.SnsTopicARN": ("SNS.Topic", "Arn"),
    "QuickSight.DataSource.Credentials.SecretArn": ("SecretsManager.Secret", "Arn"),
    "RDS.DBInstance.DomainAuthSecretArn": ("SecretsManager.Secret", "Arn"),
    "Glue.Crawler.Targets.S3Targets[].DlqEventQueueArn": ("SQS.Queue", "Arn"),
    "RDS.DBCluster.DBClusterParameterGroupName": (
        "RDS.DBClusterParameterGroup",
        "DBClusterParameterGroupName",
    ),
    "RDS.DBInstance.DBParameterGroupName": (
        "RDS.DBParameterGroup",
        "DBParameterGroupName",
    ),
    "RDS.DBCluster.DBSubnetGroupName": ("RDS.DBSubnetGroup", "DBSubnetGroupName"),
    "ECS.Service.LoadBalancers[].AdvancedConfiguration.ProductionListenerRule": (
        ("ElasticLoadBalancingV2.Listener", "ElasticLoadBalancingV2.ListenerRule"),
        "Arn",
    ),
    "ECS.Service.LoadBalancers[].AdvancedConfiguration.TestListenerRule": (
        ("ElasticLoadBalancingV2.Listener", "ElasticLoadBalancingV2.ListenerRule"),
        "Arn",
    ),
    "ECS.Service.LoadBalancers[].AdvancedConfiguration.AlternateTargetGroupArn": (
        "ElasticLoadBalancingV2.TargetGroup",
        "Arn",
    ),
    "CloudTrail.Trail.SnsTopicName": ("SNS.Topic", "TopicName"),
    "SNS.Subscription.TopicArn": ("SNS.Topic", "Arn"),
    "SNS.Subscription.SubscriptionRoleArn": ("IAM.Role", "Arn"),
    "Glue.Connection.ConnectionInput.AuthenticationConfiguration.SecretArn": (
        "SecretsManager.Secret",
        "Arn",
    ),
    "Glue.Database.DatabaseInput.FederatedDatabase.ConnectionName": (
        "Glue.Connection",
        "Name",
    ),
    "Glue.Crawler.CrawlerSecurityConfiguration": ("Glue.SecurityConfiguration", "Name"),
    "Glue.Crawler.DatabaseName": ("Glue.Database", "Name"),
    "Glue.Crawler.Role": ("IAM.Role", "RoleName"),
    "RDS.DBInstance.DBSubnetGroupName": ("RDS.DBSubnetGroup", "DBSubnetGroupName"),
    "CodeBuild.Project.EncryptionKey": (("KMS.Key", "KMS.Alias"), None),
    "S3.Bucket.ReplicationConfiguration.Rules[].Destination.EncryptionConfiguration.ReplicaKmsKeyID": (
        ("KMS.Key", "KMS.Alias"),
        None,
    ),
    "ApiGatewayV2.Stage.AccessLogSettings.DestinationArn": ("Logs.LogGroup", "Arn"),
    "S3.Bucket.ReplicationConfiguration.Rules[].Destination.Bucket": (
        "S3.Bucket",
        "Arn",
    ),
    "SageMaker.Domain.VpcId": ("EC2.VPC", "VpcId"),
    "NetworkFirewall.Firewall.VpcId": ("EC2.VPC", "VpcId"),
    "ECS.TaskDefinition.TaskRoleArn": ("IAM.Role", "Arn"),
    "ECS.TaskDefinition.ExecutionRoleArn": ("IAM.Role", "Arn"),
    "Route53.HostedZone.QueryLoggingConfig.CloudWatchLogsLogGroupArn": (
        "Logs.LogGroup",
        "Arn",
    ),
    "Scheduler.Schedule.Target.RoleArn": ("IAM.Role", "Arn"),
    "S3.Bucket.ReplicationConfiguration.Role": ("IAM.Role", "Arn"),
    "DynamoDB.Table.SSESpecification.KMSMasterKeyId": (("KMS.Key", "KMS.Alias"), None),
    "KMS.Alias.TargetKeyId": (("KMS.Key",), None),
    "CloudTrail.Trail.KMSKeyId": (("KMS.Key", "KMS.Alias"), None),
    "CloudTrail.Trail.CloudWatchLogsRoleArn": ("IAM.Role", "Arn"),
    "CloudTrail.Trail.CloudWatchLogsLogGroupArn": ("Logs.LogGroup", "Arn"),
    "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": (
        ("KMS.Key", "KMS.Alias"),
        None,
    ),
    "ECR.Repository.EncryptionConfiguration.KmsKey": (("KMS.Key", "KMS.Alias"), None),
    "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID": (
        ("KMS.Key", "KMS.Alias"),
        None,
    ),
    "Config.ConfigurationRecorder.RoleARN": ("IAM.Role", "Arn"),
    # aws-resource-guardduty-malwareprotectionplan.html: Role requires an IAM role ARN.
    "GuardDuty.MalwareProtectionPlan.Role": ("IAM.Role", "Arn"),
    "KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN": (
        "KMS.Key",
        "Arn",
    ),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN": (
        "S3.Bucket",
        "Arn",
    ),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN": (
        "IAM.Role",
        "Arn",
    ),
    "KinesisFirehose.DeliveryStream.ExtendedS3DestinationConfiguration.BucketARN": (
        "S3.Bucket",
        "Arn",
    ),
    "KinesisFirehose.DeliveryStream.ExtendedS3DestinationConfiguration.RoleARN": (
        "IAM.Role",
        "Arn",
    ),
    "LakeFormation.Resource.ResourceArn": (("Glue.Connection", "S3.Bucket"), "Arn"),
    "LakeFormation.Resource.RoleArn": ("IAM.Role", "Arn"),
    "Lambda.EventSourceMapping.FunctionName": ("Lambda.Function", "FunctionName"),
    "Lambda.EventInvokeConfig.FunctionName": ("Lambda.Function", "FunctionName"),
    "Lambda.Function.Role": ("IAM.Role", "Arn"),
    "Lambda.Function.KmsKeyArn": ("KMS.Key", "Arn"),
    "CodeBuild.Project.ServiceRole": ("IAM.Role", "Arn"),
    "CodePipeline.Pipeline.RoleArn": ("IAM.Role", "Arn"),
    "Logs.LogGroup.KmsKeyId": (("KMS.Key", "KMS.Alias"), "Arn"),
    "Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn": (
        ("KMS.Key", "KMS.Alias"),
        "Arn",
    ),
    "Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn": (
        ("KMS.Key", "KMS.Alias"),
        "Arn",
    ),
}
IMPORT_PROPERTIES.update(
    {
        prop: (kind, {"EC2.Subnet": "SubnetId", "EC2.SecurityGroup": "GroupId"}[kind])
        for prop, kind in LINKED_LIST_PROPERTIES.items()
    }
)

# ARN formats: CloudFormation Return values and AWS Service Authorization resource tables.
# https://docs.aws.amazon.com/service-authorization/latest/reference/list_rds.html
# https://docs.aws.amazon.com/service-authorization/latest/reference/list_ecs.html
# https://docs.aws.amazon.com/service-authorization/latest/reference/list_quicksight.html
# https://docs.aws.amazon.com/service-authorization/latest/reference/list_sagemaker.html
# https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudwatch.html
# https://docs.aws.amazon.com/service-authorization/latest/reference/list_scheduler.html
# https://docs.aws.amazon.com/glue/latest/dg/glue-specifying-resource-arns.html
# https://docs.aws.amazon.com/athena/latest/ug/workgroups-access.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-networkfirewall-firewall.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-networkfirewall-firewallpolicy.html
# AWS documented ARN identities. Parsing and transient projection share these shapes.
# S3 bucket names are global. Regional/account-scoped identities require context.
ARN_SHAPES = {
    "S3.Bucket": (
        "BucketName",
        "arn:{partition}:s3:::{id}",
        {"id": r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"},
    ),
    "KMS.Key": (
        "KeyId",
        "arn:{partition}:kms:{region}:{account}:key/{id}",
        {
            "id": r"(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})"
        },
    ),
    "KMS.Alias": (
        "AliasName",
        "arn:{partition}:kms:{region}:{account}:{id}",
        {"id": r"alias/[A-Za-z0-9:/_-]+"},
    ),
    "Lambda.Function": (
        "FunctionName",
        "arn:{partition}:lambda:{region}:{account}:function:{id}",
        {"id": r"[A-Za-z0-9_-]{1,64}"},
    ),
    "IAM.Role": (
        {"RoleName": "id", "Path": "path"},
        "arn:{partition}:iam::{account}:role{path}{id}",
        {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,64}"},
    ),
    "Logs.LogGroup": (
        "LogGroupName",
        "arn:{partition}:logs:{region}:{account}:log-group:{id}:*",
        {"id": r"[.\-_/#A-Za-z0-9]{1,512}"},
    ),
    "Glue.Job": (
        "Name",
        "arn:{partition}:glue:{region}:{account}:job/{id}",
        {"id": r"[\w+=,.@/-]{1,255}"},
    ),
    "Glue.Crawler": (
        "Name",
        "arn:{partition}:glue:{region}:{account}:crawler/{id}",
        {"id": r"[\w+=,.@/-]{1,255}"},
    ),
    "Athena.WorkGroup": (
        "Name",
        "arn:{partition}:athena:{region}:{account}:workgroup/{id}",
        {"id": r"[A-Za-z0-9._-]{1,128}"},
    ),
    "SQS.Queue": (
        "QueueName",
        "arn:{partition}:sqs:{region}:{account}:{id}",
        {"id": r"(?=.{1,80}$)[A-Za-z0-9_-]+(?:\.fifo)?"},
    ),
    "SNS.Topic": (
        "TopicName",
        "arn:{partition}:sns:{region}:{account}:{id}",
        {"id": r"(?=.{1,256}$)[A-Za-z0-9_-]+(?:\.fifo)?"},
    ),
    "ECR.Repository": (
        "RepositoryName",
        "arn:{partition}:ecr:{region}:{account}:repository/{id}",
        {"id": r"(?=.{2,256}$)[a-z0-9]+(?:(?:[._/-]|__|-+)[a-z0-9]+)*"},
    ),
    "CloudWatch.Alarm": (
        "AlarmName",
        "arn:{partition}:cloudwatch:{region}:{account}:alarm:{id}",
        {"id": r"[^:*?\x00-\x1f]{1,255}"},
    ),
    "CodeCommit.Repository": (
        "RepositoryName",
        "arn:{partition}:codecommit:{region}:{account}:{id}",
        {"id": r"(?!.*\.git$)[A-Za-z0-9_.-]{1,100}"},
    ),
    "CodeBuild.Project": (
        "Name",
        "arn:{partition}:codebuild:{region}:{account}:project/{id}",
        {"id": r"[A-Za-z0-9][A-Za-z0-9_-]{1,254}"},
    ),
    "CodePipeline.Pipeline": (
        "Name",
        "arn:{partition}:codepipeline:{region}:{account}:{id}",
        {"id": r"[A-Za-z0-9.@_-]{1,100}"},
    ),
    "MWAA.Environment": (
        "Name",
        "arn:{partition}:airflow:{region}:{account}:environment/{id}",
        {"id": r"[A-Za-z][A-Za-z0-9_-]{0,79}"},
    ),
    "CloudTrail.Trail": (
        "TrailName",
        "arn:{partition}:cloudtrail:{region}:{account}:trail/{id}",
        {"id": r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}"},
    ),
    "IAM.InstanceProfile": (
        {"InstanceProfileName": "id", "Path": "path"},
        "arn:{partition}:iam::{account}:instance-profile{path}{id}",
        {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,128}"},
    ),
    "IAM.ManagedPolicy": (
        {"ManagedPolicyName": "id", "Path": "path"},
        "arn:{partition}:iam::{account}:policy{path}{id}",
        {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,128}"},
    ),
    "IAM.User": (
        {"UserName": "id", "Path": "path"},
        "arn:{partition}:iam::{account}:user{path}{id}",
        {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,64}"},
    ),
    "Events.EventBus": (
        "Name",
        "arn:{partition}:events:{region}:{account}:event-bus/{id}",
        {"id": r"[A-Za-z0-9._-]{1,256}"},
    ),
    "Events.Rule": (
        "Name",
        "arn:{partition}:events:{region}:{account}:rule/{bus}{id}",
        {"bus": r"(?:[A-Za-z0-9._-]{1,256}/)?", "id": r"[A-Za-z0-9._-]{1,64}"},
    ),
    "DynamoDB.Table": (
        "TableName",
        "arn:{partition}:dynamodb:{region}:{account}:table/{id}",
        {"id": r"[A-Za-z0-9_.-]{3,255}"},
    ),
    "DynamoDB.GlobalTable": (
        "TableName",
        "arn:{partition}:dynamodb:{region}:{account}:table/{id}",
        {"id": r"[A-Za-z0-9_.-]{3,255}"},
    ),
    "ECS.Cluster": (
        "ClusterName",
        "arn:{partition}:ecs:{region}:{account}:cluster/{id}",
        {"id": r"[A-Za-z0-9_-]{1,255}"},
    ),
    "KinesisFirehose.DeliveryStream": (
        "DeliveryStreamName",
        "arn:{partition}:firehose:{region}:{account}:deliverystream/{id}",
        {"id": r"[A-Za-z0-9_.-]{1,64}"},
    ),
    "RDS.DBCluster": (
        "DBClusterIdentifier",
        "arn:{partition}:rds:{region}:{account}:cluster:{id}",
        {"id": r"[a-z][a-z0-9-]{0,62}"},
    ),
    "RDS.DBInstance": (
        "DBInstanceIdentifier",
        "arn:{partition}:rds:{region}:{account}:db:{id}",
        {"id": r"[a-z][a-z0-9-]{0,62}"},
    ),
    "RDS.DBClusterParameterGroup": (
        "DBClusterParameterGroupName",
        "arn:{partition}:rds:{region}:{account}:cluster-pg:{id}",
        {"id": r"[a-z][a-z0-9-]{0,254}"},
    ),
    "RDS.DBParameterGroup": (
        "DBParameterGroupName",
        "arn:{partition}:rds:{region}:{account}:pg:{id}",
        {"id": r"[a-z][a-z0-9-]{0,254}"},
    ),
    "RDS.DBSubnetGroup": (
        "DBSubnetGroupName",
        "arn:{partition}:rds:{region}:{account}:subgrp:{id}",
        {"id": r"[a-z][a-z0-9._ -]{0,254}"},
    ),
    "RDS.OptionGroup": (
        "OptionGroupName",
        "arn:{partition}:rds:{region}:{account}:og:{id}",
        {"id": r"[a-z][a-z0-9-]{0,254}"},
    ),
    "SageMaker.Space": (
        {"DomainId": "domain", "SpaceName": "id"},
        "arn:{partition}:sagemaker:{region}:{account}:space/{domain}/{id}",
        {"domain": r"d-[a-z0-9]+", "id": r"[A-Za-z0-9][A-Za-z0-9-]{0,62}"},
    ),
    "SageMaker.UserProfile": (
        {"DomainId": "domain", "UserProfileName": "id"},
        "arn:{partition}:sagemaker:{region}:{account}:user-profile/{domain}/{id}",
        {"domain": r"d-[a-z0-9]+", "id": r"[A-Za-z0-9][A-Za-z0-9-]{0,62}"},
    ),
    "CloudWatch.Dashboard": (
        "DashboardName",
        "arn:{partition}:cloudwatch::{account}:dashboard/{id}",
        {"id": r"[A-Za-z0-9_-]{1,255}"},
    ),
    "CloudFront.Function": (
        "Name",
        "arn:{partition}:cloudfront::{account}:function/{id}",
        {"id": r"[A-Za-z0-9_-]{1,64}"},
    ),
    "ECS.CapacityProvider": (
        "Name",
        "arn:{partition}:ecs:{region}:{account}:capacity-provider/{id}",
        {"id": r"[A-Za-z0-9_-]{1,255}"},
    ),
    "Scheduler.Schedule": (
        {"Name": "id", "GroupName": "group"},
        "arn:{partition}:scheduler:{region}:{account}:schedule/{group}/{id}",
        {"id": r"[A-Za-z0-9_.-]{1,64}", "group": r"[A-Za-z0-9_.-]{1,64}"},
    ),
    "SecurityHub.Hub": (
        {},
        "arn:{partition}:securityhub:{region}:{account}:hub/default",
        {},
    ),
    "Glue.Connection": (
        {"CatalogId": "account", "ConnectionInput.Name": "id"},
        "arn:{partition}:glue:{region}:{account}:connection/{id}",
        {"account": r"\d{12}", "id": r"[\w+=,.@-]{1,255}"},
    ),
    "Glue.Database": (
        {"CatalogId": "account", "DatabaseInput.Name": "id"},
        "arn:{partition}:glue:{region}:{account}:database/{id}",
        {"account": r"\d{12}", "id": r"[a-z0-9_.-]{1,255}"},
    ),
    "Glue.Table": (
        {"CatalogId": "account", "DatabaseName": "database", "TableInput.Name": "id"},
        "arn:{partition}:glue:{region}:{account}:table/{database}/{id}",
        {
            "account": r"\d{12}",
            "database": r"[a-z0-9_.-]{1,255}",
            "id": r"[a-z0-9_.-]{1,255}",
        },
    ),
    "Glue.Catalog": (
        "Name",
        "arn:{partition}:glue:{region}:{account}:catalog/{id}",
        {"id": r"[a-z0-9_-]{1,255}"},
    ),
    "NetworkFirewall.Firewall": (
        "FirewallName",
        "arn:{partition}:network-firewall:{region}:{account}:firewall/{id}",
        {"id": r"[A-Za-z0-9-]{1,128}"},
    ),
    "NetworkFirewall.FirewallPolicy": (
        "FirewallPolicyName",
        "arn:{partition}:network-firewall:{region}:{account}:firewall-policy/{id}",
        {"id": r"[A-Za-z0-9-]{1,128}"},
    ),
    "QuickSight.Analysis": (
        {"AwsAccountId": "account", "AnalysisId": "id"},
        "arn:{partition}:quicksight:{region}:{account}:analysis/{id}",
        {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
    ),
    "QuickSight.Dashboard": (
        {"AwsAccountId": "account", "DashboardId": "id"},
        "arn:{partition}:quicksight:{region}:{account}:dashboard/{id}",
        {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
    ),
    "QuickSight.DataSet": (
        {"AwsAccountId": "account", "DataSetId": "id"},
        "arn:{partition}:quicksight:{region}:{account}:dataset/{id}",
        {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
    ),
    "QuickSight.DataSource": (
        {"AwsAccountId": "account", "DataSourceId": "id"},
        "arn:{partition}:quicksight:{region}:{account}:datasource/{id}",
        {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
    ),
    "QuickSight.VPCConnection": (
        {"AwsAccountId": "account", "VPCConnectionId": "id"},
        "arn:{partition}:quicksight:{region}:{account}:vpcConnection/{id}",
        {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
    ),
    # API Gateway management ARNs have no account component; execute-api is a different value.
    # https://docs.aws.amazon.com/apigateway/latest/developerguide/arn-format-reference.html
    "ApiGateway.Stage": (
        {"RestApiId": "api", "StageName": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/stages/{id}",
        {"api": r"[a-z0-9]+", "id": r"[A-Za-z0-9_-]{1,128}"},
    ),
    "ApiGateway.DomainName": (
        "DomainName",
        "arn:{partition}:apigateway:{region}::/domainnames/{id}",
        {"id": r"[a-z0-9.-]+"},
    ),
    "ApiGatewayV2.DomainName": (
        "DomainName",
        "arn:{partition}:apigateway:{region}::/domainnames/{id}",
        {"id": r"[a-z0-9.-]+"},
    ),
    "ApiGatewayV2.Stage": (
        {"ApiId": "api", "StageName": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/stages/{id}",
        {"api": r"[a-z0-9]+", "id": r"(?:\$default|[A-Za-z0-9_-]{1,128})"},
    ),
    "ApiGateway.BasePathMapping": (
        {"DomainName": "domain", "BasePath": "id"},
        "arn:{partition}:apigateway:{region}::/domainnames/{domain}/basepathmappings/{id}",
        {"domain": r"[A-Za-z0-9.-]+", "id": r"[A-Za-z0-9_.-]+"},
    ),
    "ApiGateway.GatewayResponse": (
        {"RestApiId": "api", "ResponseType": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/gatewayresponses/{id}",
        {"api": r"[a-z0-9]+", "id": r"[A-Z][A-Z0-9_]+"},
    ),
    "ApiGateway.Method": (
        {"RestApiId": "api", "ResourceId": "resource", "HttpMethod": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/resources/{resource}/methods/{id}",
        {"api": r"[a-z0-9]+", "resource": r"[a-z0-9]+", "id": r"[A-Z]+"},
    ),
    "ApiGateway.Model": (
        {"RestApiId": "api", "Name": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/models/{id}",
        {"api": r"[a-z0-9]+", "id": r"[A-Za-z0-9]+"},
    ),
    "NetworkFirewall.RuleGroup": (
        "RuleGroupName",
        "arn:{partition}:network-firewall:{region}:{account}:{type}-rulegroup/{id}",
        {"id": r"[A-Za-z0-9-]{1,128}", "type": r"(?:stateful|stateless)"},
    ),
    # Generated identifiers define logical ARN semantics, never writable template values.
    # AWS Service Authorization Reference: EC2, CloudFront, Route53 and API Gateway.
    "EC2.EIP": (
        "AllocationId",
        "arn:{partition}:ec2:{region}:{account}:elastic-ip/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.FlowLog": (
        "Id",
        "arn:{partition}:ec2:{region}:{account}:vpc-flow-log/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.Instance": (
        "InstanceId",
        "arn:{partition}:ec2:{region}:{account}:instance/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.InternetGateway": (
        "InternetGatewayId",
        "arn:{partition}:ec2:{region}:{account}:internet-gateway/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.LaunchTemplate": (
        "LaunchTemplateId",
        "arn:{partition}:ec2:{region}:{account}:launch-template/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.NatGateway": (
        "NatGatewayId",
        "arn:{partition}:ec2:{region}:{account}:natgateway/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.RouteTable": (
        "RouteTableId",
        "arn:{partition}:ec2:{region}:{account}:route-table/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.SecurityGroup": (
        "GroupId",
        "arn:{partition}:ec2:{region}:{account}:security-group/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.Subnet": (
        "SubnetId",
        "arn:{partition}:ec2:{region}:{account}:subnet/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.TransitGatewayRouteTable": (
        "TransitGatewayRouteTableId",
        "arn:{partition}:ec2:{region}:{account}:transit-gateway-route-table/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.TransitGatewayVpcAttachment": (
        "Id",
        "arn:{partition}:ec2:{region}:{account}:transit-gateway-attachment/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.VPC": (
        "VpcId",
        "arn:{partition}:ec2:{region}:{account}:vpc/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.VPCBlockPublicAccessExclusion": (
        "ExclusionId",
        "arn:{partition}:ec2:{region}:{account}:vpc-block-public-access-exclusion/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "EC2.VPCEndpoint": (
        "Id",
        "arn:{partition}:ec2:{region}:{account}:vpc-endpoint/{id}",
        {"id": "[a-z0-9-]+"},
    ),
    "CloudFront.CachePolicy": (
        "Id",
        "arn:{partition}:cloudfront::{account}:cache-policy/{id}",
        {"id": "[A-Za-z0-9-]+"},
    ),
    "CloudFront.Distribution": (
        "Id",
        "arn:{partition}:cloudfront::{account}:distribution/{id}",
        {"id": "[A-Za-z0-9-]+"},
    ),
    "CloudFront.OriginAccessControl": (
        "Id",
        "arn:{partition}:cloudfront::{account}:origin-access-control/{id}",
        {"id": "[A-Za-z0-9-]+"},
    ),
    "CloudFront.OriginRequestPolicy": (
        "Id",
        "arn:{partition}:cloudfront::{account}:origin-request-policy/{id}",
        {"id": "[A-Za-z0-9-]+"},
    ),
    "CloudFront.ResponseHeadersPolicy": (
        "Id",
        "arn:{partition}:cloudfront::{account}:response-headers-policy/{id}",
        {"id": "[A-Za-z0-9-]+"},
    ),
    "Route53.HostedZone": (
        "Id",
        "arn:{partition}:route53:::hostedzone/{id}",
        {"id": "[A-Z0-9]+"},
    ),
    "ApiGateway.ApiKey": (
        "APIKeyId",
        "arn:{partition}:apigateway:{region}::/apikeys/{id}",
        {"id": "[a-z0-9]+"},
    ),
    "ApiGateway.RestApi": (
        "RestApiId",
        "arn:{partition}:apigateway:{region}::/restapis/{id}",
        {"id": "[a-z0-9]+"},
    ),
    "ApiGateway.VpcLink": (
        "VpcLinkId",
        "arn:{partition}:apigateway:{region}::/vpclinks/{id}",
        {"id": "[a-z0-9]+"},
    ),
    "ApiGateway.Authorizer": (
        {"RestApiId": "api", "AuthorizerId": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/authorizers/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGateway.Deployment": (
        {"RestApiId": "api", "DeploymentId": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/deployments/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGateway.RequestValidator": (
        {"RestApiId": "api", "RequestValidatorId": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/requestvalidators/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGateway.Resource": (
        {"RestApiId": "api", "ResourceId": "id"},
        "arn:{partition}:apigateway:{region}::/restapis/{api}/resources/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGateway.UsagePlan": (
        "Id",
        "arn:{partition}:apigateway:{region}::/usageplans/{id}",
        {"id": "[a-z0-9]+"},
    ),
    "ApiGateway.UsagePlanKey": (
        {"UsagePlanId": "plan", "KeyId": "id"},
        "arn:{partition}:apigateway:{region}::/usageplans/{plan}/keys/{id}",
        {"plan": "[a-z0-9]+", "id": "[A-Za-z0-9]+"},
    ),
    "ApiGatewayV2.Api": (
        "ApiId",
        "arn:{partition}:apigateway:{region}::/apis/{id}",
        {"id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.VpcLink": (
        "VpcLinkId",
        "arn:{partition}:apigateway:{region}::/vpclinks/{id}",
        {"id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.Authorizer": (
        {"ApiId": "api", "AuthorizerId": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/authorizers/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.Deployment": (
        {"ApiId": "api", "DeploymentId": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/deployments/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.Integration": (
        {"ApiId": "api", "IntegrationId": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/integrations/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.Route": (
        {"ApiId": "api", "RouteId": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/routes/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.ApiMapping": (
        {"DomainName": "domain", "ApiMappingId": "id"},
        "arn:{partition}:apigateway:{region}::/domainnames/{domain}/apimappings/{id}",
        {"domain": "[A-Za-z0-9.-]+", "id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.IntegrationResponse": (
        {"ApiId": "api", "IntegrationResponseId": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/integrationresponses/{id}",
        {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "ApiGatewayV2.RouteResponse": (
        {"ApiId": "api", "RouteId": "route", "RouteResponseId": "id"},
        "arn:{partition}:apigateway:{region}::/apis/{api}/routes/{route}/routeresponses/{id}",
        {"api": "[a-z0-9]+", "route": "[a-z0-9]+", "id": "[a-z0-9]+"},
    ),
    "GuardDuty.Detector": (
        "Id",
        "arn:{partition}:guardduty:{region}:{account}:detector/{id}",
        {"id": r"[a-f0-9]{32}"},
    ),
    "SSM.Association": (
        "AssociationId",
        "arn:{partition}:ssm:{region}:{account}:association/{id}",
        {"id": r"[a-f0-9-]+"},
    ),
    "SSM.MaintenanceWindow": (
        "WindowId",
        "arn:{partition}:ssm:{region}:{account}:maintenancewindow/{id}",
        {"id": r"mw-[a-f0-9]+"},
    ),
    "SSM.MaintenanceWindowTarget": (
        "WindowTargetId",
        "arn:{partition}:ssm:{region}:{account}:windowtarget/{id}",
        {"id": r"[a-f0-9-]+"},
    ),
    "SSM.MaintenanceWindowTask": (
        "WindowTaskId",
        "arn:{partition}:ssm:{region}:{account}:windowtask/{id}",
        {"id": r"[a-f0-9-]+"},
    ),
    "SSM.PatchBaseline": (
        "Id",
        "arn:{partition}:ssm:{region}:{account}:patchbaseline/{id}",
        {"id": r"pb-[a-f0-9]+"},
    ),
}


ARN_DEFAULTS = {
    ("IAM.Role", "Path"): "/",
    ("IAM.User", "Path"): "/",
    ("IAM.InstanceProfile", "Path"): "/",
    ("IAM.ManagedPolicy", "Path"): "/",
    ("Scheduler.Schedule", "GroupName"): "default",
}


def _arn_pattern(shape):
    _, template, identity_patterns = shape
    patterns = {
        "partition": r"aws(?:-[a-z]+)*",
        "region": r"[a-z]{2}(?:-[a-z]+)+-\d+",
        "account": r"\d{12}",
        **identity_patterns,
    }
    result = re.escape(template)
    for name, pattern in patterns.items():
        result = result.replace(
            re.escape("{" + name + "}"), "(?P<" + name + ">" + pattern + ")"
        )
    return result


# Shapes with service-specific components cannot infer Producer identity from a name alone.
ARN_FORMS = {
    (kind, "Arn"): (shape[0], _arn_pattern(shape))
    for kind, shape in ARN_SHAPES.items()
    if kind not in {"Events.Rule", "NetworkFirewall.RuleGroup", "ApiGateway.DomainName"}
}
ARN_FORMS.update(
    {
        (kind, ARN_ATTRIBUTES[kind]): form
        for (kind, _), form in list(ARN_FORMS.items())
        if kind in ARN_ATTRIBUTES
    }
)
ARN_FORMS["S3.Bucket", "ObjectArn"] = (
    "BucketName",
    ARN_FORMS["S3.Bucket", "Arn"][1] + r"/(?P<prefix>[^*]*)",
)
# DataResource Values selects objects below the bucket, including the required slash.
ATTRIBUTE_SUFFIXES = {("S3.Bucket", "ObjectArn"): ("Arn", "/")}
VALUE_IDENTITIES = {
    ("SecretsManager.Secret", "Name"): r"(?P<id>[^:]+)(?::[^:]*){0,3}",
    (
        "SecretsManager.Secret",
        "Id",
    ): r"(?P<id>arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:\d{12}:secret:[^:]+)(?::[^:]*){0,3}",
}
# Allowed consumer forms do not replace an explicit Model attribute. Retain the
# established Secret Id-to-name literal comparison only in this consumer context.
REFERENCE_EQUIVALENT_FORMS = {
    (
        "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
        "SecretsManager.Secret",
        "Id",
    ): {"Name"},
}
TYPE_FORMS = {"KMS.Key": {"KeyId", "Arn"}, "KMS.Alias": {"AliasName", "Arn"}}
# Existing Framework format policies, shared by the Resolver and comparison.
KMS_FORMS = {
    "CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id": {"AliasArn"},
    "Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn": {
        "AliasArn"
    },
    "Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn": {
        "AliasArn"
    },
    "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": {
        "KeyArn"
    },
    "Logs.LogGroup.KmsKeyId": {"KeyArn", "AliasArn"},
}
CONTEXT_PROPERTIES = {
    "CodeBuild.Project.Source.Location": ("CodeBuild.Project.Source.Type", {}),
    "CodeBuild.Project.Cache.Location": ("CodeBuild.Project.Cache.Type", {}),
    "CodeBuild.Project.Artifacts.Location": (
        "CodeBuild.Project.Artifacts.Type",
        {"S3": ("S3.Bucket", "BucketName")},
    ),
    "Lambda.EventSourceMapping.SourceAccessConfigurations[].URI": (
        "Lambda.EventSourceMapping.SourceAccessConfigurations[].Type",
        {
            "BASIC_AUTH": ("SecretsManager.Secret", "Arn"),
            "SASL_SCRAM_256_AUTH": ("SecretsManager.Secret", "Arn"),
            "SASL_SCRAM_512_AUTH": ("SecretsManager.Secret", "Arn"),
            "CLIENT_CERTIFICATE_TLS_AUTH": ("SecretsManager.Secret", "Arn"),
            "SERVER_ROOT_CA_CERTIFICATE": ("SecretsManager.Secret", "Arn"),
        },
    ),
    "CodeBuild.Project.Environment.EnvironmentVariables[].Value": (
        "CodeBuild.Project.Environment.EnvironmentVariables[].Type",
        {
            "SECRETS_MANAGER": ("SecretsManager.Secret", ("Name", "Id")),
            "PARAMETER_STORE": ("SSM.Parameter", "Name"),
        },
    ),
    "CloudTrail.Trail.EventSelectors[].DataResources[].Values": (
        "CloudTrail.Trail.EventSelectors[].DataResources[].Type",
        {
            "AWS::S3::Object": ("S3.Bucket", "ObjectArn"),
            "AWS::Lambda::Function": ("Lambda.Function", "Arn"),
        },
    ),
    "EC2.FlowLog.ResourceId": (
        "EC2.FlowLog.ResourceType",
        {"VPC": ("EC2.VPC", "VpcId")},
    ),
}
# Existing link rendering defaults unsupported explicit attributes for these rows.
CONTEXT_DEFAULT_ON_MISMATCH = {
    "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
    "CloudTrail.Trail.EventSelectors[].DataResources[].Values[]",
}
ACTION_CONFIGURATION = "CodePipeline.Pipeline.Stages[].Actions[].Configuration"
ACTION_CONFIGURATION_CONTRACTS = {
    ("Source", "AWS", "CodeCommit", "1", "RepositoryName"): (
        "CodeCommit.Repository",
        "Name",
    ),
    ("Build", "AWS", "CodeBuild", "1", "ProjectName"): ("CodeBuild.Project", "Name"),
    ("Source", "AWS", "S3", "1", "S3Bucket"): ("S3.Bucket", "BucketName"),
}
CONFIGURATION_PROPERTIES = {
    ACTION_CONFIGURATION: (
        ACTION_CONFIGURATION.removesuffix("Configuration") + "ActionTypeId.Provider",
        {
            (provider, key): (
                kind,
                RETURN_ATTRIBUTE_PROPERTIES.get((kind, attribute), attribute),
            )
            for (_, _, provider, _, key), (
                kind,
                attribute,
            ) in ACTION_CONFIGURATION_CONTRACTS.items()
        },
    ),
}


def action_contexts(rows):
    contexts = {}
    for _, row in rows:
        prop = row["property"].removeprefix("CodePipeline.Pipeline.")
        action = re.fullmatch(
            r"(.*\.Actions\[\d+\])\.ActionTypeId\.(Category|Owner|Provider|Version)",
            prop,
        )
        if action:
            value = row["value"]
            value = (
                value[1:-1] if value.startswith("`") and value.endswith("`") else value
            )
            put_row(
                contexts.setdefault(action[1], {}), "ActionTypeId." + action[2], value
            )
    return contexts


def row_contexts(kind, rows):
    """Context for split rows; callers already scope rows to one Resource."""
    contexts, variables = {}, {}
    for index, (rid, row) in enumerate(rows):
        prop = row["property"].removeprefix(kind + ".")
        value = row["value"]
        value = value[1:-1] if value.startswith("`") and value.endswith("`") else value
        if kind == "CodeBuild.Project" and re.fullmatch(
            r"Environment.EnvironmentVariables\[\d*\]\.(Name|Type|Value)", prop
        ):
            put_row(variables, prop, rid if prop.endswith(".Value") else value)
        if kind == "Lambda.EventSourceMapping" and (
            access := re.fullmatch(r"(SourceAccessConfigurations\[\d+\])\.Type", prop)
        ):
            variables.setdefault("lambda_types", {}).setdefault(access[1], []).append(
                value
            )
        if kind == "CloudTrail.Trail" and (
            data := re.fullmatch(r"(.*\.DataResources\[\d+\])\.Type", prop)
        ):
            put_row(contexts.setdefault(data[1], {}), "Type", value)
        if (
            kind == "CloudTrail.Trail"
            and prop.endswith(".DataResources[].Type")
            and index + 1 < len(rows)
            and rows[index + 1][1]["property"]
            == row["property"].removesuffix("Type") + "Values"
        ):
            contexts[rows[index + 1][0]] = {"Type": value}
    if kind == "CodeBuild.Project":
        types = [
            row["value"].strip("`")
            for _, row in rows
            if row["property"] == kind + ".Artifacts.Type"
        ]
        if len(types) == 1:
            for rid, row in rows:
                if row["property"] == kind + ".Artifacts.Location":
                    contexts[rid] = {"Type": types[0]}
    if kind == "Lambda.EventSourceMapping":
        for path, types in variables.get("lambda_types", {}).items():
            if len(types) == 1:
                contexts[path] = {"Type": types[0]}
        for rid, row in rows:
            match = re.fullmatch(
                r"Lambda\.EventSourceMapping\.(SourceAccessConfigurations\[\d+\])\.URI",
                row["property"],
            )
            if match and match[1] in contexts:
                contexts[rid] = contexts[match[1]]
    for variable in variables.get("Environment", {}).get("EnvironmentVariables", []):
        if "Value" in variable:
            contexts[variable["Value"]] = variable
    if kind == "EC2.FlowLog":
        types = [
            row["value"].strip("`")
            for _, row in rows
            if row["property"] == kind + ".ResourceType"
        ]
        if len(types) == 1:
            contexts["ResourceId"] = {"ResourceType": types[0]}
    return contexts


def reference_error(prop, context=None):
    """Policy for a Resource reference, independent of its producer or attribute."""
    if (
        re.sub(r"\[\d+\]", "[]", prop)
        == "CodeBuild.Project.Environment.EnvironmentVariables[].Value"
        and (context or {}).get("Type", "PLAINTEXT") == "PLAINTEXT"
    ):
        return "PLAINTEXTではResource linkは禁止 (Resource links are forbidden for PLAINTEXT)"
    return None


def reference_context(path, value, context):
    """Bind context to its containing object, never a sibling or a previous traversal."""
    path = re.sub(r"\[\d+\]", "[]", path)
    if path in {
        "EC2.FlowLog",
        "SourceAccessConfigurations[]",
        "Artifacts",
        "CodeBuild.Project.Artifacts",
    } or path.endswith(
        (
            ".Actions[]",
            ".DataResources[]",
            ".EnvironmentVariables[]",
            ".SourceAccessConfigurations[]",
        )
    ):
        return value
    return context


def configuration_contract(prop, context=None):
    prop = re.sub(r"\[\d+\]", "[]", prop)
    if not prop.startswith(ACTION_CONFIGURATION + "."):
        return None
    action = (context or {}).get("ActionTypeId")
    if not isinstance(action, dict) or set(action) != {
        "Category",
        "Owner",
        "Provider",
        "Version",
    }:
        return {}
    parts = [action[key] for key in ("Category", "Owner", "Provider", "Version")]
    if not all(isinstance(value, str) for value in parts):
        return {}
    found = ACTION_CONFIGURATION_CONTRACTS.get(
        (*parts, prop.removeprefix(ACTION_CONFIGURATION + "."))
    )
    return {found[0]: (found[1],)} if found else {}


def contract(prop, context=None):
    prop = re.sub(r"\[[0-9]+\]", "[]", prop)
    if prop in {
        "S3.BucketPolicy.PolicyDocument.Statement"
        + statement
        + ".Condition.StringNotEquals.s3:x-amz-server-side-encryption-aws-kms-key-id"
        + values
        for statement in ("", "[]")
        for values in ("", "[]")
    }:
        return {"KMS.Key": ("Arn",)}
    for root, style in POLICY_FORMATS.items():
        if style not in {"statement", "wrapped-statement"}:
            continue
        prefix = root + (".PolicyDocument" if style == "wrapped-statement" else "")
        if prop in {
            prefix
            + ".Statement"
            + array
            + ".Condition.StringEquals.aws:SourceVpc"
            + value_array
            for array in ("", "[]")
            for value_array in ("", "[]")
        }:
            return {"EC2.VPC": ("VpcId",)}
    for prefix in (
        "IAM.Role.AssumeRolePolicyDocument",
        "IAM.Role.Policies[].PolicyDocument",
    ):
        for array in ("", "[]"):
            condition = prefix + ".Statement" + array + ".Condition."
            for value_array in ("", "[]"):
                for operator in ("ArnEquals", "ArnLike"):
                    if prop == condition + operator + ".aws:SourceArn" + value_array:
                        return {
                            "S3.Bucket": ("Arn",),
                            "SecretsManager.Secret": ("Arn",),
                        }
                if (
                    prop
                    == condition
                    + "StringEquals.kms:EncryptionContext:aws:s3:arn"
                    + value_array
                ):
                    return {"S3.Bucket": ("Arn",)}
                if (
                    prop
                    == condition
                    + "StringLike.kms:EncryptionContext:SecretARN"
                    + value_array
                ):
                    return {"SecretsManager.Secret": ("Arn",)}
    configuration = configuration_contract(prop, context)
    if configuration is not None:
        return configuration
    # Mapping represents terminal list scalars with or without [].
    prop = next(
        (
            candidate
            for candidate in (prop, prop + "[]", prop.removesuffix("[]"))
            if candidate in IMPORT_PROPERTIES or candidate in CONTEXT_PROPERTIES
        ),
        prop,
    )
    found = IMPORT_PROPERTIES.get(prop)
    if found is None and prop in CONTEXT_PROPERTIES:
        selector, choices = CONTEXT_PROPERTIES[prop]
        value = (context or {}).get(
            selector, (context or {}).get(selector.rsplit(".", 1)[-1])
        )
        found = choices.get(value) if isinstance(value, str) else None
    if found is None:
        return {}
    kinds, attribute = found
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    forms = REFERENCE_FORMS.get(
        prop,
        set(attribute)
        if isinstance(attribute, tuple)
        else {attribute}
        if attribute
        else {"KeyId", "Arn", "AliasName"},
    )
    result = {
        kind: tuple(sorted(forms & TYPE_FORMS.get(kind, forms))) for kind in kinds
    }
    if prop in KMS_FORMS:
        result = {
            kind: tuple(
                form
                for form in attributes
                if {"KMS.Key": {"Arn": "KeyArn"}, "KMS.Alias": {"Arn": "AliasArn"}}.get(
                    kind, {}
                ).get(form, form)
                in KMS_FORMS[prop]
            )
            for kind, attributes in result.items()
        }
    return {kind: attributes for kind, attributes in result.items() if attributes}


def policy_condition(prop):
    prop = re.sub(r"\[\d+\]", "[]", prop)
    for root, style in POLICY_FORMATS.items():
        if style not in {"statement", "wrapped-statement"}:
            continue
        prefix = root + (".PolicyDocument" if style == "wrapped-statement" else "")
        if any(
            prop.startswith(prefix + ".Statement" + array + ".Condition.")
            for array in ("", "[]")
        ):
            return True
    return False


def unproven_document_reference(prop):
    prop = re.sub(r"\[\d+\]", "[]", prop)
    return prop in {
        "ECS.TaskDefinition.ContainerDefinitions[].Secrets[].ValueFrom",
        "Glue.Crawler.Targets.S3Targets[].Path",
        "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.OutputLocation",
        "ApiGatewayV2.DomainName.MutualTlsAuthentication.TruststoreUri",
        "DataZone.Connection.Props.S3Properties.S3Uri",
    } or prop.startswith("Organizations.Policy.Content.")


def requires_context(prop, context=None):
    prop = re.sub(r"\[\d+\]", "[]", prop)
    if (
        prop == "CodeBuild.Project.Environment.EnvironmentVariables[].Value"
        and (context or {}).get("Type") == "PLAINTEXT"
    ):
        # PLAINTEXT is rejected by reference_error before reference resolution.
        return False
    return (
        policy_condition(prop)
        or unproven_document_reference(prop)
        or any(
            candidate in CONTEXT_PROPERTIES
            for candidate in (prop, prop + "[]", prop.removesuffix("[]"))
        )
        or prop.startswith(ACTION_CONFIGURATION + ".")
    )


@lru_cache(maxsize=None)
def attributes_for(kind):
    contracts = [contract(prop) for prop in IMPORT_PROPERTIES]
    contracts += [
        contract(prop, {selector: key})
        for prop, (selector, choices) in CONTEXT_PROPERTIES.items()
        for key in choices
    ]
    forms = {form for item in contracts for form in item.get(kind, ())}
    forms.update(
        form
        for _, choices in CONFIGURATION_PROPERTIES.values()
        for target, form in choices.values()
        if target == kind
    )
    forms.update(
        field
        for (target, _), (attribute, _) in ARN_FORMS.items()
        if target == kind
        for field in (attribute if isinstance(attribute, dict) else (attribute,))
    )
    return tuple(sorted(kind + "." + form for form in forms))


def reference_attribute(kind: str, attribute: str) -> str:
    """Map proven Model attributes to provider attributes, never GetAtt aliases."""
    if (kind, attribute) == ("CloudFront.Function", "FunctionMetadata.FunctionARN"):
        return "FunctionARN"
    mapped = [
        returned
        for (resource_type, returned), setting in RETURN_ATTRIBUTE_PROPERTIES.items()
        if resource_type == kind and setting == attribute
    ]
    if len(mapped) > 1:
        raise ValueError("ambiguous returned attribute")
    if mapped:
        return mapped[0]
    # Ref/GetAtt Id return the Secret ARN; ManagedPolicy uses PolicyArn, not Arn.
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-managedpolicy.html
    return ARN_ATTRIBUTES.get(kind, attribute) if attribute == "Arn" else attribute

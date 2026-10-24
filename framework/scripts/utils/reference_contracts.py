"""Explicit AWS receiving-property contracts shared by comparison and IMPORT."""
import re
from functools import lru_cache

# Returned attributes whose explicit setting has a different property name.
RETURN_ATTRIBUTE_PROPERTIES = {('CodeCommit.Repository', 'Name'): 'RepositoryName'}


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


S3_KMS_MASTER_KEY_ID = ('S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]'
                        '.ServerSideEncryptionByDefault.KMSMasterKeyID')

# Documented identifier formats absent from the provider schema's string pattern.
# Each entry is a property contract, not permission to erase reference attributes.
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-kms-alias.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cloudtrail-trail.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-athena-workgroup-encryptionconfiguration.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecr-repository-encryptionconfiguration.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-s3-bucket-serversideencryptionbydefault.html
REFERENCE_FORMS = {
    'KMS.Alias.TargetKeyId': {'KeyId', 'Arn'},
    'CloudTrail.Trail.KMSKeyId': {'KeyId', 'Arn', 'AliasName'},
    # Framework design/comparison policy: this property requires a key ARN.
    'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': {'Arn'},
    'ECR.Repository.EncryptionConfiguration.KmsKey': {'KeyId', 'Arn', 'AliasName'},
    'S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID': {'KeyId', 'Arn', 'AliasName'},
    # aws-resource-codecommit-repository.html; aws-properties-ec2-instance-ebs.html
    'CodeCommit.Repository.KmsKeyId': {'KeyId', 'Arn', 'AliasName'},
    'EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId': {'KeyId', 'Arn', 'AliasName'},
    # aws-properties-codepipeline-pipeline-encryptionkey.html: alias ARN, not alias name.
    'CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id': {'KeyId', 'Arn'},
    # aws-resource-mwaa-environment.html; aws-resource-secretsmanager-secret.html
    'MWAA.Environment.KmsKey': {'KeyId', 'Arn', 'AliasName'},
    'SecretsManager.Secret.KmsKeyId': {'KeyId', 'Arn', 'AliasName'},
    # aws-resource-glue-job.html; aws-resource-lambda-permission.html
    'Glue.Job.Role': {'RoleName', 'Arn'},
    'Lambda.Permission.FunctionName': {'FunctionName', 'Arn'},
    # aws-resource-secretsmanager-rotationschedule.html: Ref returns the secret ARN (Id).
    'SecretsManager.RotationSchedule.SecretId': {'Id', 'Name'},
}

# Explicit receiving-property contracts: target type(s) and the Model link attribute.
# Sources are the named resource/property pages in the CloudFormation TemplateReference.
# No identifier suffix or primaryIdentifier determines a receiving property's meaning.
REFERENCE_PROPERTIES = {
    'CloudTrail.Trail.S3BucketName': ('S3.Bucket', 'BucketName'),
    'CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName': ('Logs.LogGroup', 'LogGroupName'),
    'CodeBuild.Project.VpcConfig.VpcId': ('EC2.VPC', 'VpcId'),
    'CodeBuild.Project.VpcConfig.Subnets[]': ('EC2.Subnet', 'SubnetId'),
    'CodeBuild.Project.VpcConfig.SecurityGroupIds[]': ('EC2.SecurityGroup', 'GroupId'),
    'CodeCommit.Repository.KmsKeyId': (('KMS.Key', 'KMS.Alias'), None),
    'CodePipeline.Pipeline.ArtifactStore.Location': ('S3.Bucket', 'BucketName'),
    'CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id': (('KMS.Key', 'KMS.Alias'), None),
    'EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId': (('KMS.Key', 'KMS.Alias'), None),
    'EC2.Instance.IamInstanceProfile': ('IAM.InstanceProfile', 'InstanceProfileName'),
    'EC2.Instance.SecurityGroupIds[]': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.Instance.SubnetId': ('EC2.Subnet', 'SubnetId'),
    'EC2.SecurityGroup.VpcId': ('EC2.VPC', 'VpcId'),
    'EC2.SecurityGroup.SecurityGroupEgress[].DestinationSecurityGroupId': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.SecurityGroupIngress.GroupId': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.SecurityGroupIngress.SourceSecurityGroupId': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.SecurityGroupEgress.GroupId': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.SecurityGroupEgress.DestinationSecurityGroupId': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.Subnet.VpcId': ('EC2.VPC', 'VpcId'),
    'EC2.TransitGatewayVpcAttachment.VpcId': ('EC2.VPC', 'VpcId'),
    'EC2.SubnetRouteTableAssociation.RouteTableId': ('EC2.RouteTable', 'RouteTableId'),
    'EC2.RouteTable.VpcId': ('EC2.VPC', 'VpcId'),
    'EC2.FlowLog.LogGroupName': ('Logs.LogGroup', 'LogGroupName'),
    'EC2.VPCEndpoint.RouteTableIds[]': ('EC2.RouteTable', 'RouteTableId'),
    'EC2.VPCEndpoint.VpcId': ('EC2.VPC', 'VpcId'),
    'EC2.VPCEndpoint.SecurityGroupIds[]': ('EC2.SecurityGroup', 'GroupId'),
    'EC2.VPCEndpoint.SubnetIds[]': ('EC2.Subnet', 'SubnetId'),
    'Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList[]': ('EC2.SecurityGroup', 'GroupId'),
    'Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SubnetId': ('EC2.Subnet', 'SubnetId'),
    'Glue.Job.Connections.Connections[]': ('Glue.Connection', 'Name'),
    'Glue.Job.Role': ('IAM.Role', 'RoleName'),
    'Glue.Job.SecurityConfiguration': ('Glue.SecurityConfiguration', 'Name'),
    'GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName': ('S3.Bucket', 'BucketName'),
    'IAM.ManagedPolicy.Roles[]': ('IAM.Role', 'RoleName'),
    'IAM.InstanceProfile.Roles[]': ('IAM.Role', 'RoleName'),
    'Lambda.Function.Code.S3Bucket': ('S3.Bucket', 'BucketName'),
    'Lambda.Function.LoggingConfig.LogGroup': ('Logs.LogGroup', 'LogGroupName'),
    'Lambda.Function.VpcConfig.SecurityGroupIds[]': ('EC2.SecurityGroup', 'GroupId'),
    'Lambda.Function.VpcConfig.SubnetIds[]': ('EC2.Subnet', 'SubnetId'),
    'Lambda.Permission.FunctionName': ('Lambda.Function', 'FunctionName'),
    'MWAA.Environment.KmsKey': (('KMS.Key', 'KMS.Alias'), None),
    'MWAA.Environment.NetworkConfiguration.SecurityGroupIds[]': ('EC2.SecurityGroup', 'GroupId'),
    'MWAA.Environment.NetworkConfiguration.SubnetIds[]': ('EC2.Subnet', 'SubnetId'),
    'QuickSight.DataSource.Permissions[].Principal': ('QuickSight.Group', 'Arn'),
    'QuickSight.VPCConnection.SecurityGroupIds[]': ('EC2.SecurityGroup', 'GroupId'),
    'QuickSight.VPCConnection.SubnetIds[]': ('EC2.Subnet', 'SubnetId'),
    'Route53.HostedZone.VPCs[].VPCId': ('EC2.VPC', 'VpcId'),
    'Route53.RecordSet.HostedZoneId': ('Route53.HostedZone', 'Id'),
    'SecretsManager.Secret.KmsKeyId': (('KMS.Key', 'KMS.Alias'), None),
    'SecretsManager.RotationSchedule.SecretId': ('SecretsManager.Secret', 'Id'),
    'SQS.QueuePolicy.Queues[]': ('SQS.Queue', 'QueueUrl'),
}


# ARN receiving forms are explicit, not inferred from an Id/Arn suffix.
IMPORT_PROPERTIES = {
    **REFERENCE_PROPERTIES,
    'KMS.Alias.TargetKeyId': (('KMS.Key',), None),
    'CloudTrail.Trail.KMSKeyId': (('KMS.Key', 'KMS.Alias'), None),
    'CloudTrail.Trail.CloudWatchLogsRoleArn': ('IAM.Role', 'Arn'),
    'CloudTrail.Trail.CloudWatchLogsLogGroupArn': ('Logs.LogGroup', 'Arn'),
    'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': (('KMS.Key', 'KMS.Alias'), None),
    'ECR.Repository.EncryptionConfiguration.KmsKey': (('KMS.Key', 'KMS.Alias'), None),
    'S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID': (('KMS.Key', 'KMS.Alias'), None),
    'Config.ConfigurationRecorder.RoleARN': ('IAM.Role', 'Arn'),
    # aws-resource-guardduty-malwareprotectionplan.html: Role requires an IAM role ARN.
    'GuardDuty.MalwareProtectionPlan.Role': ('IAM.Role', 'Arn'),
    'KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN': ('KMS.Key', 'Arn'),
    'KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN': ('S3.Bucket', 'Arn'),
    'KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN': ('IAM.Role', 'Arn'),
    'KinesisFirehose.DeliveryStream.ExtendedS3DestinationConfiguration.BucketARN': ('S3.Bucket', 'Arn'),
    'KinesisFirehose.DeliveryStream.ExtendedS3DestinationConfiguration.RoleARN': ('IAM.Role', 'Arn'),
    'Lambda.Function.Role': ('IAM.Role', 'Arn'),
    'Lambda.Function.KmsKeyArn': ('KMS.Key', 'Arn'),
    'CodeBuild.Project.ServiceRole': ('IAM.Role', 'Arn'),
    'CodePipeline.Pipeline.RoleArn': ('IAM.Role', 'Arn'),
    'Logs.LogGroup.KmsKeyId': (('KMS.Key', 'KMS.Alias'), 'Arn'),
    'Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn': (('KMS.Key', 'KMS.Alias'), 'Arn'),
    'Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn': (('KMS.Key', 'KMS.Alias'), 'Arn'),
}
IMPORT_PROPERTIES.update({prop: (kind, {'EC2.Subnet': 'SubnetId', 'EC2.SecurityGroup': 'GroupId'}[kind])
                          for prop, kind in LINKED_LIST_PROPERTIES.items()})

# AWS documented ARN identities. Parsing and transient projection share these shapes.
# S3 bucket names are global. Regional/account-scoped identities require context.
ARN_SHAPES = {
    'S3.Bucket': ('BucketName', 'arn:{partition}:s3:::{id}', {'id': r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]'}),
    'KMS.Key': ('KeyId', 'arn:{partition}:kms:{region}:{account}:key/{id}', {'id': r'(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})'}),
    'KMS.Alias': ('AliasName', 'arn:{partition}:kms:{region}:{account}:{id}', {'id': r'alias/[A-Za-z0-9:/_-]+'}),
    'Lambda.Function': ('FunctionName', 'arn:{partition}:lambda:{region}:{account}:function:{id}', {'id': r'[A-Za-z0-9_-]{1,64}'}),
    'IAM.Role': ({'RoleName': 'id', 'Path': 'path'}, 'arn:{partition}:iam::{account}:role{path}{id}',
                 {'path': r'/(?:[^/]+/)*', 'id': r'[A-Za-z0-9_+=,.@-]+'}),
    'Logs.LogGroup': ('LogGroupName', 'arn:{partition}:logs:{region}:{account}:log-group:{id}', {'id': r'[.\-_/#A-Za-z0-9]{1,512}'}),
}


def _arn_pattern(shape):
    _, template, identity_patterns = shape
    patterns = {'partition': r'aws(?:-[a-z]+)*', 'region': r'[a-z0-9-]+', 'account': r'\d{12}', **identity_patterns}
    return template.format(**{name: '(?P<' + name + '>' + pattern + ')' for name, pattern in patterns.items()})


ARN_FORMS = {(kind, 'Arn'): (shape[0], _arn_pattern(shape) + (r'(?::\*)?' if kind == 'Logs.LogGroup' else ''))
             for kind, shape in ARN_SHAPES.items()}
ARN_IDENTITIES = {kind: ARN_FORMS[kind, 'Arn'] for kind in ('S3.Bucket', 'KMS.Key', 'KMS.Alias')}
ARN_FORMS['S3.Bucket', 'ObjectArn'] = ('BucketName', ARN_FORMS['S3.Bucket', 'Arn'][1] + r'/(?P<prefix>[^*]*)')
VALUE_IDENTITIES = {
    ('SecretsManager.Secret', 'Name'): r'(?P<id>[^:]+)(?::[^:]*){0,3}',
    ('SecretsManager.Secret', 'Id'): r'(?P<id>arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:\d{12}:secret:[^:]+)(?::[^:]*){0,3}',
}
TYPE_FORMS = {'KMS.Key': {'KeyId', 'Arn'}, 'KMS.Alias': {'AliasName', 'Arn'}}
CONTEXT_PROPERTIES = {
    'CodeBuild.Project.Environment.EnvironmentVariables[].Value': (
        'CodeBuild.Project.Environment.EnvironmentVariables[].Type',
        {'SECRETS_MANAGER': ('SecretsManager.Secret', ('Name', 'Id')), 'PARAMETER_STORE': ('SSM.Parameter', 'Name')}),
    'CloudTrail.Trail.EventSelectors[].DataResources[].Values': (
        'CloudTrail.Trail.EventSelectors[].DataResources[].Type',
        {'AWS::S3::Object': ('S3.Bucket', 'ObjectArn'), 'AWS::Lambda::Function': ('Lambda.Function', 'Arn')}),
}
CONFIGURATION_PROPERTIES = {
    'CodePipeline.Pipeline.Stages[].Actions[].Configuration': (
        'CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Provider',
        {('CodeCommit', 'RepositoryName'): ('CodeCommit.Repository', 'RepositoryName'),
         ('CodeBuild', 'ProjectName'): ('CodeBuild.Project', 'Name')}),
}


def contract(prop, context=None):
    prop = re.sub(r'\[[0-9]+\]', '[]', prop)
    # Mapping represents terminal list scalars with or without [].
    found = IMPORT_PROPERTIES.get(prop) or IMPORT_PROPERTIES.get(prop + '[]')
    if found is None and prop in CONTEXT_PROPERTIES:
        selector, choices = CONTEXT_PROPERTIES[prop]
        value = (context or {}).get(selector)
        found = choices.get(value) if isinstance(value, str) else None
    if found is None:
        return {}
    kinds, attribute = found
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    forms = REFERENCE_FORMS.get(prop, set(attribute) if isinstance(attribute, tuple) else {attribute} if attribute else {'KeyId', 'Arn', 'AliasName'})
    return {kind: tuple(sorted(forms & TYPE_FORMS.get(kind, forms))) for kind in kinds}


@lru_cache(maxsize=None)
def attributes_for(kind):
    contracts = [contract(prop) for prop in IMPORT_PROPERTIES]
    contracts += [contract(prop, {selector: key}) for prop, (selector, choices) in CONTEXT_PROPERTIES.items() for key in choices]
    forms = {form for item in contracts for form in item.get(kind, ())}
    forms.update(form for _, choices in CONFIGURATION_PROPERTIES.values()
                 for target, form in choices.values() if target == kind)
    forms.update(field for (target, _), (attribute, _) in ARN_FORMS.items() if target == kind
                 for field in (attribute if isinstance(attribute, dict) else (attribute,)))
    return tuple(sorted(kind + '.' + form for form in forms))


def reference_attribute(kind: str, attribute: str) -> str:
    """Map proven Model attributes to provider attributes, never GetAtt aliases."""
    mapped = [returned for (resource_type, returned), setting in RETURN_ATTRIBUTE_PROPERTIES.items()
              if resource_type == kind and setting == attribute]
    if len(mapped) > 1:
        raise ValueError('ambiguous returned attribute')
    if mapped:
        return mapped[0]
    # Ref/GetAtt Id return the Secret ARN; ManagedPolicy uses PolicyArn, not Arn.
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-managedpolicy.html
    return {"SecretsManager.Secret": "Id", "IAM.ManagedPolicy": "PolicyArn"}.get(kind, attribute) if attribute == "Arn" else attribute

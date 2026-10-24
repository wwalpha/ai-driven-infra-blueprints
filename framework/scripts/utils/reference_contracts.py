"""Explicit AWS receiving-property contracts shared by comparison and IMPORT."""
import re
from functools import lru_cache

from utils.comparison_rows import put_row

# Returned attributes whose explicit setting has a different property name.
RETURN_ATTRIBUTE_PROPERTIES = {('CodeCommit.Repository', 'Name'): 'RepositoryName',
                               ('Events.Rule', 'RuleName'): 'Name'}


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
# DataResource Values selects objects below the bucket, including the required slash.
ATTRIBUTE_SUFFIXES = {('S3.Bucket', 'ObjectArn'): ('Arn', '/')}
VALUE_IDENTITIES = {
    ('SecretsManager.Secret', 'Name'): r'(?P<id>[^:]+)(?::[^:]*){0,3}',
    ('SecretsManager.Secret', 'Id'): r'(?P<id>arn:[a-z0-9-]+:secretsmanager:[a-z0-9-]+:\d{12}:secret:[^:]+)(?::[^:]*){0,3}',
}
TYPE_FORMS = {'KMS.Key': {'KeyId', 'Arn'}, 'KMS.Alias': {'AliasName', 'Arn'}}
# Existing Framework format policies, shared by the Resolver and comparison.
KMS_FORMS = {
    'CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id': {'AliasArn'},
    'Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn': {'AliasArn'},
    'Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn': {'AliasArn'},
    'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': {'KeyArn'},
    'Logs.LogGroup.KmsKeyId': {'KeyArn', 'AliasArn'},
}
CONTEXT_PROPERTIES = {
    'CodeBuild.Project.Environment.EnvironmentVariables[].Value': (
        'CodeBuild.Project.Environment.EnvironmentVariables[].Type',
        {'SECRETS_MANAGER': ('SecretsManager.Secret', ('Name', 'Id')), 'PARAMETER_STORE': ('SSM.Parameter', 'Name')}),
    'CloudTrail.Trail.EventSelectors[].DataResources[].Values': (
        'CloudTrail.Trail.EventSelectors[].DataResources[].Type',
        {'AWS::S3::Object': ('S3.Bucket', 'ObjectArn'), 'AWS::Lambda::Function': ('Lambda.Function', 'Arn')}),
    'EC2.FlowLog.ResourceId': ('EC2.FlowLog.ResourceType', {'VPC': ('EC2.VPC', 'VpcId')}),
}
ACTION_CONFIGURATION = 'CodePipeline.Pipeline.Stages[].Actions[].Configuration'
ACTION_CONFIGURATION_CONTRACTS = {
    ('Source', 'AWS', 'CodeCommit', '1', 'RepositoryName'): ('CodeCommit.Repository', 'Name'),
    ('Build', 'AWS', 'CodeBuild', '1', 'ProjectName'): ('CodeBuild.Project', 'Name'),
    ('Source', 'AWS', 'S3', '1', 'S3Bucket'): ('S3.Bucket', 'BucketName'),
}
CONFIGURATION_PROPERTIES = {
    ACTION_CONFIGURATION: (ACTION_CONFIGURATION.removesuffix('Configuration') + 'ActionTypeId.Provider',
        {(provider, key): (kind, RETURN_ATTRIBUTE_PROPERTIES.get((kind, attribute), attribute))
         for (_, _, provider, _, key), (kind, attribute) in ACTION_CONFIGURATION_CONTRACTS.items()}),
}


def action_contexts(rows):
    contexts = {}
    for _, row in rows:
        prop = row['property'].removeprefix('CodePipeline.Pipeline.')
        action = re.fullmatch(r'(.*\.Actions\[\d+\])\.ActionTypeId\.(Category|Owner|Provider|Version)', prop)
        if action:
            value = row['value']
            value = value[1:-1] if value.startswith('`') and value.endswith('`') else value
            put_row(contexts.setdefault(action[1], {}), 'ActionTypeId.' + action[2], value)
    return contexts


def row_contexts(kind, rows):
    """Context for split rows; callers already scope rows to one Resource."""
    contexts, variables = {}, {}
    for index, (rid, row) in enumerate(rows):
        prop = row['property'].removeprefix(kind + '.')
        value = row['value']
        value = value[1:-1] if value.startswith('`') and value.endswith('`') else value
        if kind == 'CodeBuild.Project' and re.fullmatch(r'Environment.EnvironmentVariables\[\d*\]\.(Name|Type|Value)', prop):
            put_row(variables, prop, rid if prop.endswith('.Value') else value)
        if kind == 'CloudTrail.Trail' and (data := re.fullmatch(r'(.*\.DataResources\[\d+\])\.Type', prop)):
            put_row(contexts.setdefault(data[1], {}), 'Type', value)
        if (kind == 'CloudTrail.Trail' and prop.endswith('.DataResources[].Type') and index + 1 < len(rows)
                and rows[index + 1][1]['property'] == row['property'].removesuffix('Type') + 'Values'):
            contexts[rows[index + 1][0]] = {'Type': value}
    for variable in variables.get('Environment', {}).get('EnvironmentVariables', []):
        if 'Value' in variable:
            contexts[variable['Value']] = variable
    if kind == 'EC2.FlowLog':
        types = [row['value'].strip('`') for _, row in rows if row['property'] == kind + '.ResourceType']
        if len(types) == 1:
            contexts['ResourceId'] = {'ResourceType': types[0]}
    return contexts


def reference_context(path, value, context):
    """Bind context to its containing object, never a sibling or a previous traversal."""
    path = re.sub(r'\[\d+\]', '[]', path)
    if path == 'EC2.FlowLog' or path.endswith(('.Actions[]', '.DataResources[]', '.EnvironmentVariables[]')):
        return value
    return context


def configuration_contract(prop, context=None):
    prop = re.sub(r'\[\d+\]', '[]', prop)
    if not prop.startswith(ACTION_CONFIGURATION + '.'):
        return None
    action = (context or {}).get('ActionTypeId')
    if not isinstance(action, dict) or set(action) != {'Category', 'Owner', 'Provider', 'Version'}:
        return {}
    parts = [action[key] for key in ('Category', 'Owner', 'Provider', 'Version')]
    if not all(isinstance(value, str) for value in parts):
        return {}
    found = ACTION_CONFIGURATION_CONTRACTS.get((*parts, prop.removeprefix(ACTION_CONFIGURATION + '.')))
    return {found[0]: (found[1],)} if found else {}


def contract(prop, context=None):
    prop = re.sub(r'\[[0-9]+\]', '[]', prop)
    configuration = configuration_contract(prop, context)
    if configuration is not None:
        return configuration
    # Mapping represents terminal list scalars with or without [].
    prop = next((candidate for candidate in (prop, prop + '[]', prop.removesuffix('[]'))
                 if candidate in IMPORT_PROPERTIES or candidate in CONTEXT_PROPERTIES), prop)
    found = IMPORT_PROPERTIES.get(prop)
    if found is None and prop in CONTEXT_PROPERTIES:
        selector, choices = CONTEXT_PROPERTIES[prop]
        value = (context or {}).get(selector, (context or {}).get(selector.rsplit('.', 1)[-1]))
        found = choices.get(value) if isinstance(value, str) else None
    if found is None:
        return {}
    kinds, attribute = found
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    forms = REFERENCE_FORMS.get(prop, set(attribute) if isinstance(attribute, tuple) else {attribute} if attribute else {'KeyId', 'Arn', 'AliasName'})
    result = {kind: tuple(sorted(forms & TYPE_FORMS.get(kind, forms))) for kind in kinds}
    if prop in KMS_FORMS:
        result = {kind: tuple(form for form in attributes if
                  {'KMS.Key': {'Arn': 'KeyArn'}, 'KMS.Alias': {'Arn': 'AliasArn'}}.get(kind, {}).get(form, form) in KMS_FORMS[prop])
                  for kind, attributes in result.items()}
    return {kind: attributes for kind, attributes in result.items() if attributes}


def requires_context(prop, context=None):
    prop = re.sub(r'\[\d+\]', '[]', prop)
    if prop == 'CodeBuild.Project.Environment.EnvironmentVariables[].Value' and (context or {}).get('Type') == 'PLAINTEXT':
        return False  # Arbitrary string values still undergo producer attribute/type validation.
    return (any(candidate in CONTEXT_PROPERTIES for candidate in (prop, prop + '[]', prop.removesuffix('[]')))
            or configuration_contract(prop) is not None)


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
    return {"SecretsManager.Secret": "Id", "IAM.ManagedPolicy": "PolicyArn", "KMS.Alias": "AliasArn"}.get(kind, attribute) if attribute == "Arn" else attribute

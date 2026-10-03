"""codebuild: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('CodeBuild.Project',)
APIS = {('codebuild', 'batch_get_projects')}
IDENTITIES = {'CodeBuild.Project': ('base', 'name', 'arn', 'Name')}
FIELDS = {}
FIELDS.update(fields('CodeBuild.Project', 'base', {
    'Artifacts.Type': 'artifacts.type',
    'Cache.Type': 'cache.type',
    'ConcurrentBuildLimit': 'concurrentBuildLimit',
    'Environment.ComputeType': 'environment.computeType',
    'Environment.EnvironmentVariables[].Name': 'environment.environmentVariables[].name',
    'Environment.EnvironmentVariables[].Type': 'environment.environmentVariables[].type',
    'Environment.EnvironmentVariables[].Value': 'environment.environmentVariables[].value',
    'Environment.Image': 'environment.image',
    'Environment.ImagePullCredentialsType': 'environment.imagePullCredentialsType',
    'Environment.PrivilegedMode': 'environment.privilegedMode',
    'Environment.Type': 'environment.type',
    'Id': 'name',
    'LogsConfig.CloudWatchLogs.GroupName': 'logsConfig.cloudWatchLogs.groupName',
    'LogsConfig.CloudWatchLogs.Status': 'logsConfig.cloudWatchLogs.status',
    'LogsConfig.S3Logs.Status': 'logsConfig.s3Logs.status',
    'Name': 'name',
    'QueuedTimeoutInMinutes': 'queuedTimeoutInMinutes',
    'ServiceRole': 'serviceRole',
    'Source.BuildSpec': 'source.buildspec',
    'Source.Type': 'source.type',
    'TimeoutInMinutes': 'timeoutInMinutes',
    'VpcConfig.SecurityGroupIds': 'vpcConfig.securityGroupIds',
    'VpcConfig.Subnets': 'vpcConfig.subnets',
    'VpcConfig.VpcId': 'vpcConfig.vpcId',
}, norms={'ServiceRole': 'arn', 'VpcConfig.VpcId': 'id', 'VpcConfig.Subnets': 'id', 'VpcConfig.SecurityGroupIds': 'id', 'Environment.EnvironmentVariables[].Value': 'name'}))


def sensitive(prop):
    return prop.endswith('EnvironmentVariables[].Value') or prop.endswith('Source.BuildSpec')


def fetch(ctx, r, getter):
    return one(ctx.call('codebuild', 'batch_get_projects', names=[r.value('Name')]).get('projects', []), 'codebuild.batch_get_projects')

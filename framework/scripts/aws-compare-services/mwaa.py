"""mwaa: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('MWAA.Environment',)
APIS = {('mwaa', 'get_environment')}
IDENTITIES = {'MWAA.Environment': ('base', 'Name', 'Arn', 'Name')}
FIELDS = {}
FIELDS.update(fields('MWAA.Environment', 'base', {
    'AirflowVersion': 'AirflowVersion',
    'DagS3Path': 'DagS3Path',
    'EndpointManagement': 'EndpointManagement',
    'EnvironmentClass': 'EnvironmentClass',
    'ExecutionRoleArn': 'ExecutionRoleArn',
    'KmsKey': 'KmsKey',
    'LoggingConfiguration.DagProcessingLogs.Enabled': 'LoggingConfiguration.DagProcessingLogs.Enabled',
    'LoggingConfiguration.DagProcessingLogs.LogLevel': 'LoggingConfiguration.DagProcessingLogs.LogLevel',
    'LoggingConfiguration.SchedulerLogs.Enabled': 'LoggingConfiguration.SchedulerLogs.Enabled',
    'LoggingConfiguration.SchedulerLogs.LogLevel': 'LoggingConfiguration.SchedulerLogs.LogLevel',
    'LoggingConfiguration.TaskLogs.Enabled': 'LoggingConfiguration.TaskLogs.Enabled',
    'LoggingConfiguration.TaskLogs.LogLevel': 'LoggingConfiguration.TaskLogs.LogLevel',
    'LoggingConfiguration.WebserverLogs.Enabled': 'LoggingConfiguration.WebserverLogs.Enabled',
    'LoggingConfiguration.WebserverLogs.LogLevel': 'LoggingConfiguration.WebserverLogs.LogLevel',
    'LoggingConfiguration.WorkerLogs.Enabled': 'LoggingConfiguration.WorkerLogs.Enabled',
    'LoggingConfiguration.WorkerLogs.LogLevel': 'LoggingConfiguration.WorkerLogs.LogLevel',
    'MaxWebservers': 'MaxWebservers',
    'MaxWorkers': 'MaxWorkers',
    'MinWebservers': 'MinWebservers',
    'MinWorkers': 'MinWorkers',
    'Name': 'Name',
    'NetworkConfiguration.SecurityGroupIds': 'NetworkConfiguration.SecurityGroupIds',
    'NetworkConfiguration.SubnetIds': 'NetworkConfiguration.SubnetIds',
    'RequirementsS3Path': 'RequirementsS3Path',
    'Schedulers': 'Schedulers',
    'SourceBucketArn': 'SourceBucketArn',
    'WebserverAccessMode': 'WebserverAccessMode',
}, norms={'ExecutionRoleArn': 'arn', 'KmsKey': 'kms', 'SourceBucketArn': 'arn', 'NetworkConfiguration.SecurityGroupIds': 'id', 'NetworkConfiguration.SubnetIds': 'id'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call('mwaa', 'get_environment', Name=r.value('Name'))['Environment']

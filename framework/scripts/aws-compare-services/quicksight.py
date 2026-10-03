"""quicksight: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('QuickSight.DataSource', 'QuickSight.VPCConnection')
APIS = {('quicksight', 'describe_vpc_connection'), ('quicksight', 'describe_data_source_permissions'), ('quicksight', 'describe_data_source')}
IDENTITIES = {'QuickSight.DataSource': ('base', 'DataSourceId', 'Arn', 'Name'), 'QuickSight.VPCConnection': ('vpc', 'VPCConnectionId', 'Arn', 'Name')}
FIELDS = {}
FIELDS.update(fields('QuickSight.DataSource', 'base', {
    'AwsAccountId': 'AwsAccountId',
    'Credentials.SecretArn': 'SecretArn',
    'DataSourceId': 'DataSourceId',
    'DataSourceParameters.AthenaParameters.RoleArn': 'DataSourceParameters.AthenaParameters.RoleArn',
    'DataSourceParameters.AthenaParameters.WorkGroup': 'DataSourceParameters.AthenaParameters.WorkGroup',
    'DataSourceParameters.SnowflakeParameters.AuthenticationType': 'DataSourceParameters.SnowflakeParameters.AuthenticationType',
    'DataSourceParameters.SnowflakeParameters.Database': 'DataSourceParameters.SnowflakeParameters.Database',
    'DataSourceParameters.SnowflakeParameters.DatabaseAccessControlRole': 'DataSourceParameters.SnowflakeParameters.DatabaseAccessControlRole',
    'DataSourceParameters.SnowflakeParameters.Host': 'DataSourceParameters.SnowflakeParameters.Host',
    'DataSourceParameters.SnowflakeParameters.Warehouse': 'DataSourceParameters.SnowflakeParameters.Warehouse',
    'Name': 'Name',
    'SslProperties.DisableSsl': 'SslProperties.DisableSsl',
    'Type': 'Type',
    'VpcConnectionProperties.VpcConnectionArn': 'VpcConnectionProperties.VpcConnectionArn',
}, norms={'Credentials.SecretArn': 'arn', 'DataSourceParameters.AthenaParameters.RoleArn': 'arn', 'VpcConnectionProperties.VpcConnectionArn': 'arn'}))
FIELDS.update(fields('QuickSight.DataSource', 'permissions', {
    'Permissions[].Actions': 'Permissions[].Actions',
    'Permissions[].Principal': 'Permissions[].Principal',
}))
FIELDS.update(fields('QuickSight.VPCConnection', 'vpc', {
    'AwsAccountId': 'AwsAccountId',
    'Name': 'Name',
    'RoleArn': 'RoleArn',
    'SecurityGroupIds': 'SecurityGroupIds',
    'SubnetIds': 'NetworkInterfaces[].SubnetId',
    'VPCConnectionId': 'VPCConnectionId',
}, norms={'RoleArn': 'arn', 'SecurityGroupIds': 'id', 'SubnetIds': 'id'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    account=r.value('AwsAccountId')
    if account!=ctx.target['awsAccountId']:
        raise Unresolved('QuickSight AwsAccountId conflicts with target')
    if getter=='vpc':
        result=ctx.call('quicksight','describe_vpc_connection',AwsAccountId=account,VPCConnectionId=r.value('VPCConnectionId'))['VPCConnection']
    elif getter=='permissions':
        return ctx.call('quicksight','describe_data_source_permissions',AwsAccountId=account,DataSourceId=r.value('DataSourceId'))
    else:
        result=ctx.call('quicksight','describe_data_source',AwsAccountId=account,DataSourceId=r.value('DataSourceId'))['DataSource']
    return dict(result,AwsAccountId=account)

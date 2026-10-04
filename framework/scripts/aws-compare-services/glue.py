"""glue: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Glue.Catalog', 'Glue.Connection', 'Glue.Database', 'Glue.Job', 'Glue.SecurityConfiguration', 'Glue.Table')
APIS = {('glue', 'get_security_configuration'), ('glue', 'get_catalog'), ('glue', 'get_table'), ('glue', 'get_catalogs'), ('glue', 'get_connection'), ('glue', 'get_database'), ('glue', 'get_job')}
IDENTITIES = {'Glue.Catalog': ('base', 'CatalogId', 'ResourceArn', 'Name'), 'Glue.Connection': ('base', 'Name', None, 'ConnectionInput.Name'), 'Glue.Database': ('base', 'Name', None, 'DatabaseInput.Name'), 'Glue.Table': ('base', 'Name', None, 'TableInput.Name'), 'Glue.Job': ('base', 'Name', None, 'Name'), 'Glue.SecurityConfiguration': ('base', 'Name', None, 'Name')}
FIELDS = {}
FIELDS.update(fields('Glue.Catalog', 'base', {
    'CatalogId': 'CatalogId',
    'FederatedCatalog.ConnectionName': 'FederatedCatalog.ConnectionName',
    'Name': 'Name',
}))
FIELDS.update(fields('Glue.Connection', 'base', {
    'CatalogId': 'CatalogId',
    'ConnectionInput.AuthenticationConfiguration.AuthenticationType': 'AuthenticationConfiguration.AuthenticationType',
    'ConnectionInput.AuthenticationConfiguration.SecretArn': 'AuthenticationConfiguration.SecretArn',
    'ConnectionInput.ConnectionProperties': 'ConnectionProperties',
    'ConnectionInput.ConnectionType': 'ConnectionType',
    'ConnectionInput.Description': 'Description',
    'ConnectionInput.Name': 'Name',
    'ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone': 'PhysicalConnectionRequirements.AvailabilityZone',
    'ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList': 'PhysicalConnectionRequirements.SecurityGroupIdList',
    'ConnectionInput.PhysicalConnectionRequirements.SubnetId': 'PhysicalConnectionRequirements.SubnetId',
    'Name': 'Name',
}, norms={'ConnectionInput.AuthenticationConfiguration.SecretArn': 'arn', 'ConnectionInput.PhysicalConnectionRequirements.SubnetId': 'id', 'ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList': 'id', 'Name': 'name', 'ConnectionInput.ConnectionProperties': 'json'}))
FIELDS.update(fields('Glue.Database', 'base', {
    'CatalogId': 'CatalogId',
    'DatabaseInput.Description': 'Description',
    'DatabaseInput.Name': 'Name',
}))
FIELDS.update(fields('Glue.Table', 'base', {
    'CatalogId': 'CatalogId',
    'DatabaseName': 'DatabaseName',
    'Id': 'Name',
    'TableInput.Name': 'Name',
    'TableInput.Parameters': 'Parameters',
    'TableInput.StorageDescriptor.InputFormat': 'StorageDescriptor.InputFormat',
    'TableInput.StorageDescriptor.Location': 'StorageDescriptor.Location',
    'TableInput.StorageDescriptor.OutputFormat': 'StorageDescriptor.OutputFormat',
    'TableInput.StorageDescriptor.SerdeInfo.Parameters': 'StorageDescriptor.SerdeInfo.Parameters',
    'TableInput.StorageDescriptor.SerdeInfo.SerializationLibrary': 'StorageDescriptor.SerdeInfo.SerializationLibrary',
    'TableInput.TableType': 'TableType',
}, norms={'TableInput.Parameters': 'json', 'TableInput.StorageDescriptor.SerdeInfo.Parameters': 'json'}))
FIELDS.update(fields('Glue.Job', 'base', {
    'Command.Name': 'Command.Name',
    'Command.PythonVersion': 'Command.PythonVersion',
    'Command.ScriptLocation': 'Command.ScriptLocation',
    'Connections.Connections': 'Connections.Connections',
    'DefaultArguments': 'DefaultArguments',
    'Description': 'Description',
    'ExecutionClass': 'ExecutionClass',
    'ExecutionProperty.MaxConcurrentRuns': 'ExecutionProperty.MaxConcurrentRuns',
    'GlueVersion': 'GlueVersion',
    'JobRunQueuingEnabled': 'JobRunQueuingEnabled',
    'MaxRetries': 'MaxRetries',
    'Name': 'Name',
    'NonOverridableArguments': 'NonOverridableArguments',
    'NumberOfWorkers': 'NumberOfWorkers',
    'Role': 'Role',
    'SecurityConfiguration': 'SecurityConfiguration',
    'Timeout': 'Timeout',
    'WorkerType': 'WorkerType',
}, norms={'Role': 'iam_role', 'SecurityConfiguration': 'name', 'Connections.Connections': 'name', 'DefaultArguments': 'json', 'NonOverridableArguments': 'json'}))
FIELDS.update(fields('Glue.SecurityConfiguration', 'base', {
    'EncryptionConfiguration.CloudWatchEncryption.CloudWatchEncryptionMode': 'EncryptionConfiguration.CloudWatchEncryption.CloudWatchEncryptionMode',
    'EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn': 'EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn',
    'EncryptionConfiguration.S3Encryptions[].KmsKeyArn': 'EncryptionConfiguration.S3Encryption[].KmsKeyArn',
    'EncryptionConfiguration.S3Encryptions[].S3EncryptionMode': 'EncryptionConfiguration.S3Encryption[].S3EncryptionMode',
    'Name': 'Name',
}, norms={'EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn': 'kms', 'EncryptionConfiguration.S3Encryptions[].KmsKeyArn': 'kms'}))
FIELDS['Glue.Connection.ConnectionInput.ValidateForComputeEnvironments'] = unavailable('CreateConnection validation request input is not returned by GetConnection; CompatibleComputeEnvironments is a different, derived capability.')


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == 'Glue.Catalog':
        current=r.current('CatalogId')
        if current:
            return ctx.call('glue','get_catalog',CatalogId=current)['Catalog']
        return one([v for v in ctx.pages('glue','get_catalogs',ParentCatalogId=ctx.target.get('awsExecutionAccountId',ctx.target['awsAccountId'])).get('CatalogList',[]) if v['Name']==r.value('Name')], 'glue.get_catalogs')
    if r.kind == 'Glue.Connection':
        catalog=r.value('CatalogId')
        record=ctx.call('glue','get_connection',CatalogId=catalog,Name=r.value('ConnectionInput.Name'),HidePassword=True)['Connection']
        return dict(record,CatalogId=catalog)
    if r.kind == 'Glue.Database':
        catalog=r.value('CatalogId')
        return dict(ctx.call('glue','get_database',CatalogId=catalog,Name=r.value('DatabaseInput.Name'))['Database'],CatalogId=catalog)
    if r.kind == 'Glue.Table':
        catalog, database=r.value('CatalogId'),r.value('DatabaseName')
        record=ctx.call('glue','get_table',CatalogId=catalog,DatabaseName=database,Name=r.value('TableInput.Name'))['Table']
        return dict(record,CatalogId=catalog,DatabaseName=database)
    if r.kind == 'Glue.Job':
        return ctx.call('glue','get_job',JobName=r.value('Name'))['Job']
    return ctx.call('glue','get_security_configuration',Name=r.value('Name'))['SecurityConfiguration']

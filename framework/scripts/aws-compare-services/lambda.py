"""lambda: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Lambda.Function', 'Lambda.Permission')
APIS = {('lambda', 'get_function_recursion_config'), ('lambda', 'get_policy'), ('lambda', 'get_function')}
IDENTITIES = {'Lambda.Function': ('base', 'Configuration.FunctionName', 'Configuration.FunctionArn', 'FunctionName'), 'Lambda.Permission': ('permission', 'Sid', None, None)}
FIELDS = {}
FIELDS.update(fields('Lambda.Function', 'base', {
    'Architectures': 'Configuration.Architectures',
    'EphemeralStorage.Size': 'Configuration.EphemeralStorage.Size',
    'FunctionName': 'Configuration.FunctionName',
    'Handler': 'Configuration.Handler',
    'LoggingConfig.LogFormat': 'Configuration.LoggingConfig.LogFormat',
    'LoggingConfig.LogGroup': 'Configuration.LoggingConfig.LogGroup',
    'MemorySize': 'Configuration.MemorySize',
    'PackageType': 'Configuration.PackageType',
    'Role': 'Configuration.Role',
    'Runtime': 'Configuration.Runtime',
    'Timeout': 'Configuration.Timeout',
    'TracingConfig.Mode': 'Configuration.TracingConfig.Mode',
    'VpcConfig.Ipv6AllowedForDualStack': 'Configuration.VpcConfig.Ipv6AllowedForDualStack',
    'VpcConfig.SecurityGroupIds': 'Configuration.VpcConfig.SecurityGroupIds',
    'VpcConfig.SubnetIds': 'Configuration.VpcConfig.SubnetIds',
}, norms={'LoggingConfig.LogGroup': 'name', 'Role': 'arn', 'VpcConfig.SecurityGroupIds': 'id', 'VpcConfig.SubnetIds': 'id'}, defaults={'VpcConfig.Ipv6AllowedForDualStack': False}))
FIELDS.update(fields('Lambda.Function', 'base', {
    'Code.S3Bucket': 'Code.ResolvedS3Object.S3Bucket',
    'Code.S3Key': 'Code.ResolvedS3Object.S3Key',
    'ReservedConcurrentExecutions': 'Concurrency.ReservedConcurrentExecutions',
}, norms={'Code.S3Bucket': 'name'}))
FIELDS.update(fields('Lambda.Function', 'recursion', {
    'RecursiveLoop': 'RecursiveLoop',
}))
FIELDS.update(fields('Lambda.Permission', 'permission', {
    'Action': 'Action',
    'FunctionName': 'FunctionName',
    'Id': 'Sid',
    'Principal': 'Principal',
    'SourceAccount': 'SourceAccount',
    'SourceArn': 'SourceArn',
}, norms={'FunctionName': 'name', 'SourceArn': 'arn'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind=='Lambda.Function':
        name=r.value('FunctionName')
        if getter=='recursion':
            return ctx.call('lambda','get_function_recursion_config',FunctionName=name)
        return ctx.call('lambda','get_function',FunctionName=name)
    parent=r.parent()
    name=parent.value('FunctionName')
    if r.value('FunctionName','name')!=name:
        raise Unresolved('permission FunctionName does not identify its parent')
    import json
    statements=json.loads(ctx.call('lambda','get_policy',FunctionName=name)['Policy']).get('Statement',[])
    current=r.current('Id')
    if current:
        statement=one([v for v in statements if v.get('Sid')==current], 'lambda.get_policy')
    else:
        action=r.value('Action'); principal=r.value('Principal'); source=r.optional('SourceArn',norm='arn'); account=r.optional('SourceAccount')
        candidates=[]
        for v in statements:
            principals=v.get('Principal',{})
            principal_values=[principals] if isinstance(principals,str) else list(principals.values())
            condition=v.get('Condition',{})
            actual_source=condition.get('ArnLike',condition.get('ArnEquals',{})).get('AWS:SourceArn')
            actual_account=condition.get('StringEquals',{}).get('AWS:SourceAccount')
            if v.get('Action')==action and principal in principal_values and (source is None or source==actual_source) and (account is None or account==actual_account):
                candidates.append(v)
        statement=one(candidates,'lambda.get_policy')
    principal=statement.get('Principal',{})
    if isinstance(principal,dict):
        principal=one(list(principal.values()),'lambda.get_policy')
    condition=statement.get('Condition',{})
    return dict(statement,FunctionName=name,Principal=principal,SourceArn=condition.get('ArnLike',condition.get('ArnEquals',{})).get('AWS:SourceArn',MISSING),SourceAccount=condition.get('StringEquals',{}).get('AWS:SourceAccount',MISSING))

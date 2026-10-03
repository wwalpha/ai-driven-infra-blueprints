"""iam: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('IAM.InstanceProfile', 'IAM.ManagedPolicy', 'IAM.Role', 'IAM.User')
APIS = {('iam', 'list_attached_user_policies'), ('iam', 'list_role_policies'), ('iam', 'get_user_policy'), ('iam', 'list_attached_role_policies'), ('iam', 'get_policy_version'), ('iam', 'list_entities_for_policy'), ('iam', 'list_policies'), ('iam', 'get_instance_profile'), ('iam', 'get_role_policy'), ('iam', 'list_user_policies'), ('iam', 'get_user'), ('iam', 'get_role')}
IDENTITIES = {'IAM.Role': ('base', 'RoleName', 'Arn', 'RoleName'), 'IAM.User': ('base', 'UserName', 'Arn', 'UserName'), 'IAM.ManagedPolicy': ('base', 'PolicyName', 'Arn', 'ManagedPolicyName'), 'IAM.InstanceProfile': ('base', 'InstanceProfileName', 'Arn', 'InstanceProfileName')}
FIELDS = {}
FIELDS.update(fields('IAM.Role', 'base', {
    'AssumeRolePolicyDocument': 'AssumeRolePolicyDocument',
    'Description': 'Description',
    'RoleName': 'RoleName',
}, norms={'AssumeRolePolicyDocument': 'policy'}))
FIELDS.update(fields('IAM.Role', 'attached', {
    'ManagedPolicyArns': 'Arns',
}, norms={'ManagedPolicyArns': 'arn'}))
FIELDS.update(fields('IAM.Role', 'inline', {
    'Policies[].PolicyDocument': 'Policies[].PolicyDocument',
    'Policies[].PolicyName': 'Policies[].PolicyName',
}, norms={'Policies[].PolicyDocument': 'policy'}))
FIELDS.update(fields('IAM.User', 'base', {
    'UserName': 'UserName',
}))
FIELDS.update(fields('IAM.User', 'attached', {
    'ManagedPolicyArns': 'Arns',
}, norms={'ManagedPolicyArns': 'arn'}))
FIELDS.update(fields('IAM.User', 'inline', {
    'Policies[].PolicyDocument': 'Policies[].PolicyDocument',
    'Policies[].PolicyName': 'Policies[].PolicyName',
}, norms={'Policies[].PolicyDocument': 'policy'}))
FIELDS.update(fields('IAM.ManagedPolicy', 'base', {
    'ManagedPolicyName': 'PolicyName',
}))
FIELDS.update(fields('IAM.ManagedPolicy', 'document', {
    'PolicyDocument': 'Document',
}, norms={'PolicyDocument': 'policy'}))
FIELDS.update(fields('IAM.ManagedPolicy', 'entities', {
    'Roles': 'Roles',
}, norms={'Roles': 'name'}))
FIELDS.update(fields('IAM.InstanceProfile', 'base', {
    'InstanceProfileName': 'InstanceProfileName',
    'Roles': 'Roles[].RoleName',
}, norms={'Roles': 'name'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == 'IAM.InstanceProfile':
        return ctx.call('iam','get_instance_profile',InstanceProfileName=r.value('InstanceProfileName'))['InstanceProfile']
    if r.kind == 'IAM.ManagedPolicy':
        record=one([v for v in ctx.pages('iam','list_policies',Scope='Local').get('Policies',[]) if v['PolicyName']==r.value('ManagedPolicyName')], 'iam.list_policies')
        if getter=='document':
            return ctx.call('iam','get_policy_version',PolicyArn=record['Arn'],VersionId=record['DefaultVersionId'])['PolicyVersion']
        if getter=='entities':
            return {'Roles':[v['RoleName'] for v in ctx.pages('iam','list_entities_for_policy',PolicyArn=record['Arn'],EntityFilter='Role').get('PolicyRoles',[])]}
        return record
    kind='role' if r.kind=='IAM.Role' else 'user'
    argument='RoleName' if kind=='role' else 'UserName'
    name=r.value(argument)
    if getter=='attached':
        result=ctx.pages('iam','list_attached_'+kind+'_policies',**{argument:name})
        return {'Arns':[v['PolicyArn'] for v in result.get('AttachedPolicies',[])]}
    if getter=='inline':
        names=ctx.pages('iam','list_'+kind+'_policies',**{argument:name}).get('PolicyNames',[])
        return {'Policies':[{'PolicyName':p,'PolicyDocument':ctx.call('iam','get_'+kind+'_policy',**{argument:name,'PolicyName':p})['PolicyDocument']} for p in names]}
    return ctx.call('iam','get_'+kind,**{argument:name})['Role' if kind=='role' else 'User']

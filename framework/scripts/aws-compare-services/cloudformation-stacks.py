"""Only stack presence/state is remote; deployment files/policy are local metadata."""
from model_aws_compare import entries, metadata, AcquisitionError

RESOURCE_TYPES = ('CloudFormation.Stack',)
APIS = {('cloudformation', 'describe_stacks')}
IDENTITIES = {}
FIELDS = {}


def sensitive(prop):
    return False


def classify(key):
    if key.startswith('desired.stack.'):
        return 'supported' if key.endswith('.name') else 'local_metadata' if key.rsplit('.',1)[-1] in {'template','parameters','deployOrder'} else 'unimplemented'
    if key.startswith('desired.artifact.') or key in {'desired.deployment.maxConcurrentStacks','desired.deployment.templateBucket','desired.deployment.templateKeyPrefix'}:
        return 'local_metadata'
    return 'unimplemented'


def fetch(ctx,r,getter):
    raise ValueError('stack models use explicit stack entries')


def compare(ctx,model):
    results=[]
    for number,stack in entries(model.values,'desired.stack.'):
        key='desired.stack.'+number+'.name'
        name=stack['name']
        item={'resource':name,'resourceType':'CloudFormation.Stack','propertiesKey':key,'modelKeys':[key],
              'source':[dict(model.locations[key],key=key)],'designValue':name,'awsValue':None,'apis':[]}
        start=len(ctx.trace)
        try:
            records=ctx.call('cloudformation','describe_stacks',StackName=name).get('Stacks',[])
            if len(records)!=1 or records[0].get('StackName')!=name:
                raise AcquisitionError('cloudformation.describe_stacks','StackNotFound','resource_missing')
            state=records[0]['StackStatus']
            healthy=state in {'CREATE_COMPLETE','UPDATE_COMPLETE','IMPORT_COMPLETE'}
            results.append(dict(item,status='match' if healthy else 'difference',awsValue={'StackName':name,'StackStatus':state},apis=ctx.trace[start:]))
        except AcquisitionError as error:
            # DescribeStacks uses ValidationError for missing stacks, but the same
            # code covers invalid requests. Do not call all ValidationErrors absence.
            results.append(dict(item,status=error.status,reason=error.code,affectedKeys=[key],apis=ctx.trace[start:]))
    for key,value in model.values.items():
        if key.startswith('desired.') and not key.endswith('.name'):
            status=classify(key)
            results.append({'resource':None,'propertiesKey':key,'modelKeys':[key],'status':status,'designValue':value,'awsValue':None,
                            'source':[dict(model.locations[key],key=key)],'apis':[],
                            'reason':'local deployment input; no CloudFormation settings/template comparison'})
    return results

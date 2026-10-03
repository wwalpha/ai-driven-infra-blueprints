"""sqs: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('SQS.Queue', 'SQS.QueuePolicy')
APIS = {('sqs', 'get_queue_url'), ('sqs', 'get_queue_attributes')}
IDENTITIES = {'SQS.Queue': ('queue', 'QueueUrl', 'Attributes.QueueArn', 'QueueName'), 'SQS.QueuePolicy': ('policy', 'Queues', None, None)}
FIELDS = {}
FIELDS.update(fields('SQS.Queue', 'queue', {
    'QueueName': 'QueueName',
    'QueueUrl': 'QueueUrl',
    'FifoQueue': 'Attributes.FifoQueue',
    'MessageRetentionPeriod': 'Attributes.MessageRetentionPeriod',
}, norms={'FifoQueue': 'boolean', 'MessageRetentionPeriod': 'number'}, defaults={'FifoQueue': 'false'}))
FIELDS.update(fields('SQS.QueuePolicy', 'policy', {
    'PolicyDocument': 'Policy',
    'Queues[]': 'Queues',
}, norms={'PolicyDocument': 'policy', 'Queues[]': 'id'}))
FIELDS['SQS.QueuePolicy.Id'] = unavailable('SQS has no independent QueuePolicy resource ID; GetQueueAttributes returns only the queue policy document.')


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind=='SQS.Queue':
        name=r.value('QueueName')
        url=ctx.call('sqs','get_queue_url',QueueName=name,QueueOwnerAWSAccountId=ctx.target['awsAccountId'])['QueueUrl']
        return {'QueueName':name,'QueueUrl':url,**ctx.call('sqs','get_queue_attributes',QueueUrl=url,AttributeNames=['All'])}
    queues=[r.parse(row,'id') for _,row in r.rows_for('Queues[]')]
    urls=[url for value in queues for url in (value if isinstance(value,list) else [value])]
    documents=[ctx.call('sqs','get_queue_attributes',QueueUrl=url,AttributeNames=['Policy']).get('Attributes',{}).get('Policy',MISSING) for url in urls]
    if not documents:
        raise Unresolved('queue policy has no queue relationship')
    from model_aws_compare import policy, stable
    if len({stable(policy(v)) for v in documents if v!=MISSING})>1 or any(v==MISSING for v in documents):
        raise Unresolved('associated queues have missing or different policies')
    return {'Queues':urls,'Policy':documents[0]}

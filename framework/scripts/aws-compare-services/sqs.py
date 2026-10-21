"""sqs: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import MISSING, Unresolved

APIS = {('sqs', 'get_queue_url'), ('sqs', 'get_queue_attributes')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind=='SQS.Queue':
        name=r.value('QueueName')
        url=ctx.call('sqs','get_queue_url',QueueName=name,QueueOwnerAWSAccountId=ctx.target.get('awsExecutionAccountId',ctx.target['awsAccountId']))['QueueUrl']
        return {'QueueName':name,'QueueUrl':url,**ctx.call('sqs','get_queue_attributes',QueueUrl=url,AttributeNames=['All'])}
    queues=[r.parse(row,'id') for _,row in r.rows_for('Queues[]')]
    urls=[url for value in queues for url in (value if isinstance(value,list) else [value])]
    documents=[ctx.call('sqs','get_queue_attributes',QueueUrl=url,AttributeNames=['Policy']).get('Attributes',{}).get('Policy',MISSING) for url in urls]
    if not documents:
        raise Unresolved('queue policy has no queue relationship')
    from model.adapters.aws import policy, stable
    if len({stable(policy(v)) for v in documents if v!=MISSING})>1 or any(v==MISSING for v in documents):
        raise Unresolved('associated queues have missing or different policies')
    return {'Queues':urls,'Policy':documents[0]}

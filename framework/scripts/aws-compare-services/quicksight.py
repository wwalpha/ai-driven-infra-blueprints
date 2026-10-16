"""quicksight: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import Unresolved

APIS = {('quicksight', 'describe_vpc_connection'), ('quicksight', 'describe_data_source_permissions'), ('quicksight', 'describe_data_source')}


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

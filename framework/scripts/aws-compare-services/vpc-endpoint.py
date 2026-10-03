"""vpc-endpoint: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('EC2.VPCEndpoint',)
APIS = {('ec2', 'describe_vpc_endpoints')}
IDENTITIES = {'EC2.VPCEndpoint': ('base', 'VpcEndpointId', None, None)}
FIELDS = {}
FIELDS.update(fields('EC2.VPCEndpoint', 'base', {
    'DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint': 'DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint',
    'Id': 'VpcEndpointId',
    'IpAddressType': 'IpAddressType',
    'PolicyDocument': 'PolicyDocument',
    'PrivateDnsEnabled': 'PrivateDnsEnabled',
    'RouteTableIds': 'RouteTableIds',
    'SecurityGroupIds': 'Groups[].GroupId',
    'ServiceName': 'ServiceName',
    'SubnetIds': 'SubnetIds',
    'Tags[].Key': 'Tags[].Key',
    'Tags[].Value': 'Tags[].Value',
    'VpcEndpointType': 'VpcEndpointType',
    'VpcId': 'VpcId',
}, norms={'PolicyDocument': 'policy', 'VpcId': 'id', 'SecurityGroupIds': 'id', 'SubnetIds': 'id', 'RouteTableIds': 'id'}, defaults={'DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint': False}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    current = r.current('Id')
    if current:
        inputs = {'VpcEndpointIds':[current]}
    else:
        names = [(rid,row) for rid,row in r.rows if row['property'].endswith('Tags[].Key') and row['value'].strip('`') == 'Name']
        if len(names) != 1:
            raise Unresolved('endpoint requires confirmed ID or one Name tag')
        rows = r.rows; index = next(i for i,item in enumerate(rows) if item[0] == names[0][0])
        name = r.parse(rows[index+1][1])
        inputs = {'Filters':[{'Name':'tag:Name','Values':[name]},{'Name':'vpc-id','Values':[r.value('VpcId','id')]},{'Name':'service-name','Values':[r.value('ServiceName')]}]}
    return one(ctx.pages('ec2','describe_vpc_endpoints',**inputs).get('VpcEndpoints',[]), 'ec2.describe_vpc_endpoints')

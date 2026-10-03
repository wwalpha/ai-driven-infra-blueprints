"""vpc: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('EC2.FlowLog', 'EC2.RouteTable', 'EC2.Subnet', 'EC2.SubnetRouteTableAssociation', 'EC2.VPC')
APIS = {('ec2', 'describe_vpc_attribute'), ('ec2', 'describe_subnets'), ('ec2', 'describe_flow_logs'), ('ec2', 'describe_route_tables'), ('ec2', 'describe_vpcs')}
IDENTITIES = {'EC2.VPC': ('base', 'VpcId', None, 'Name'), 'EC2.Subnet': ('base', 'SubnetId', None, 'Name'), 'EC2.RouteTable': ('base', 'RouteTableId', None, 'Name'), 'EC2.FlowLog': ('base', 'FlowLogId', None, 'Name')}
FIELDS = {}
FIELDS.update(fields('EC2.VPC', 'base', {
    'CidrBlock': 'CidrBlock',
    'Name': 'NameTag',
    'VpcId': 'VpcId',
}))
FIELDS.update(fields('EC2.VPC', 'hostnames', {
    'EnableDnsHostnames': 'EnableDnsHostnames.Value',
}))
FIELDS.update(fields('EC2.VPC', 'support', {
    'EnableDnsSupport': 'EnableDnsSupport.Value',
}))
FIELDS.update(fields('EC2.Subnet', 'base', {
    'AvailabilityZone': 'AvailabilityZone',
    'CidrBlock': 'CidrBlock',
    'MapPublicIpOnLaunch': 'MapPublicIpOnLaunch',
    'Name': 'NameTag',
    'SubnetId': 'SubnetId',
    'VpcId': 'VpcId',
}, norms={'VpcId': 'id'}))
FIELDS.update(fields('EC2.SubnetRouteTableAssociation', 'association', {
    'RouteTableId': 'RouteTableId',
}, norms={'RouteTableId': 'id'}))
FIELDS.update(fields('EC2.RouteTable', 'base', {
    'Name': 'NameTag',
    'RouteTableId': 'RouteTableId',
    'VpcId': 'VpcId',
}, norms={'VpcId': 'id'}))
FIELDS.update(fields('EC2.FlowLog', 'base', {
    'DeliverLogsPermissionArn': 'DeliverLogsPermissionArn',
    'Id': 'FlowLogId',
    'LogDestinationType': 'LogDestinationType',
    'LogGroupName': 'LogGroupName',
    'MaxAggregationInterval': 'MaxAggregationInterval',
    'Name': 'NameTag',
    'ResourceId': 'ResourceId',
    'TrafficType': 'TrafficType',
}, norms={'DeliverLogsPermissionArn': 'arn', 'LogGroupName': 'name', 'ResourceId': 'id'}))
FIELDS.update(fields('EC2.FlowLog', 'resource_type', {
    'ResourceType': 'ResourceType',
}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter in {'hostnames','support'}:
        return ctx.call('ec2','describe_vpc_attribute',VpcId=r.identity(),Attribute='enableDnsHostnames' if getter == 'hostnames' else 'enableDnsSupport')
    if getter == 'association':
        records = ctx.pages('ec2','describe_route_tables',Filters=[{'Name':'association.subnet-id','Values':[r.identity()]}]).get('RouteTables',[])
        record = one([v for v in records if any(a.get('SubnetId') == r.identity() and a.get('AssociationState',{}).get('State','associated') == 'associated' for a in v.get('Associations',[]))], 'ec2.describe_route_tables')
        return {'RouteTableId':record['RouteTableId']}
    operations = {'EC2.VPC':('describe_vpcs','Vpcs','VpcId','VpcIds'),'EC2.Subnet':('describe_subnets','Subnets','SubnetId','SubnetIds'),'EC2.RouteTable':('describe_route_tables','RouteTables','RouteTableId','RouteTableIds'),'EC2.FlowLog':('describe_flow_logs','FlowLogs','Id','FlowLogIds')}
    op,collection,prop,argument = operations[r.kind]
    current = r.current(prop)
    if current:
        inputs = {argument:[current]}
    else:
        inputs = {'Filters':[{'Name':'tag:Name','Values':[r.value('Name')]}]}
        if r.kind == 'EC2.FlowLog':
            inputs['Filters'].append({'Name':'resource-id','Values':[r.value('ResourceId','id')]})
        elif r.kind != 'EC2.VPC' and r.rows_for('VpcId'):
            inputs['Filters'].append({'Name':'vpc-id','Values':[r.value('VpcId','id')]})
    record = dict(one(ctx.pages('ec2',op,**inputs).get(collection,[]), 'ec2.'+op))
    record['NameTag'] = one([v['Value'] for v in record.get('Tags',[]) if v['Key'] == 'Name'], 'ec2.'+op) if any(v['Key']=='Name' for v in record.get('Tags',[])) else MISSING
    if getter == 'resource_type':
        # ResourceId is returned by DescribeFlowLogs. Prefix is AWS's typed ID grammar.
        rid = record['ResourceId']
        kind = next((value for prefix,value in [('vpc-','VPC'),('subnet-','Subnet'),('eni-','NetworkInterface')] if rid.startswith(prefix)),None)
        if not kind:
            raise Unresolved('unknown SDK-confirmed flow log resource type')
        return {'ResourceType':kind}
    return record

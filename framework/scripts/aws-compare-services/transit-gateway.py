"""transit-gateway: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('EC2.TransitGatewayVpcAttachment',)
APIS = {('ec2', 'describe_transit_gateway_vpc_attachments')}
IDENTITIES = {'EC2.TransitGatewayVpcAttachment': ('base', 'TransitGatewayAttachmentId', None, None)}
FIELDS = {}
FIELDS.update(fields('EC2.TransitGatewayVpcAttachment', 'base', {
    'Id': 'TransitGatewayAttachmentId',
    'SubnetIds': 'SubnetIds',
    'TransitGatewayId': 'TransitGatewayId',
    'VpcId': 'VpcId',
}, norms={'VpcId': 'id', 'SubnetIds': 'id'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    current = r.current('Id')
    inputs = {'TransitGatewayAttachmentIds': [current]} if current else {'Filters': [{'Name':'vpc-id','Values':[r.value('VpcId','id')]}, {'Name':'transit-gateway-id','Values':[r.value('TransitGatewayId')]}]}
    return one(ctx.pages('ec2', 'describe_transit_gateway_vpc_attachments', **inputs).get('TransitGatewayVpcAttachments', []), 'ec2.describe_transit_gateway_vpc_attachments')

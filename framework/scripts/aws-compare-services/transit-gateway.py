"""transit-gateway: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import one

APIS = {('ec2', 'describe_transit_gateway_vpc_attachments')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    current = r.current('Id')
    inputs = {'TransitGatewayAttachmentIds': [current]} if current else {'Filters': [{'Name':'vpc-id','Values':[r.value('VpcId','id')]}, {'Name':'transit-gateway-id','Values':[r.value('TransitGatewayId')]}]}
    return one(ctx.pages('ec2', 'describe_transit_gateway_vpc_attachments', **inputs).get('TransitGatewayVpcAttachments', []), 'ec2.describe_transit_gateway_vpc_attachments')

"""vpc comparison contracts and projections."""

from policy_tables import literal
from utils.cloudformation.inputs import Blocked

REF_ATTRIBUTES = {'EC2.Subnet': 'SubnetId', 'EC2.VPC': 'VpcId', 'EC2.RouteTable': 'RouteTableId'}



NAME_TAG_KINDS = {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'}


def contexts(rows):
    types = [literal(row['value']) for _, row in rows if row['property'] == 'EC2.FlowLog.ResourceType']
    return {'ResourceId': {'ResourceType': types[0]}} if len(types) == 1 else {}


def reference_contract(path, attribute, context):
    if path != 'ResourceId':
        return NotImplemented
    if context.get('ResourceType') != 'VPC' or attribute not in {None, 'VpcId'}:
        raise Blocked('reference property contract unproven: EC2.FlowLog.ResourceId requires ResourceType=VPC')
    return 'EC2.VPC', 'VpcId'

CONTEXT_PROPERTIES = {'ResourceId': {'ResourceType'}}

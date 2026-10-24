"""vpc comparison contracts and projections."""

from utils.cloudformation.inputs import Blocked
from utils.reference_contracts import row_contexts

NAME_TAG_KINDS = {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'}


def contexts(rows):
    return row_contexts('EC2.FlowLog', rows)


def reference_contract(path, attribute, context):
    if path != 'ResourceId':
        return NotImplemented
    if context.get('ResourceType') != 'VPC' or attribute not in {None, 'VpcId'}:
        raise Blocked('reference property contract unproven: EC2.FlowLog.ResourceId requires ResourceType=VPC')
    return 'EC2.VPC', 'VpcId'

CONTEXT_PROPERTIES = {'ResourceId': {'ResourceType'}}

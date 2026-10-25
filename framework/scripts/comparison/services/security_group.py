"""security group comparison contracts and projections."""

import re

from utils.cloudformation.inputs import Blocked
from utils.iac_values import ResourceReference


def ref_attribute(vpc, resource_type):
    if isinstance(vpc, ResourceReference):
        confirmed = resource_type(vpc) == "EC2.VPC" and vpc["$attribute"] == "VpcId"
    else:
        confirmed = isinstance(vpc, str) and re.fullmatch(r"vpc-[0-9a-f]+", vpc)
    if not confirmed:
        raise Blocked(
            "SecurityGroup Ref requires a proven explicit VpcId; group name is not a group ID"
        )
    return "GroupId"


REF_PROPERTIES = {"EC2.SecurityGroup": "VpcId"}

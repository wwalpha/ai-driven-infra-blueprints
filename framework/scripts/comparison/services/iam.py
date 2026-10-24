"""iam comparison contracts and projections."""

import re

from design.policy_tables import POLICY_FORMATS
from utils.cloudformation.inputs import Blocked, condition_active
from utils.iac_values import ResourceReference, same, unordered_same

REF_ATTRIBUTES = {'IAM.Role': 'RoleName', 'IAM.InstanceProfile': 'InstanceProfileName', 'IAM.ManagedPolicy': 'PolicyArn'}




def managed_policy_roles(service, identity, stack, direct, *, stack_inputs, evaluate, reference_same, symbol):
    """Combine direct Roles with proven same-stack active Role attachments."""
    roles = evaluate(stack, direct)
    if not isinstance(roles, list):
        raise Blocked('ManagedPolicy Roles is not a proven list')
    roles = list(roles)
    policy = ResourceReference({'$resource': [service, identity], '$attribute': 'PolicyArn'})
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-role.html#cfn-iam-role-managedpolicyarns
    document, parameters, pseudo = stack_inputs[stack]
    for logical, definition in document.get('Resources', {}).items():
        if definition.get('Type') != 'AWS::IAM::Role' or not condition_active(document, parameters, pseudo, definition):
            continue
        attachments = evaluate(stack, definition.get('Properties', {}).get('ManagedPolicyArns', []))
        if not isinstance(attachments, list):
            raise Blocked('role ManagedPolicyArns is not a proven list')
        matches = [False if isinstance(item, str) and re.fullmatch(r'arn:aws[a-z-]*:iam::aws:policy/.+', item) else
                   reference_same(policy, item, 'IAM.Role', 'ManagedPolicyArns[]') for item in attachments]
        if any(result is None for result in matches) and not any(result is True for result in matches):
            raise Blocked('inverse role attachment identity is unproven')
        if any(result is True for result in matches):
            role = symbol(stack, logical)
            if not any(reference_same(role, item, 'IAM.ManagedPolicy', 'Roles[]') is True for item in roles):
                roles.append(role)
    return roles


def reference_compare(kind, left, right, path, reference):
    if (path.endswith('.Statement') and isinstance(left, list) and isinstance(right, list)
            and POLICY_FORMATS.get(kind + '.' + path.removesuffix('.Statement')) == 'statement'):
        return unordered_same(left, right, path=path, reference=reference)
    if (path.endswith('.Statement[].Action')
            and POLICY_FORMATS.get(kind + '.' + path.removesuffix('.Statement[].Action')) == 'statement'
            and (isinstance(left, str) and isinstance(right, list) or isinstance(left, list) and isinstance(right, str))):
        return same([left] if isinstance(left, str) else left, [right] if isinstance(right, str) else right)
    return NotImplemented

INVERSE_ROLES = ('IAM.ManagedPolicy', 'Roles')

"""Explicit comparison rule ownership; no dynamic discovery or service cross-imports."""

import re

import utils.cloudformation.inputs as _imports_cfn_inputs
from utils.reference_contracts import ARN_DEFAULTS, ARN_SHAPES, REF_ATTRIBUTES

from .services import (
    athena,
    cloudtrail,
    cloudwatch_logs,
    codebuild,
    codepipeline,
    events,
    glue,
    iam,
    kms,
    quicksight,
    s3,
    secrets_manager,
    security_group,
    vpc,
)

SERVICES = {
    'S3.Bucket': s3,
    'Logs.LogGroup': cloudwatch_logs,
    'KMS.Key': kms,
    'KMS.Alias': kms,
    'IAM.Role': iam,
    'IAM.InstanceProfile': iam,
    'IAM.ManagedPolicy': iam,
    'IAM.Policy': iam,
    'IAM.Group': iam,
    'IAM.User': iam,
    'EC2.Subnet': vpc,
    'EC2.VPC': vpc,
    'EC2.RouteTable': vpc,
    'EC2.FlowLog': vpc,
    'EC2.SecurityGroup': security_group,
    'EC2.SecurityGroupIngress': security_group,
    'EC2.SecurityGroupEgress': security_group,
    'CodeBuild.Project': codebuild,
    'Glue.Connection': glue,
    'Glue.SecurityConfiguration': glue,
    'Glue.Job': glue,
    'Glue.Crawler': glue,
    'Glue.Database': glue,
    'Glue.Table': glue,
    'Athena.WorkGroup': athena,
    'SecretsManager.Secret': secrets_manager,
    'CloudTrail.Trail': cloudtrail,
    'CodePipeline.Pipeline': codepipeline,
    'QuickSight.Group': quicksight,
    'QuickSight.DataSource': quicksight,
    'Events.Rule': events,
}


def rules(kind):
    return SERVICES.get(kind)


def ref_attribute(kind):
    return REF_ATTRIBUTES.get(kind)


def kms_forms(kind, path):
    return getattr(rules(kind), 'KMS_FORMS', {}).get(kind + '.' + path)


def hook(kind, name):
    return getattr(rules(kind), name, None)




def import_consumer(prop, kind, attribute):
    return (prop, kind, attribute) == hook(kind, 'IMPORT_CONSUMER')


def kms_format(value, resources):
    return kms.kms_format(value, resources)


def named_arn(kind, properties, pseudo, *, evaluate):
    """Concretize a proven Producer using the shared ARN identity contract."""
    Blocked = _imports_cfn_inputs.Blocked
    identifier, template, patterns = ARN_SHAPES[kind]
    fields = identifier if isinstance(identifier, dict) else {identifier: 'id'}
    components = {}
    for field, group in fields.items():
        explicit = properties
        for token in field.split('.'):
            explicit = explicit.get(token, ARN_DEFAULTS.get((kind, field))) if isinstance(explicit, dict) else None
        explicit = evaluate(explicit)
        if (not isinstance(explicit, str) or explicit in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}
                or re.fullmatch(patterns[group], explicit) is None
                or any(token in explicit for token in ('*', '?', '${', '{{resolve:'))):
            raise Blocked('ARN requires a valid explicit resource ' + field)
        components[group] = explicit
    provider = hook(kind, 'arn_components')
    if provider:
        components.update(provider(properties, evaluate))
    for group, field, pattern in [('partition', 'Partition', r'aws(?:-[a-z]+)*'),
                                 ('region', 'Region', r'[a-z]{2}(?:-[a-z]+)+-\d+'),
                                 ('account', 'AccountId', r'[0-9]{12}')]:
        if '{' + group + '}' not in template:
            continue
        value = pseudo.get('AWS::' + field)
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise Blocked('ARN requires a confirmed ' + field)
        if group in components and components[group] != value:
            raise Blocked('ARN identifier and confirmed ' + field + ' differ')
        components[group] = value
    return template.format(**components)


def compare_kms_forms(left, right, allowed, *, resolve_literal, format_of):
    return kms.compare_forms(left, right, allowed, resolve_literal=resolve_literal, format_of=format_of)

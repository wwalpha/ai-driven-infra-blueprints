"""Explicit comparison rule ownership; no dynamic discovery or service cross-imports."""

import re

import utils.cloudformation.inputs as _imports_cfn_inputs
from utils.reference_contracts import ARN_DEFAULTS, ARN_SHAPES, REF_ATTRIBUTES

from .services import (
    apigateway,
    athena,
    cloudtrail,
    cloudwatch_logs,
    codebuild,
    codepipeline,
    events,
    glue,
    iam,
    kms,
    network_firewall,
    quicksight,
    route53,
    s3,
    secrets_manager,
    security_group,
    vpc,
)

SERVICES = {
    'ApiGateway.DomainName': apigateway,
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
    'Route53.RecordSet': route53,
    'Events.Rule': events,
    'NetworkFirewall.RuleGroup': network_firewall,
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


def context_value(pseudo, group):
    field, pattern = {'partition': ('Partition', r'aws(?:-[a-z]+)*'),
                      'region': ('Region', r'[a-z]{2}(?:-[a-z]+)+-\d+'),
                      'account': ('AccountId', r'[0-9]{12}')}[group]
    value = pseudo.get('AWS::' + field)
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise _imports_cfn_inputs.Blocked('reference requires a confirmed ' + field)
    return value


def named_arn(kind, properties, pseudo, *, evaluate, schema, recorded=None):
    """Concretize a proven Producer using the shared ARN identity contract."""
    Blocked = _imports_cfn_inputs.Blocked
    identifier, template, patterns = ARN_SHAPES[kind]
    fields = identifier if isinstance(identifier, dict) else {identifier: 'id'}
    generated = [field for field in fields if any(
        ('/properties/' + field.replace('.', '/')).startswith(pointer.rstrip('/') + '/') or
        '/properties/' + field.replace('.', '/') == pointer for pointer in schema.get('readOnlyProperties', ()))]
    if generated:
        if recorded is None:
            raise Blocked('ARN requires a proven generated identifier: ' + ', '.join(generated))
    components = {}
    for field, group in fields.items():
        if field in generated:
            explicit = recorded(field)
        else:
            explicit = properties
            for token in field.split('.'):
                explicit = explicit.get(token, ARN_DEFAULTS.get((kind, field))) if isinstance(explicit, dict) else None
            explicit = evaluate(explicit)
        if (not isinstance(explicit, str) or explicit in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}
                or re.fullmatch(patterns[group], explicit) is None
                or any(token in explicit for token in ('*', '?', '${', '{{resolve:'))):
            raise Blocked(('attribute_format_unproven: recorded ARN identifier format: ' if field in generated else
                           'ARN requires a valid explicit resource ') + field)
        components[group] = explicit
    provider = hook(kind, 'arn_components')
    if provider:
        components.update(provider(properties, evaluate))
    for group in ('partition', 'region', 'account'):
        if '{' + group + '}' not in template:
            continue
        value = context_value(pseudo, group)
        if group in components and components[group] != value:
            raise Blocked('ARN identifier and confirmed ' + group + ' differ')
        components[group] = value
    return template.format(**components)


def compare_kms_forms(left, right, allowed, *, resolve_literal, format_of):
    return kms.compare_forms(left, right, allowed, resolve_literal=resolve_literal, format_of=format_of)

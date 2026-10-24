"""Explicit comparison rule ownership; no dynamic discovery or service cross-imports."""

import re

import utils.cloudformation.inputs as _imports_cfn_inputs

from .services import (
    athena,
    cloudtrail,
    cloudwatch_logs,
    codebuild,
    codecommit,
    codepipeline,
    events,
    glue,
    iam,
    kms,
    lambda_function,
    quicksight,
    route53,
    s3,
    secrets_manager,
    security_group,
    sqs,
    vpc,
)

SERVICES = {
    'S3.Bucket': s3,
    'Logs.LogGroup': cloudwatch_logs,
    'SQS.Queue': sqs,
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
    'Lambda.Function': lambda_function,
    'CodeCommit.Repository': codecommit,
    'Route53.HostedZone': route53,
    'Glue.Connection': glue,
    'Glue.SecurityConfiguration': glue,
    'Glue.Job': glue,
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
    return getattr(rules(kind), 'REF_ATTRIBUTES', {}).get(kind)


def kms_forms(kind, path):
    return getattr(rules(kind), 'KMS_FORMS', {}).get(kind + '.' + path)


def hook(kind, name):
    return getattr(rules(kind), name, None)




def special_attribute(kind, attribute):
    return (kind, attribute) in getattr(rules(kind), 'SPECIAL_ATTRIBUTES', set())


def sub_arn(kind):
    return kind in getattr(rules(kind), 'SUB_ARN_KINDS', set())


def import_consumer(prop, kind, attribute):
    return (prop, kind, attribute) == hook(kind, 'IMPORT_CONSUMER')


def kms_format(value, resources):
    return kms.kms_format(value, resources)


def literal_arn(kind, mode, properties, pseudo, *, resolve_attribute, substitute, reference):
    if kind == 'S3.Bucket':
        return s3.literal_arn(resolve_attribute('BucketName'), pseudo, mode)
    if kind == 'Lambda.Function':
        return lambda_function.literal_arn(properties, pseudo, substitute, reference)
    return NotImplemented


def named_arn(kind, properties, pseudo, *, evaluate):

    Blocked = _imports_cfn_inputs.Blocked
    field, pattern, service, prefix, suffix = hook(kind, 'NAMED_ARN')
    explicit = evaluate(properties.get(field))
    if not isinstance(explicit, str) or not re.fullmatch(pattern, explicit):
        raise Blocked('ARN requires a valid explicit resource name')
    validator = hook(kind, 'validate_arn_context')
    if validator:
        validator(properties, evaluate)
    return f"arn:{pseudo['AWS::Partition']}:{service}:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:{prefix}{explicit}{suffix}"


def compare_kms_forms(left, right, allowed, *, resolve_literal, format_of):
    return kms.compare_forms(left, right, allowed, resolve_literal=resolve_literal, format_of=format_of)

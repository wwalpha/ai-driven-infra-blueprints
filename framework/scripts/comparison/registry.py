"""Explicit comparison rule ownership; no dynamic discovery or service cross-imports."""

from utils.arn_values import context_value as context_value
from utils.arn_values import named_arn as named_arn
from utils.reference_contracts import REF_ATTRIBUTES

from .services import (
    athena,
    cloudtrail,
    cloudwatch_logs,
    codebuild,
    codepipeline,
    glue,
    iam,
    kms,
    quicksight,
    route53,
    s3,
    secrets_manager,
    security_group,
    vpc,
)

SERVICES = {
    "S3.Bucket": s3,
    "Logs.LogGroup": cloudwatch_logs,
    "KMS.Key": kms,
    "KMS.Alias": kms,
    "IAM.Role": iam,
    "IAM.InstanceProfile": iam,
    "IAM.ManagedPolicy": iam,
    "IAM.Policy": iam,
    "IAM.Group": iam,
    "IAM.User": iam,
    "EC2.Subnet": vpc,
    "EC2.VPC": vpc,
    "EC2.RouteTable": vpc,
    "EC2.FlowLog": vpc,
    "EC2.SecurityGroup": security_group,
    "EC2.SecurityGroupIngress": security_group,
    "EC2.SecurityGroupEgress": security_group,
    "CodeBuild.Project": codebuild,
    "Glue.Connection": glue,
    "Glue.SecurityConfiguration": glue,
    "Glue.Job": glue,
    "Glue.Crawler": glue,
    "Glue.Database": glue,
    "Glue.Table": glue,
    "Athena.WorkGroup": athena,
    "SecretsManager.Secret": secrets_manager,
    "CloudTrail.Trail": cloudtrail,
    "CodePipeline.Pipeline": codepipeline,
    "QuickSight.Group": quicksight,
    "QuickSight.DataSource": quicksight,
    "Route53.RecordSet": route53,
}


def rules(kind):
    return SERVICES.get(kind)


def ref_attribute(kind):
    return REF_ATTRIBUTES.get(kind)


def kms_forms(kind, path):
    return getattr(rules(kind), "KMS_FORMS", {}).get(kind + "." + path)


def hook(kind, name):
    return getattr(rules(kind), name, None)


def import_consumer(prop, kind, attribute):
    return (prop, kind, attribute) == hook(kind, "IMPORT_CONSUMER")


def kms_format(value, resources, *, project_arn=None):
    return kms.kms_format(value, resources, project_arn=project_arn)


def compare_kms_forms(
    left, right, allowed, *, resolve_literal, format_of, project_arn=None
):
    return kms.compare_forms(
        left,
        right,
        allowed,
        resolve_literal=resolve_literal,
        format_of=format_of,
        project_arn=project_arn,
    )

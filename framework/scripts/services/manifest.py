"""Explicit registration list. Each service declares its own capabilities."""

from . import (
    api_gateway,
    api_gatewayv2,
    athena,
    auto_scaling,
    certificate_manager,
    cloudfront,
    cloudtrail,
    cloudwatch,
    codebuild,
    codecommit,
    codepipeline,
    config,
    datazone,
    dynamodb,
    ec2,
    ecr,
    ecs,
    elastic_load_balancing_v2,
    events,
    fms,
    glue,
    guardduty,
    iam,
    kinesis_firehose,
    kms,
    lakeformation,
    lambda_,
    logs,
    macie,
    mwaa,
    network_firewall,
    organizations,
    quicksight,
    rds,
    route53,
    route53_resolver,
    s3,
    sagemaker,
    scheduler,
    secrets_manager,
    security_hub,
    sns,
    sqs,
    ssm,
    sso,
    wafv2,
)
from .contracts import ServiceDefinition

DECLARATIONS = (
    api_gateway.DECLARATION,
    api_gatewayv2.DECLARATION,
    athena.DECLARATION,
    auto_scaling.DECLARATION,
    certificate_manager.DECLARATION,
    cloudfront.DECLARATION,
    cloudtrail.DECLARATION,
    cloudwatch.DECLARATION,
    codebuild.DECLARATION,
    codecommit.DECLARATION,
    codepipeline.DECLARATION,
    config.DECLARATION,
    datazone.DECLARATION,
    dynamodb.DECLARATION,
    ec2.DECLARATION,
    ecr.DECLARATION,
    ecs.DECLARATION,
    elastic_load_balancing_v2.DECLARATION,
    events.DECLARATION,
    fms.DECLARATION,
    glue.DECLARATION,
    guardduty.DECLARATION,
    iam.DECLARATION,
    kinesis_firehose.DECLARATION,
    kms.DECLARATION,
    lakeformation.DECLARATION,
    lambda_.DECLARATION,
    logs.DECLARATION,
    macie.DECLARATION,
    mwaa.DECLARATION,
    network_firewall.DECLARATION,
    organizations.DECLARATION,
    quicksight.DECLARATION,
    rds.DECLARATION,
    route53.DECLARATION,
    route53_resolver.DECLARATION,
    s3.DECLARATION,
    sagemaker.DECLARATION,
    scheduler.DECLARATION,
    secrets_manager.DECLARATION,
    security_hub.DECLARATION,
    sns.DECLARATION,
    sqs.DECLARATION,
    ssm.DECLARATION,
    sso.DECLARATION,
    wafv2.DECLARATION,
)

TYPE_FORMS = {
    kind: forms
    for service in DECLARATIONS
    for kind, forms in service.tables.type_forms.items()
}
FORMAT_NAMES = {
    kind: forms
    for service in DECLARATIONS
    for kind, forms in service.tables.format_names.items()
}
SERVICES: tuple[ServiceDefinition, ...] = tuple(
    service.build(TYPE_FORMS, FORMAT_NAMES) for service in DECLARATIONS
)

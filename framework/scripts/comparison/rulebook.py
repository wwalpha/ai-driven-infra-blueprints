"""Static service rules; runtime comparison never reads Catalogs or schemas.

Named container rules declare recursive typed contents. Named descendant paths
(including [] elements) override the method without expanding Model selection.
"""

import re

from .rules import (
    api_gateway,
    api_gatewayv2,
    athena,
    auto_scaling,
    certificate_manager,
    cloud_front,
    cloud_trail,
    cloud_watch,
    code_build,
    code_commit,
    code_pipeline,
    config,
    data_zone,
    dynamodb,
    ec2,
    ecr,
    ecs,
    elastic_load_balancingv2,
    events,
    fms,
    glue,
    guard_duty,
    iam,
    kinesis_firehose,
    kms,
    lake_formation,
    lambda_function,
    logs,
    macie,
    mwaa,
    network_firewall,
    organizations,
    quick_sight,
    rds,
    route53,
    route53_resolver,
    s3,
    sage_maker,
    scheduler,
    secrets_manager,
    security_hub,
    sns,
    sqs,
    ssm,
    sso,
    wafv2,
)

RULES = {
    **api_gateway.RULES,
    **api_gatewayv2.RULES,
    **athena.RULES,
    **auto_scaling.RULES,
    **certificate_manager.RULES,
    **cloud_front.RULES,
    **cloud_trail.RULES,
    **cloud_watch.RULES,
    **code_build.RULES,
    **code_commit.RULES,
    **code_pipeline.RULES,
    **config.RULES,
    **data_zone.RULES,
    **dynamodb.RULES,
    **ec2.RULES,
    **ecr.RULES,
    **ecs.RULES,
    **elastic_load_balancingv2.RULES,
    **events.RULES,
    **fms.RULES,
    **glue.RULES,
    **guard_duty.RULES,
    **iam.RULES,
    **kms.RULES,
    **kinesis_firehose.RULES,
    **lake_formation.RULES,
    **lambda_function.RULES,
    **logs.RULES,
    **mwaa.RULES,
    **macie.RULES,
    **network_firewall.RULES,
    **organizations.RULES,
    **quick_sight.RULES,
    **rds.RULES,
    **route53.RULES,
    **route53_resolver.RULES,
    **s3.RULES,
    **sns.RULES,
    **sqs.RULES,
    **ssm.RULES,
    **sso.RULES,
    **sage_maker.RULES,
    **scheduler.RULES,
    **secrets_manager.RULES,
    **security_hub.RULES,
    **wafv2.RULES,
}


def rules(kind):
    try:
        return RULES[kind]
    except KeyError as error:
        raise ValueError(f"Framework comparison rule missing: {kind}") from error


def require(kind, path):
    path = re.sub(r"\[\d+\]", "[]", path)
    try:
        return rules(kind)[path]
    except KeyError as error:
        raise ValueError(f"Framework comparison rule missing: {kind}.{path}") from error

"""Static registrations for offline adapter contracts."""

from model.importing.adapter_contract_cases.services import (
    athena,
    cloudtrail,
    cloudwatch_logs,
    codebuild,
    codecommit,
    codepipeline,
    config,
    data_firehose,
    datazone,
    ec2,
    eventbridge,
    glue,
    guardduty,
    iam,
    kms,
    lake_formation,
    lambda_,
    macie,
    mwaa,
    quicksight,
    route53,
    s3,
    secrets_manager,
    security_group,
    security_hub,
    sqs,
    transit_gateway,
    vpc,
    vpc_endpoint,
)


def _collect(groups):
    contracts = {}
    for group in groups:
        for key, fixture, operation, selectors, *additional in group:
            if key in contracts:
                raise ValueError(f"Duplicate adapter fixture registration: {key}")
            contracts[key] = (
                fixture,
                operation,
                selectors,
                additional[0] if additional else (),
            )
    return contracts


CONTRACTS = _collect(
    (
        athena.CONTRACTS,
        cloudtrail.CONTRACTS,
        cloudwatch_logs.CONTRACTS,
        codebuild.CONTRACTS,
        codecommit.CONTRACTS,
        codepipeline.CONTRACTS,
        config.CONTRACTS,
        data_firehose.CONTRACTS,
        datazone.CONTRACTS,
        ec2.CONTRACTS,
        eventbridge.CONTRACTS,
        glue.CONTRACTS,
        guardduty.CONTRACTS,
        iam.CONTRACTS,
        kms.CONTRACTS,
        lake_formation.CONTRACTS,
        lambda_.CONTRACTS,
        macie.CONTRACTS,
        mwaa.CONTRACTS,
        quicksight.CONTRACTS,
        route53.CONTRACTS,
        s3.CONTRACTS,
        secrets_manager.CONTRACTS,
        security_group.CONTRACTS,
        security_hub.CONTRACTS,
        sqs.CONTRACTS,
        transit_gateway.CONTRACTS,
        vpc.CONTRACTS,
        vpc_endpoint.CONTRACTS,
    )
)

"""Explicit fixed-data registry; service modules are the sole definition owners."""

from design.services.definitions import (
    api_gateway,
    cloudtrail,
    codebuild,
    codecommit,
    codepipeline,
    config,
    dynamodb,
    ec2,
    ecr,
    events,
    glue,
    guardduty,
    iam,
    kinesis_firehose,
    kms,
    lambda_permission,
    logs,
    macie,
    organizations,
    quicksight,
    s3,
    secrets_manager,
    sns,
    sqs,
    sso,
)

SERVICES = (
    api_gateway,
    cloudtrail,
    codebuild,
    codecommit,
    codepipeline,
    config,
    dynamodb,
    ec2,
    ecr,
    events,
    glue,
    guardduty,
    iam,
    kinesis_firehose,
    kms,
    lambda_permission,
    logs,
    macie,
    organizations,
    quicksight,
    s3,
    secrets_manager,
    sns,
    sqs,
    sso,
)


def merge_definitions(services, name):
    result = {}
    for service in services:
        values = getattr(service, name, {})
        for key in values:
            if key in result:
                raise ValueError(f"duplicate {name} definition: {key}")
            if isinstance(values, dict):
                result[key] = values[key]
            else:
                result[key] = None
    return result


POLICY_FORMATS = dict(
    sorted(
        merge_definitions(SERVICES, "POLICY_FORMATS").items(),
        key=lambda item: (item[1] == "settings", item[0]),
    )
)
RESOURCE_REFERENCE_PROPERTIES = merge_definitions(
    SERVICES, "RESOURCE_REFERENCE_PROPERTIES"
)
HIDDEN_PROPERTIES = set(merge_definitions(SERVICES, "HIDDEN_PROPERTIES"))
REQUIRED_NAME_TAG_TYPES = set(merge_definitions(SERVICES, "REQUIRED_NAME_TAG_TYPES"))
COMPACT_FIELDS = merge_definitions(SERVICES, "COMPACT_FIELDS")
PACKED_ARRAY_PREFIXES = tuple(merge_definitions(SERVICES, "PACKED_ARRAY_PREFIXES"))
IMPORT_PENDING_PROPERTIES = set(
    merge_definitions(SERVICES, "IMPORT_PENDING_PROPERTIES")
)

"""cloudtrail reference declarations."""

import re

from utils.comparison_rows import put_row

from ..reference_data import ReferenceTables


def row_contexts(rows):
    kind = "CloudTrail.Trail"
    contexts = {}
    for index, (_, row) in enumerate(rows):
        prop = row["property"].removeprefix(kind + ".")
        value = row["value"]
        value = value[1:-1] if value.startswith("`") and value.endswith("`") else value
        if match := re.fullmatch(r"(.*\.DataResources\[\d+\])\.Type", prop):
            put_row(contexts.setdefault(match[1], {}), "Type", value)
        if (
            prop.endswith(".DataResources[].Type")
            and index + 1 < len(rows)
            and rows[index + 1][1]["property"]
            == row["property"].removesuffix("Type") + "Values"
        ):
            contexts[rows[index + 1][0]] = {"Type": value}
    return contexts


REFERENCES = ReferenceTables(
    ref_attributes={
        "CloudTrail.Trail": "TrailName",
    },
    reference_forms={
        "CloudTrail.Trail.KMSKeyId": {"KeyId", "Arn", "AliasName"},
    },
    reference_properties={
        "CloudTrail.Trail.S3BucketName": ("S3.Bucket", "BucketName"),
    },
    import_properties={
        "CloudTrail.Trail.SnsTopicName": ("SNS.Topic", "TopicName"),
        "CloudTrail.Trail.KMSKeyId": (("KMS.Key", "KMS.Alias"), None),
        "CloudTrail.Trail.CloudWatchLogsRoleArn": ("IAM.Role", "Arn"),
        "CloudTrail.Trail.CloudWatchLogsLogGroupArn": ("Logs.LogGroup", "Arn"),
    },
    arn_shapes={
        "CloudTrail.Trail": (
            "TrailName",
            "arn:{partition}:cloudtrail:{region}:{account}:trail/{id}",
            {"id": r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}"},
        ),
    },
    context_properties={
        "CloudTrail.Trail.EventSelectors[].DataResources[].Values": (
            "CloudTrail.Trail.EventSelectors[].DataResources[].Type",
            {
                "AWS::S3::Object": ("S3.Bucket", "ObjectArn"),
                "AWS::Lambda::Function": ("Lambda.Function", "Arn"),
            },
        ),
    },
    default_on_mismatch={
        "CloudTrail.Trail.EventSelectors[].DataResources[].Values[]",
    },
    context_suffixes={"CloudTrail.Trail": (".DataResources[]",)},
    row_contexts={"CloudTrail.Trail": row_contexts},
)

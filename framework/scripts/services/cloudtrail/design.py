"""Fixed cloudtrail design definitions; no display-engine dependencies."""

import re

ARRAY_DATA_RESOURCE = re.compile(
    r"EventSelectors\.DataResources\[[1-9]\d*\]\.(S3|Lambda)$"
)
ARRAY_DATA_RESOURCE_PREFIX = re.compile(r"EventSelectors\.DataResources\[[1-9]\d*\]")
ARRAY_DATA_RESOURCE_TEMPLATE = "EventSelectors[].DataResources[]"
COMPACT_ARRAY = re.compile(r"DataResources\[\]\.(?:S3|Lambda)$")

COMPACT_FIELDS = {
    "CloudTrail.Trail.EventSelectors[].DataResources[].Type": (
        ("Type", "Values"),
        "Values",
    ),
}

CLOUDTRAIL_DATA_RESOURCE = re.compile(
    r"^EventSelectors\.DataResources\[([1-9]\d*)\]\.(S3|Lambda)$"
)

CLOUDTRAIL_RESOURCE_TYPES = {"S3": "AWS::S3::Object", "Lambda": "AWS::Lambda::Function"}

CLOUDTRAIL_FORMAL_DATA_RESOURCE = "CloudTrail.Trail.EventSelectors[].DataResources[]."

"""Static CloudTrail comparison methods; container rules include their recursive contents."""

import re
from functools import partial

from model.display import display_rows
from utils.comparison_rows import Unresolved
from utils.reference_contracts import row_contexts

from ..contracts import ResourceContract
from ..methods import OBJECT, properties


def cloudtrail_rows(rows, *, index_rows):
    """Project fixed Model row identities through the lossless indexed display."""
    kind = "CloudTrail.Trail"
    prefix = kind + ".EventSelectors[]"
    selected = [
        (rid, row) for rid, row in rows if row["property"].startswith(prefix + ".")
    ]
    if not any(".DataResources[]" in row["property"] for _, row in selected):
        return rows
    # Model entries have fixed IDs; the caller's list order is not membership evidence.
    if len(dict(selected)) != len(selected) or any(
        not re.fullmatch(r".+-[0-9]+", rid) for rid, _ in selected
    ):
        raise Unresolved(
            "array membership unresolved: EventSelectors; fixed Model row identities required"
        )
    canonical = sorted(selected)
    if any(
        row["property"].startswith(kind + ".EventSelectors")
        and not row["property"].startswith(prefix + ".")
        for _, row in rows
    ):
        raise Unresolved(
            "array membership unresolved: EventSelectors; mixed whole/indexed/wildcard rows"
        )
    try:
        displayed = index_rows(
            display_rows(
                kind,
                [
                    [rid, row["property"], row["value"], row.get("comment", "")]
                    for rid, row in canonical
                ],
            ),
            kind,
        )
    except ValueError as error:
        raise Unresolved(
            f"array membership unresolved: EventSelectors; {error}"
        ) from error
    partners = {
        rid: canonical[index + 1][0]
        for index, (rid, row) in enumerate(canonical)
        if row["property"] == prefix + ".DataResources[].Type"
    }
    properties = {}
    for rid, prop, _, _ in displayed:
        if rid in properties:
            raise Unresolved(
                "array membership unresolved: EventSelectors; display row maps to multiple elements"
            )
        data = re.fullmatch(
            r"(EventSelectors\[[1-9]\d*\]\.DataResources\[[1-9]\d*\])\.(S3|Lambda)",
            prop,
        )
        if data:
            properties[rid] = kind + "." + data[1] + ".Type"
            properties[partners[rid]] = kind + "." + data[1] + ".Values"
        else:
            values = re.fullmatch(
                r"(EventSelectors\[[1-9]\d*\]\.DataResources\[[1-9]\d*\]\.Values)\[1\]",
                prop,
            )
            if (
                values
                and dict(canonical)[rid]["property"]
                == prefix + ".DataResources[].Values"
            ):
                prop = values[1]
            properties[rid] = kind + "." + prop
    for rid, partner in partners.items():
        if properties.get(rid, "").removesuffix(".Type") != properties.get(
            partner, ""
        ).removesuffix(".Values"):
            raise Unresolved(
                "array membership unresolved: EventSelectors; incomplete Type/Values pair"
            )
    if properties.keys() != dict(canonical).keys():
        raise Unresolved(
            "array membership unresolved: EventSelectors; incomplete display-to-Model mapping"
        )
    return [
        (rid, dict(row, property=properties[rid]) if rid in properties else row)
        for rid, row in rows
    ]


RULES = {
    "CloudTrail.Trail": properties(
        resource=ResourceContract(
            prepare_rows=cloudtrail_rows,
            deferred_rows="EventSelectors",
            contexts=partial(row_contexts, "CloudTrail.Trail"),
        ),
        objects="""
            AdvancedEventSelectors[]
            AdvancedEventSelectors[].FieldSelectors[]
            EventSelectors[]
            EventSelectors[].DataResources[]
            InsightSelectors[]
            Tags[]
        """,
        ordered="""
            AdvancedEventSelectors
            AdvancedEventSelectors[].FieldSelectors
            AdvancedEventSelectors[].FieldSelectors[].EndsWith
            AdvancedEventSelectors[].FieldSelectors[].Equals
            AdvancedEventSelectors[].FieldSelectors[].NotEndsWith
            AdvancedEventSelectors[].FieldSelectors[].NotEquals
            AdvancedEventSelectors[].FieldSelectors[].NotStartsWith
            AdvancedEventSelectors[].FieldSelectors[].StartsWith
            EventSelectors
            EventSelectors[].DataResources
            EventSelectors[].DataResources[].Values
            EventSelectors[].ExcludeManagementEventSources
            InsightSelectors
            InsightSelectors[].EventCategories
        """,
        references="""
            KMSKeyId
            S3BucketName
        """,
        scalars="""
            AdvancedEventSelectors[].FieldSelectors[].Field
            AdvancedEventSelectors[].Name
            CloudWatchLogsLogGroupArn
            CloudWatchLogsRoleArn
            EnableLogFileValidation
            EventSelectors[].DataResources[].Type
            EventSelectors[].IncludeManagementEvents
            EventSelectors[].ReadWriteType
            IncludeGlobalServiceEvents
            InsightSelectors[].InsightType
            IsLogging
            IsMultiRegionTrail
            IsOrganizationTrail
            S3KeyPrefix
            SnsTopicName
            Tags[].Key
            Tags[].Value
            TrailName
        """,
        tags="""
            Tags
        """,
    ),
}


RULES["CloudTrail.Trail"]["EventSelectors[].DataResources[].Values[]"] = OBJECT

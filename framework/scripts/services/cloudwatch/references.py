"""CloudWatch reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "CloudWatch.Alarm": "AlarmName",
        "CloudWatch.Dashboard": "DashboardName",
    },
    arn_shapes={
        "CloudWatch.Alarm": (
            "AlarmName",
            "arn:{partition}:cloudwatch:{region}:{account}:alarm:{id}",
            {"id": r"[^:*?\x00-\x1f]{1,255}"},
        ),
        "CloudWatch.Dashboard": (
            "DashboardName",
            "arn:{partition}:cloudwatch::{account}:dashboard/{id}",
            {"id": r"[A-Za-z0-9_-]{1,255}"},
        ),
    },
)

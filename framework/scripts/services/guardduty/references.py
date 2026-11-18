"""GuardDuty reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "GuardDuty.Detector": "Id",
    },
    reference_properties={
        "GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.BucketName": (
            "S3.Bucket",
            "BucketName",
        ),
    },
    import_properties={
        "GuardDuty.MalwareProtectionPlan.Role": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "GuardDuty.Detector": (
            "Id",
            "arn:{partition}:guardduty:{region}:{account}:detector/{id}",
            {"id": r"[a-f0-9]{32}"},
        ),
    },
)

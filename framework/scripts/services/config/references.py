"""Config reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "Config.ConfigRule": "ConfigRuleName",
        "Config.ConfigurationRecorder": "Name",
        "Config.DeliveryChannel": "Name",
    },
    getatt_attributes={
        "Config.ConfigurationRecorder": {"ResourceARN"},
    },
    return_types={
        ("Config.ConfigurationRecorder", "ResourceARN"): "string",
    },
    arn_attributes={
        "Config.ConfigurationRecorder": "ResourceARN",
    },
    import_properties={
        "Config.DeliveryChannel.S3BucketName": ("S3.Bucket", "BucketName"),
        "Config.DeliveryChannel.SnsTopicARN": ("SNS.Topic", "Arn"),
        "Config.ConfigurationRecorder.RoleARN": ("IAM.Role", "Arn"),
    },
)

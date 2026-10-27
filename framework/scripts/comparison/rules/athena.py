"""Static Athena comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from utils.reference_contracts import KMS_FORMS

from ..methods import REFERENCE, properties
from .kms import compare_forms

RULES = {
    "Athena.WorkGroup": properties(
        objects="""
            Tags[]
            WorkGroupConfiguration
            WorkGroupConfiguration.EngineVersion
            WorkGroupConfiguration.ResultConfiguration
            WorkGroupConfiguration.ResultConfiguration.AclConfiguration
            WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration
        """,
        scalars="""
            Description
            Name
            State
            Tags[].Key
            Tags[].Value
            WorkGroupConfiguration.BytesScannedCutoffPerQuery
            WorkGroupConfiguration.EnforceWorkGroupConfiguration
            WorkGroupConfiguration.EngineVersion.SelectedEngineVersion
            WorkGroupConfiguration.PublishCloudWatchMetricsEnabled
            WorkGroupConfiguration.RequesterPaysEnabled
            WorkGroupConfiguration.ResultConfiguration.AclConfiguration.S3AclOption
            WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.EncryptionOption
            WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner
            WorkGroupConfiguration.ResultConfiguration.OutputLocation
        """,
        tags="""
            Tags
        """,
    ),
}

_path = "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey"
RULES["Athena.WorkGroup"][_path] = replace(
    REFERENCE, forms=KMS_FORMS["Athena.WorkGroup." + _path], form_compare=compare_forms
)

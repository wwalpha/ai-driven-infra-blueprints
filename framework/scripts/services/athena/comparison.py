"""Static Athena comparison methods; container rules include their recursive contents."""

from dataclasses import replace
from functools import partial

from comparison.contracts import compare_producer_forms
from comparison.methods import REFERENCE, properties

from .references import REFERENCES

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
    REFERENCE,
    forms=REFERENCES.format_limits["Athena.WorkGroup." + _path],
    form_compare=partial(compare_producer_forms, "KMS.Key"),
)

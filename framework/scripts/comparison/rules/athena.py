"""Static Athena comparison methods; container rules include their recursive contents."""

from ..methods import properties

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
        references="""
            WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey
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

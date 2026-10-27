"""Static GuardDuty comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "GuardDuty.Detector": properties(
        objects="""
            DataSources
            DataSources.Kubernetes
            DataSources.Kubernetes.AuditLogs
            DataSources.MalwareProtection
            DataSources.MalwareProtection.ScanEc2InstanceWithFindings
            DataSources.S3Logs
            Features[]
            Features[].AdditionalConfiguration[]
            Tags[]
        """,
        ordered="""
            Features
            Features[].AdditionalConfiguration
        """,
        scalars="""
            DataSources.Kubernetes.AuditLogs.Enable
            DataSources.MalwareProtection.ScanEc2InstanceWithFindings.EbsVolumes
            DataSources.S3Logs.Enable
            Enable
            Features[].AdditionalConfiguration[].Name
            Features[].AdditionalConfiguration[].Status
            Features[].Name
            Features[].Status
            FindingPublishingFrequency
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "GuardDuty.MalwareProtectionPlan": properties(
        objects="""
            Actions
            Actions.Tagging
            ProtectedResource
            ProtectedResource.S3Bucket
            Tags[]
        """,
        ordered="""
            ProtectedResource.S3Bucket.ObjectPrefixes
        """,
        references="""
            ProtectedResource.S3Bucket.BucketName
        """,
        scalars="""
            Actions.Tagging.Status
            ProtectedResource.S3Bucket.ObjectPrefixes[]
            Role
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}

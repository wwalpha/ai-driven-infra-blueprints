"""Static ECR comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "ECR.Repository": properties(
        objects="""
            EncryptionConfiguration
            ImageScanningConfiguration
            ImageTagMutabilityExclusionFilters[]
            LifecyclePolicy
            RepositoryPolicyText
            Tags[]
        """,
        ordered="""
            ImageTagMutabilityExclusionFilters
        """,
        references="""
            EncryptionConfiguration.KmsKey
        """,
        scalars="""
            EmptyOnDelete
            EncryptionConfiguration.EncryptionType
            ImageScanningConfiguration.ScanOnPush
            ImageTagMutability
            ImageTagMutabilityExclusionFilters[].ImageTagMutabilityExclusionFilterType
            ImageTagMutabilityExclusionFilters[].ImageTagMutabilityExclusionFilterValue
            RepositoryName
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}

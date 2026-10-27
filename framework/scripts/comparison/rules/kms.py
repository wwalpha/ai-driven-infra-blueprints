"""Static KMS comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "KMS.Alias": properties(
        references="""
            TargetKeyId
        """,
        scalars="""
            AliasName
        """,
    ),
    "KMS.Key": properties(
        objects="""
            KeyPolicy
            Tags[]
        """,
        scalars="""
            BypassPolicyLockoutSafetyCheck
            Description
            EnableKeyRotation
            Enabled
            KeySpec
            KeyUsage
            MultiRegion
            Origin
            PendingWindowInDays
            RotationPeriodInDays
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}

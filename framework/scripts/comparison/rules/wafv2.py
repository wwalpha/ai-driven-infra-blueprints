"""Static WAFv2 comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "WAFv2.IPSet": properties(
        objects="""
            Tags[]
        """,
        ordered="""
            Addresses
        """,
        scalars="""
            Addresses[]
            Description
            IPAddressVersion
            Name
            Scope
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "WAFv2.LoggingConfiguration": properties(
        objects="""
            LoggingFilter
        """,
        ordered="""
            LogDestinationConfigs
            RedactedFields
        """,
        scalars="""
            LogDestinationConfigs[]
            ResourceArn
        """,
    ),
    "WAFv2.RuleGroup": properties(
        objects="""
            CustomResponseBodies
            MonetizationConfig
            Tags[]
            VisibilityConfig
        """,
        ordered="""
            Rules
        """,
        scalars="""
            Capacity
            Description
            Name
            Scope
            Tags[].Key
            Tags[].Value
            VisibilityConfig.CloudWatchMetricsEnabled
            VisibilityConfig.MetricName
            VisibilityConfig.SampledRequestsEnabled
        """,
        tags="""
            Tags
        """,
    ),
    "WAFv2.WebACL": properties(
        objects="""
            ApplicationConfig
            AssociationConfig
            CaptchaConfig
            CaptchaConfig.ImmunityTimeProperty
            ChallengeConfig
            ChallengeConfig.ImmunityTimeProperty
            CustomResponseBodies
            DataProtectionConfig
            DefaultAction
            MonetizationConfig
            OnSourceDDoSProtectionConfig
            Tags[]
            VisibilityConfig
        """,
        ordered="""
            Rules
            TokenDomains
        """,
        scalars="""
            CaptchaConfig.ImmunityTimeProperty.ImmunityTime
            ChallengeConfig.ImmunityTimeProperty.ImmunityTime
            Description
            Name
            Scope
            Tags[].Key
            Tags[].Value
            TokenDomains[]
            VisibilityConfig.CloudWatchMetricsEnabled
            VisibilityConfig.MetricName
            VisibilityConfig.SampledRequestsEnabled
        """,
        tags="""
            Tags
        """,
    ),
    "WAFv2.WebACLAssociation": properties(
        scalars="""
            ResourceArn
            WebACLArn
        """,
    ),
}

"""Static Route53 comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "Route53.HostedZone": properties(
        objects="""
            HostedZoneConfig
            HostedZoneTags[]
            QueryLoggingConfig
            VPCs[]
        """,
        ordered="""
            VPCs
        """,
        references="""
            VPCs[].VPCId
        """,
        scalars="""
            HostedZoneConfig.Comment
            HostedZoneTags[].Key
            HostedZoneTags[].Value
            Name
            QueryLoggingConfig.CloudWatchLogsLogGroupArn
            VPCs[].VPCRegion
        """,
        tags="""
            HostedZoneTags
        """,
    ),
    "Route53.RecordSet": properties(
        objects="""
            AliasTarget
            GeoLocation
        """,
        ordered="""
            ResourceRecords
        """,
        references="""
            HostedZoneId
        """,
        scalars="""
            AliasTarget.DNSName
            AliasTarget.EvaluateTargetHealth
            AliasTarget.HostedZoneId
            Comment
            Failover
            GeoLocation.ContinentCode
            GeoLocation.CountryCode
            GeoLocation.SubdivisionCode
            HealthCheckId
            HostedZoneName
            MultiValueAnswer
            Name
            Region
            SetIdentifier
            TTL
            Type
            Weight
        """,
    ),
}

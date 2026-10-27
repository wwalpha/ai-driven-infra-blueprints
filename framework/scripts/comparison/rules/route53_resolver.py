"""Static Route53Resolver comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "Route53Resolver.ResolverEndpoint": properties(
        objects="""
            IpAddresses[]
            Tags[]
        """,
        ordered="""
            IpAddresses
            Protocols
            SecurityGroupIds
        """,
        scalars="""
            Direction
            IpAddresses[].Ip
            IpAddresses[].SubnetId
            Name
            ResolverEndpointType
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "Route53Resolver.ResolverRule": properties(
        objects="""
            Tags[]
            TargetIps[]
        """,
        ordered="""
            TargetIps
        """,
        scalars="""
            DomainName
            Name
            ResolverEndpointId
            RuleType
            Tags[].Key
            Tags[].Value
            TargetIps[].Ip
            TargetIps[].Port
            TargetIps[].Protocol
            TargetIps[].ServerNameIndication
        """,
        tags="""
            Tags
        """,
    ),
    "Route53Resolver.ResolverRuleAssociation": properties(
        scalars="""
            Name
            ResolverRuleId
            VPCId
        """,
    ),
}

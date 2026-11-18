"""route53-resolver reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "Route53Resolver.ResolverRuleAssociation": "ResolverRuleAssociationId",
    },
    getatt_attributes={
        "Route53Resolver.ResolverEndpoint": {"Direction", "Name"},
        "Route53Resolver.ResolverRule": {
            "DomainName",
            "Name",
            "ResolverEndpointId",
            "TargetIps",
        },
        "Route53Resolver.ResolverRuleAssociation": {"Name", "ResolverRuleId", "VPCId"},
    },
    import_properties={
        "Route53Resolver.ResolverRuleAssociation.VPCId": ("EC2.VPC", "VpcId"),
        "Route53Resolver.ResolverEndpoint.IpAddresses[].SubnetId": (
            "EC2.Subnet",
            "SubnetId",
        ),
    },
)

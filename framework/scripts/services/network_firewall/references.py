"""network-firewall reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "NetworkFirewall.Firewall": "FirewallArn",
        "NetworkFirewall.FirewallPolicy": "FirewallPolicyArn",
        "NetworkFirewall.LoggingConfiguration": "FirewallArn",
        "NetworkFirewall.RuleGroup": "RuleGroupArn",
    },
    getatt_attributes={
        "NetworkFirewall.Firewall": {"NumberOfAssociations"},
    },
    return_types={
        ("NetworkFirewall.Firewall", "NumberOfAssociations"): "integer",
    },
    arn_attributes={
        "NetworkFirewall.Firewall": "FirewallArn",
        "NetworkFirewall.FirewallPolicy": "FirewallPolicyArn",
        "NetworkFirewall.RuleGroup": "RuleGroupArn",
        "NetworkFirewall.LoggingConfiguration": "FirewallArn",
    },
    import_properties={
        "NetworkFirewall.Firewall.SubnetMappings[].SubnetId": (
            "EC2.Subnet",
            "SubnetId",
        ),
        "NetworkFirewall.Firewall.VpcId": ("EC2.VPC", "VpcId"),
    },
    arn_shapes={
        "NetworkFirewall.Firewall": (
            "FirewallName",
            "arn:{partition}:network-firewall:{region}:{account}:firewall/{id}",
            {"id": r"[A-Za-z0-9-]{1,128}"},
        ),
        "NetworkFirewall.FirewallPolicy": (
            "FirewallPolicyName",
            "arn:{partition}:network-firewall:{region}:{account}:firewall-policy/{id}",
            {"id": r"[A-Za-z0-9-]{1,128}"},
        ),
        "NetworkFirewall.RuleGroup": (
            "RuleGroupName",
            "arn:{partition}:network-firewall:{region}:{account}:{type}-rulegroup/{id}",
            {"id": r"[A-Za-z0-9-]{1,128}", "type": r"(?:stateful|stateless)"},
        ),
    },
    arn_components={"NetworkFirewall.RuleGroup": ("Type",)},
    arn_without_forms=frozenset(("NetworkFirewall.RuleGroup",)),
)

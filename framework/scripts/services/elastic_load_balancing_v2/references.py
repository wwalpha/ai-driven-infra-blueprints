"""ElasticLoadBalancingV2 reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "ElasticLoadBalancingV2.Listener": "ListenerArn",
        "ElasticLoadBalancingV2.ListenerRule": "RuleArn",
        "ElasticLoadBalancingV2.LoadBalancer": "LoadBalancerArn",
        "ElasticLoadBalancingV2.TargetGroup": "TargetGroupArn",
    },
    getatt_attributes={
        "ElasticLoadBalancingV2.LoadBalancer": {"SecurityGroups"},
    },
    arn_attributes={
        "ElasticLoadBalancingV2.Listener": "ListenerArn",
        "ElasticLoadBalancingV2.ListenerRule": "RuleArn",
        "ElasticLoadBalancingV2.LoadBalancer": "LoadBalancerArn",
        "ElasticLoadBalancingV2.TargetGroup": "TargetGroupArn",
    },
    linked_subnets={
        "ElasticLoadBalancingV2.LoadBalancer.Subnets[]",
    },
    reference_properties={
        "ElasticLoadBalancingV2.LoadBalancer.SecurityGroups[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "ElasticLoadBalancingV2.TargetGroup.VpcId": ("EC2.VPC", "VpcId"),
    },
    import_properties={
        "ElasticLoadBalancingV2.LoadBalancer.SubnetMappings[].SubnetId": (
            "EC2.Subnet",
            "SubnetId",
        ),
    },
)

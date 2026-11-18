"""ECS reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("ECS.Service", "Name"): "ServiceName",
    },
    ref_attributes={
        "ECS.Cluster": "ClusterName",
        "ECS.CapacityProvider": "Name",
        "ECS.Service": "ServiceArn",
        "ECS.TaskDefinition": "TaskDefinitionArn",
        "ECS.ClusterCapacityProviderAssociations": "ClusterName",
    },
    arn_attributes={
        "ECS.Service": "ServiceArn",
        "ECS.TaskDefinition": "TaskDefinitionArn",
    },
    linked_subnets={
        "ECS.CapacityProvider.ManagedInstancesProvider.InstanceLaunchTemplate.NetworkConfiguration.Subnets[]",
        "ECS.Service.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
    },
    reference_forms={
        "ECS.TaskDefinition.TaskRoleArn": {"RoleName", "Arn"},
        "ECS.Service.Cluster": {"ClusterName", "Arn"},
        "ECS.Service.Role": {"RoleName", "Arn"},
    },
    reference_properties={
        "ECS.Service.NetworkConfiguration.AwsvpcConfiguration.SecurityGroups[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "ECS.CapacityProvider.ManagedInstancesProvider.InstanceLaunchTemplate.NetworkConfiguration.SecurityGroups[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
    },
    import_properties={
        "ECS.Service.CapacityProviderStrategy[].CapacityProvider": (
            "ECS.CapacityProvider",
            "Name",
        ),
        "ECS.Service.TaskDefinition": ("ECS.TaskDefinition", "Arn"),
        "ECS.Service.Cluster": ("ECS.Cluster", "ClusterName"),
        "ECS.Service.LoadBalancers[].TargetGroupArn": (
            "ElasticLoadBalancingV2.TargetGroup",
            "Arn",
        ),
        "ECS.Cluster.Configuration.ExecuteCommandConfiguration.LogConfiguration.S3BucketName": (
            "S3.Bucket",
            "BucketName",
        ),
        "ECS.Service.DeploymentConfiguration.LifecycleHooks[].RoleArn": (
            "IAM.Role",
            "Arn",
        ),
        "ECS.Service.LoadBalancers[].AdvancedConfiguration.RoleArn": (
            "IAM.Role",
            "Arn",
        ),
        "ECS.Service.Role": ("IAM.Role", "RoleName"),
        "ECS.ClusterCapacityProviderAssociations.Cluster": (
            "ECS.Cluster",
            "ClusterName",
        ),
        "ECS.Service.LoadBalancers[].AdvancedConfiguration.ProductionListenerRule": (
            ("ElasticLoadBalancingV2.Listener", "ElasticLoadBalancingV2.ListenerRule"),
            "Arn",
        ),
        "ECS.Service.LoadBalancers[].AdvancedConfiguration.TestListenerRule": (
            ("ElasticLoadBalancingV2.Listener", "ElasticLoadBalancingV2.ListenerRule"),
            "Arn",
        ),
        "ECS.Service.LoadBalancers[].AdvancedConfiguration.AlternateTargetGroupArn": (
            "ElasticLoadBalancingV2.TargetGroup",
            "Arn",
        ),
        "ECS.TaskDefinition.TaskRoleArn": ("IAM.Role", "Arn"),
        "ECS.TaskDefinition.ExecutionRoleArn": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "ECS.Cluster": (
            "ClusterName",
            "arn:{partition}:ecs:{region}:{account}:cluster/{id}",
            {"id": r"[A-Za-z0-9_-]{1,255}"},
        ),
        "ECS.CapacityProvider": (
            "Name",
            "arn:{partition}:ecs:{region}:{account}:capacity-provider/{id}",
            {"id": r"[A-Za-z0-9_-]{1,255}"},
        ),
    },
    unproven_document={
        "ECS.TaskDefinition": (
            "ECS.TaskDefinition.ContainerDefinitions[].Secrets[].ValueFrom",
        )
    },
)

"""RDS reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "RDS.DBCluster": "DBClusterIdentifier",
        "RDS.DBInstance": "DBInstanceIdentifier",
        "RDS.DBClusterParameterGroup": "DBClusterParameterGroupName",
        "RDS.DBParameterGroup": "DBParameterGroupName",
        "RDS.DBProxy": "DBProxyName",
        "RDS.DBProxyEndpoint": "DBProxyEndpointName",
        "RDS.DBSubnetGroup": "DBSubnetGroupName",
        "RDS.OptionGroup": "OptionGroupName",
        "RDS.DBProxyTargetGroup": "TargetGroupArn",
    },
    getatt_attributes={
        "RDS.DBInstance": {"DBSystemId"},
        "RDS.DBParameterGroup": {"DBParameterGroupName"},
    },
    arn_attributes={
        "RDS.DBCluster": "DBClusterArn",
        "RDS.DBInstance": "DBInstanceArn",
        "RDS.DBParameterGroup": "DBParameterGroupArn",
        "RDS.DBSubnetGroup": "DBSubnetGroupArn",
        "RDS.DBProxy": "DBProxyArn",
        "RDS.DBProxyEndpoint": "DBProxyEndpointArn",
        "RDS.DBProxyTargetGroup": "TargetGroupArn",
    },
    linked_subnets={
        "RDS.DBProxy.VpcSubnetIds[]",
        "RDS.DBProxyEndpoint.VpcSubnetIds[]",
        "RDS.DBSubnetGroup.SubnetIds[]",
    },
    reference_forms={
        "RDS.DBCluster.PerformanceInsightsKmsKeyId": {"KeyId", "Arn", "AliasName"},
    },
    reference_properties={
        "RDS.DBInstance.VPCSecurityGroups[]": ("EC2.SecurityGroup", "GroupId"),
        "RDS.DBCluster.VpcSecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
        "RDS.DBProxy.VpcSecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
        "RDS.DBProxyEndpoint.VpcSecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
    },
    import_properties={
        "RDS.DBProxy.Auth[].SecretArn": ("SecretsManager.Secret", "Arn"),
        "RDS.DBProxy.RoleArn": ("IAM.Role", "Arn"),
        "RDS.DBCluster.AssociatedRoles[].RoleArn": ("IAM.Role", "Arn"),
        "RDS.DBInstance.AssociatedRoles[].RoleArn": ("IAM.Role", "Arn"),
        "RDS.DBCluster.DBInstanceParameterGroupName": (
            "RDS.DBParameterGroup",
            "DBParameterGroupName",
        ),
        "RDS.DBCluster.DomainIAMRoleName": ("IAM.Role", "RoleName"),
        "RDS.DBInstance.DomainIAMRoleName": ("IAM.Role", "RoleName"),
        "RDS.DBCluster.MonitoringRoleArn": ("IAM.Role", "Arn"),
        "RDS.DBInstance.MonitoringRoleArn": ("IAM.Role", "Arn"),
        "RDS.DBCluster.PerformanceInsightsKmsKeyId": (("KMS.Key", "KMS.Alias"), None),
        "RDS.DBInstance.DomainAuthSecretArn": ("SecretsManager.Secret", "Arn"),
        "RDS.DBCluster.DBClusterParameterGroupName": (
            "RDS.DBClusterParameterGroup",
            "DBClusterParameterGroupName",
        ),
        "RDS.DBInstance.DBParameterGroupName": (
            "RDS.DBParameterGroup",
            "DBParameterGroupName",
        ),
        "RDS.DBCluster.DBSubnetGroupName": ("RDS.DBSubnetGroup", "DBSubnetGroupName"),
        "RDS.DBInstance.DBSubnetGroupName": ("RDS.DBSubnetGroup", "DBSubnetGroupName"),
    },
    arn_shapes={
        "RDS.DBCluster": (
            "DBClusterIdentifier",
            "arn:{partition}:rds:{region}:{account}:cluster:{id}",
            {"id": r"[a-z][a-z0-9-]{0,62}"},
        ),
        "RDS.DBInstance": (
            "DBInstanceIdentifier",
            "arn:{partition}:rds:{region}:{account}:db:{id}",
            {"id": r"[a-z][a-z0-9-]{0,62}"},
        ),
        "RDS.DBClusterParameterGroup": (
            "DBClusterParameterGroupName",
            "arn:{partition}:rds:{region}:{account}:cluster-pg:{id}",
            {"id": r"[a-z][a-z0-9-]{0,254}"},
        ),
        "RDS.DBParameterGroup": (
            "DBParameterGroupName",
            "arn:{partition}:rds:{region}:{account}:pg:{id}",
            {"id": r"[a-z][a-z0-9-]{0,254}"},
        ),
        "RDS.DBSubnetGroup": (
            "DBSubnetGroupName",
            "arn:{partition}:rds:{region}:{account}:subgrp:{id}",
            {"id": r"[a-z][a-z0-9._ -]{0,254}"},
        ),
        "RDS.OptionGroup": (
            "OptionGroupName",
            "arn:{partition}:rds:{region}:{account}:og:{id}",
            {"id": r"[a-z][a-z0-9-]{0,254}"},
        ),
    },
)

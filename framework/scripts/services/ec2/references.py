"""ec2 reference declarations."""

from ..reference_data import ReferenceTables


def row_contexts(rows):
    types = [
        row["value"].strip("`")
        for _, row in rows
        if row["property"] == "EC2.FlowLog.ResourceType"
    ]
    return {"ResourceId": {"ResourceType": types[0]}} if len(types) == 1 else {}


REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("EC2.SecurityGroup", "GroupId"): "Id",
    },
    ref_attributes={
        "EC2.Subnet": "SubnetId",
        "EC2.VPC": "VpcId",
        "EC2.VPCCidrBlock": "Id",
        "EC2.RouteTable": "RouteTableId",
        "EC2.Instance": "InstanceId",
        "EC2.FlowLog": "Id",
        "EC2.GatewayRouteTableAssociation": "AssociationId",
        "EC2.InternetGateway": "InternetGatewayId",
        "EC2.VPNGateway": "VPNGatewayId",
        "EC2.LaunchTemplate": "LaunchTemplateId",
        "EC2.NatGateway": "NatGatewayId",
        "EC2.VPCEndpoint": "Id",
        "EC2.TransitGateway": "Id",
        "EC2.EIP": "PublicIp",
        "EC2.SubnetRouteTableAssociation": "Id",
        "EC2.TransitGatewayRouteTable": "TransitGatewayRouteTableId",
        "EC2.TransitGatewayVpcAttachment": "Id",
        "EC2.VPCBlockPublicAccessExclusion": "ExclusionId",
        "EC2.VPCBlockPublicAccessOptions": "AccountId",
        "EC2.TransitGatewayRouteTablePropagation": "TransitGatewayRouteTableId",
        "EC2.Route": "Ref",
        "EC2.SecurityGroupEgress": "Ref",
        "EC2.TransitGatewayRoute": "Ref",
        "EC2.TransitGatewayRouteTableAssociation": "Ref",
        "EC2.VPCGatewayAttachment": "Ref",
    },
    getatt_attributes={
        "EC2.SecurityGroup": {"VpcId"},
        "EC2.Subnet": {
            "AvailabilityZone",
            "AvailabilityZoneId",
            "CidrBlock",
            "OutpostArn",
            "VpcId",
        },
        "EC2.VPC": {"CidrBlock"},
    },
    arn_attributes={
        "EC2.TransitGateway": "TransitGatewayArn",
    },
    linked_subnets={
        "EC2.TransitGatewayVpcAttachment.SubnetIds",
        "EC2.VPCEndpoint.SubnetIds",
    },
    type_forms={
        "EC2.InternetGateway": {"InternetGatewayId", "Arn"},
        "EC2.VPNGateway": {"VPNGatewayId"},
    },
    reference_forms={
        "EC2.GatewayRouteTableAssociation.GatewayId": {
            "InternetGatewayId",
            "VPNGatewayId",
        },
        "EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId": {
            "KeyId",
            "Arn",
            "AliasName",
        },
    },
    reference_properties={
        "EC2.Instance.BlockDeviceMappings[].Ebs.KmsKeyId": (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
        "EC2.Instance.IamInstanceProfile": (
            "IAM.InstanceProfile",
            "InstanceProfileName",
        ),
        "EC2.Instance.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
        "EC2.Instance.SubnetId": ("EC2.Subnet", "SubnetId"),
        "EC2.SecurityGroup.SecurityGroupIngress[].SourceSecurityGroupId": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "EC2.SecurityGroup.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.SecurityGroup.SecurityGroupEgress[].DestinationSecurityGroupId": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "EC2.SecurityGroupIngress.GroupId": ("EC2.SecurityGroup", "GroupId"),
        "EC2.SecurityGroupIngress.SourceSecurityGroupId": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "EC2.SecurityGroupEgress.GroupId": ("EC2.SecurityGroup", "GroupId"),
        "EC2.SecurityGroupEgress.DestinationSecurityGroupId": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "EC2.Subnet.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.TransitGatewayVpcAttachment.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.SubnetRouteTableAssociation.RouteTableId": (
            "EC2.RouteTable",
            "RouteTableId",
        ),
        "EC2.GatewayRouteTableAssociation.GatewayId": (
            ("EC2.InternetGateway", "EC2.VPNGateway"),
            ("InternetGatewayId", "VPNGatewayId"),
        ),
        "EC2.GatewayRouteTableAssociation.RouteTableId": (
            "EC2.RouteTable",
            "RouteTableId",
        ),
        "EC2.VPCCidrBlock.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.RouteTable.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.FlowLog.LogGroupName": ("Logs.LogGroup", "LogGroupName"),
        "EC2.VPCEndpoint.RouteTableIds[]": ("EC2.RouteTable", "RouteTableId"),
        "EC2.VPCEndpoint.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.VPCEndpoint.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
        "EC2.VPCEndpoint.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    },
    import_properties={
        "EC2.VPCBlockPublicAccessExclusion.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.VPCBlockPublicAccessExclusion.SubnetId": ("EC2.Subnet", "SubnetId"),
        "EC2.VPCGatewayAttachment.VpcId": ("EC2.VPC", "VpcId"),
        "EC2.Instance.NetworkInterfaces[].SubnetId": ("EC2.Subnet", "SubnetId"),
        "EC2.LaunchTemplate.LaunchTemplateData.NetworkInterfaces[].SubnetId": (
            "EC2.Subnet",
            "SubnetId",
        ),
        "EC2.NatGateway.SubnetId": ("EC2.Subnet", "SubnetId"),
        "EC2.SubnetRouteTableAssociation.SubnetId": ("EC2.Subnet", "SubnetId"),
        "EC2.FlowLog.DeliverCrossAccountRole": ("IAM.Role", "Arn"),
        "EC2.FlowLog.DeliverLogsPermissionArn": ("IAM.Role", "Arn"),
        "EC2.Route.VpcEndpointId": ("EC2.VPCEndpoint", "Id"),
    },
    arn_shapes={
        "EC2.EIP": (
            "AllocationId",
            "arn:{partition}:ec2:{region}:{account}:elastic-ip/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.FlowLog": (
            "Id",
            "arn:{partition}:ec2:{region}:{account}:vpc-flow-log/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.Instance": (
            "InstanceId",
            "arn:{partition}:ec2:{region}:{account}:instance/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.InternetGateway": (
            "InternetGatewayId",
            "arn:{partition}:ec2:{region}:{account}:internet-gateway/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.LaunchTemplate": (
            "LaunchTemplateId",
            "arn:{partition}:ec2:{region}:{account}:launch-template/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.NatGateway": (
            "NatGatewayId",
            "arn:{partition}:ec2:{region}:{account}:natgateway/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.RouteTable": (
            "RouteTableId",
            "arn:{partition}:ec2:{region}:{account}:route-table/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.SecurityGroup": (
            "GroupId",
            "arn:{partition}:ec2:{region}:{account}:security-group/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.Subnet": (
            "SubnetId",
            "arn:{partition}:ec2:{region}:{account}:subnet/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.TransitGatewayRouteTable": (
            "TransitGatewayRouteTableId",
            "arn:{partition}:ec2:{region}:{account}:transit-gateway-route-table/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.TransitGatewayVpcAttachment": (
            "Id",
            "arn:{partition}:ec2:{region}:{account}:transit-gateway-attachment/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.VPC": (
            "VpcId",
            "arn:{partition}:ec2:{region}:{account}:vpc/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.VPCBlockPublicAccessExclusion": (
            "ExclusionId",
            "arn:{partition}:ec2:{region}:{account}:vpc-block-public-access-exclusion/{id}",
            {"id": "[a-z0-9-]+"},
        ),
        "EC2.VPCEndpoint": (
            "Id",
            "arn:{partition}:ec2:{region}:{account}:vpc-endpoint/{id}",
            {"id": "[a-z0-9-]+"},
        ),
    },
    context_properties={
        "EC2.FlowLog.ResourceId": (
            "EC2.FlowLog.ResourceType",
            {"VPC": ("EC2.VPC", "VpcId")},
        ),
    },
    context_paths={"EC2.FlowLog": ("EC2.FlowLog",)},
    row_contexts={"EC2.FlowLog": row_contexts},
)

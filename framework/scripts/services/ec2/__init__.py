"""ec2 service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..import_contracts import DerivedInventory, ImportProfile, inventory_handler
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.ec2.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "ec2",
    (
        "EC2.EIP",
        "EC2.FlowLog",
        "EC2.Instance",
        "EC2.InternetGateway",
        "EC2.LaunchTemplate",
        "EC2.NatGateway",
        "EC2.Route",
        "EC2.RouteTable",
        "EC2.SecurityGroup",
        "EC2.SecurityGroupEgress",
        "EC2.SecurityGroupIngress",
        "EC2.Subnet",
        "EC2.SubnetRouteTableAssociation",
        "EC2.TransitGateway",
        "EC2.TransitGatewayRoute",
        "EC2.TransitGatewayRouteTable",
        "EC2.TransitGatewayRouteTableAssociation",
        "EC2.TransitGatewayRouteTablePropagation",
        "EC2.TransitGatewayVpcAttachment",
        "EC2.VPC",
        "EC2.VPCBlockPublicAccessExclusion",
        "EC2.VPCBlockPublicAccessOptions",
        "EC2.VPCEndpoint",
        "EC2.VPCGatewayAttachment",
    ),
    REFERENCES,
    design=design,
    displays={
        "EC2.VPC": partial(load_display, "EC2.VPC"),
        "EC2.Subnet": partial(load_display, "EC2.Subnet"),
        "EC2.RouteTable": partial(load_display, "EC2.RouteTable"),
        "EC2.FlowLog": partial(load_display, "EC2.FlowLog"),
        "EC2.Instance": partial(load_display, "EC2.Instance"),
        "EC2.VPCEndpoint": partial(load_display, "EC2.VPCEndpoint"),
        "EC2.SecurityGroup": partial(load_display, "EC2.SecurityGroup"),
        "EC2.SecurityGroupIngress": partial(load_display, "EC2.SecurityGroupIngress"),
        "EC2.SecurityGroupEgress": partial(load_display, "EC2.SecurityGroupEgress"),
    },
    aws_adapters={
        "ec2": "aws",
        "security-group": "aws_security_group",
        "transit-gateway": "aws_transit_gateway",
        "vpc-endpoint": "aws_vpc_endpoint",
        "vpc": "aws_vpc",
    },
    import_profiles={
        "EC2.VPC": ImportProfile(
            adapter=("ec2", "describe_vpcs", "Vpcs"),
            name_tag=True,
            decorate=inventory_handler("services.ec2.inventory", "name_tag"),
        ),
        "EC2.Subnet": ImportProfile(
            adapter=("ec2", "describe_subnets", "Subnets"),
            name_tag=True,
            dependencies=("EC2.RouteTable",),
            decorate=inventory_handler("services.ec2.inventory", "name_tag"),
            related_fields=(
                ("association", "EC2.SubnetRouteTableAssociation.RouteTableId"),
            ),
        ),
        "EC2.RouteTable": ImportProfile(
            adapter=("ec2", "describe_route_tables", "RouteTables"),
            name_tag=True,
            decorate=inventory_handler("services.ec2.inventory", "name_tag"),
            related_records=inventory_handler(
                "services.ec2.inventory", "subnet_associations"
            ),
        ),
        "EC2.FlowLog": ImportProfile(
            adapter=("ec2", "describe_flow_logs", "FlowLogs"),
            name_tag=True,
            decorate=inventory_handler("services.ec2.inventory", "name_tag"),
            derived_getters=inventory_handler(
                "services.ec2.inventory", "flow_log_getters"
            ),
        ),
        "EC2.TransitGatewayVpcAttachment": ImportProfile(
            adapter=(
                "ec2",
                "describe_transit_gateway_vpc_attachments",
                "TransitGatewayVpcAttachments",
            ),
            decorate=inventory_handler("services.ec2.inventory", "name_tag"),
        ),
        "EC2.SubnetRouteTableAssociation": ImportProfile(
            derived=DerivedInventory(
                parents=("EC2.RouteTable", "EC2.Subnet"),
                reason_code="SUBNET_ASSOCIATION_EXPANSION",
                reason="Route table associations attach to selected subnets; no independent candidates",
                unavailable_reason="Existing expansion requires SDK route-table and subnet inventories",
                identity_code="DERIVED_ASSOCIATION_ID",
                identity_reason="RouteTableAssociationId is retained; association is attached by SubnetId, never independently published",
                identity_paths=(
                    "Associations[].RouteTableAssociationId",
                    "Associations[].SubnetId",
                ),
                components=("RouteTableAssociationId", "SubnetId"),
                attach=inventory_handler(
                    "services.ec2.inventory", "attach_subnet_association"
                ),
            ),
        ),
    },
)

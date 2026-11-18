"""ec2 service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
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
)

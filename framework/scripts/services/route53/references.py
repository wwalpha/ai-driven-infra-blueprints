"""route53 reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    split_reference_operands={
        f"Route53.RecordSet.{path}": (
            "EC2.VPCEndpoint",
            "DnsEntries",
            "Endpoint DNS extraction requires EC2.VPCEndpoint.DnsEntries",
        )
        for path in ("ResourceRecords", "ResourceRecords[]", "AliasTarget.DNSName")
    },
    ref_attributes={
        "Route53.HostedZone": "Id",
        "Route53.RecordSet": "Name",
    },
    reference_properties={
        "Route53.HostedZone.VPCs[].VPCId": ("EC2.VPC", "VpcId"),
        "Route53.RecordSet.HostedZoneId": ("Route53.HostedZone", "Id"),
    },
    import_properties={
        "Route53.HostedZone.QueryLoggingConfig.CloudWatchLogsLogGroupArn": (
            "Logs.LogGroup",
            "Arn",
        ),
    },
    arn_shapes={
        "Route53.HostedZone": (
            "Id",
            "arn:{partition}:route53:::hostedzone/{id}",
            {"id": "[A-Z0-9]+"},
        ),
    },
)

"""Offline discovery selection shared by acquisition and capability diagnostics."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from utils.mapping_types import Property, Registry

SchemaLookup = Callable[[str], Mapping[str, Any]]


# Existing adapter discovery optimizations; every other Mapping type uses provider discovery.
ADAPTER_INVENTORIES = {
    "EC2.VPC": ("ec2", "describe_vpcs", "Vpcs"),
    "EC2.Subnet": ("ec2", "describe_subnets", "Subnets"),
    "EC2.RouteTable": ("ec2", "describe_route_tables", "RouteTables"),
    "EC2.FlowLog": ("ec2", "describe_flow_logs", "FlowLogs"),
    "EC2.TransitGatewayVpcAttachment": (
        "ec2",
        "describe_transit_gateway_vpc_attachments",
        "TransitGatewayVpcAttachments",
    ),
    "Config.ConfigurationRecorder": (
        "config",
        "describe_configuration_recorders",
        "ConfigurationRecorders",
    ),
    "Config.DeliveryChannel": (
        "config",
        "describe_delivery_channels",
        "DeliveryChannels",
    ),
    "CodeBuild.Project": ("codebuild", "list_projects", "projects"),
    "Macie.ClassificationJob": ("macie2", "list_classification_jobs", "items"),
    "Logs.LogGroup": ("logs", "describe_log_groups", "logGroups"),
    "QuickSight.DataSource": ("quicksight", "list_data_sources", "DataSources"),
    "QuickSight.VPCConnection": (
        "quicksight",
        "list_vpc_connections",
        "VPCConnectionSummaries",
    ),
    "KinesisFirehose.DeliveryStream": (
        "firehose",
        "list_delivery_streams",
        "DeliveryStreamNames",
    ),
    "SecurityHub.Hub": ("securityhub", "describe_hub", None),
}


@dataclass(frozen=True)
class ScopedInventory:
    api: str
    operations: tuple[str, ...]
    payload: tuple[str, str]
    components: tuple[str, ...]
    selectors: tuple[str, ...] = ()


SCOPED_INVENTORIES = {
    "QuickSight.Group": ScopedInventory(
        "quicksight",
        ("list_namespaces", "list_groups"),
        ("list_groups", "GroupList[]"),
        ("AwsAccountId", "Namespace", "GroupName"),
        ("AwsAccountId", "Namespace"),
    ),
    "Glue.Table": ScopedInventory(
        "glue",
        ("get_catalogs", "get_databases", "get_tables"),
        ("get_tables", "TableList[]"),
        ("CatalogId", "DatabaseName", "TableInput.Name"),
        ("CatalogId", "DatabaseName"),
    ),
    "LakeFormation.Resource": ScopedInventory(
        "lakeformation",
        ("list_resources", "describe_resource"),
        ("describe_resource", "ResourceInfo"),
        ("ResourceArn",),
    ),
    "DataZone.Project": ScopedInventory(
        "datazone",
        ("list_domains", "list_projects", "get_project"),
        ("get_project", "$"),
        ("DomainId", "Id"),
    ),
    "SQS.QueuePolicy": ScopedInventory(
        "sqs",
        ("get_queue_attributes",),
        ("get_queue_attributes", "Attributes"),
        ("Queues[]",),
        ("Queues[]",),
    ),
}


def adapter_detail(kind: str) -> tuple[str, str, str] | None:
    """Existing inventory detail envelopes, shared with offline shape inspection."""
    if kind == "KinesisFirehose.DeliveryStream":
        return (
            "describe_delivery_stream",
            "DeliveryStreamName",
            "DeliveryStreamDescription",
        )
    if kind == "CodeBuild.Project":
        return "batch_get_projects", "names", "projects[]"
    if kind == "Macie.ClassificationJob":
        return "describe_classification_job", "jobId", "$"
    if kind == "QuickSight.DataSource":
        return "describe_data_source", "DataSourceId", "DataSource"
    if kind == "QuickSight.VPCConnection":
        return "describe_vpc_connection", "VPCConnectionId", "VPCConnection"
    return None


@dataclass(frozen=True)
class DiscoveryPlan:
    mode: str
    status: str
    reason_code: str
    reason: str
    required_filters: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()


def type_name(kind: str) -> str:
    return "AWS::" + kind.replace(".", "::", 1)


def required_filters(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = (
        schema.get("handlers", {})
        .get("list", {})
        .get("handlerSchema", {})
        .get("required", ())
    )
    if (
        not isinstance(required, (list, tuple))
        or any(not isinstance(name, str) or not name for name in required)
        or len(set(required)) != len(required)
    ):
        raise ValueError("Invalid CloudFormation List required filters")
    return tuple(required)


def filter_parents(
    kinds: Sequence[str], kind: str, required: Sequence[str], schema: SchemaLookup
) -> tuple[str, ...]:
    """Keep the runtime's exact same-owner, ordered primary-identifier rule."""
    return tuple(
        parent
        for parent in kinds
        if parent != kind
        and tuple(schema(parent).get("primaryIdentifier", ()))
        == tuple("/properties/" + name for name in required)
        and not required_filters(schema(parent))
    )


def resolve(
    mapping: Registry,
    properties: Mapping[str, Property],
    kind: str,
    schema: SchemaLookup | None = None,
) -> DiscoveryPlan:
    """Omit schema inspection at runtime: existing execution owns failures/statuses.

    Schema inspection is offline and never changes the selected execution branch.
    Adapter readiness still needs payload/identity checks in Coverage.
    """
    if not any(
        p.include for key, p in properties.items() if key.startswith(kind + ".")
    ):
        return DiscoveryPlan(
            "not_modelled",
            "not_modelled",
            "NO_MODEL_PROPERTIES",
            "No model.include properties",
        )
    if kind in SCOPED_INVENTORIES:
        return DiscoveryPlan(
            "scoped_sdk",
            "uncertain",
            "SCOPED_SDK_INVENTORY",
            "SDK inventory preserves parent selectors and composite identity",
            parents=("SQS.Queue",) if kind == "SQS.QueuePolicy" else (),
        )
    if kind in ADAPTER_INVENTORIES and kind in mapping.identities:
        return DiscoveryPlan(
            "adapter",
            "uncertain",
            "ADAPTER_REGISTERED",
            "SDK inventory selected; payload and identity require inspection",
        )
    if (
        kind == "EC2.SubnetRouteTableAssociation"
        and "EC2.RouteTable" in mapping.resource_types
    ):
        return DiscoveryPlan(
            "parent_derived",
            "uncertain",
            "SUBNET_ASSOCIATION_EXPANSION",
            "Route table associations attach to selected subnets; no independent candidates",
            parents=("EC2.RouteTable", "EC2.Subnet"),
        )
    if schema is None:
        return DiscoveryPlan(
            "cloudcontrol",
            "uncertain",
            "PROVIDER_DISCOVERY",
            "Cloud Control fallback selected; provider capabilities not inspected",
        )
    try:
        definition = schema(kind)
    except KeyError:
        return DiscoveryPlan(
            "unsupported",
            "unsupported",
            "SCHEMA_UNSUPPORTED",
            "No CloudFormation schema and no executable SDK inventory/identity pair",
        )
    if "list" not in definition.get("handlers", {}):
        return DiscoveryPlan(
            "unsupported",
            "unsupported",
            "LIST_UNSUPPORTED",
            "CloudFormation schema has no List handler; SDK inventory/identity pair unavailable",
        )
    handler_schema = definition["handlers"]["list"].get("handlerSchema", {})
    if any(
        key in handler_schema
        for key in (
            "$ref",
            "allOf",
            "anyOf",
            "oneOf",
            "if",
            "dependentRequired",
            "dependencies",
        )
    ):
        return DiscoveryPlan(
            "cloudcontrol",
            "uncertain",
            "LIST_CONDITIONS_UNCONFIRMED",
            "List handler has conditions not resolved by the existing required-filter builder",
        )
    required = required_filters(definition)
    if not required:
        return DiscoveryPlan(
            "cloudcontrol",
            "ready",
            "PROVIDER_LIST",
            "Cloud Control List has no required filters",
        )
    if kind == "Glue.Connection" and required == ("CatalogId",):
        return DiscoveryPlan(
            "cloudcontrol",
            "ready",
            "TARGET_ACCOUNT_FILTER",
            "CatalogId comes from the verified target account when execution and target accounts match",
            required,
        )
    try:
        parents = filter_parents(sorted(mapping.resource_types), kind, required, schema)
    except KeyError as error:
        return DiscoveryPlan(
            "cloudcontrol",
            "unsupported",
            "PARENT_SCHEMA_UNSUPPORTED",
            "Runtime parent search encounters an unsupported sibling schema: "
            + str(error),
            required,
        )
    if len(parents) != 1:
        return DiscoveryPlan(
            "cloudcontrol",
            "unsupported",
            "REQUIRED_FILTER_AMBIGUOUS" if parents else "REQUIRED_FILTER_UNRESOLVED",
            "Runtime requires exactly one same-owner parent with matching ordered primary identifiers",
            required,
            parents,
        )
    parent = resolve(mapping, properties, parents[0], schema)
    if parent.mode != "cloudcontrol" or parent.status != "ready":
        return DiscoveryPlan(
            "cloudcontrol",
            "unsupported",
            "PARENT_FILTER_UNAVAILABLE",
            "Parent cannot supply cloudProperties to the existing filter builder: "
            + parents[0]
            + " ("
            + parent.reason_code
            + ")",
            required,
            parents,
        )
    if "read" not in schema(parents[0]).get("handlers", {}):
        return DiscoveryPlan(
            "cloudcontrol",
            "uncertain",
            "PARENT_VALUES_UNCONFIRMED",
            "Parent List may omit identifier properties and no Read handler can fill them",
            required,
            parents,
        )
    return DiscoveryPlan(
        "cloudcontrol",
        "ready",
        "PARENT_FILTER",
        "Required filters derive from parent cloudProperties primary identifiers",
        required,
        parents,
    )

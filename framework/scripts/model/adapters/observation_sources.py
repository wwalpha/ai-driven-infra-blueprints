"""Select existing acquisition contracts for CloudFormation observations."""

import re

from aws_mapping import registry
from contracts.model import RESOURCE_TYPE_KEY
from utils.aws_mappings import owners
from utils.reference_contracts import REF_ATTRIBUTES


def cloudcontrol_source(root, catalog, resource, prop):
    kind = resource[RESOURCE_TYPE_KEY]
    owner = owners(root).get(kind)
    if not owner:
        return None
    mapping = registry(root, owner)
    item = mapping.properties.get(prop)
    if item is None:
        return None
    getter = mapping.getters.get(item.field.getter, {})
    schema = catalog.schema(kind)
    primary = tuple(schema.get("primaryIdentifier", ()))
    if (
        getter.get("kind") != "cloudcontrol"
        or getter.get("service") != "cloudcontrol"
        or getter.get("operation") != "get_resource"
        or getter.get("resourceType") != kind
        or tuple(getter.get("identifier", ())) != primary
        or len(primary) != 1
        or "read" not in schema.get("handlers", {})
        or primary[0]
        != "/properties/"
        + str(
            REF_ATTRIBUTES.get(kind)
            or {
                "CloudFront.OriginAccessControl": "Id",
                "Route53Resolver.ResolverEndpoint": "ResolverEndpointId",
            }.get(kind, "")
        )
        or item.transform != "identity"
    ):
        return None
    return primary[0], item


def permission_source(root, resource, prop):
    if (
        resource[RESOURCE_TYPE_KEY] != "Lambda.Permission"
        or prop != "Lambda.Permission.Id"
    ):
        return False
    mapping = registry(root, "lambda")
    item = mapping.properties.get(prop)
    return bool(
        item
        and item.field.getter == "permission"
        and item.field.path == "Sid"
        and mapping.getters.get("permission", {}).get("kind") == "adapter"
    )


def physical_identifier_source(resource, prop, physical=None):
    # EC2 Security Group names can be physical IDs; only an actual group ID is usable.
    return (
        resource[RESOURCE_TYPE_KEY] == "EC2.SecurityGroup"
        and prop == "EC2.SecurityGroup.Id"
        and (physical is None or re.fullmatch(r"sg-[0-9a-f]+", physical) is not None)
    )

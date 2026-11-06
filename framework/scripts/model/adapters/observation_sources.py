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
    kind = resource[RESOURCE_TYPE_KEY]
    prefix = {
        "EC2.SecurityGroup": "sg",
        "EC2.SecurityGroupIngress": "sgr",
        "EC2.SecurityGroupEgress": "sgr",
    }.get(kind)
    # CloudFormation can also return a name or the owning group ID for a rule.
    return (
        prefix is not None
        and prop == f"{kind}.Id"
        and (physical is None or re.fullmatch(rf"{prefix}-[0-9a-f]+", physical) is not None)
    )


def codebuild_source(root, resource, prop):
    if (
        resource[RESOURCE_TYPE_KEY] != "CodeBuild.Project"
        or prop != "CodeBuild.Project.Id"
    ):
        return None
    mapping = registry(root, "codebuild")
    item = mapping.properties.get(prop)
    identity = mapping.identities.get("CodeBuild.Project")
    base = mapping.getters.get("base", {})
    sdk = mapping.getters.get("sdk-codebuild-project", {})
    if (
        item is None
        or item.field.getter != "base"
        or item.field.path != "name"
        or item.transform != "identity"
        or identity is None
        or identity.getter != "base"
        or identity.id_path != "name"
        or identity.arn_path != "arn"
        or identity.name_property != "Name"
        or base.get("kind") != "adapter"
        or "CodeBuild.Project" not in base.get("resources", ())
        or sdk.get("kind") != "sdk"
        or sdk.get("service") != "codebuild"
        or sdk.get("operation") != "batch_get_projects"
        or sdk.get("result") != "projects[]"
        or sdk.get("resourceType") != "CodeBuild.Project"
    ):
        return None
    return item

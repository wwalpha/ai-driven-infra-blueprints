"""Parent-scoped SDK paths used by the existing Import inventory."""

import json
import re
from typing import Any
from urllib.parse import urlparse

from utils.aws_sdk import aws_runtime
from utils.json_format import policy_json

from model.importing.discovery import SCOPED_INVENTORIES


def account_for(ctx: Any) -> str:
    account = ctx.target.get("awsAccountId")
    if (
        not isinstance(account, str)
        or len(account) != 12
        or not account.isdigit()
        or ctx.target.get("awsExecutionAccountId", account) != account
    ):
        raise ValueError(
            "Import target account differs from verified execution account"
        )
    return account


def collection(
    ctx: Any, api: str, operation: str, key: str, **inputs: Any
) -> list[Any]:
    response = ctx.pages(api, operation, **inputs)
    if not isinstance(response, dict):
        raise ValueError("Invalid inventory response: " + api + "." + operation)
    values = response.get(key)
    if not isinstance(values, list):
        raise ValueError("Invalid inventory collection: " + api + "." + operation)
    return values


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or value in {"UNSET", "PENDING_DEPLOY"}:
        raise ValueError("Missing SDK inventory identifier")
    return value


def record(
    kind: str,
    values: dict[str, Any],
    getters: dict[str, Any],
    *,
    selectors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components = [
        {"property": kind + "." + prop, "value": values[prop]}
        for prop in SCOPED_INVENTORIES[kind].components
    ]
    return {
        "kind": kind,
        "identity": json.dumps(components, sort_keys=True),
        "identityProperty": components[0]["property"] if len(components) == 1 else None,
        "identityProperties": [component["property"] for component in components],
        "identityComponents": components,
        "identityStatus": "known",
        "getters": getters,
        "selectorProperties": {
            kind + "." + prop: value for prop, value in (selectors or {}).items()
        },
        "provenance": {
            "api": SCOPED_INVENTORIES[kind].api,
            "operations": list(SCOPED_INVENTORIES[kind].operations),
            "selectors": selectors or {},
        },
    }


def quicksight_groups(ctx: Any) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records = []
    namespaces = collection(
        ctx, "quicksight", "list_namespaces", "Namespaces", AwsAccountId=account
    )
    seen = set()
    for namespace in namespaces:
        name = identifier(namespace.get("Name"))
        if name in seen:
            raise ValueError("Duplicate QuickSight namespace")
        seen.add(name)
        for group in collection(
            ctx,
            "quicksight",
            "list_groups",
            "GroupList",
            AwsAccountId=account,
            Namespace=name,
        ):
            group_name = identifier(group.get("GroupName"))
            selectors = {"AwsAccountId": account, "Namespace": name}
            records.append(
                record(
                    "QuickSight.Group",
                    {**selectors, "GroupName": group_name},
                    {"sdk-quicksight-group": {"Group": group}},
                    selectors=selectors,
                )
            )
    return records


def glue_tables(ctx: Any) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records, seen = [], set()
    catalogs = collection(
        ctx,
        "glue",
        "get_catalogs",
        "CatalogList",
        ParentCatalogId=account,
        Recursive=True,
        IncludeRoot=True,
    )
    for catalog in catalogs:
        catalog_id = identifier(catalog.get("CatalogId"))
        arn = identifier(catalog.get("ResourceArn"))
        if (
            catalog_id.split(":")[0] != account
            or arn.split(":")[3:5] != [ctx.target["awsRegion"], account]
            or catalog_id in seen
        ):
            raise ValueError("Glue catalog ownership/scope is unknown or duplicate")
        seen.add(catalog_id)
        databases = collection(
            ctx, "glue", "get_databases", "DatabaseList", CatalogId=catalog_id
        )
        database_names = set()
        for database in databases:
            name = identifier(database.get("Name"))
            if database.get("CatalogId") != catalog_id or name in database_names:
                raise ValueError("Glue database scope mismatch or duplicate")
            database_names.add(name)
            for table in collection(
                ctx,
                "glue",
                "get_tables",
                "TableList",
                CatalogId=catalog_id,
                DatabaseName=name,
            ):
                table_name = identifier(table.get("Name"))
                if (
                    table.get("CatalogId") != catalog_id
                    or table.get("DatabaseName") != name
                ):
                    raise ValueError("Glue table scope mismatch")
                selectors = {"CatalogId": catalog_id, "DatabaseName": name}
                records.append(
                    record(
                        "Glue.Table",
                        {**selectors, "TableInput.Name": table_name},
                        {"base": table, "sdk-glue-table": {"Table": table}},
                        selectors=selectors,
                    )
                )
    return records


def lakeformation_resources(ctx: Any) -> list[dict[str, Any]]:
    records = []
    for item in collection(ctx, "lakeformation", "list_resources", "ResourceInfoList"):
        arn = identifier(item.get("ResourceArn"))
        detail = ctx.call("lakeformation", "describe_resource", ResourceArn=arn).get(
            "ResourceInfo"
        )
        if not isinstance(detail, dict) or detail.get("ResourceArn") != arn:
            raise ValueError("Lake Formation detail identity mismatch")
        records.append(
            record(
                "LakeFormation.Resource",
                {"ResourceArn": arn},
                {"sdk-lakeformation-resource": {"ResourceInfo": detail}},
            )
        )
    return records


def datazone_projects(ctx: Any) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records, domains_seen = [], set()
    for domain in collection(ctx, "datazone", "list_domains", "items"):
        domain_id = identifier(domain.get("id"))
        arn = identifier(domain.get("arn"))
        if (
            arn.split(":")[3:5] != [ctx.target["awsRegion"], account]
            or domain_id in domains_seen
        ):
            raise ValueError("DataZone domain scope mismatch or duplicate")
        domains_seen.add(domain_id)
        for item in collection(
            ctx, "datazone", "list_projects", "items", domainIdentifier=domain_id
        ):
            project_id = identifier(item.get("id"))
            if item.get("domainId") != domain_id:
                raise ValueError("DataZone listed project has another domain")
            detail = ctx.call(
                "datazone",
                "get_project",
                domainIdentifier=domain_id,
                identifier=project_id,
            )
            if detail.get("domainId") != domain_id or detail.get("id") != project_id:
                raise ValueError("DataZone detail identity mismatch")
            provider = {
                "DomainId": detail["domainId"],
                "Id": detail["id"],
                "Name": detail["name"],
            }
            records.append(
                record(
                    "DataZone.Project",
                    {"DomainId": domain_id, "Id": project_id},
                    {
                        "sdk-datazone-project": detail,
                        "provider-datazone-project": provider,
                    },
                )
            )
    return records


def queue_policies(ctx: Any, parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records = []
    region = ctx.target["awsRegion"]
    endpoint = (
        aws_runtime()
        .sdk_session()
        .get_component("endpoint_resolver")
        .construct_endpoint("sqs", region)
    )
    if not endpoint or endpoint.get("endpointName") != region:
        raise ValueError("SQS endpoint is unknown for target region")
    hosts = {endpoint["hostname"], endpoint.get("sslCommonName")}
    hosts.update(variant["hostname"] for variant in endpoint.get("variants", []))
    for parent in parents:
        if parent.get("kind") != "SQS.Queue":
            raise ValueError("QueuePolicy requires acquired Queue parents")
        url = parent.get("cloudProperties", {}).get("QueueUrl")
        url = identifier(url)
        parsed = urlparse(url)
        if (
            parsed.geturl() != url
            or parsed.scheme != "https"
            or parsed.netloc not in hosts
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(
                r"/" + account + r"/[A-Za-z0-9_-]{1,80}(?:\.fifo)?", parsed.path
            )
            or len(parsed.path.rsplit("/", 1)[-1]) > 80
        ):
            raise ValueError("SQS queue is outside target scope")
        response = ctx.call(
            "sqs", "get_queue_attributes", QueueUrl=url, AttributeNames=["Policy"]
        )
        # A successful Policy-only read may omit the optional Attributes map.
        attributes = response.get("Attributes", {})
        if not isinstance(attributes, dict):
            raise ValueError("Invalid SQS attributes")
        if "Policy" not in attributes:
            continue
        policy = policy_json(attributes["Policy"])
        if not isinstance(policy, dict):
            raise ValueError("Invalid SQS queue policy")
        value = record(
            "SQS.QueuePolicy",
            {"Queues[]": [url]},
            {"policy": {"Queues": [url], "Policy": policy}},
            selectors={"Queues[]": [url]},
        )
        value["structureStatus"] = "unresolved"
        value["structureReason"] = (
            "AWS does not retain the original QueuePolicy queue grouping; explicitly confirm a single-queue structure or exclude this candidate"
        )
        records.append(value)
    return records


HANDLERS = {
    "QuickSight.Group": quicksight_groups,
    "Glue.Table": glue_tables,
    "LakeFormation.Resource": lakeformation_resources,
    "DataZone.Project": datazone_projects,
}


def collect(
    ctx: Any, kind: str, *, parents: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    specification = SCOPED_INVENTORIES[kind]
    ctx.allowed.update(
        (specification.api, operation) for operation in specification.operations
    )
    if kind == "SQS.QueuePolicy":
        if parents is None:
            raise ValueError("QueuePolicy requires the existing Queue inventory")
        records = queue_policies(ctx, parents)
    else:
        records = HANDLERS[kind](ctx)
    if len({item["identity"] for item in records}) != len(records):
        raise ValueError("Duplicate scoped SDK identity")
    return records

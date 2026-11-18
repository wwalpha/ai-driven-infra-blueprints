"""datazone IMPORT acquisition."""

from typing import Any

from contracts.target import AWS_REGION_KEY
from model.importing.sdk_inventory import account_for, collection, identifier, record


def datazone_projects(ctx: Any) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records, domains_seen = [], set()
    for domain in collection(ctx, "datazone", "list_domains", "items"):
        domain_id = identifier(domain.get("id"))
        arn = identifier(domain.get("arn"))
        if (
            arn.split(":")[3:5] != [ctx.target[AWS_REGION_KEY], account]
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

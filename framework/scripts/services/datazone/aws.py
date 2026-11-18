"""DataZone reads use explicit domain/project identifiers."""

from typing import Any

from model.adapters.aws import Unresolved, execution_account, one

APIS = {
    ("datazone", "get_project"),
    ("datazone", "get_domain"),
    ("datazone", "list_domains"),
}
SDK_OPERATIONS = {"DataZone.Project": "get_project", "DataZone.Domain": "get_domain"}


def sensitive(prop: str) -> bool:
    return False


def fetch(ctx: Any, resource: Any, getter: str) -> dict[str, Any]:
    raise ValueError("DataZone has no adapter getter")


def fetch_sdk(ctx: Any, resource: Any, operation: str) -> dict[str, Any]:
    if operation == "get_domain":
        domain_id = resource.current("Id")
        if not domain_id:
            name = resource.value("Name")
            account = execution_account(ctx.target)
            domain = one(
                [
                    item
                    for item in ctx.pages("datazone", "list_domains").get("items", [])
                    if item.get("name") == name
                    and item.get("managedAccountId") == account
                ],
                "datazone.list_domains",
            )
            domain_id = domain.get("id")
            if not domain_id:
                raise Unresolved("DataZone domain has no confirmed Id")
        return ctx.call("datazone", operation, identifier=domain_id)
    return ctx.call(
        "datazone",
        operation,
        domainIdentifier=resource.value("DomainIdentifier"),
        identifier=resource.value("Id"),
    )

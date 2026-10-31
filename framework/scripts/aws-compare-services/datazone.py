"""DataZone reads use explicit domain/project identifiers."""

from typing import Any

from model.adapters.aws import Unresolved

APIS = {("datazone", "get_project"), ("datazone", "get_domain")}
SDK_OPERATIONS = {"DataZone.Project": "get_project", "DataZone.Domain": "get_domain"}


def sensitive(prop: str) -> bool:
    return False


def fetch(ctx: Any, resource: Any, getter: str) -> dict[str, Any]:
    raise ValueError("DataZone has no adapter getter")


def fetch_sdk(ctx: Any, resource: Any, operation: str) -> dict[str, Any]:
    if operation == "get_domain":
        domain_id = resource.current("Id")
        if not domain_id:
            raise Unresolved("DataZone domain requires a confirmed Id")
        return ctx.call("datazone", operation, identifier=domain_id)
    return ctx.call(
        "datazone",
        operation,
        domainIdentifier=resource.value("DomainIdentifier"),
        identifier=resource.value("Id"),
    )

"""DataZone project reads use explicit domain/project identifiers."""

from typing import Any

APIS = {("datazone", "get_project")}
SDK_OPERATIONS = {"DataZone.Project": "get_project"}


def sensitive(prop: str) -> bool:
    return False


def fetch(ctx: Any, resource: Any, getter: str) -> dict[str, Any]:
    raise ValueError("DataZone has no adapter getter")


def fetch_sdk(ctx: Any, resource: Any, operation: str) -> dict[str, Any]:
    return ctx.call(
        "datazone",
        operation,
        domainIdentifier=resource.value("DomainIdentifier"),
        identifier=resource.value("Id"),
    )

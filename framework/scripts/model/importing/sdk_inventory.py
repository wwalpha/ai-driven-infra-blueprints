"""Parent-scoped SDK paths used by the existing Import inventory."""

import json
from typing import Any

from contracts.model import MODEL_PENDING_DEPLOY, MODEL_UNSET
from contracts.target import (
    AWS_ACCOUNT_ID_KEY,
    AWS_EXECUTION_ACCOUNT_ID_KEY,
)
from services.registry import REGISTRY


def account_for(ctx: Any) -> str:
    account = ctx.target.get(AWS_ACCOUNT_ID_KEY)
    if (
        not isinstance(account, str)
        or len(account) != 12
        or not account.isdigit()
        or ctx.target.get(AWS_EXECUTION_ACCOUNT_ID_KEY, account) != account
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
    if (
        not isinstance(value, str)
        or not value
        or value in {MODEL_UNSET, MODEL_PENDING_DEPLOY}
    ):
        raise ValueError("Missing SDK inventory identifier")
    return value


def record(
    kind: str,
    values: dict[str, Any],
    getters: dict[str, Any],
    *,
    selectors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specification = REGISTRY.import_profile(kind).scoped
    if specification is None:
        raise KeyError(kind)
    components = [
        {"property": kind + "." + prop, "value": values[prop]}
        for prop in specification.components
    ]
    return {
        "kind": kind,
        "identity": json.dumps(components, sort_keys=True),
        "identityProperty": components[0]["property"] if len(components) == 1 else None,
        "identityProperties": [component["property"] for component in components],
        "identityComponents": components,
        "identityStatus": "known",
        "getters": getters,
        "seedProperties": {
            kind + "." + prop: value
            for prop, value in values.items()
            if value is not None
        },
        "selectorProperties": {
            kind + "." + prop: value for prop, value in (selectors or {}).items()
        },
        "provenance": {
            "api": specification.api,
            "operations": list(specification.operations),
            "selectors": selectors or {},
        },
    }


def verified_detail(
    ctx: Any, resource: Any, listed: dict[str, Any], getter: Any, response: Any
) -> bool:
    """Preserve a closed default for SDK detail responses without a proof contract."""
    kind = listed.get("kind")
    if not isinstance(kind, str):
        return False
    verify = REGISTRY.import_profile(kind).verify_detail
    return verify(ctx, resource, listed, getter, response) if verify else False


def collect(
    ctx: Any, kind: str, *, parents: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    specification = REGISTRY.import_profile(kind).scoped
    if specification is None:
        raise KeyError(kind)
    ctx.allowed.update(
        (specification.api, operation) for operation in specification.operations
    )
    if specification.parents:
        if parents is None:
            raise ValueError(kind + " requires its parent inventory")
        records = specification.collect(ctx, parents)
    else:
        records = specification.collect(ctx)
    if len({item["identity"] for item in records}) != len(records):
        raise ValueError("Duplicate scoped SDK identity")
    return records

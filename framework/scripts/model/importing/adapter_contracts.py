"""Executable, in-process Import adapter evidence; no AWS calls or saved receipts."""

from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Any

from services.registry import REGISTRY

from model.importing.adapter_contract_cases import core
from model.importing.contract_fixtures import InvalidFixture as InvalidFixture


def collect_cases(registrations):
    contracts = {}
    for key, fixture, operation, selectors, *additional in registrations:
        if key in contracts:
            raise ValueError(f"Duplicate adapter fixture registration: {key}")
        contracts[key] = (
            fixture,
            operation,
            selectors,
            additional[0] if additional else (),
        )
    return contracts


@lru_cache(maxsize=None)
def cases_for(service):
    adapter = REGISTRY.aws_adapters.get(service)
    if adapter is None:
        return {}
    return collect_cases(import_module(adapter.evidence_module).CONTRACTS)


def run(root: Path, mapping: Any, kind: str) -> dict[str, Any]:
    return core.run(root, mapping, kind, cases_for(mapping.service))

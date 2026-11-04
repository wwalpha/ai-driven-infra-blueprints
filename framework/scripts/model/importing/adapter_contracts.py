"""Executable, in-process Import adapter evidence; no AWS calls or saved receipts."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases import core
from model.importing.adapter_contract_cases.registry import CONTRACTS
from model.importing.contract_fixtures import InvalidFixture as InvalidFixture


def run(root: Path, mapping: Any, kind: str) -> dict[str, Any]:
    return core.run(root, mapping, kind, CONTRACTS)

"""Framework validation must never inspect real consumer inputs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
from contextlib import ExitStack, redirect_stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model.validations import (
    change_inputs,
    environment,
    full_inputs,
    identity,
    json_settings,
    naming,
    policies,
    presentation,
    references,
    schema,
    stacks,
    structure,
)
from support.validator import MODULE
from validation.findings import Findings
from validation.framework_contracts import check_structure
from validation.project import check_validation_scope
from validation_cache import PassCache

ROOT = Path(__file__).resolve().parents[4]


__all__ = [
    "PUBLIC_API_MODULES",
    "VALIDATION_MODULES",
    "ExitStack",
    "Findings",
    "MODULE",
    "PassCache",
    "Path",
    "ROOT",
    "TemporaryDirectory",
    "check_structure",
    "check_validation_scope",
    "io",
    "patch",
    "redirect_stdout",
    "sys",
]


PUBLIC_API_MODULES = (
    "deploy.scheduler",
    "deploy.run_context",
    "deploy.controller",
    "deploy.failures",
    "model.sources",
    "model.operations",
    "model.importing.approval",
    "comparison.runner",
)


VALIDATION_MODULES = (
    full_inputs,
    change_inputs,
    structure,
    naming,
    schema,
    json_settings,
    environment,
    references,
    policies,
    identity,
    stacks,
    presentation,
)

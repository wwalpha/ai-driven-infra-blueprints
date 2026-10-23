#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.issues_api_only_fixtures import (
    ROOT,
    DesignSchemaCatalog,
    Path,
    sys,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_api_type_rejection():
    catalog = DesignSchemaCatalog(ROOT)
    for kind in catalog.api_schemas:
        try:
            catalog.cloudformation_type(kind)
        except ValueError as error:
            assert 'implementation remains incomplete if this resource is in scope' in str(error)
        else:
            raise AssertionError('API resource accepted as implemented CFn')




pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))

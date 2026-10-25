#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.glue_datazone_catalog_fixtures import (
    ROOT,
    CloudFormationSchemaCatalog,
    Path,
    snapshot_errors,
    sys,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_catalog_schema():
    assert snapshot_errors(ROOT) == []
    catalog = CloudFormationSchemaCatalog(ROOT)
    for resource_type in (
        "Glue.Catalog",
        "DataZone.Domain",
        "DataZone.Project",
        "DataZone.DataSource",
    ):
        assert catalog.schema(resource_type)[
            "typeName"
        ] == "AWS::" + resource_type.replace(".", "::", 1)
    assert catalog.required_properties("Glue.Catalog") == {"Name"}
    assert catalog.required_properties("DataZone.Domain") == {"Name"}
    assert catalog.required_properties("DataZone.Project") == {
        "DomainIdentifier",
        "Name",
    }
    assert catalog.required_properties("DataZone.DataSource") == {
        "DomainIdentifier",
        "Name",
        "ProjectIdentifier",
        "Type",
    }
    assert catalog.literal_errors("DataZone.Domain", "DomainVersion", "V2") == []
    assert catalog.literal_errors("DataZone.DataSource", "Type", "GLUE") == []


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

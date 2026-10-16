#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.glue_datazone_catalog_fixtures import *

from support.it_workspace import copy_framework

def main() -> None:
    import sync_runtime as model
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        copy_framework(root / 'framework')
        glue, datazone = write_designs(root)
        glue_model = model_projection.model_for(glue, root)
        datazone_model = model_projection.model_for(datazone, root)
        assert glue_model == model_projection.model_for(glue, root)
        assert datazone_model == model_projection.model_for(datazone, root)
        assert "desired.resource.001.resourceType=Glue.Catalog" in glue_model
        assert "desired.row.001-001.value=[FederatedCatalog](#glue-federatedcatalog)" in glue_model
        assert "observed.row.001-001.value=PENDING_DEPLOY" in glue_model
        assert "desired.service.datazone.ownedCatalogResourceTypes=DataZone.Domain,DataZone.Project,DataZone.DataSource" in datazone_model
        assert "desired.resource.003.resourceType=DataZone.DataSource" in datazone_model
        assert "desired.row.003-003.value=[FederatedCatalog](glue.md#glue-federatedcatalog)" in datazone_model
        assert "observed.row.003-003.value=federated-catalog" in datazone_model
        assert "desired.row.003-007.value=GLUE" in datazone_model
        for design, contents in ((glue, glue_model), (datazone, datazone_model)):
            output = root / "model" / design.relative_to(root / "docs/designs").with_suffix(".properties")
            output.parent.mkdir(parents=True, exist_ok=True)
            write_model(output, contents)
        original = {path: path.read_bytes() for path in (glue, datazone)}
        with redirect_stdout(io.StringIO()):
            try:
                model.sync(root, False)
            except ValueError as error:
                assert "anchor must be unique and match its name" in str(error)
            else:
                raise AssertionError("legacy model with internal-ID headings was silently adopted")
        assert original == {path: path.read_bytes() for path in (glue, datazone)}
    print("glue-datazone-catalog: PASS (schema and read-only projection and legacy-input rejection)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()


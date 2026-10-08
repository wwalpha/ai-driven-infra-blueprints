#!/usr/bin/env python3
"""Focused catalog and deterministic-model checks for Glue Catalog and DataZone."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import model_projection
import io
import shutil
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors


ROOT = Path(__file__).resolve().parents[2]


def write_designs(root: Path) -> tuple[Path, Path]:
    directory = root / "docs/designs/dev/123456789012"
    directory.mkdir(parents=True)
    glue = directory / "glue.md"
    glue.write_text(
        """# AWS Glue 詳細設計

- Design service ID: `glue`
- Owned catalog resource types: `Glue.Catalog`

## リソース詳細

<a id="glue-federatedcatalog"></a>

### Glue.Catalog: FederatedCatalog

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | CatalogId | PENDING_DEPLOY | federated catalogを識別するID |
| 2 | FederatedCatalog.ConnectionName | snowflake-connection | Snowflake接続に使用するGlue connection名 |
| 3 | FederatedCatalog.Identifier | snowflake-catalog | Snowflake側のcatalog名 |
| 4 | Name | federated-catalog | Glue federated catalog名 |
""",
        encoding="utf-8",
    )
    datazone = directory / "datazone.md"
    datazone.write_text(
        """# Amazon DataZone 詳細設計

- Design service ID: `datazone`
- Owned catalog resource types: `DataZone.Domain`, `DataZone.Project`, `DataZone.DataSource`

## リソース詳細

<a id="datazone-domain"></a>

### DataZone.Domain: Domain

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | PENDING_DEPLOY | DataZone domainを識別するID |
| 2 | DomainVersion | V2 | DataZone domainのversion |
| 3 | Name | catalog-domain | DataZone domain名 |

<a id="datazone-project"></a>

### DataZone.Project: Project

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | DomainId | PENDING_DEPLOY | 所属するDataZone domainのID |
| 2 | Id | PENDING_DEPLOY | DataZone projectを識別するID |
| 3 | DomainIdentifier | [PENDING_DEPLOY](#datazone-domain) | projectが所属するdomain |
| 4 | Name | catalog-project | DataZone project名 |

<a id="datazone-datasource"></a>

### DataZone.DataSource: DataSource

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | DomainId | PENDING_DEPLOY | 所属するDataZone domainのID |
| 2 | Id | PENDING_DEPLOY | DataZone data sourceを識別するID |
| 3 | Configuration.GlueRunConfiguration.CatalogName | [federated-catalog](glue.md#glue-federatedcatalog) | 参照するGlue catalog名 |
| 4 | DomainIdentifier | [PENDING_DEPLOY](#datazone-domain) | data sourceが所属するdomain |
| 5 | Name | glue-data-source | DataZone data source名 |
| 6 | ProjectIdentifier | [PENDING_DEPLOY](#datazone-project) | data sourceが所属するproject |
| 7 | Type | GLUE | data sourceの種別 |
""",
        encoding="utf-8",
    )
    return glue, datazone


def main() -> None:
    assert snapshot_errors(ROOT) == []
    catalog = CloudFormationSchemaCatalog(ROOT)
    for resource_type in (
        "Glue.Catalog",
        "DataZone.Domain",
        "DataZone.Project",
        "DataZone.DataSource",
    ):
        assert catalog.schema(resource_type)["typeName"] == "AWS::" + resource_type.replace(".", "::", 1)
    assert catalog.required_properties("Glue.Catalog") == {"Name"}
    assert catalog.required_properties("DataZone.Domain") == {"Name"}
    assert catalog.required_properties("DataZone.Project") == {"DomainIdentifier", "Name"}
    assert catalog.required_properties("DataZone.DataSource") == {
        "DomainIdentifier",
        "Name",
        "ProjectIdentifier",
        "Type",
    }
    assert catalog.literal_errors("DataZone.Domain", "DomainVersion", "V2") == []
    assert catalog.literal_errors("DataZone.DataSource", "Type", "GLUE") == []

    import sync_runtime as model
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "framework", root / "framework")
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
            output.write_text(contents, encoding="utf-8")
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
    main()

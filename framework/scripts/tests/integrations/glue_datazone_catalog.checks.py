#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.glue_datazone_catalog_fixtures import *

from support.it_workspace import copy_framework

@it_case
def main() -> None:
    import sync_runtime as model
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(__import__("json").dumps({"projectName": "synthetic", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n")
        copy_framework(root / 'framework')
        glue, datazone = write_designs(root)
        write_model(root / 'model/dev/123456789012/cloudformation-stacks.properties', {
            'desired.stack.001.name': 'fixture', 'desired.stack.001.placementName': 'fixture',
            'desired.stack.001.template': 'fixture.yaml', 'desired.stack.001.parameters': 'fixture.json',
            'desired.stack.001.deployOrder': '1', 'display.stack.001.comment': '合成Stack'})
        glue_model = """# Synthetic authoritative Model fixture.
display.service.title=# Glue 詳細設計
display.resource.001.comment=合成 Glue catalog
desired.service.identity.lastAllocated={"Glue.Catalog":1}
desired.service.glue.serviceId=glue
desired.service.glue.ownedCatalogResourceTypes=Glue.Catalog
desired.resource.001.resourceType=Glue.Catalog
desired.resource.001.logicalId=Glue_Catalog_001
desired.resource.001.anchor=resource-Glue_Catalog_001
desired.resource.001.cfn-logicalId=fixture-FederatedCatalog
desired.row.001-001.property=Glue.Catalog.CatalogId
desired.row.001-001.value=[Glue_Catalog_001](glue.md#resource-Glue_Catalog_001)
desired.row.001-001.comment=federated catalogを識別するID
observed.row.001-001.property=Glue.Catalog.CatalogId
observed.row.001-001.value=PENDING_DEPLOY
observed.row.001-001.comment=federated catalogを識別するID
desired.row.001-002.property=Glue.Catalog.FederatedCatalog.ConnectionName
desired.row.001-002.value=snowflake-connection
desired.row.001-002.comment=Snowflake接続に使用するGlue connection名
desired.row.001-003.property=Glue.Catalog.FederatedCatalog.Identifier
desired.row.001-003.value=snowflake-catalog
desired.row.001-003.comment=Snowflake側のcatalog名
desired.row.001-004.property=Glue.Catalog.Name
desired.row.001-004.value=federated-catalog
desired.row.001-004.comment=Glue federated catalog名
"""
        datazone_model = """# Synthetic authoritative Model fixture.
display.service.title=# DataZone 詳細設計
display.resource.001.comment=合成 DataZone domain
display.resource.002.comment=合成 DataZone project
display.resource.003.comment=合成 DataZone data source
desired.service.identity.lastAllocated={"DataZone.Domain":1,"DataZone.Project":1,"DataZone.DataSource":1}
desired.service.datazone.serviceId=datazone
desired.service.datazone.ownedCatalogResourceTypes=DataZone.Domain,DataZone.Project,DataZone.DataSource
desired.resource.001.resourceType=DataZone.Domain
desired.resource.001.logicalId=DataZone_Domain_001
desired.resource.001.anchor=resource-DataZone_Domain_001
desired.resource.001.cfn-logicalId=fixture-Domain
desired.row.001-001.property=DataZone.Domain.Id
desired.row.001-001.value=[DataZone_Domain_001](datazone.md#resource-DataZone_Domain_001)
desired.row.001-001.comment=DataZone domainを識別するID
observed.row.001-001.property=DataZone.Domain.Id
observed.row.001-001.value=PENDING_DEPLOY
observed.row.001-001.comment=DataZone domainを識別するID
desired.row.001-002.property=DataZone.Domain.DomainVersion
desired.row.001-002.value=V2
desired.row.001-002.comment=DataZone domainのversion
desired.row.001-003.property=DataZone.Domain.Name
desired.row.001-003.value=catalog-domain
desired.row.001-003.comment=DataZone domain名
desired.resource.002.resourceType=DataZone.Project
desired.resource.002.logicalId=DataZone_Project_001
desired.resource.002.anchor=resource-DataZone_Project_001
desired.resource.002.cfn-logicalId=fixture-Project
desired.row.002-001.property=DataZone.Project.DomainId
desired.row.002-001.value=[DataZone_Project_001](datazone.md#resource-DataZone_Project_001)
desired.row.002-001.comment=所属するDataZone domainのID
observed.row.002-001.property=DataZone.Project.DomainId
observed.row.002-001.value=PENDING_DEPLOY
observed.row.002-001.comment=所属するDataZone domainのID
desired.row.002-002.property=DataZone.Project.Id
desired.row.002-002.value=[DataZone_Project_001](datazone.md#resource-DataZone_Project_001)
desired.row.002-002.comment=DataZone projectを識別するID
observed.row.002-002.property=DataZone.Project.Id
observed.row.002-002.value=PENDING_DEPLOY
observed.row.002-002.comment=DataZone projectを識別するID
desired.row.002-003.property=DataZone.Project.DomainIdentifier
desired.row.002-003.value=[DataZone_Domain_001](datazone.md#resource-DataZone_Domain_001)
desired.row.002-003.comment=projectが所属するdomain
observed.row.002-003.property=DataZone.Project.DomainIdentifier
observed.row.002-003.value=PENDING_DEPLOY
observed.row.002-003.comment=projectが所属するdomain
desired.row.002-004.property=DataZone.Project.Name
desired.row.002-004.value=catalog-project
desired.row.002-004.comment=DataZone project名
desired.resource.003.resourceType=DataZone.DataSource
desired.resource.003.logicalId=DataZone_DataSource_001
desired.resource.003.anchor=resource-DataZone_DataSource_001
desired.resource.003.cfn-logicalId=fixture-DataSource
desired.row.003-001.property=DataZone.DataSource.DomainId
desired.row.003-001.value=[DataZone_DataSource_001](datazone.md#resource-DataZone_DataSource_001)
desired.row.003-001.comment=所属するDataZone domainのID
observed.row.003-001.property=DataZone.DataSource.DomainId
observed.row.003-001.value=PENDING_DEPLOY
observed.row.003-001.comment=所属するDataZone domainのID
desired.row.003-002.property=DataZone.DataSource.Id
desired.row.003-002.value=[DataZone_DataSource_001](datazone.md#resource-DataZone_DataSource_001)
desired.row.003-002.comment=DataZone data sourceを識別するID
observed.row.003-002.property=DataZone.DataSource.Id
observed.row.003-002.value=PENDING_DEPLOY
observed.row.003-002.comment=DataZone data sourceを識別するID
desired.row.003-003.property=DataZone.DataSource.Configuration.GlueRunConfiguration.CatalogName
desired.row.003-003.value=[Glue_Catalog_001](glue.md#resource-Glue_Catalog_001)
desired.row.003-003.comment=参照するGlue catalog名
observed.row.003-003.property=DataZone.DataSource.Configuration.GlueRunConfiguration.CatalogName
observed.row.003-003.value=federated-catalog
observed.row.003-003.comment=参照するGlue catalog名
desired.row.003-004.property=DataZone.DataSource.DomainIdentifier
desired.row.003-004.value=[DataZone_Domain_001](datazone.md#resource-DataZone_Domain_001)
desired.row.003-004.comment=data sourceが所属するdomain
observed.row.003-004.property=DataZone.DataSource.DomainIdentifier
observed.row.003-004.value=PENDING_DEPLOY
observed.row.003-004.comment=data sourceが所属するdomain
desired.row.003-005.property=DataZone.DataSource.Name
desired.row.003-005.value=glue-data-source
desired.row.003-005.comment=DataZone data source名
desired.row.003-006.property=DataZone.DataSource.ProjectIdentifier
desired.row.003-006.value=[DataZone_Project_001](datazone.md#resource-DataZone_Project_001)
desired.row.003-006.comment=data sourceが所属するproject
observed.row.003-006.property=DataZone.DataSource.ProjectIdentifier
observed.row.003-006.value=PENDING_DEPLOY
observed.row.003-006.comment=data sourceが所属するproject
desired.row.003-007.property=DataZone.DataSource.Type
desired.row.003-007.value=GLUE
desired.row.003-007.comment=data sourceの種別
"""
        assert "| CatalogId | PENDING_DEPLOY |" in glue.read_text()
        assert "[federated-catalog](glue.md#glue-federatedcatalog)" in datazone.read_text()
        assert "desired.resource.001.resourceType=Glue.Catalog" in glue_model
        assert "desired.row.001-001.value=[Glue_Catalog_001](glue.md#resource-Glue_Catalog_001)" in glue_model
        assert "observed.row.001-001.value=PENDING_DEPLOY" in glue_model
        assert "desired.service.datazone.ownedCatalogResourceTypes=DataZone.Domain,DataZone.Project,DataZone.DataSource" in datazone_model
        assert "desired.resource.003.resourceType=DataZone.DataSource" in datazone_model
        assert "desired.row.003-003.value=[Glue_Catalog_001](glue.md#resource-Glue_Catalog_001)" in datazone_model
        assert "observed.row.003-003.value=federated-catalog" in datazone_model
        assert "desired.row.003-007.value=GLUE" in datazone_model
        for design, contents in ((glue, glue_model), (datazone, datazone_model)):
            output = root / "model" / design.relative_to(root / "docs/designs").with_suffix(".properties")
            output.parent.mkdir(parents=True, exist_ok=True)
            write_model(output, contents)
        original = {path: path.read_bytes() for path in (glue, datazone)}
        try:
            with redirect_stdout(io.StringIO()):
                model.sync(root, False)
        except ValueError as error:
            assert "generated Markdown is stale or missing" in str(error), error
        else:
            raise AssertionError("stale design accepted by generation")
        assert original == {path: path.read_bytes() for path in (glue, datazone)}
    print("glue-datazone-catalog: PASS (schema, fixed anchors, read-only projection and stale view rejection)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()


"""Focused catalog and deterministic-model checks for Glue Catalog and DataZone."""

from __future__ import annotations

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model

import model_projection

import io

import shutil

import tempfile

from contextlib import redirect_stdout

from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors

ROOT = Path(__file__).resolve().parents[4]

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


__all__ = ['CloudFormationSchemaCatalog', 'Path', 'ROOT', 'annotations', 'io', 'model_projection', 'redirect_stdout', 'shutil', 'snapshot_errors', 'sys', 'tempfile', 'write_designs', 'write_model']

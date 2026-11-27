"""glue service registration."""

from functools import partial
from importlib import import_module

from ..contracts import DisplayExtension
from ..import_contracts import (
    AccountFilter,
    ImportProfile,
    ScopedInventory,
    inventory_handler,
)
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display(kind: str) -> DisplayExtension:
    return import_module("services.glue.display").EXTENSIONS[kind]


DECLARATION = ServiceDeclaration(
    "glue",
    (
        "Glue.Catalog",
        "Glue.Connection",
        "Glue.Crawler",
        "Glue.Database",
        "Glue.Job",
        "Glue.SecurityConfiguration",
        "Glue.Table",
        "Glue.Trigger",
    ),
    REFERENCES,
    design=design,
    displays={"Glue.Job": partial(load_display, "Glue.Job")},
    aws_adapters={"glue": "aws"},
    import_profiles={
        "Glue.Table": ImportProfile(
            unobservable={
                "Glue.Table.Id": (
                    "glue",
                    "get_table",
                    "Table.Id",
                    "PROVIDER_OUTPUT_NOT_OBSERVABLE",
                )
            },
            scoped=ScopedInventory(
                "glue",
                ("get_catalogs", "get_databases", "get_tables"),
                ("get_tables", "TableList[]"),
                ("CatalogId", "DatabaseName", "TableInput.Name"),
                inventory_handler("services.glue.inventory", "glue_tables"),
                selectors=("CatalogId", "DatabaseName"),
            ),
        ),
        "Glue.Connection": ImportProfile(
            account_filter=AccountFilter(
                "CatalogId",
                "CatalogId comes from the verified target account when execution and target accounts match",
                "CatalogId is checked against both the verified target account and returned resource identity",
                "CatalogScopeMismatch",
            ),
        ),
    },
)

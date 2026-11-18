"""glue IMPORT acquisition."""

from typing import Any

from contracts.target import AWS_REGION_KEY
from model.importing.sdk_inventory import account_for, collection, identifier, record


def glue_tables(ctx: Any) -> list[dict[str, Any]]:
    account = account_for(ctx)
    records, seen = [], set()
    catalogs = collection(
        ctx,
        "glue",
        "get_catalogs",
        "CatalogList",
        ParentCatalogId=account,
        Recursive=True,
        IncludeRoot=True,
    )
    for catalog in catalogs:
        catalog_id = identifier(catalog.get("CatalogId"))
        arn = identifier(catalog.get("ResourceArn"))
        if (
            catalog_id.split(":")[0] != account
            or arn.split(":")[3:5] != [ctx.target[AWS_REGION_KEY], account]
            or catalog_id in seen
        ):
            raise ValueError("Glue catalog ownership/scope is unknown or duplicate")
        seen.add(catalog_id)
        databases = collection(
            ctx, "glue", "get_databases", "DatabaseList", CatalogId=catalog_id
        )
        database_names = set()
        for database in databases:
            name = identifier(database.get("Name"))
            if database.get("CatalogId") != catalog_id or name in database_names:
                raise ValueError("Glue database scope mismatch or duplicate")
            database_names.add(name)
            for table in collection(
                ctx,
                "glue",
                "get_tables",
                "TableList",
                CatalogId=catalog_id,
                DatabaseName=name,
            ):
                table_name = identifier(table.get("Name"))
                if (
                    table.get("CatalogId") != catalog_id
                    or table.get("DatabaseName") != name
                ):
                    raise ValueError("Glue table scope mismatch")
                selectors = {"CatalogId": catalog_id, "DatabaseName": name}
                records.append(
                    record(
                        "Glue.Table",
                        {**selectors, "TableInput.Name": table_name},
                        {"base": table, "sdk-glue-table": {"Table": table}},
                        selectors=selectors,
                    )
                )
    return records

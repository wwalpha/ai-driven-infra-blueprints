"""Static LakeFormation comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "LakeFormation.Resource": properties(
        references="ResourceArn RoleArn",
        scalars="UseServiceLinkedRole WithFederation HybridAccessEnabled",
    ),
    "LakeFormation.PrincipalPermissions": properties(
        objects="""
            Principal
            Resource
            Resource.Catalog
            Resource.Database
            Resource.Table
            Resource.Table.TableWildcard
            Resource.TableWithColumns
            Resource.TableWithColumns.ColumnWildcard
        """,
        ordered="""
            Permissions
            PermissionsWithGrantOption
            Resource.TableWithColumns.ColumnNames
            Resource.TableWithColumns.ColumnWildcard.ExcludedColumnNames
        """,
        scalars="""
            Catalog
            Principal.DataLakePrincipalIdentifier
            Resource.Database.CatalogId
            Resource.Database.Name
            Resource.Table.CatalogId
            Resource.Table.DatabaseName
            Resource.Table.Name
            Resource.TableWithColumns.CatalogId
            Resource.TableWithColumns.DatabaseName
            Resource.TableWithColumns.Name
        """,
    ),
}

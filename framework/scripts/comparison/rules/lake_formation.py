"""Static LakeFormation comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "LakeFormation.DataLakeSettings": properties(
        scalars="""
            AllowExternalDataFiltering AllowFullTableExternalDataAccess MutationType
            Admins[].DataLakePrincipalIdentifier
            ReadOnlyAdmins[].DataLakePrincipalIdentifier
            ExternalDataFilteringAllowList[].DataLakePrincipalIdentifier
            CreateDatabaseDefaultPermissions[].Principal.DataLakePrincipalIdentifier
            CreateTableDefaultPermissions[].Principal.DataLakePrincipalIdentifier
        """,
        objects="""
            Parameters Admins[] ReadOnlyAdmins[] ExternalDataFilteringAllowList[]
            CreateDatabaseDefaultPermissions[] CreateDatabaseDefaultPermissions[].Principal
            CreateTableDefaultPermissions[] CreateTableDefaultPermissions[].Principal
        """,
        ordered="""
            Admins ReadOnlyAdmins ExternalDataFilteringAllowList
            AuthorizedSessionTagValueList TrustedResourceOwners
            CreateDatabaseDefaultPermissions CreateDatabaseDefaultPermissions[].Permissions
            CreateTableDefaultPermissions CreateTableDefaultPermissions[].Permissions
        """,
    ),
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

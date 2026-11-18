"""QuickSight service registration."""

from ..import_contracts import Detail, ImportProfile, ScopedInventory, inventory_handler
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "quicksight",
    (
        "QuickSight.Analysis",
        "QuickSight.Dashboard",
        "QuickSight.DataSet",
        "QuickSight.DataSource",
        "QuickSight.Group",
        "QuickSight.VPCConnection",
    ),
    REFERENCES,
    design=design,
    aws_adapters={"quicksight": "aws"},
    import_profiles={
        "QuickSight.DataSource": ImportProfile(
            adapter=("quicksight", "list_data_sources", "DataSources"),
            detail=Detail("describe_data_source", "DataSourceId", "DataSource"),
            execution_account_input="AwsAccountId",
            additional_getters=inventory_handler(
                "services.quicksight.inventory", "permissions"
            ),
        ),
        "QuickSight.VPCConnection": ImportProfile(
            adapter=("quicksight", "list_vpc_connections", "VPCConnectionSummaries"),
            detail=Detail(
                "describe_vpc_connection",
                "VPCConnectionId",
                "VPCConnection",
                mismatch="IMPORT QuickSight detail identifier mismatch",
            ),
            execution_account_input="AwsAccountId",
        ),
        "QuickSight.Group": ImportProfile(
            scoped=ScopedInventory(
                "quicksight",
                ("list_namespaces", "list_groups"),
                ("list_groups", "GroupList[]"),
                ("AwsAccountId", "Namespace", "GroupName"),
                inventory_handler("services.quicksight.inventory", "quicksight_groups"),
                selectors=("AwsAccountId", "Namespace"),
            ),
            verify_detail=inventory_handler(
                "services.quicksight.inventory", "verified_detail"
            ),
        ),
    },
)

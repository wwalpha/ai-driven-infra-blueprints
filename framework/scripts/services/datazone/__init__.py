"""DataZone service registration."""

from ..import_contracts import ImportProfile, ScopedInventory, inventory_handler
from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "datazone",
    (
        "DataZone.Connection",
        "DataZone.DataSource",
        "DataZone.Domain",
        "DataZone.Environment",
        "DataZone.EnvironmentBlueprintConfiguration",
        "DataZone.EnvironmentProfile",
        "DataZone.Owner",
        "DataZone.Project",
        "DataZone.ProjectMembership",
        "DataZone.ProjectProfile",
    ),
    REFERENCES,
    aws_adapters={"datazone": "aws"},
    import_profiles={
        "DataZone.Project": ImportProfile(
            scoped=ScopedInventory(
                "datazone",
                ("list_domains", "list_projects", "get_project"),
                ("get_project", "$"),
                ("DomainId", "Id"),
                inventory_handler("services.datazone.inventory", "datazone_projects"),
                cloudcontrol_fields={
                    "DomainId": "domainId",
                    "Id": "id",
                    "Name": "name",
                },
            ),
        ),
    },
)

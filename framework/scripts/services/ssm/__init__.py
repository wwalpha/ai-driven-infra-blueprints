"""SSM service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "ssm",
    (
        "SSM.Association",
        "SSM.CloudConnector",
        "SSM.Document",
        "SSM.MaintenanceWindow",
        "SSM.MaintenanceWindowTarget",
        "SSM.MaintenanceWindowTask",
        "SSM.OpsItem",
        "SSM.Parameter",
        "SSM.PatchBaseline",
        "SSM.ResourceDataSync",
        "SSM.ResourcePolicy",
        "SSM.ServiceSetting",
    ),
    REFERENCES,
    design=design,
)

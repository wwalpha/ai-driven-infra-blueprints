"""QuickSight service registration."""

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
)

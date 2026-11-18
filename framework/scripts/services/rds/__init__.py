"""RDS service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "rds",
    (
        "RDS.DBCluster",
        "RDS.DBClusterParameterGroup",
        "RDS.DBInstance",
        "RDS.DBParameterGroup",
        "RDS.DBProxy",
        "RDS.DBProxyEndpoint",
        "RDS.DBProxyTargetGroup",
        "RDS.DBSubnetGroup",
        "RDS.OptionGroup",
    ),
    REFERENCES,
)

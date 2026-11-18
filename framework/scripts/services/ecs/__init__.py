"""ECS service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "ecs",
    (
        "ECS.CapacityProvider",
        "ECS.Cluster",
        "ECS.ClusterCapacityProviderAssociations",
        "ECS.Service",
        "ECS.TaskDefinition",
    ),
    REFERENCES,
)

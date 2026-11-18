"""api-gateway service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "api-gateway",
    (
        "ApiGateway.ApiKey",
        "ApiGateway.Authorizer",
        "ApiGateway.BasePathMapping",
        "ApiGateway.Deployment",
        "ApiGateway.DomainName",
        "ApiGateway.GatewayResponse",
        "ApiGateway.Method",
        "ApiGateway.Model",
        "ApiGateway.RequestValidator",
        "ApiGateway.Resource",
        "ApiGateway.RestApi",
        "ApiGateway.Stage",
        "ApiGateway.UsagePlan",
        "ApiGateway.UsagePlanKey",
        "ApiGateway.VpcLink",
    ),
    REFERENCES,
    design=design,
    package="api_gateway",
)

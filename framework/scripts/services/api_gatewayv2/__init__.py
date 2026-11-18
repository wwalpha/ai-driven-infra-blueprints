"""api-gateway-v2 service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "api-gateway-v2",
    (
        "ApiGatewayV2.Api",
        "ApiGatewayV2.ApiMapping",
        "ApiGatewayV2.Authorizer",
        "ApiGatewayV2.Deployment",
        "ApiGatewayV2.DomainName",
        "ApiGatewayV2.Integration",
        "ApiGatewayV2.IntegrationResponse",
        "ApiGatewayV2.Route",
        "ApiGatewayV2.RouteResponse",
        "ApiGatewayV2.Stage",
        "ApiGatewayV2.VpcLink",
    ),
    REFERENCES,
    package="api_gatewayv2",
)

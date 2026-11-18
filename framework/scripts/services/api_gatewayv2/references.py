"""api-gateway-v2 reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "ApiGatewayV2.Api": "ApiId",
        "ApiGatewayV2.ApiMapping": "ApiMappingId",
        "ApiGatewayV2.Authorizer": "AuthorizerId",
        "ApiGatewayV2.Deployment": "DeploymentId",
        "ApiGatewayV2.DomainName": "DomainName",
        "ApiGatewayV2.Integration": "IntegrationId",
        "ApiGatewayV2.IntegrationResponse": "IntegrationResponseId",
        "ApiGatewayV2.Route": "RouteId",
        "ApiGatewayV2.RouteResponse": "RouteResponseId",
        "ApiGatewayV2.Stage": "StageName",
        "ApiGatewayV2.VpcLink": "VpcLinkId",
    },
    arn_attributes={
        "ApiGatewayV2.DomainName": "DomainNameArn",
    },
    linked_subnets={
        "ApiGatewayV2.VpcLink.SubnetIds[]",
    },
    import_properties={
        "ApiGatewayV2.Api.BodyS3Location.Bucket": ("S3.Bucket", "BucketName"),
        "ApiGatewayV2.Integration.ConnectionId": ("ApiGatewayV2.VpcLink", "VpcLinkId"),
        "ApiGatewayV2.Stage.AccessLogSettings.DestinationArn": ("Logs.LogGroup", "Arn"),
    },
    arn_shapes={
        "ApiGatewayV2.DomainName": (
            "DomainName",
            "arn:{partition}:apigateway:{region}::/domainnames/{id}",
            {"id": r"[a-z0-9.-]+"},
        ),
        "ApiGatewayV2.Stage": (
            {"ApiId": "api", "StageName": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/stages/{id}",
            {"api": r"[a-z0-9]+", "id": r"(?:\$default|[A-Za-z0-9_-]{1,128})"},
        ),
        "ApiGatewayV2.Api": (
            "ApiId",
            "arn:{partition}:apigateway:{region}::/apis/{id}",
            {"id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.VpcLink": (
            "VpcLinkId",
            "arn:{partition}:apigateway:{region}::/vpclinks/{id}",
            {"id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.Authorizer": (
            {"ApiId": "api", "AuthorizerId": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/authorizers/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.Deployment": (
            {"ApiId": "api", "DeploymentId": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/deployments/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.Integration": (
            {"ApiId": "api", "IntegrationId": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/integrations/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.Route": (
            {"ApiId": "api", "RouteId": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/routes/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.ApiMapping": (
            {"DomainName": "domain", "ApiMappingId": "id"},
            "arn:{partition}:apigateway:{region}::/domainnames/{domain}/apimappings/{id}",
            {"domain": "[A-Za-z0-9.-]+", "id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.IntegrationResponse": (
            {"ApiId": "api", "IntegrationResponseId": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/integrationresponses/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGatewayV2.RouteResponse": (
            {"ApiId": "api", "RouteId": "route", "RouteResponseId": "id"},
            "arn:{partition}:apigateway:{region}::/apis/{api}/routes/{route}/routeresponses/{id}",
            {"api": "[a-z0-9]+", "route": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
    },
    unproven_document={
        "ApiGatewayV2.DomainName": (
            "ApiGatewayV2.DomainName.MutualTlsAuthentication.TruststoreUri",
        )
    },
)

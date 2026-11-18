"""api-gateway reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "ApiGateway.ApiKey": "APIKeyId",
        "ApiGateway.Authorizer": "AuthorizerId",
        "ApiGateway.Deployment": "DeploymentId",
        "ApiGateway.DomainName": "DomainName",
        "ApiGateway.Model": "Name",
        "ApiGateway.RequestValidator": "RequestValidatorId",
        "ApiGateway.Resource": "ResourceId",
        "ApiGateway.RestApi": "RestApiId",
        "ApiGateway.Stage": "StageName",
        "ApiGateway.UsagePlan": "Id",
        "ApiGateway.UsagePlanKey": "Id",
        "ApiGateway.VpcLink": "VpcLinkId",
        "ApiGateway.Method": "Ref",
    },
    arn_attributes={
        "ApiGateway.DomainName": "DomainNameArn",
    },
    import_properties={
        "ApiGateway.RestApi.BodyS3Location.Bucket": ("S3.Bucket", "BucketName"),
    },
    arn_shapes={
        "ApiGateway.Stage": (
            {"RestApiId": "api", "StageName": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/stages/{id}",
            {"api": r"[a-z0-9]+", "id": r"[A-Za-z0-9_-]{1,128}"},
        ),
        "ApiGateway.DomainName": (
            "DomainName",
            "arn:{partition}:apigateway:{region}::/domainnames/{id}",
            {"id": r"[a-z0-9.-]+"},
        ),
        "ApiGateway.BasePathMapping": (
            {"DomainName": "domain", "BasePath": "id"},
            "arn:{partition}:apigateway:{region}::/domainnames/{domain}/basepathmappings/{id}",
            {"domain": r"[A-Za-z0-9.-]+", "id": r"[A-Za-z0-9_.-]+"},
        ),
        "ApiGateway.GatewayResponse": (
            {"RestApiId": "api", "ResponseType": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/gatewayresponses/{id}",
            {"api": r"[a-z0-9]+", "id": r"[A-Z][A-Z0-9_]+"},
        ),
        "ApiGateway.Method": (
            {"RestApiId": "api", "ResourceId": "resource", "HttpMethod": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/resources/{resource}/methods/{id}",
            {"api": r"[a-z0-9]+", "resource": r"[a-z0-9]+", "id": r"[A-Z]+"},
        ),
        "ApiGateway.Model": (
            {"RestApiId": "api", "Name": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/models/{id}",
            {"api": r"[a-z0-9]+", "id": r"[A-Za-z0-9]+"},
        ),
        "ApiGateway.ApiKey": (
            "APIKeyId",
            "arn:{partition}:apigateway:{region}::/apikeys/{id}",
            {"id": "[a-z0-9]+"},
        ),
        "ApiGateway.RestApi": (
            "RestApiId",
            "arn:{partition}:apigateway:{region}::/restapis/{id}",
            {"id": "[a-z0-9]+"},
        ),
        "ApiGateway.VpcLink": (
            "VpcLinkId",
            "arn:{partition}:apigateway:{region}::/vpclinks/{id}",
            {"id": "[a-z0-9]+"},
        ),
        "ApiGateway.Authorizer": (
            {"RestApiId": "api", "AuthorizerId": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/authorizers/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGateway.Deployment": (
            {"RestApiId": "api", "DeploymentId": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/deployments/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGateway.RequestValidator": (
            {"RestApiId": "api", "RequestValidatorId": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/requestvalidators/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGateway.Resource": (
            {"RestApiId": "api", "ResourceId": "id"},
            "arn:{partition}:apigateway:{region}::/restapis/{api}/resources/{id}",
            {"api": "[a-z0-9]+", "id": "[a-z0-9]+"},
        ),
        "ApiGateway.UsagePlan": (
            "Id",
            "arn:{partition}:apigateway:{region}::/usageplans/{id}",
            {"id": "[a-z0-9]+"},
        ),
        "ApiGateway.UsagePlanKey": (
            {"UsagePlanId": "plan", "KeyId": "id"},
            "arn:{partition}:apigateway:{region}::/usageplans/{plan}/keys/{id}",
            {"plan": "[a-z0-9]+", "id": "[A-Za-z0-9]+"},
        ),
    },
    arn_components={"ApiGateway.DomainName": ("EndpointConfiguration",)},
    arn_without_forms=frozenset(("ApiGateway.DomainName",)),
)

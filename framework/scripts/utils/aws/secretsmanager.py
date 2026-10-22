"""secretsmanager SDK operations with structured AWS arguments."""
from .client import request, pages


def describe_secret(context, **arguments):
    return request(context, 'secretsmanager', 'describe_secret', arguments)


def list_secret_version_ids(context, **arguments):
    return pages(context, 'secretsmanager', 'list_secret_version_ids', 'Versions', arguments)


def get_secret_value(context, **arguments):
    response = request(context, 'secretsmanager', 'get_secret_value', arguments)
    return {"ARN": response.get("ARN"), "VersionId": response.get("VersionId"),
            "VersionStages": response.get("VersionStages"),
            "HasValue": "SecretString" in response or "SecretBinary" in response}


def put_secret_value(context, **arguments):
    response = request(context, 'secretsmanager', 'put_secret_value', arguments)
    return {key: response[key] for key in ("ARN", "Name", "VersionId", "VersionStages") if key in response}


def update_secret_version_stage(context, **arguments):
    response = request(context, 'secretsmanager', 'update_secret_version_stage', arguments)
    return {key: response[key] for key in ("ARN", "Name", "VersionId", "VersionStages") if key in response}



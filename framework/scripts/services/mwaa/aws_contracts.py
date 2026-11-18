"""Offline mwaa adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    direct_properties,
    direct_resource,
    failure_branches,
)


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "mwaa",
        "get_environment",
        "Name",
        "Name",
        "Environment",
    )
    cloud = {"Name": "fixture"}
    payload = {
        "Name": "fixture",
        "AirflowVersion": "2.10.3",
        "DagS3Path": "dags",
        "EndpointManagement": "SERVICE",
        "EnvironmentClass": "mw1.small",
        "ExecutionRoleArn": "arn:aws:iam::123456789012:role/fixture",
        "KmsKey": "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
        "LoggingConfiguration": {
            name: {"Enabled": True, "LogLevel": "INFO"}
            for name in (
                "DagProcessingLogs",
                "SchedulerLogs",
                "TaskLogs",
                "WebserverLogs",
                "WorkerLogs",
            )
        },
        "MaxWebservers": 2,
        "MaxWorkers": 3,
        "MinWebservers": 1,
        "MinWorkers": 1,
        "NetworkConfiguration": {
            "SecurityGroupIds": ["sg-12345678"],
            "SubnetIds": ["subnet-12345678", "subnet-87654321"],
        },
        "RequirementsS3Path": "requirements.txt",
        "Schedulers": 2,
        "SourceBucketArn": "arn:aws:s3:::fixture-bucket",
        "WebserverAccessMode": "PRIVATE_ONLY",
    }
    cases = {
        name: (
            name,
            "kms" if name == "KmsKey" else "arn" if name.endswith("Arn") else "typed",
            value,
        )
        for name, value in payload.items()
        if name not in {"LoggingConfiguration", "NetworkConfiguration"}
    }
    for name, values in payload["LoggingConfiguration"].items():
        for field, value in values.items():
            path = "LoggingConfiguration." + name + "." + field
            cases[path] = (path, "typed", value)
    for name, value in payload["NetworkConfiguration"].items():
        path = "NetworkConfiguration." + name
        cases[path] = (path, "id", value)
    ctx, fake, resource = direct_resource(
        root,
        mapping,
        kind,
        api,
        operation,
        {argument: "fixture"},
        envelope,
        cloud,
        payload,
    )
    items = direct_properties(
        ctx,
        fake,
        resource,
        mapping,
        properties,
        kind,
        cases,
        payload,
        (
            "Name",
            "repositoryName",
            "InstanceProfileName",
            "RoleName",
            "UserName",
            "Roles",
        ),
    )
    if not fake.calls:
        return items
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


CONTRACTS = (
    (("MWAA.Environment", "base"), direct_fixture, "mwaa.get_environment", ("Name",)),
)

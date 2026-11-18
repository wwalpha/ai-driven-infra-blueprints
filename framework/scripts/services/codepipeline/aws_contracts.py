"""Offline codepipeline adapter fixtures."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing.adapter_contract_cases.core import (
    clear_fetch,
    direct_properties,
    direct_resource,
    failure_branches,
    import_normalize,
)
from utils.comparison_rows import MISSING


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "codepipeline",
        "get_pipeline",
        "Name",
        "name",
        "pipeline",
    )
    cloud = {"Name": "fixture"}
    key = "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012"
    payload = {
        "name": "fixture",
        "roleArn": "arn:aws:iam::123456789012:role/fixture",
        "artifactStore": {
            "type": "S3",
            "location": "fixture-artifacts",
            "encryptionKey": {"id": key, "type": "KMS"},
        },
        "executionMode": "SUPERSEDED",
        "pipelineType": "V2",
        "variables": [{"name": "fixture-variable"}],
        "stages": [
            {
                "name": "Source",
                "actions": [
                    {
                        "name": "Source",
                        "namespace": "SourceVariables",
                        "actionTypeId": {
                            "category": "Source",
                            "owner": "AWS",
                            "provider": "CodeCommit",
                            "version": "1",
                        },
                        "runOrder": 1,
                        "configuration": {"RepositoryName": "fixture"},
                        "inputArtifacts": [{"name": "input"}],
                        "outputArtifacts": [{"name": "output"}],
                        "environmentVariables": [
                            {
                                "name": "FIXTURE",
                                "type": "PLAINTEXT",
                                "value": "fixture",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    cases = {
        "Name": ("name", "typed", "fixture"),
        "RoleArn": ("roleArn", "arn", payload["roleArn"]),
        "ArtifactStore.Type": ("artifactStore.type", "typed", "S3"),
        "ArtifactStore.Location": (
            "artifactStore.location",
            "name",
            "fixture-artifacts",
        ),
        "ArtifactStore.EncryptionKey.Id": (
            "artifactStore.encryptionKey.id",
            "kms",
            key,
        ),
        "ArtifactStore.EncryptionKey.Type": (
            "artifactStore.encryptionKey.type",
            "typed",
            "KMS",
        ),
        "ExecutionMode": ("executionMode", "typed", "SUPERSEDED"),
        "PipelineType": ("pipelineType", "typed", "V2"),
        "Stages[].Name": ("stages[].name", "typed", ["Source"]),
        "Variables[].Name": ("variables[].name", "typed", ["fixture-variable"]),
    }
    for name, value in {
        "Category": "Source",
        "Owner": "AWS",
        "Provider": "CodeCommit",
        "Version": "1",
    }.items():
        cases["Stages[].Actions[].ActionTypeId." + name] = (
            "stages[].actions[].actionTypeId." + name[0].lower() + name[1:],
            "string" if name == "Version" else "typed",
            [[value]],
        )
    cases.update(
        {
            "Stages[].Actions[].Name": (
                "stages[].actions[].name",
                "typed",
                [["Source"]],
            ),
            "Stages[].Actions[].Namespace": (
                "stages[].actions[].namespace",
                "typed",
                [["SourceVariables"]],
            ),
            "Stages[].Actions[].RunOrder": (
                "stages[].actions[].runOrder",
                "typed",
                [[1]],
            ),
            "Stages[].Actions[].InputArtifacts[].Name": (
                "stages[].actions[].inputArtifacts[].name",
                "typed",
                [[["input"]]],
            ),
            "Stages[].Actions[].OutputArtifacts[].Name": (
                "stages[].actions[].outputArtifacts[].name",
                "typed",
                [[["output"]]],
            ),
            "Stages[].Actions[].EnvironmentVariables[].Name": (
                "stages[].actions[].environmentVariables[].name",
                "typed",
                [[["FIXTURE"]]],
            ),
            "Stages[].Actions[].EnvironmentVariables[].Type": (
                "stages[].actions[].environmentVariables[].type",
                "typed",
                [[["PLAINTEXT"]]],
            ),
        }
    )
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
        ("name", "roleArn", "stages"),
    )
    if not fake.calls:
        return items
    namespace = kind + ".Stages[].Actions[].Namespace"
    if namespace in items and items[namespace]["status"] == "verified":
        for values in (
            [["QuarantineSource"], [MISSING], [MISSING], [MISSING]],
            [[MISSING, "Second", MISSING]],
            [[MISSING], [MISSING]],
            [["Source"], ["Build"]],
        ):
            fake.payload = deepcopy(payload)
            fake.payload["stages"] = namespace_stages(values)
            clear_fetch(ctx)
            _, raw = mapping_value(
                ctx, resource, mapping, mapping.properties[namespace], namespace
            )
            if raw != values:
                raise ValueError("Namespace projection lost Stage/Action membership")
            import_normalize(ctx, kind, namespace, raw)
        items[namespace]["branches"].append("partial-optional-namespace")
        fake.payload = payload
        clear_fetch(ctx)
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


CONTRACTS = (
    (
        ("CodePipeline.Pipeline", "base"),
        direct_fixture,
        "codepipeline.get_pipeline",
        ("Name",),
    ),
    (
        ("CodePipeline.Pipeline", "sdk-codepipeline-pipeline"),
        direct_fixture,
        "codepipeline.get_pipeline",
        ("Name",),
    ),
)


def namespace_stages(values):
    """Build valid named actions while omitting only the selected optional leaves."""
    return [
        {
            "name": f"stage-{i}",
            "actions": [
                {
                    "name": f"action-{i}-{j}",
                    "actionTypeId": {
                        "category": "Source",
                        "owner": "AWS",
                        "provider": "CodeCommit",
                        "version": "1",
                    },
                    "runOrder": 1,
                    "configuration": {"RepositoryName": "fixture"},
                    **({"namespace": value} if value != MISSING else {}),
                }
                for j, value in enumerate(actions)
            ],
        }
        for i, actions in enumerate(values)
    ]

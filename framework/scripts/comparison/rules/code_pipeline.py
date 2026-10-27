"""Static CodePipeline comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from design.services.codepipeline import pipeline_rows
from utils.cloudformation.inputs import Blocked
from utils.reference_contracts import KMS_FORMS, action_contexts, configuration_contract

from ..contracts import ResourceContract
from ..methods import REFERENCE, properties
from .kms import compare_forms


def prepare_rows(rows, *, index_rows):
    kind = "CodePipeline.Pipeline"
    if not any("Stages[]." in row["property"] for _, row in rows):
        return rows
    original = dict(rows)
    displayed = pipeline_rows(
        [
            [
                rid,
                row["property"].removeprefix(kind + "."),
                row["value"],
                row.get("comment", ""),
            ]
            for rid, row in rows
        ]
    )
    prepared, configurations = [], set()
    for rid, prop, value, _ in index_rows(displayed, kind):
        row = original[rid]
        if row["property"].endswith(".Configuration"):
            if rid in configurations:
                continue
            configurations.add(rid)
            prop = prop.split(".Configuration.", 1)[0] + ".Configuration"
            value = row["value"]
        prepared.append((rid, dict(row, property=kind + "." + prop, value=value)))
    return prepared


def reference_contract(path, attribute, context):
    if not path.startswith("Stages[].Actions[].Configuration."):
        return NotImplemented
    contract = configuration_contract("CodePipeline.Pipeline." + path, context)
    if not contract:
        raise Blocked(
            f"CodePipeline {path} reference contract unproven: ActionTypeId={context.get('ActionTypeId')}"
        )
    (kind,) = contract
    (expected,) = contract[kind]
    if attribute is not None and attribute != expected:
        raise Blocked(f"CodePipeline {path} reference attribute must be {expected}")
    return kind, expected


RULES = {
    "CodePipeline.Pipeline": properties(
        resource=ResourceContract(prepare_rows=prepare_rows, contexts=action_contexts),
        objects="""
            ArtifactStore
            ArtifactStore.EncryptionKey
            ArtifactStores[]
            ArtifactStores[].ArtifactStore
            ArtifactStores[].ArtifactStore.EncryptionKey
            Stages[]
            Stages[].Actions[]
            Stages[].Actions[].ActionTypeId
            Stages[].Actions[].Configuration
            Stages[].Actions[].EnvironmentVariables[]
            Stages[].Actions[].InputArtifacts[]
            Stages[].Actions[].OutputArtifacts[]
            Tags[]
            Triggers[]
            Triggers[].GitConfiguration
            Triggers[].GitConfiguration.PullRequest[]
            Triggers[].GitConfiguration.PullRequest[].Branches
            Triggers[].GitConfiguration.PullRequest[].FilePaths
            Triggers[].GitConfiguration.Push[]
            Triggers[].GitConfiguration.Push[].Branches
            Triggers[].GitConfiguration.Push[].FilePaths
            Triggers[].GitConfiguration.Push[].Tags
            Variables[]
        """,
        ordered="""
            ArtifactStores
            Stages
            Stages[].Actions
            Stages[].Actions[].Commands
            Stages[].Actions[].EnvironmentVariables
            Stages[].Actions[].InputArtifacts
            Stages[].Actions[].OutputArtifacts
            Stages[].Actions[].OutputArtifacts[].Files
            Stages[].Actions[].OutputVariables
            Triggers
            Triggers[].GitConfiguration.PullRequest
            Triggers[].GitConfiguration.PullRequest[].Branches.Excludes
            Triggers[].GitConfiguration.PullRequest[].Branches.Includes
            Triggers[].GitConfiguration.PullRequest[].Events
            Triggers[].GitConfiguration.PullRequest[].FilePaths.Excludes
            Triggers[].GitConfiguration.PullRequest[].FilePaths.Includes
            Triggers[].GitConfiguration.Push
            Triggers[].GitConfiguration.Push[].Branches.Excludes
            Triggers[].GitConfiguration.Push[].Branches.Includes
            Triggers[].GitConfiguration.Push[].FilePaths.Excludes
            Triggers[].GitConfiguration.Push[].FilePaths.Includes
            Triggers[].GitConfiguration.Push[].Tags.Excludes
            Triggers[].GitConfiguration.Push[].Tags.Includes
            Variables
        """,
        references="""
            ArtifactStore.Location
        """,
        scalars="""
            ArtifactStore.EncryptionKey.Type
            ArtifactStore.Type
            ArtifactStores[].ArtifactStore.EncryptionKey.Id
            ArtifactStores[].ArtifactStore.EncryptionKey.Type
            ArtifactStores[].ArtifactStore.Location
            ArtifactStores[].ArtifactStore.Type
            ArtifactStores[].Region
            ExecutionMode
            Name
            PipelineType
            RestartExecutionOnUpdate
            RoleArn
            Stages[].Actions[].ActionTypeId.Category
            Stages[].Actions[].ActionTypeId.Owner
            Stages[].Actions[].ActionTypeId.Provider
            Stages[].Actions[].ActionTypeId.Version
            Stages[].Actions[].EnvironmentVariables[].Name
            Stages[].Actions[].EnvironmentVariables[].Type
            Stages[].Actions[].EnvironmentVariables[].Value
            Stages[].Actions[].InputArtifacts[].Name
            Stages[].Actions[].Name
            Stages[].Actions[].Namespace
            Stages[].Actions[].OutputArtifacts[].Name
            Stages[].Actions[].Region
            Stages[].Actions[].RoleArn
            Stages[].Actions[].RunOrder
            Stages[].Actions[].TimeoutInMinutes
            Stages[].Name
            Tags[].Key
            Tags[].Value
            Triggers[].GitConfiguration.SourceActionName
            Triggers[].ProviderType
            Variables[].DefaultValue
            Variables[].Description
            Variables[].Name
        """,
        tags="""
            Tags
        """,
    ),
}


RULES["CodePipeline.Pipeline"]["Stages[].Actions[].Configuration"] = replace(
    RULES["CodePipeline.Pipeline"]["Stages[].Actions[].Configuration"],
    consumer=reference_contract,
)

_path = "ArtifactStore.EncryptionKey.Id"
RULES["CodePipeline.Pipeline"][_path] = replace(
    REFERENCE,
    forms=KMS_FORMS["CodePipeline.Pipeline." + _path],
    form_compare=compare_forms,
)

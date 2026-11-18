"""codepipeline reference declarations."""

import re
from importlib import import_module

from utils.comparison_rows import put_row

from ..contracts import ConfigurationContext, ReferencePolicy
from ..reference_data import ReferenceTables

ACTION_CONFIGURATION = "CodePipeline.Pipeline.Stages[].Actions[].Configuration"
ACTION_CONFIGURATION_CONTRACTS = {
    ("Source", "AWS", "CodeCommit", "1", "RepositoryName"): (
        "CodeCommit.Repository",
        "Name",
    ),
    ("Build", "AWS", "CodeBuild", "1", "ProjectName"): ("CodeBuild.Project", "Name"),
    ("Source", "AWS", "S3", "1", "S3Bucket"): ("S3.Bucket", "BucketName"),
}


def action_contexts(rows):
    contexts = {}
    for _, row in rows:
        prop = row["property"].removeprefix("CodePipeline.Pipeline.")
        action = re.fullmatch(
            r"(.*\.Actions\[\d+\])\.ActionTypeId\.(Category|Owner|Provider|Version)",
            prop,
        )
        if action:
            value = row["value"]
            value = (
                value[1:-1] if value.startswith("`") and value.endswith("`") else value
            )
            put_row(
                contexts.setdefault(action[1], {}), "ActionTypeId." + action[2], value
            )
    return contexts


def configuration_contract(prop, context=None, mode=None):
    prop = re.sub(r"\[\d+\]", "[]", prop)
    prop = "CodePipeline.Pipeline." + prop if prop.startswith("Stages") else prop
    if not prop.startswith(ACTION_CONFIGURATION + "."):
        return None
    action = (context or {}).get("ActionTypeId")
    if not isinstance(action, dict) or set(action) != {
        "Category",
        "Owner",
        "Provider",
        "Version",
    }:
        return {}
    parts = [action[key] for key in ("Category", "Owner", "Provider", "Version")]
    if not all(isinstance(value, str) for value in parts):
        return {}
    found = ACTION_CONFIGURATION_CONTRACTS.get(
        (*parts, prop.removeprefix(ACTION_CONFIGURATION + "."))
    )
    return {found[0]: (found[1],)} if found else {}


def reference_policy(path, context):
    return ReferencePolicy(
        unproven_reason="CodePipeline ActionTypeId or Configuration"
        if ("CodePipeline.Pipeline." + path).startswith(ACTION_CONFIGURATION + ".")
        else None
    )


def configuration_rows(rows, root, *, index_rows):
    """Index action membership without parsing Configuration documents."""
    kind = "CodePipeline.Pipeline"
    selected = [
        [
            rid,
            row["property"].removeprefix(kind + "."),
            row["value"],
            row.get("comment", ""),
        ]
        for rid, row in rows
    ]
    membership = import_module("services.codepipeline.display").pipeline_membership(
        selected
    )
    indexed = index_rows(membership, kind, root)
    contexts = action_contexts(
        [(rid, {"property": prop, "value": value}) for rid, prop, value, _ in indexed]
    )
    return {
        rid: contexts.get(prop.rsplit(".Configuration", 1)[0], {})
        for rid, prop, _, _ in indexed
        if prop.endswith(".Configuration") or ".Configuration." in prop
    }


def configuration_signature(rows):
    return [
        (prop, row.get("value") if ".ActionTypeId." in prop else None)
        for _, row in rows
        if (prop := row.get("property", "")).startswith(
            "CodePipeline.Pipeline.Stages[]."
        )
    ]


REFERENCES = ReferenceTables(
    configurations={
        "CodePipeline.Pipeline": ConfigurationContext(
            ACTION_CONFIGURATION,
            configuration_rows,
            configuration_signature,
            ACTION_CONFIGURATION.removesuffix("Configuration")
            + "ActionTypeId.Provider",
            {
                (provider, key): target
                for (
                    _,
                    _,
                    provider,
                    _,
                    key,
                ), target in ACTION_CONFIGURATION_CONTRACTS.items()
            },
        )
    },
    ref_attributes={
        "CodePipeline.Pipeline": "Name",
    },
    reference_forms={
        "CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id": {"KeyId", "Arn"},
    },
    reference_properties={
        "CodePipeline.Pipeline.ArtifactStore.Location": ("S3.Bucket", "BucketName"),
        "CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id": (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
    },
    import_properties={
        "CodePipeline.Pipeline.ArtifactStores[].ArtifactStore.Location": (
            "S3.Bucket",
            "BucketName",
        ),
        "CodePipeline.Pipeline.Stages[].Actions[].RoleArn": ("IAM.Role", "Arn"),
        "CodePipeline.Pipeline.RoleArn": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "CodePipeline.Pipeline": (
            "Name",
            "arn:{partition}:codepipeline:{region}:{account}:{id}",
            {"id": r"[A-Za-z0-9.@_-]{1,100}"},
        ),
    },
    format_limits={
        "CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id": {"AliasArn", "KeyId"},
    },
    contextual={"CodePipeline.Pipeline": configuration_contract},
    reference_policy={"CodePipeline.Pipeline": reference_policy},
    context_paths={"CodePipeline.Pipeline": ()},
    context_suffixes={"CodePipeline.Pipeline": (".Actions[]",)},
    context_targets={
        "CodePipeline.Pipeline": frozenset(
            value[0] for value in ACTION_CONFIGURATION_CONTRACTS.values()
        )
    },
    row_contexts={"CodePipeline.Pipeline": action_contexts},
)

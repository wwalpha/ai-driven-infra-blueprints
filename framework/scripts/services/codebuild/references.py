"""codebuild reference declarations."""

import re

from utils.comparison_rows import put_row

from ..contracts import ReferencePolicy
from ..reference_data import ReferenceTables


def row_contexts(rows):
    kind = "CodeBuild.Project"
    contexts, variables = {}, {}
    for identity, row in rows:
        prop = row["property"].removeprefix(kind + ".")
        value = row["value"]
        value = value[1:-1] if value.startswith("`") and value.endswith("`") else value
        if re.fullmatch(
            r"Environment.EnvironmentVariables\[\d*\]\.(Name|Type|Value)", prop
        ):
            put_row(variables, prop, identity if prop.endswith(".Value") else value)
    types = [
        row["value"].strip("`")
        for _, row in rows
        if row["property"] == kind + ".Artifacts.Type"
    ]
    if len(types) == 1:
        for identity, row in rows:
            if row["property"] == kind + ".Artifacts.Location":
                contexts[identity] = {"Type": types[0]}
    for variable in variables.get("Environment", {}).get("EnvironmentVariables", []):
        if "Value" in variable:
            contexts[variable["Value"]] = variable
    return contexts


def reference_policy(path, context):
    if path != "Environment.EnvironmentVariables[].Value":
        return ReferencePolicy()
    kind = (context or {}).get("Type")
    plaintext = (context or {}).get("Type", "PLAINTEXT") == "PLAINTEXT"
    return ReferencePolicy(
        error="PLAINTEXTではResource linkは禁止 (Resource links are forbidden for PLAINTEXT)"
        if plaintext
        else None,
        requires_context=False if kind == "PLAINTEXT" else None,
    )


REFERENCES = ReferenceTables(
    ref_attributes={
        "CodeBuild.Project": "Name",
    },
    linked_references={
        "CodeBuild.Project.VpcConfig.SecurityGroupIds": ("EC2.SecurityGroup", "GroupId")
    },
    linked_subnets={
        "CodeBuild.Project.VpcConfig.Subnets",
    },
    reference_forms={
        "CodeBuild.Project.EncryptionKey": {"Arn", "AliasName"},
    },
    reference_properties={
        "CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName": (
            "Logs.LogGroup",
            "LogGroupName",
        ),
        "CodeBuild.Project.VpcConfig.VpcId": ("EC2.VPC", "VpcId"),
        "CodeBuild.Project.VpcConfig.Subnets[]": ("EC2.Subnet", "SubnetId"),
        "CodeBuild.Project.VpcConfig.SecurityGroupIds[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
    },
    import_properties={
        "CodeBuild.Project.EncryptionKey": (("KMS.Key", "KMS.Alias"), None),
        "CodeBuild.Project.ServiceRole": ("IAM.Role", "Arn"),
    },
    arn_shapes={
        "CodeBuild.Project": (
            "Name",
            "arn:{partition}:codebuild:{region}:{account}:project/{id}",
            {"id": r"[A-Za-z0-9][A-Za-z0-9_-]{1,254}"},
        ),
    },
    equivalent_forms={
        (
            "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
            "SecretsManager.Secret",
            "Id",
        ): {"Name"},
    },
    context_properties={
        "CodeBuild.Project.Source.Location": ("CodeBuild.Project.Source.Type", {}),
        "CodeBuild.Project.Cache.Location": ("CodeBuild.Project.Cache.Type", {}),
        "CodeBuild.Project.Artifacts.Location": (
            "CodeBuild.Project.Artifacts.Type",
            {"S3": ("S3.Bucket", "BucketName")},
        ),
        "CodeBuild.Project.Environment.EnvironmentVariables[].Value": (
            "CodeBuild.Project.Environment.EnvironmentVariables[].Type",
            {
                "SECRETS_MANAGER": ("SecretsManager.Secret", ("Name", "Id")),
                "PARAMETER_STORE": ("SSM.Parameter", "Name"),
            },
        ),
    },
    default_on_mismatch={
        "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
    },
    reference_policy={"CodeBuild.Project": reference_policy},
    context_paths={"CodeBuild.Project": ("Artifacts", "CodeBuild.Project.Artifacts")},
    context_suffixes={"CodeBuild.Project": (".EnvironmentVariables[]",)},
    row_contexts={"CodeBuild.Project": row_contexts},
)

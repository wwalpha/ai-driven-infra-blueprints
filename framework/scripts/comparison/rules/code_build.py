"""Static CodeBuild comparison methods; container rules include their recursive contents."""

from dataclasses import replace
from functools import partial as _bind_framework_callback

from utils.cloudformation.inputs import Blocked
from utils.iac_values import ResourceReference, same
from utils.reference_contracts import (
    IMPORT_PROPERTIES,
    row_contexts,
)

from ..contracts import ResourceContract
from ..methods import properties


def _callback_reference_compare_secret_value(
    path, reference, resolve_literal, resource_type, record, /, a, b, p
):
    if p == path:
        return NotImplemented
    if p.endswith(".Value") and isinstance(a, ResourceReference) != isinstance(
        b, ResourceReference
    ):
        symbol, text = (a, b) if isinstance(a, ResourceReference) else (b, a)
        if (
            resource_type(symbol) == "SecretsManager.Secret"
            and isinstance(text, str)
            and not text.startswith("arn:")
        ):
            try:
                name = resolve_literal(
                    ResourceReference(dict(symbol, **{"$attribute": "Name"}))
                )
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                return None
            return record(a, b, p, same(name, text))
    return reference(a, b, p)


def compare_reference_value(
    left, right, path, resolve_literal, kms_format, resource_type, reference, *, record
):
    if isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
        return same(left, right)
    if isinstance(left, ResourceReference) != isinstance(right, ResourceReference):
        symbol, other = (
            (left, right) if isinstance(left, ResourceReference) else (right, left)
        )
        if isinstance(other, str):
            forms = kms_format(symbol), kms_format(other)
            if (
                all(form not in {None, "invalid"} for form in forms)
                and forms[0] != forms[1]
            ):
                return False
            try:
                return same(resolve_literal(symbol), other)
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                return None
    return NotImplemented


def compare_environment_variable(
    left, right, path, resolve_literal, kms_format, resource_type, reference, *, record
):
    if (
        path.endswith("EnvironmentVariables[]")
        and isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("Type") == right.get("Type") == "SECRETS_MANAGER"
    ):
        secret_value = _bind_framework_callback(
            _callback_reference_compare_secret_value,
            path,
            reference,
            resolve_literal,
            resource_type,
            record,
        )
        return same(left, right, reference=secret_value, path=path)
    return NotImplemented


RULES = {
    "CodeBuild.Project": properties(
        resource=ResourceContract(
            contexts=_bind_framework_callback(row_contexts, "CodeBuild.Project")
        ),
        objects="""
            Artifacts
            Cache
            Environment
            Environment.EnvironmentVariables[]
            Environment.RegistryCredential
            LogsConfig
            LogsConfig.CloudWatchLogs
            LogsConfig.S3Logs
            Source
            Source.Auth
            Source.GitSubmodulesConfig
            Tags[]
            Triggers
            VpcConfig
        """,
        ordered="""
            Cache.Modes
            Environment.EnvironmentVariables
            VpcConfig.SecurityGroupIds
            VpcConfig.Subnets
        """,
        references="""
            LogsConfig.CloudWatchLogs.GroupName
            VpcConfig.VpcId
        """,
        scalars="""
            Artifacts.ArtifactIdentifier
            Artifacts.EncryptionDisabled
            Artifacts.Location
            Artifacts.Name
            Artifacts.NamespaceType
            Artifacts.OverrideArtifactName
            Artifacts.Packaging
            Artifacts.Path
            Artifacts.Type
            AutoRetryLimit
            Cache.Location
            Cache.Type
            ConcurrentBuildLimit
            Description
            EncryptionKey
            Environment.Certificate
            Environment.ComputeType
            Environment.EnvironmentVariables[].Name
            Environment.EnvironmentVariables[].Type
            Environment.EnvironmentVariables[].Value
            Environment.Image
            Environment.ImagePullCredentialsType
            Environment.PrivilegedMode
            Environment.RegistryCredential.Credential
            Environment.RegistryCredential.CredentialProvider
            Environment.Type
            LogsConfig.CloudWatchLogs.Status
            LogsConfig.CloudWatchLogs.StreamName
            LogsConfig.S3Logs.EncryptionDisabled
            LogsConfig.S3Logs.Location
            LogsConfig.S3Logs.Status
            Name
            QueuedTimeoutInMinutes
            ServiceRole
            Source.Auth.Resource
            Source.Auth.Type
            Source.BuildSpec
            Source.GitCloneDepth
            Source.GitSubmodulesConfig.FetchSubmodules
            Source.InsecureSsl
            Source.Location
            Source.ReportBuildStatus
            Source.Type
            SourceVersion
            Tags[].Key
            Tags[].Value
            TimeoutInMinutes
            Triggers.BuildType
            Triggers.Webhook
            Visibility
        """,
        tags="""
            Tags
        """,
    ),
}


_path = "Environment.EnvironmentVariables[]"
RULES["CodeBuild.Project"][_path] = replace(
    RULES["CodeBuild.Project"][_path], reference=compare_environment_variable
)
_path = "Environment.EnvironmentVariables[].Value"
RULES["CodeBuild.Project"][_path] = replace(
    RULES["CodeBuild.Project"][_path],
    reference=compare_reference_value,
)
RULES["CodeBuild.Project"]["ServiceRole"] = replace(
    RULES["CodeBuild.Project"]["ServiceRole"],
    direct_attribute=IMPORT_PROPERTIES["CodeBuild.Project.ServiceRole"][1],
)

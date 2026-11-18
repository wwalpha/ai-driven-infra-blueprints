"""Static CodeBuild comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from comparison.contracts import ResourceContract
from comparison.methods import properties
from utils.iac_values import ResourceReference

from .references import REFERENCES, row_contexts


def identifier_evidence(left, right, context):
    return (
        context.get("Type") == "PLAINTEXT"
        and isinstance(left, ResourceReference)
        and getattr(left, "declared_format", None) == "identifier"
        and left.saved_property == "KMS.Key.KeyId"
        and isinstance(right, ResourceReference)
        and right["$resource"][0] == "kms"
        and right["$attribute"] == "KeyId"
    )


RULES = {
    "CodeBuild.Project": properties(
        resource=ResourceContract(
            contexts=row_contexts, identifier_evidence=identifier_evidence
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
            Environment.EnvironmentVariables[].Value
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
    RULES["CodeBuild.Project"][_path], reference_context=True
)
_path = "Environment.EnvironmentVariables[].Value"
RULES["CodeBuild.Project"][_path] = replace(
    RULES["CodeBuild.Project"][_path], reference_context=True
)
RULES["CodeBuild.Project"]["ServiceRole"] = replace(
    RULES["CodeBuild.Project"]["ServiceRole"],
    direct_attribute=REFERENCES.import_properties["CodeBuild.Project.ServiceRole"][1],
)

RULES["CodeBuild.Project"]["Artifacts"] = replace(
    RULES["CodeBuild.Project"]["Artifacts"], reference_context=True
)

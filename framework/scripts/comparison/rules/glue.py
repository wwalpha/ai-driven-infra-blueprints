"""Static Glue comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from utils.iac_values import ResourceReference
from utils.reference_contracts import KMS_FORMS

from ..methods import REFERENCE, properties
from .kms import compare_forms


def compare_federated_identifier(inputs, left, right, _path, *, export_origins):
    if (
        isinstance(left, ResourceReference)
        and isinstance(right, ResourceReference)
        and not hasattr(left, "saved_literal")
        and not hasattr(right, "saved_literal")
        and left == right
        and left["$attribute"] == "Name"
        and inputs.resource_type(left) == "Glue.Connection"
        and not export_origins([left, right], inputs.export_provenance)
    ):
        return True, "same explicit Glue Connection Name reference"
    return NotImplemented


RULES = {
    "Glue.Catalog": properties(
        objects="""
            CatalogProperties
            CatalogProperties.DataLakeAccessProperties
            FederatedCatalog
            Parameters
            Tags[]
            TargetRedshiftCatalog
        """,
        ordered="""
            CreateDatabaseDefaultPermissions
            CreateTableDefaultPermissions
        """,
        references="""
            FederatedCatalog.ConnectionName
        """,
        scalars="""
            AllowFullTableExternalDataAccess
            CatalogProperties.DataLakeAccessProperties.AllowFullTableExternalDataAccess
            CatalogProperties.DataLakeAccessProperties.CatalogType
            CatalogProperties.DataLakeAccessProperties.DataLakeAccess
            CatalogProperties.DataLakeAccessProperties.DataTransferRole
            CatalogProperties.DataLakeAccessProperties.KmsKey
            Description
            FederatedCatalog.Identifier
            Name
            OverwriteChildResourcePermissionsWithDefault
            Tags[].Key
            Tags[].Value
            TargetRedshiftCatalog.CatalogArn
        """,
        tags="""
            Tags
        """,
    ),
    "Glue.Connection": properties(
        objects="""
            ConnectionInput
            ConnectionInput.AthenaProperties
            ConnectionInput.AuthenticationConfiguration
            ConnectionInput.ConnectionProperties
            ConnectionInput.PhysicalConnectionRequirements
        """,
        ordered="""
            ConnectionInput.MatchCriteria
            ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList
            ConnectionInput.ValidateForComputeEnvironments
        """,
        references="""
            ConnectionInput.PhysicalConnectionRequirements.SubnetId
        """,
        scalars="""
            CatalogId
            ConnectionInput.AuthenticationConfiguration.AuthenticationType
            ConnectionInput.AuthenticationConfiguration.KmsKeyArn
            ConnectionInput.AuthenticationConfiguration.SecretArn
            ConnectionInput.ConnectionType
            ConnectionInput.Description
            ConnectionInput.Name
            ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone
            ConnectionInput.ValidateCredentials
        """,
    ),
    "Glue.Crawler": properties(
        objects="""
            LakeFormationConfiguration
            RecrawlPolicy
            Schedule
            SchemaChangePolicy
            Tags
            Targets
            Targets.JdbcTargets[]
            Targets.S3Targets[]
        """,
        ordered="""
            Classifiers
            Targets.JdbcTargets
            Targets.JdbcTargets[].Exclusions
            Targets.S3Targets
            Targets.S3Targets[].Exclusions
        """,
        scalars="""
            Configuration
            CrawlerSecurityConfiguration
            DatabaseName
            Description
            LakeFormationConfiguration.AccountId
            LakeFormationConfiguration.UseLakeFormationCredentials
            Name
            RecrawlPolicy.RecrawlBehavior
            Role
            Schedule.ScheduleExpression
            SchemaChangePolicy.DeleteBehavior
            SchemaChangePolicy.UpdateBehavior
            TablePrefix
            Targets.JdbcTargets[].ConnectionName
            Targets.JdbcTargets[].Path
            Targets.S3Targets[].ConnectionName
            Targets.S3Targets[].DlqEventQueueArn
            Targets.S3Targets[].EventQueueArn
            Targets.S3Targets[].Path
            Targets.S3Targets[].SampleSize
        """,
    ),
    "Glue.Database": properties(
        objects="""
            DatabaseInput
            DatabaseInput.Parameters
        """,
        scalars="""
            CatalogId
            DatabaseInput.Description
            DatabaseInput.LocationUri
            DatabaseInput.Name
            DatabaseName
        """,
    ),
    "Glue.Job": properties(
        objects="""
            Command
            Connections
            DefaultArguments
            ExecutionProperty
            NonOverridableArguments
            NotificationProperty
            Tags
        """,
        ordered="""
            Connections.Connections
        """,
        references="""
            Role
            SecurityConfiguration
        """,
        scalars="""
            Command.Name
            Command.PythonVersion
            Command.Runtime
            Command.ScriptLocation
            Description
            ExecutionClass
            ExecutionProperty.MaxConcurrentRuns
            GlueVersion
            JobMode
            JobRunQueuingEnabled
            MaintenanceWindow
            MaxRetries
            Name
            NotificationProperty.NotifyDelayAfter
            NumberOfWorkers
            Timeout
            WorkerType
        """,
    ),
    "Glue.SecurityConfiguration": properties(
        objects="""
            EncryptionConfiguration
            EncryptionConfiguration.CloudWatchEncryption
            EncryptionConfiguration.JobBookmarksEncryption
            EncryptionConfiguration.S3Encryptions[]
        """,
        ordered="""
            EncryptionConfiguration.S3Encryptions
        """,
        scalars="""
            EncryptionConfiguration.CloudWatchEncryption.CloudWatchEncryptionMode
            EncryptionConfiguration.JobBookmarksEncryption.JobBookmarksEncryptionMode
            EncryptionConfiguration.JobBookmarksEncryption.KmsKeyArn
            EncryptionConfiguration.S3Encryptions[].S3EncryptionMode
            Name
        """,
    ),
    "Glue.Table": properties(
        objects="""
            TableInput
            TableInput.Parameters
            TableInput.PartitionKeys[]
            TableInput.StorageDescriptor
            TableInput.StorageDescriptor.Columns[]
            TableInput.StorageDescriptor.Parameters
            TableInput.StorageDescriptor.SerdeInfo
            TableInput.StorageDescriptor.SerdeInfo.Parameters
            TableInput.StorageDescriptor.SortColumns[]
        """,
        ordered="""
            TableInput.PartitionKeys
            TableInput.StorageDescriptor.BucketColumns
            TableInput.StorageDescriptor.Columns
            TableInput.StorageDescriptor.SortColumns
        """,
        scalars="""
            CatalogId
            DatabaseName
            TableInput.Description
            TableInput.Name
            TableInput.Owner
            TableInput.PartitionKeys[].Comment
            TableInput.PartitionKeys[].Name
            TableInput.PartitionKeys[].Type
            TableInput.Retention
            TableInput.StorageDescriptor.Columns[].Comment
            TableInput.StorageDescriptor.Columns[].Name
            TableInput.StorageDescriptor.Columns[].Type
            TableInput.StorageDescriptor.Compressed
            TableInput.StorageDescriptor.InputFormat
            TableInput.StorageDescriptor.Location
            TableInput.StorageDescriptor.NumberOfBuckets
            TableInput.StorageDescriptor.OutputFormat
            TableInput.StorageDescriptor.SerdeInfo.Name
            TableInput.StorageDescriptor.SerdeInfo.SerializationLibrary
            TableInput.StorageDescriptor.SortColumns[].Column
            TableInput.StorageDescriptor.SortColumns[].SortOrder
            TableInput.StorageDescriptor.StoredAsSubDirectories
            TableInput.TableType
        """,
    ),
}

RULES["Glue.Catalog"]["FederatedCatalog.Identifier"] = replace(
    RULES["Glue.Catalog"]["FederatedCatalog.Identifier"],
    selected_decision=compare_federated_identifier,
)

for _path in (
    "EncryptionConfiguration.S3Encryptions[].KmsKeyArn",
    "EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn",
):
    RULES["Glue.SecurityConfiguration"][_path] = replace(
        REFERENCE,
        forms=KMS_FORMS["Glue.SecurityConfiguration." + _path],
        form_compare=compare_forms,
    )

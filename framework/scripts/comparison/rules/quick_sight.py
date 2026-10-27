"""Static QuickSight comparison methods; container rules include their recursive contents."""

from design.policy_tables import literal
from model.importing.references import known
from utils.cloudformation.inputs import Blocked

from ..contracts import ResourceContract
from ..methods import properties


def imported_group_arn(all_rows, catalog, partition, target, stack_inputs):
    fields = {}
    for field in catalog.schema("QuickSight.Group")["identityProperties"]:
        rows = [
            row for _, row in all_rows if row["property"] == "QuickSight.Group." + field
        ]
        if len(rows) != 1 or "document" in rows[0]:
            raise Blocked(
                "QuickSight Group requires one scalar identity property: " + field
            )
        candidate = literal(rows[0]["value"])
        if not known(candidate) or catalog.literal_errors(
            "QuickSight.Group", field, candidate
        ):
            raise Blocked(
                "QuickSight Group requires one confirmed identity property: " + field
            )
        fields[field] = candidate
    # stack_input establishes partition from the target's recorded SDK Region.
    region = target.get("awsRegion")
    if (
        not partition
        or not region
        or not any(
            pseudo.get("AWS::Region") == region
            and pseudo.get("AWS::Partition") == partition
            for _, _, pseudo in stack_inputs.values()
        )
    ):
        raise Blocked(
            "QuickSight Group ARN requires a confirmed CloudFormation Region and partition"
        )
    # https://docs.aws.amazon.com/cli/latest/reference/quicksight/create-group.html
    return (
        f"arn:{partition}:quicksight:{region}:{fields['AwsAccountId']}:"
        f"group/{fields['Namespace']}/{fields['GroupName']}"
    )


RULES = {
    "QuickSight.Analysis": properties(
        objects="""
            Permissions[]
            SourceEntity
            SourceEntity.SourceTemplate
            SourceEntity.SourceTemplate.DataSetReferences[]
            Tags[]
            ValidationStrategy
        """,
        ordered="""
            FolderArns
            Permissions
            Permissions[].Actions
            SourceEntity.SourceTemplate.DataSetReferences
        """,
        scalars="""
            AnalysisId
            AwsAccountId
            Name
            Permissions[].Principal
            SourceEntity.SourceTemplate.Arn
            SourceEntity.SourceTemplate.DataSetReferences[].DataSetArn
            SourceEntity.SourceTemplate.DataSetReferences[].DataSetPlaceholder
            Tags[].Key
            Tags[].Value
            ThemeArn
            ValidationStrategy.Mode
        """,
        tags="""
            Tags
        """,
    ),
    "QuickSight.Dashboard": properties(
        objects="""
            DashboardPublishOptions
            DashboardPublishOptions.AdHocFilteringOption
            DashboardPublishOptions.DataPointDrillUpDownOption
            DashboardPublishOptions.DataPointMenuLabelOption
            DashboardPublishOptions.DataPointTooltipOption
            DashboardPublishOptions.DataQAEnabledOption
            DashboardPublishOptions.ExportToCSVOption
            DashboardPublishOptions.ExportWithHiddenFieldsOption
            DashboardPublishOptions.SheetControlsOption
            DashboardPublishOptions.SheetLayoutElementMaximizationOption
            DashboardPublishOptions.VisualAxisSortOption
            DashboardPublishOptions.VisualMenuOption
            LinkSharingConfiguration
            LinkSharingConfiguration.Permissions[]
            Permissions[]
            SourceEntity
            SourceEntity.SourceTemplate
            SourceEntity.SourceTemplate.DataSetReferences[]
            Tags[]
            ValidationStrategy
        """,
        ordered="""
            FolderArns
            LinkEntities
            LinkSharingConfiguration.Permissions
            LinkSharingConfiguration.Permissions[].Actions
            Permissions
            Permissions[].Actions
            SourceEntity.SourceTemplate.DataSetReferences
        """,
        scalars="""
            AwsAccountId
            DashboardId
            DashboardPublishOptions.AdHocFilteringOption.AvailabilityStatus
            DashboardPublishOptions.DataPointDrillUpDownOption.AvailabilityStatus
            DashboardPublishOptions.DataPointMenuLabelOption.AvailabilityStatus
            DashboardPublishOptions.DataPointTooltipOption.AvailabilityStatus
            DashboardPublishOptions.DataQAEnabledOption.AvailabilityStatus
            DashboardPublishOptions.ExportToCSVOption.AvailabilityStatus
            DashboardPublishOptions.ExportWithHiddenFieldsOption.AvailabilityStatus
            DashboardPublishOptions.SheetControlsOption.VisibilityState
            DashboardPublishOptions.SheetLayoutElementMaximizationOption.AvailabilityStatus
            DashboardPublishOptions.VisualAxisSortOption.AvailabilityStatus
            DashboardPublishOptions.VisualMenuOption.AvailabilityStatus
            LinkSharingConfiguration.Permissions[].Principal
            Name
            Permissions[].Principal
            SourceEntity.SourceTemplate.Arn
            SourceEntity.SourceTemplate.DataSetReferences[].DataSetArn
            SourceEntity.SourceTemplate.DataSetReferences[].DataSetPlaceholder
            Tags[].Key
            Tags[].Value
            ThemeArn
            ValidationStrategy.Mode
            VersionDescription
        """,
        tags="""
            Tags
        """,
    ),
    "QuickSight.DataSet": properties(
        objects="""
            DataSetRefreshProperties
            DataSetRefreshProperties.FailureConfiguration
            DataSetRefreshProperties.FailureConfiguration.EmailAlert
            DataSetRefreshProperties.RefreshConfiguration
            DataSetRefreshProperties.RefreshConfiguration.IncrementalRefresh
            DataSetRefreshProperties.RefreshConfiguration.IncrementalRefresh.LookbackWindow
            DataSetUsageConfiguration
            FieldFolders
            IngestionWaitPolicy
            PerformanceConfiguration
            PerformanceConfiguration.UniqueKeys[]
            Permissions[]
            PhysicalTableMap
            Tags[]
        """,
        ordered="""
            FolderArns
            PerformanceConfiguration.UniqueKeys
            PerformanceConfiguration.UniqueKeys[].ColumnNames
            Permissions
            Permissions[].Actions
        """,
        scalars="""
            AwsAccountId
            DataSetId
            DataSetRefreshProperties.FailureConfiguration.EmailAlert.AlertStatus
            DataSetRefreshProperties.RefreshConfiguration.IncrementalRefresh.LookbackWindow.ColumnName
            DataSetRefreshProperties.RefreshConfiguration.IncrementalRefresh.LookbackWindow.Size
            DataSetRefreshProperties.RefreshConfiguration.IncrementalRefresh.LookbackWindow.SizeUnit
            DataSetUsageConfiguration.DisableUseAsDirectQuerySource
            DataSetUsageConfiguration.DisableUseAsImportedSource
            ImportMode
            IngestionWaitPolicy.IngestionWaitTimeInHours
            IngestionWaitPolicy.WaitForSpiceIngestion
            Name
            Permissions[].Principal
            Tags[].Key
            Tags[].Value
            UseAs
        """,
        tags="""
            Tags
        """,
    ),
    "QuickSight.DataSource": properties(
        objects="""
            Credentials
            Credentials.CredentialPair
            Credentials.KeyPairCredentials
            DataSourceParameters
            DataSourceParameters.AthenaParameters
            DataSourceParameters.AthenaParameters.IdentityCenterConfiguration
            DataSourceParameters.S3Parameters
            DataSourceParameters.S3Parameters.ManifestFileLocation
            DataSourceParameters.SnowflakeParameters
            DataSourceParameters.SnowflakeParameters.OAuthParameters
            DataSourceParameters.SnowflakeParameters.OAuthParameters.IdentityProviderVpcConnectionProperties
            Permissions[]
            SslProperties
            Tags[]
            VpcConnectionProperties
        """,
        ordered="""
            Permissions
            Permissions[].Actions
        """,
        references="""
            Permissions[].Principal
        """,
        scalars="""
            AwsAccountId
            Credentials.CredentialPair.Password
            Credentials.CredentialPair.Username
            Credentials.KeyPairCredentials.KeyPairUsername
            Credentials.KeyPairCredentials.PrivateKey
            Credentials.KeyPairCredentials.PrivateKeyPassphrase
            Credentials.SecretArn
            DataSourceId
            DataSourceParameters.AthenaParameters.IdentityCenterConfiguration.EnableIdentityPropagation
            DataSourceParameters.AthenaParameters.RoleArn
            DataSourceParameters.AthenaParameters.WorkGroup
            DataSourceParameters.S3Parameters.ManifestFileLocation.Bucket
            DataSourceParameters.S3Parameters.ManifestFileLocation.Key
            DataSourceParameters.S3Parameters.RoleArn
            DataSourceParameters.SnowflakeParameters.AuthenticationType
            DataSourceParameters.SnowflakeParameters.Database
            DataSourceParameters.SnowflakeParameters.DatabaseAccessControlRole
            DataSourceParameters.SnowflakeParameters.Host
            DataSourceParameters.SnowflakeParameters.OAuthParameters.IdentityProviderResourceUri
            DataSourceParameters.SnowflakeParameters.OAuthParameters.IdentityProviderVpcConnectionProperties.VpcConnectionArn
            DataSourceParameters.SnowflakeParameters.OAuthParameters.OAuthScope
            DataSourceParameters.SnowflakeParameters.OAuthParameters.TokenProviderUrl
            DataSourceParameters.SnowflakeParameters.Warehouse
            Name
            Permissions[].Resource
            SslProperties.DisableSsl
            Tags[].Key
            Tags[].Value
            Type
            VpcConnectionProperties.VpcConnectionArn
        """,
        tags="""
            Tags
        """,
    ),
    "QuickSight.VPCConnection": properties(
        objects="""
            Tags[]
        """,
        ordered="""
            DnsResolvers
            SecurityGroupIds
            SubnetIds
        """,
        scalars="""
            AwsAccountId
            Name
            RoleArn
            Tags[].Key
            Tags[].Value
            VPCConnectionId
        """,
        tags="""
            Tags
        """,
    ),
}


# IMPORT-only Producer identity; this type has no comparable Catalog properties.
RULES["QuickSight.Group"] = properties(
    resource=ResourceContract(imported_arn=imported_group_arn)
)

"""QuickSight reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    linked_subnets={
        "QuickSight.VPCConnection.SubnetIds",
    },
    reference_properties={
        "QuickSight.DataSource.Permissions[].Principal": ("QuickSight.Group", "Arn"),
        "QuickSight.VPCConnection.SecurityGroupIds[]": ("EC2.SecurityGroup", "GroupId"),
        "QuickSight.VPCConnection.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    },
    import_properties={
        "QuickSight.DataSource.DataSourceParameters.AthenaParameters.RoleArn": (
            "IAM.Role",
            "Arn",
        ),
        "QuickSight.DataSource.DataSourceParameters.S3Parameters.ManifestFileLocation.Bucket": (
            "S3.Bucket",
            "BucketName",
        ),
        "QuickSight.DataSource.VpcConnectionProperties.VpcConnectionArn": (
            "QuickSight.VPCConnection",
            "Arn",
        ),
        "QuickSight.DataSource.Credentials.SecretArn": ("SecretsManager.Secret", "Arn"),
    },
    arn_shapes={
        "QuickSight.Group": (
            {"AwsAccountId": "account", "Namespace": "namespace", "GroupName": "group"},
            "arn:{partition}:quicksight:{region}:{account}:group/{namespace}/{group}",
            {
                "account": r"[0-9]{12}",
                "namespace": r"[A-Za-z0-9._-]{1,64}",
                "group": r"[\x20-\xff]+",
            },
        ),
        "QuickSight.Analysis": (
            {"AwsAccountId": "account", "AnalysisId": "id"},
            "arn:{partition}:quicksight:{region}:{account}:analysis/{id}",
            {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
        ),
        "QuickSight.Dashboard": (
            {"AwsAccountId": "account", "DashboardId": "id"},
            "arn:{partition}:quicksight:{region}:{account}:dashboard/{id}",
            {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
        ),
        "QuickSight.DataSet": (
            {"AwsAccountId": "account", "DataSetId": "id"},
            "arn:{partition}:quicksight:{region}:{account}:dataset/{id}",
            {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
        ),
        "QuickSight.DataSource": (
            {"AwsAccountId": "account", "DataSourceId": "id"},
            "arn:{partition}:quicksight:{region}:{account}:datasource/{id}",
            {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
        ),
        "QuickSight.VPCConnection": (
            {"AwsAccountId": "account", "VPCConnectionId": "id"},
            "arn:{partition}:quicksight:{region}:{account}:vpcConnection/{id}",
            {"account": r"\d{12}", "id": r"[A-Za-z0-9_-]{1,512}"},
        ),
    },
    local_comparison={
        "QuickSight.VPCConnection.RoleArn": {"IAM.Role": ("Arn",)},
    },
)

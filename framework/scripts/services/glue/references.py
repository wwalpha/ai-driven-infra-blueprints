"""glue reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("Glue.Connection", "Name"): "ConnectionInput.Name",
        ("Glue.Database", "Name"): "DatabaseInput.Name",
        ("Glue.Table", "Name"): "TableInput.Name",
    },
    ref_attributes={
        "Glue.Connection": "Name",
        "Glue.SecurityConfiguration": "Name",
        "Glue.Job": "Name",
        "Glue.Crawler": "Name",
        "Glue.Database": "Name",
        "Glue.Table": "Name",
        "Glue.Catalog": "ResourceArn",
    },
    arn_attributes={
        "Glue.Catalog": "ResourceArn",
    },
    reference_forms={
        "Glue.Job.Role": {"RoleName", "Arn"},
        "Glue.Crawler.Role": {"RoleName", "Arn"},
    },
    reference_properties={
        "Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "Glue.Connection.ConnectionInput.PhysicalConnectionRequirements.SubnetId": (
            "EC2.Subnet",
            "SubnetId",
        ),
        "Glue.Catalog.FederatedCatalog.ConnectionName": ("Glue.Connection", "Name"),
        "Glue.Job.Connections.Connections[]": ("Glue.Connection", "Name"),
        "Glue.Job.Role": ("IAM.Role", "RoleName"),
        "Glue.Job.SecurityConfiguration": ("Glue.SecurityConfiguration", "Name"),
    },
    import_properties={
        "Glue.Crawler.Targets.JdbcTargets[].ConnectionName": (
            "Glue.Connection",
            "Name",
        ),
        "Glue.Crawler.Targets.S3Targets[].ConnectionName": ("Glue.Connection", "Name"),
        "Glue.Crawler.Targets.S3Targets[].DlqEventQueueArn": ("SQS.Queue", "Arn"),
        "Glue.Connection.ConnectionInput.AuthenticationConfiguration.SecretArn": (
            "SecretsManager.Secret",
            "Arn",
        ),
        "Glue.Database.DatabaseInput.FederatedDatabase.ConnectionName": (
            "Glue.Connection",
            "Name",
        ),
        "Glue.Crawler.CrawlerSecurityConfiguration": (
            "Glue.SecurityConfiguration",
            "Name",
        ),
        "Glue.Crawler.DatabaseName": ("Glue.Database", "Name"),
        "Glue.Crawler.Role": ("IAM.Role", "RoleName"),
        "Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn": (
            ("KMS.Key", "KMS.Alias"),
            "Arn",
        ),
        "Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn": (
            ("KMS.Key", "KMS.Alias"),
            "Arn",
        ),
    },
    arn_shapes={
        "Glue.Job": (
            "Name",
            "arn:{partition}:glue:{region}:{account}:job/{id}",
            {"id": r"[\w+=,.@/-]{1,255}"},
        ),
        "Glue.Crawler": (
            "Name",
            "arn:{partition}:glue:{region}:{account}:crawler/{id}",
            {"id": r"[\w+=,.@/-]{1,255}"},
        ),
        "Glue.Connection": (
            {"CatalogId": "account", "ConnectionInput.Name": "id"},
            "arn:{partition}:glue:{region}:{account}:connection/{id}",
            {"account": r"\d{12}", "id": r"[\w+=,.@-]{1,255}"},
        ),
        "Glue.Database": (
            {"CatalogId": "account", "DatabaseInput.Name": "id"},
            "arn:{partition}:glue:{region}:{account}:database/{id}",
            {"account": r"\d{12}", "id": r"[a-z0-9_.-]{1,255}"},
        ),
        "Glue.Table": (
            {
                "CatalogId": "account",
                "DatabaseName": "database",
                "TableInput.Name": "id",
            },
            "arn:{partition}:glue:{region}:{account}:table/{database}/{id}",
            {
                "account": r"\d{12}",
                "database": r"[a-z0-9_.-]{1,255}",
                "id": r"[a-z0-9_.-]{1,255}",
            },
        ),
        "Glue.Catalog": (
            "Name",
            "arn:{partition}:glue:{region}:{account}:catalog/{id}",
            {"id": r"[a-z0-9_-]{1,255}"},
        ),
    },
    format_limits={
        "Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn": {
            "AliasArn"
        },
        "Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn": {
            "AliasArn"
        },
    },
    unproven_document={"Glue.Crawler": ("Glue.Crawler.Targets.S3Targets[].Path",)},
    verified_symbolic_arn_attributes={"Glue.Connection": frozenset({"Name"})},
    arn_components={
        "Glue.Connection": (
            "DatabaseName",
            "DatabaseInput.Name",
            "Name",
            "TableInput.Name",
        ),
        "Glue.SecurityConfiguration": (
            "DatabaseName",
            "DatabaseInput.Name",
            "Name",
            "TableInput.Name",
        ),
        "Glue.Job": ("DatabaseName", "DatabaseInput.Name", "Name", "TableInput.Name"),
        "Glue.Crawler": (
            "DatabaseName",
            "DatabaseInput.Name",
            "Name",
            "TableInput.Name",
        ),
        "Glue.Database": (
            "DatabaseName",
            "DatabaseInput.Name",
            "Name",
            "TableInput.Name",
        ),
        "Glue.Table": ("DatabaseName", "DatabaseInput.Name", "Name", "TableInput.Name"),
    },
)

"""IAM reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "IAM.Role": "RoleName",
        "IAM.InstanceProfile": "InstanceProfileName",
        "IAM.ManagedPolicy": "PolicyArn",
        "IAM.User": "UserName",
    },
    arn_attributes={
        "IAM.ManagedPolicy": "PolicyArn",
    },
    reference_properties={
        "IAM.ManagedPolicy.Roles[]": ("IAM.Role", "RoleName"),
        "IAM.InstanceProfile.Roles[]": ("IAM.Role", "RoleName"),
    },
    arn_shapes={
        "IAM.Role": (
            {"RoleName": "id", "Path": "path"},
            "arn:{partition}:iam::{account}:role{path}{id}",
            {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,64}"},
        ),
        "IAM.InstanceProfile": (
            {"InstanceProfileName": "id", "Path": "path"},
            "arn:{partition}:iam::{account}:instance-profile{path}{id}",
            {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,128}"},
        ),
        "IAM.ManagedPolicy": (
            {"ManagedPolicyName": "id", "Path": "path"},
            "arn:{partition}:iam::{account}:policy{path}{id}",
            {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,128}"},
        ),
        "IAM.User": (
            {"UserName": "id", "Path": "path"},
            "arn:{partition}:iam::{account}:user{path}{id}",
            {"path": r"/(?:[^/]+/)*", "id": r"[A-Za-z0-9_+=,.@-]{1,64}"},
        ),
    },
    arn_defaults={
        ("IAM.Role", "Path"): "/",
        ("IAM.User", "Path"): "/",
        ("IAM.InstanceProfile", "Path"): "/",
        ("IAM.ManagedPolicy", "Path"): "/",
    },
    special_properties={
        f"{policy}.Statement{statement}.Condition.{key}{values}": target
        for policy in (
            "IAM.Role.AssumeRolePolicyDocument",
            "IAM.Role.Policies[].PolicyDocument",
        )
        for statement in ("", "[]")
        for values in ("", "[]")
        for key, target in (
            (
                "ArnEquals.aws:SourceArn",
                (("S3.Bucket", "SecretsManager.Secret"), "Arn"),
            ),
            ("ArnLike.aws:SourceArn", (("S3.Bucket", "SecretsManager.Secret"), "Arn")),
            ("StringEquals.kms:EncryptionContext:aws:s3:arn", ("S3.Bucket", "Arn")),
            (
                "StringLike.kms:EncryptionContext:SecretARN",
                ("SecretsManager.Secret", "Arn"),
            ),
        )
    },
)

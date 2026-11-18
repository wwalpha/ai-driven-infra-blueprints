"""SageMaker reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "SageMaker.Domain": "DomainId",
        "SageMaker.Space": "Ref",
        "SageMaker.UserProfile": "Ref",
    },
    arn_attributes={
        "SageMaker.Domain": "DomainArn",
        "SageMaker.Space": "SpaceArn",
        "SageMaker.UserProfile": "UserProfileArn",
    },
    linked_subnets={
        "SageMaker.Domain.SubnetIds[]",
    },
    import_properties={
        "SageMaker.Domain.DomainSettings.RStudioServerProDomainSettings.DomainExecutionRoleArn": (
            "IAM.Role",
            "Arn",
        ),
        "SageMaker.Domain.VpcId": ("EC2.VPC", "VpcId"),
    },
    arn_shapes={
        "SageMaker.Space": (
            {"DomainId": "domain", "SpaceName": "id"},
            "arn:{partition}:sagemaker:{region}:{account}:space/{domain}/{id}",
            {"domain": r"d-[a-z0-9]+", "id": r"[A-Za-z0-9][A-Za-z0-9-]{0,62}"},
        ),
        "SageMaker.UserProfile": (
            {"DomainId": "domain", "UserProfileName": "id"},
            "arn:{partition}:sagemaker:{region}:{account}:user-profile/{domain}/{id}",
            {"domain": r"d-[a-z0-9]+", "id": r"[A-Za-z0-9][A-Za-z0-9-]{0,62}"},
        ),
    },
)

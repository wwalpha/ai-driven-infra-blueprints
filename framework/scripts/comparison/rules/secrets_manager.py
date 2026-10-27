"""Static SecretsManager comparison methods; container rules include their recursive contents."""

from ..contracts import ResourceContract
from ..methods import properties

RULES = {
    "SecretsManager.ResourcePolicy": properties(
        objects="""
            ResourcePolicy
        """,
        scalars="""
            BlockPublicPolicy
            SecretId
        """,
    ),
    "SecretsManager.RotationSchedule": properties(
        objects="""
            ExternalSecretRotationMetadata[]
            HostedRotationLambda
            RotationRules
        """,
        ordered="""
            ExternalSecretRotationMetadata
        """,
        references="""
            SecretId
        """,
        scalars="""
            ExternalSecretRotationMetadata[].Key
            ExternalSecretRotationMetadata[].Value
            ExternalSecretRotationRoleArn
            HostedRotationLambda.ExcludeCharacters
            HostedRotationLambda.KmsKeyArn
            HostedRotationLambda.MasterSecretArn
            HostedRotationLambda.MasterSecretKmsKeyArn
            HostedRotationLambda.RotationLambdaName
            HostedRotationLambda.RotationType
            HostedRotationLambda.Runtime
            HostedRotationLambda.SuperuserSecretArn
            HostedRotationLambda.SuperuserSecretKmsKeyArn
            HostedRotationLambda.VpcSecurityGroupIds
            HostedRotationLambda.VpcSubnetIds
            RotateImmediatelyOnUpdate
            RotationLambdaARN
            RotationRules.AutomaticallyAfterDays
            RotationRules.Duration
            RotationRules.ScheduleExpression
        """,
    ),
    "SecretsManager.Secret": properties(
        resource=ResourceContract(explicit_name="Name"),
        objects="""
            GenerateSecretString
            ReplicaRegions[]
            Tags[]
        """,
        ordered="""
            ReplicaRegions
        """,
        references="""
            KmsKeyId
        """,
        scalars="""
            Description
            GenerateSecretString.ExcludeCharacters
            GenerateSecretString.ExcludeLowercase
            GenerateSecretString.ExcludeNumbers
            GenerateSecretString.ExcludePunctuation
            GenerateSecretString.ExcludeUppercase
            GenerateSecretString.GenerateStringKey
            GenerateSecretString.IncludeSpace
            GenerateSecretString.PasswordLength
            GenerateSecretString.RequireEachIncludedType
            GenerateSecretString.SecretStringTemplate
            Name
            ReplicaRegions[].KmsKeyId
            ReplicaRegions[].Region
            Tags[].Key
            Tags[].Value
            Type
        """,
        tags="""
            Tags
        """,
    ),
}

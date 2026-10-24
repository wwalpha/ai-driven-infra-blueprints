"""Fixed codebuild design definitions; no display-engine dependencies."""

import re

CODEBUILD_VPC_PROPERTIES = {"CodeBuild.Project.VpcConfig.Subnets", "CodeBuild.Project.VpcConfig.SecurityGroupIds"}

CODEBUILD_FORMAL_VARIABLE = "CodeBuild.Project.Environment.EnvironmentVariables[]."

CODEBUILD_VARIABLE = "CodeBuild.Project.Environment.Variables."

CODEBUILD_VARIABLE_TYPE = re.compile(r"^<!-- codebuild-variable-type: (PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER) -->\s*")

COMPACT_FIELDS = {
    CODEBUILD_FORMAL_VARIABLE + 'Name': (('Name', 'Type', 'Value'), None),
}

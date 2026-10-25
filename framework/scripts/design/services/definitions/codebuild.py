"""Fixed codebuild design definitions; no display-engine dependencies."""

import re

CODEBUILD_SUBNETS = "CodeBuild.Project.VpcConfig.Subnets"
CODEBUILD_SECURITY_GROUPS = "CodeBuild.Project.VpcConfig.SecurityGroupIds"
CODEBUILD_VPC_PROPERTIES = {CODEBUILD_SUBNETS, CODEBUILD_SECURITY_GROUPS}

ARRAY_VARIABLE = re.compile(r"(^|\.)Environment\.Variables(?=\.[^.]+$)")
COMPACT_ARRAY = re.compile(r"Environment\.Variables\[\]\.[^.]+$")

CODEBUILD_FORMAL_VARIABLE = "CodeBuild.Project.Environment.EnvironmentVariables[]."

CODEBUILD_VARIABLE = "CodeBuild.Project.Environment.Variables."

CODEBUILD_VARIABLE_TYPE = re.compile(
    r"^<!-- codebuild-variable-type: (PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER) -->\s*"
)

COMPACT_FIELDS = {
    CODEBUILD_FORMAL_VARIABLE + "Name": (("Name", "Type", "Value"), None),
}

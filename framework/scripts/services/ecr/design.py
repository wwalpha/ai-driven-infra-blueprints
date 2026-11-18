"""Fixed ecr design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "ECR.Repository.RepositoryPolicyText": "statement",
    "ECR.Repository.LifecyclePolicy": "settings",
}

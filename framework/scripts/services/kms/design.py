"""Fixed kms design definitions; no display-engine dependencies."""

POLICY_FORMATS = {
    "KMS.Key.KeyPolicy": "statement",
}

COLLAPSED_POLICY_DOCUMENTS = set(POLICY_FORMATS)


def alias_name_errors(kind: str, field: str, value: str) -> list[str]:
    if (kind, field) == ("KMS.Alias", "AliasName") and (
        not value.startswith("alias/") or value.startswith("alias/aws/")
    ):
        return ["KMS AliasName must use alias/ and exclude reserved alias/aws/"]
    return []


PROVIDER_NAME_CHECKS = {"KMS.Alias": alias_name_errors}

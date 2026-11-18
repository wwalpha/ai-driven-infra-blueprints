"""Fixed SSM design definitions."""

POLICY_DOCUMENT = "SSM.ResourcePolicy.Policy"

POLICY_FORMATS = {
    POLICY_DOCUMENT: "statement",
}

# Name identifies the referenced SSM document.
RESOURCE_NAME_FIELDS = {"SSM.Association": ("AssociationName",)}

COLLAPSED_POLICY_DOCUMENTS = {POLICY_DOCUMENT}

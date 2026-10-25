"""cloudwatch logs comparison contracts and projections."""

from utils.reference_contracts import KMS_FORMS as _KMS_FORMS

KMS_FORMS = {
    prop: forms for prop, forms in _KMS_FORMS.items() if prop.startswith("Logs.")
}

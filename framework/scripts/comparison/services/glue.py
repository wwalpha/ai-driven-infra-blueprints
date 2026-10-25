"""glue comparison contracts and projections."""

from utils.cloudformation.inputs import Blocked
from utils.reference_contracts import KMS_FORMS as _KMS_FORMS

KMS_FORMS = {
    prop: forms for prop, forms in _KMS_FORMS.items() if prop.startswith("Glue.")
}


def arn_components(properties, evaluate):
    # The newer top-level names must agree with the nested creation name.
    for field, container in [("DatabaseName", "DatabaseInput"), ("Name", "TableInput")]:
        if field in properties and container in properties:
            if evaluate(properties[field]) != evaluate(
                properties[container].get("Name")
            ):
                raise Blocked("Glue ARN requires one confirmed creation name")
    return {}

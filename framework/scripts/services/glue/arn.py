"""Service-specific checks and components for ARN assembly."""

from utils.cloudformation.inputs import Blocked


def glue_name(properties, evaluate):
    # The newer top-level names must agree with the nested creation name.
    for field, container in [("DatabaseName", "DatabaseInput"), ("Name", "TableInput")]:
        if field in properties and container in properties:
            if evaluate(properties[field]) != evaluate(
                properties[container].get("Name")
            ):
                raise Blocked("Glue ARN requires one confirmed creation name")
    return {}


COMPONENTS = {
    "Glue.Connection": glue_name,
    "Glue.SecurityConfiguration": glue_name,
    "Glue.Job": glue_name,
    "Glue.Crawler": glue_name,
    "Glue.Database": glue_name,
    "Glue.Table": glue_name,
}

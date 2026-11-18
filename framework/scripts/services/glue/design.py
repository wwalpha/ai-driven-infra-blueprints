"""Fixed glue design definitions; no display-engine dependencies."""

import re

GLUE_ARGUMENTS = {"DefaultArguments", "NonOverridableArguments"}

GLUE_ARGUMENT_SOURCE = re.compile(r"^<!-- glue-arguments-source: (.+?) --> ")

RESOURCE_NAME_FIELDS = {"Glue.Database": ("DatabaseInput.Name",)}


NAMING_EXEMPT_PROPERTIES = {
    "Glue.Connection.ConnectionInput.Name",
    "Glue.Database.DatabaseInput.Name",
    "Glue.Table.TableInput.Name",
}


def review_glue_name(kind: str, actual: str, same_type_count: int) -> list[str]:
    errors = []
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", actual):
        errors.append("Glue Name must use lower-kebab-case")
    if (
        kind == "Glue.SecurityConfiguration"
        and same_type_count > 1
        and not re.match(r"glsc-(?:0[1-9]|[1-9][0-9])(?:-|$)", actual)
    ):
        errors.append(
            "Multiple Glue SecurityConfigurations require a positive two-digit sequence"
        )
    return errors


REVIEW_NAME_CHECKS = {
    "Glue.Job.Name": review_glue_name,
    "Glue.SecurityConfiguration.Name": review_glue_name,
}

"""Fixed glue design definitions; no display-engine dependencies."""

import re

GLUE_ARGUMENTS = {"DefaultArguments", "NonOverridableArguments"}

GLUE_ARGUMENT_SOURCE = re.compile(r"^<!-- glue-arguments-source: (.+?) --> ")

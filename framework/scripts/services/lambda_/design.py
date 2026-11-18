"""Fixed lambda_permission design definitions; no display-engine dependencies."""

import re

LAMBDA_PERMISSION = "Lambda.Permission"

PERMISSION_METADATA = re.compile(r"^<!-- lambda-permission: (.+?) -->\s*")

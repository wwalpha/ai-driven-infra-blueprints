"""Fixed guardduty design definitions; no display-engine dependencies."""

import re

ARRAY_FEATURE = re.compile(r"(^|\.)Features(?=\.[^.]+$)")
COMPACT_ARRAY = re.compile(r"Features\[\]\.[^.]+$")

GUARDDUTY_FEATURE = "GuardDuty.Detector.Features."

GUARDDUTY_FORMAL_FEATURE = "GuardDuty.Detector.Features[]."

"""Fixed codepipeline design definitions; no display-engine dependencies."""

import re

PACKED_ARRAY_PREFIXES = ('CodePipeline.Pipeline.Stages[]',)

CODEPIPELINE_STAGE = re.compile(r"^Stages\[([1-9]\d*)\]\.(?:Actions(?:\[([1-9]\d*)\])?\.)?(.+)$")

CODEPIPELINE_CONFIGURATION = "CodePipeline.Pipeline.Stages[].Actions[].Configuration"

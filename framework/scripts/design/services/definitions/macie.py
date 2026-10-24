"""Fixed macie design definitions; no display-engine dependencies."""

import re

JOB = re.compile(r"^### Macie\.ClassificationJob: ([A-Za-z0-9][A-Za-z0-9_.-]*)$")

SCOPE = re.compile(r"^\|\s*\d+\s*\|\s*s3JobDefinition\s*\|\s*\[[^\]]+\]\(([^)#]+\.json)\)\s*\|")

BUCKET_LINK = re.compile(r"^\[([^\]]+)\]\(([^)#]+#[^)]+)\)$")

HEADER = "| Job | AWS account ID | Bucket |"

ALIGNMENT = "| --- | --- | --- |"

HEADING = "#### 対象S3 bucket"

MACIE_JOB = "Macie.ClassificationJob"

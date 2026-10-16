"""Shared fixture checks with service-specific policy and producer assertions."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.parameter_cases import run

for service in ('athena', 'codecommit', 'datazone', 'security-hub', 'sqs'):
    run(service)

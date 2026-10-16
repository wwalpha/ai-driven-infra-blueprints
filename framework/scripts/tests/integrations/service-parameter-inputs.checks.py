"""Shared fixture checks with service-specific policy and producer assertions."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import module_complete

from integrations.parameter_cases import run

for service in ('athena', 'codecommit', 'datazone', 'security-hub', 'sqs'):
    run(service)

module_complete(__file__)

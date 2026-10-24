"""Shared fixture checks with service-specific policy and producer assertions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from integrations.parameter_cases import run
from support.it_case_receipt import module_complete

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

for service in ('athena', 'sqs'):
    run(service)

module_complete(__file__)

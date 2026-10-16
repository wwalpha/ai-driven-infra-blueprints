"""Shared fixture checks with service-specific policy and producer assertions."""
from test_support.parameter_cases import run

for service in ('athena', 'codecommit', 'datazone', 'security-hub', 'sqs'):
    run(service)

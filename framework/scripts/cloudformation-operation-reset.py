#!/usr/bin/env python3
"""Human-operated CloudFormation journal reset CLI. Never runs AWS operations."""

from deploy.operation_reset import main

if __name__ == "__main__":
    raise SystemExit(main())

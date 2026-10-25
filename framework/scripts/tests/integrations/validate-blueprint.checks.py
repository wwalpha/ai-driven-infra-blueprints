#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.validation_checks import (
    runner,
    scope,
    task,
    terraform,
)
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def main():
    task.check_task_contract()
    task.check_idle_without_active_task()
    task.check_destroy_phase()
    task.check_task_type_dispatch()
    runner.check_module_inputs()
    scope.check_deployment_iac_scope()
    terraform.check_cli()
    print("Validator integrations: PASS")


if __name__ == "__main__":
    from support.model_sources import catalog_display

    with catalog_display():
        main()

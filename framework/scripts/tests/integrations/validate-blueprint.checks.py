#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from integrations.validation_checks import cloudformation, design, references, runner, scenario, scope, task, terraform


@it_case
def main():
    cloudformation.check_cloudformation_stack_design()
    cloudformation.check_stack_mapping_targets()
    design.check_description_design_constraints()
    references.check_identifier_propagation()
    references.check_array_source_role_links()
    references.check_s3_bucket_policy_grouping()
    references.check_subnet_association_overview()
    references.check_resource_overview()
    task.check_task_contract()
    task.check_idle_without_active_task()
    task.check_destroy_phase()
    task.check_task_type_dispatch()
    runner.check_module_inputs()
    scenario.check_records()
    scope.check_deployment_iac_scope()
    scope.check_task_file_gating()
    terraform.check_cli()
    print("Validator integrations: PASS")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()

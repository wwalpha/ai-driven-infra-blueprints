#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from units.validation_checks import terraform, cloudformation, contracts, design, references, runner, scenario, task


def main():
    terraform.check_configuration()
    contracts.check_optional_alias_contract()
    contracts.check_implementation_preflight_prompt()
    contracts.check_update_flow_prompt()
    contracts.check_design_handoff_prompt()
    contracts.check_rule_reading_contract()
    cloudformation.check_cloudformation_yaml_rules()
    cloudformation.check_cloudformation_environment_parameters()
    design.check_catalog_inputs()
    design.check_schema_backed_design_rows()
    design.check_name_tag_and_identifier_order_contract()
    design.check_cidr_pending_deploy()
    design.check_event_rule_row_order()
    references.check_artifact_naming()
    task.check_optional_alias_targets()
    task.check_model_task_boundaries()
    runner.check_dispatch()
    runner.check_boundaries()
    runner.check_module_keys()
    scenario.check_timestamp()
    from support.validator import MODULE
    assert MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("01_initialize.md")
    assert not MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("initialize.md")
    print("Validator units: PASS")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()

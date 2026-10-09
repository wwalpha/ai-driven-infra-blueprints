#!/usr/bin/env python3
"""Validator regression entrypoint; execution order stays explicit here."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from test_support.validator import MODULE, load
from validation_checks import task, design, references, cloudformation, terraform, scope, contracts, scenario, runner


def main() -> None:
    runner.check_dispatch()
    runner.check_boundaries()
    runner.check_module_inputs()
    scenario.check_records()
    load("design_document.checks").check_links(MODULE)
    scope.check_deployment_iac_scope()
    scope.check_task_file_gating()
    references.check_artifact_naming()
    assert MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("01_initialize.md")
    assert not MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch("initialize.md")
    contracts.check_rule_reading_contract()
    task.check_task_contract()
    task.check_idle_without_active_task()
    task.check_destroy_phase()
    task.check_task_type_dispatch()
    task.check_optional_alias_targets()
    contracts.check_optional_alias_contract()
    task.check_model_task_boundaries()
    design.check_schema_backed_design_rows()
    design.check_description_design_constraints()
    contracts.check_implementation_preflight_prompt()
    contracts.check_update_flow_prompt()
    references.check_identifier_propagation()
    references.check_array_source_role_links()
    design.check_name_tag_and_identifier_order_contract()
    design.check_cidr_pending_deploy()
    design.check_catalog_display_order()
    design.check_event_rule_row_order()
    references.check_s3_bucket_policy_grouping()
    references.check_resource_overview()
    references.check_subnet_association_overview()
    terraform.check_configuration()
    cloudformation.check_cloudformation_yaml_rules()
    cloudformation.check_cloudformation_environment_parameters()
    cloudformation.check_cloudformation_stack_design()
    cloudformation.check_stack_mapping_targets()
    contracts.check_design_handoff_prompt()
    print("validate-blueprint: PASS (63 existing focused checks + responsibility boundaries)")



if __name__ == "__main__":
    main()

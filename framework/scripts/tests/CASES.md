# UT / IT 全ケース台帳

## Attribute comparison Rulebook and common methods

190 collected UT cases. The shared suite owns typed equality, object selection, ordered/multiset/keyed collections, nested overrides, uncertainty and evidence extraction. Service suites retain reference resolution, preparation, classification and Runner/Issues connections. The Rulebook coverage check reads Catalogs only in this test; runtime rules are static. IAM Action and multiset algorithm assertions were moved from the old core/reference suites. Unselected PolicyName uncertainty assertions now live here instead of the Issues caller suite.

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `comparison-methods::test_scalar` | `test_scalar` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 8 | scalar | Synthetic values / static Framework definitions |
| `comparison-methods::test_object_scope` | `test_object_scope` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 2 | object scope | Synthetic values / static Framework definitions |
| `comparison-methods::test_ordered` | `test_ordered` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 4 | ordered | Synthetic values / static Framework definitions |
| `comparison-methods::test_unordered` | `test_unordered` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 4 | unordered | Synthetic values / static Framework definitions |
| `comparison-methods::test_unordered_singleton_difference_keeps_diagnostic` | `test_unordered_singleton_difference_keeps_diagnostic` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | singleton diagnostic and mismatched keys | Synthetic values / static Framework definitions |
| `comparison-methods::test_unordered_augmenting_paths` | `test_unordered_augmenting_paths` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | unordered augmenting paths | Synthetic values / static Framework definitions |
| `comparison-methods::test_keyed` | `test_keyed` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 9 | keyed | Synthetic values / static Framework definitions |
| `comparison-methods::test_unknown_presence` | `test_unknown_presence` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 3 | unknown presence | Synthetic values / static Framework definitions |
| `comparison-methods::test_reference_diagnostics_once_and_render_masking` | `test_reference_diagnostics_once_and_render_masking` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | reference diagnostics once and render masking | Synthetic values / static Framework definitions |
| `comparison-methods::test_reference_identity_and_unproven` | `test_reference_identity_and_unproven` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | reference identity and unproven | Synthetic values / static Framework definitions |
| `comparison-methods::test_iam_rules` | `test_iam_rules` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 4 | iam rules | Synthetic values / static Framework definitions |
| `comparison-methods::test_action_string_list_and_scope` | `test_action_string_list_and_scope` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 2 | action string list and scope | Synthetic values / static Framework definitions |
| `comparison-methods::test_nested_override_and_keyed_evidence` | `test_nested_override_and_keyed_evidence` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | nested override and keyed evidence | Synthetic values / static Framework definitions |
| `comparison-methods::test_rulebook_complete_static_coverage` | `test_rulebook_complete_static_coverage` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | rulebook complete static coverage | Synthetic values / static Framework definitions |
| `comparison-methods::test_unregistered_rule_is_framework_error` | `test_unregistered_rule_is_framework_error` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | unregistered rule is framework error | Synthetic values / static Framework definitions |
| `comparison-methods::test_codebuild_nested_reference_proof_is_reused` | `test_codebuild_nested_reference_proof_is_reused` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | codebuild nested reference proof is reused | Synthetic values / static Framework definitions |
| `comparison-methods::test_reference_atomic_difference_path_and_missing` | `test_reference_atomic_difference_path_and_missing` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | reference atomic difference path and missing | Synthetic values / static Framework definitions |
| `comparison-methods::test_nested_array_rule_and_unknown_prefix` | `test_nested_array_rule_and_unknown_prefix` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | nested array rule and unknown prefix | Synthetic values / static Framework definitions |
| `comparison-methods::test_contextual_secret_comparison` | `test_contextual_secret_comparison` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 40 | contextual secret comparison | Synthetic values / static Framework definitions |
| `comparison-methods::test_contextual_reference_identity_and_unknown` | `test_contextual_reference_identity_and_unknown` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 2 | contextual reference identity and unknown | Synthetic values / static Framework definitions |
| `comparison-methods::test_contextual_symbol_attributes_are_not_rewritten` | `test_contextual_symbol_attributes_are_not_rewritten` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 16 | contextual symbol attributes are not rewritten | Synthetic values / static Framework definitions |
| `comparison-methods::test_contextual_parameter_name` | `test_contextual_parameter_name` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | contextual parameter name | Synthetic values / static Framework definitions |
| `comparison-methods::test_codebuild_parameter_partial_selection_preserves_extra_fields` | `test_codebuild_parameter_partial_selection_preserves_extra_fields` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | codebuild parameter partial selection preserves extra fields | Synthetic values / static Framework definitions |
| `comparison-methods::test_codebuild_full_selection_detects_extra_fields` | `test_codebuild_full_selection_detects_extra_fields` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | codebuild full selection detects extra fields | Synthetic values / static Framework definitions |
| `comparison-methods::test_codebuild_dynamic_literal_is_unresolved` | `test_codebuild_dynamic_literal_is_unresolved` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | codebuild dynamic literal is unresolved | Synthetic values / static Framework definitions |
| `comparison-methods::test_unordered_length_mismatch_does_not_compare_pairs` | `test_unordered_length_mismatch_does_not_compare_pairs` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 3 | unordered length mismatch does not compare pairs | Synthetic values / static Framework definitions |
| `comparison-methods::test_policy_name_unselected_uses_selected_unordered_comparison` | `test_policy_name_unselected_uses_selected_unordered_comparison` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 2 | policy name unselected uses selected unordered comparison | Synthetic values / static Framework definitions |
| `comparison-methods::test_policy_key_selection_uncertainty` | `test_policy_key_selection_uncertainty` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 48 | IAM Role/User direct and projected key selection, unresolved Ref/Expression, invalid unselected intrinsic, selected document uncertainty and differences; zero unselected key evaluation and accurate candidate evidence | Synthetic values / Mock Evaluator |
| `comparison-methods::test_keyless_comparison_and_separate_key_integrity` | `test_keyless_comparison_and_separate_key_integrity` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 20 | Reordered keyless/mixed selection; zero unselected key evaluation in attribute comparison; independent Resource key integrity detects resolved duplicates and preserves unresolved/invalid-name evidence and conditional pointers | Synthetic values / Mock Evaluator |
| `comparison-methods::test_keyless_match_ignores_rejected_candidate_diagnostics` | `test_keyless_match_ignores_rejected_candidate_diagnostics` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | keyless match ignores rejected candidate diagnostics | Synthetic values / static Framework definitions |
| `comparison-methods::test_keyless_policy_matching_and_actual_differences` | `test_keyless_policy_matching_and_actual_differences` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 2 | keyless policy matching and actual differences | Synthetic values / static Framework definitions |
| `comparison-methods::test_policy_unique_attribute_evidence` | `test_policy_unique_attribute_evidence` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 12 | policy unique attribute evidence | Synthetic values / static Framework definitions |
| `comparison-methods::test_keyless_unique_remainder_after_reordered_matches` | `test_keyless_unique_remainder_after_reordered_matches` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | keyless unique remainder after reordered matches | Synthetic values / static Framework definitions |
| `comparison-methods::test_keyless_unproven_pairs_remain_missing` | `test_keyless_unproven_pairs_remain_missing` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 10 | Role/User ambiguous correspondence, duplicates, missing candidates, selected-name mismatch and unresolved candidates preserve tri-state evidence | Synthetic values / static Framework definitions |
| `comparison-methods::test_keyless_conditional_projection_and_masking_use_cached_evidence` | `test_keyless_conditional_projection_and_masking_use_cached_evidence` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | keyless conditional projection and masking use cached evidence | Synthetic values / static Framework definitions |
| `comparison-methods::test_keyless_policy_unresolved_sibling_keeps_known_difference` | `test_keyless_policy_unresolved_sibling_keeps_known_difference` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | keyless policy unresolved sibling keeps known difference | Synthetic values / static Framework definitions |
| `comparison-methods::test_unordered_length_difference_retains_proven_sid_and_pointers` | `test_unordered_length_difference_retains_proven_sid_and_pointers` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 1 | unordered length difference retains proven sid and pointers | Synthetic values / static Framework definitions |
| `comparison-methods::test_nested_policy_reference_difference_keeps_keyed_path_and_values` | `test_nested_policy_reference_difference_keeps_keyed_path_and_values` | UT | [units/comparison_methods-unit.checks.py](units/comparison_methods-unit.checks.py) | pytest / 2 | nested policy reference difference keeps keyed path and values | Synthetic values / static Framework definitions |


## Issue cause classification and proven Service ownership

16 UT entrypoints / 47 collected pytest cases. Synthetic inputs only. Ownership proof combinations live in this suite; caller suites verify routing, Reference/Human/PLAINTEXT/cfn-lint integration and v6 publication.

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `issues-cause-owner::owner_evidence` | `check_owner_evidence` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 11 | owner evidence | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::shared_multiple_and_redirected_sources` | `check_shared_multiple_and_redirected_sources` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | shared multiple and redirected sources | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::cause_does_not_change_existing_identity` | `check_cause_does_not_change_existing_identity` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | cause does not change existing identity | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::proven_required_property_and_generic_exception` | `check_proven_required_property_and_generic_exception` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | proven required property and generic exception | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::model_read_is_processing_with_proven_owner` | `check_model_read_is_processing_with_proven_owner` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | model read is processing with proven owner | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::reference_taxonomy` | `check_reference_taxonomy` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 3 | reference taxonomy | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::source_path_and_unstructured_violation_retained` | `check_source_path_and_unstructured_violation_retained` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | source path and unstructured violation retained | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::model_syntax_is_explicit_input_error` | `check_model_syntax_is_explicit_input_error` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | model syntax is explicit input error | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::v6_owner_assignment_and_unresolved_snapshot` | `check_v6_owner_assignment_and_unresolved_snapshot` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 8 | v6 owner assignment and unresolved snapshot | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::review_rejects_unproven_assignment` | `check_review_rejects_unproven_assignment` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 4 | review rejects unproven assignment | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::python_owner_needs_no_llm_assignment` | `check_python_owner_needs_no_llm_assignment` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | python owner needs no llm assignment | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::outside_diagnostics_do_not_require_assignment` | `check_outside_diagnostics_do_not_require_assignment` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | outside diagnostics do not require assignment | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::wrapped_findings_keep_classification_and_ids` | `check_wrapped_findings_keep_classification_and_ids` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | wrapped findings keep classification and ids | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::identical_service_failures_keep_independent_ids` | `check_identical_service_failures_keep_independent_ids` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 1 | identical service failures keep independent ids | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::v6_diagnostic_contract_rejects_misrouting` | `check_v6_diagnostic_contract_rejects_misrouting` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 6 | v6 diagnostic contract rejects misrouting | Synthetic source/Model/Scan/Review |
| `issues-cause-owner::real_input_violations_are_never_processing_failures` | `check_real_input_violations_are_never_processing_failures` | UT | [units/issues-ownership-unit.checks.py](units/issues-ownership-unit.checks.py) | pytest / 5 | real input violations are never processing failures | Synthetic source/Model/Scan/Review |


## Mapping-defined pending environment Values

28 UT entrypoints / 83 collected pytest cases; synthetic data only, no local IT or AWS.
The common suite owns the parser/state combinations; existing service suites retain their
service policy and delegation assertions. Id fixture correction in codebuild-plaintext
changes no test count. Existing IT registrations and their connection responsibilities
remain unchanged.

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `environment-values::model_pending_values` | `check_model_pending_values` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 14 | model pending values | Synthetic Mapping/Model/CFn inputs |
| `environment-values::pending_not_an_escape` | `check_pending_not_an_escape` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 10 | pending not an escape | Synthetic Mapping/Model/CFn inputs |
| `environment-values::codebuild_secret_reference_not_plaintext` | `check_codebuild_secret_reference_not_plaintext` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 2 | codebuild secret reference not plaintext | Synthetic Mapping/Model/CFn inputs |
| `environment-values::glue_quoting` | `check_glue_quoting` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | glue quoting | Synthetic Mapping/Model/CFn inputs |
| `environment-values::invalid_mapping_metadata` | `check_invalid_mapping_metadata` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 5 | invalid mapping metadata | Synthetic Mapping/Model/CFn inputs |
| `environment-values::mapping_schema_paths_and_publication` | `check_mapping_schema_paths_and_publication` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | mapping schema paths and publication | Synthetic Mapping/Model/CFn inputs |
| `environment-values::pipeline_name_reference_and_candidate_guard` | `check_pipeline_name_reference_and_candidate_guard` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 2 | pipeline name reference and candidate guard | Synthetic Mapping/Model/CFn inputs |
| `environment-values::unrelated_pending_does_not_hide_invalid_requested_value` | `check_unrelated_pending_does_not_hide_invalid_requested_value` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | unrelated pending does not hide invalid requested value | Synthetic Mapping/Model/CFn inputs |
| `environment-values::codebuild_plaintext_link_still_rejected` | `check_codebuild_plaintext_link_still_rejected` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | codebuild plaintext link still rejected | Synthetic Mapping/Model/CFn inputs |
| `environment-values::comparison_preserves_confirmed_siblings` | `check_comparison_preserves_confirmed_siblings` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 5 | comparison preserves confirmed siblings | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_blocks_literals_and_parameters` | `check_deploy_blocks_literals_and_parameters` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 8 | deploy blocks literals and parameters | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_accepts_cfn_references` | `check_deploy_accepts_cfn_references` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 13 | deploy accepts cfn references | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_selects_active_branch_and_only_environment` | `check_deploy_selects_active_branch_and_only_environment` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | deploy selects active branch and only environment | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_snapshot_guard_precedes_aws_and_is_per_stack` | `check_deploy_snapshot_guard_precedes_aws_and_is_per_stack` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | deploy snapshot guard precedes aws and is per stack | Synthetic Mapping/Model/CFn inputs |
| `environment-values::display_and_artifact_retain_pending` | `check_display_and_artifact_retain_pending` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | Display and JSON View retain Pending with warnings; AWS input validation remains independent | Synthetic Mapping/Model/CFn inputs |
| `environment-values::pipeline_direct_display_roundtrip` | `check_pipeline_direct_display_roundtrip` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | pipeline direct display roundtrip | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_five_services` | `check_deploy_five_services` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 7 | deploy five services | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_only_evaluates_selected_settings` | `check_deploy_only_evaluates_selected_settings` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | deploy only evaluates selected settings | Synthetic Mapping/Model/CFn inputs |
| `environment-values::pending_stack_keeps_independent_peer_running` | `check_pending_stack_keeps_independent_peer_running` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 4 | pending stack keeps independent peer running | Synthetic Mapping/Model/CFn inputs |
| `environment-values::encoded_configuration_roundtrip` | `check_encoded_configuration_roundtrip` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | encoded configuration roundtrip | Synthetic Mapping/Model/CFn inputs |
| `environment-values::all_confirmed_values_are_preserved` | `check_all_confirmed_values_are_preserved` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | all confirmed values are preserved | Synthetic Mapping/Model/CFn inputs |
| `environment-values::snapshot_validated_once` | `check_snapshot_validated_once` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | snapshot validated once | Synthetic Mapping/Model/CFn inputs |
| `environment-values::comparison_pipeline_records_only_pending_leaf` | `check_comparison_pipeline_records_only_pending_leaf` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 2 | comparison pipeline records only pending leaf | Synthetic Mapping/Model/CFn inputs |
| `environment-values::deploy_uses_existing_select_and_mapping_evaluation` | `check_deploy_uses_existing_select_and_mapping_evaluation` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 2 | deploy uses existing select and mapping evaluation | Synthetic Mapping/Model/CFn inputs |
| `environment-values::encoded_environment_typed_reference_retains_state` | `check_encoded_environment_typed_reference_retains_state` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 2 | encoded environment typed reference retains state | Synthetic Mapping/Model/CFn inputs |
| `environment-values::glue_execution_expressions` | `check_glue_execution_expressions` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 2 | glue execution expressions | Synthetic Mapping/Model/CFn inputs |
| `environment-values::encoded_environment_invalid_entries` | `check_encoded_environment_invalid_entries` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 4 | encoded environment invalid entries | Synthetic Mapping/Model/CFn inputs |
| `environment-values::plain_json_string_is_not_an_encoded_environment_structure` | `check_plain_json_string_is_not_an_encoded_environment_structure` | UT | [units/environment_values-unit.checks.py](units/environment_values-unit.checks.py) | pytest / 1 | plain json string is not an encoded environment structure | Synthetic Mapping/Model/CFn inputs |


## ARN計算とPending成果物

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `arn-pending::named` | `test_named_arn_with_pending_output` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 5 | CodeBuild Id待ち、IAM Path、Lambda、Glue複合識別、Events EventBusの既存計算 | 追加 |
| `arn-pending::identity` | `test_only_generated_identity_waits` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 3 | KMS・EC2・SecretのAWS生成識別子待ちと大文字表示 | 追加 |
| `arn-pending::policy` | `test_pending_policy_display_keeps_resolved_positions` | UT | [units/model-reference-classification-unit.checks.py](units/model-reference-classification-unit.checks.py) | pytest / 1 | Policyの確定位置維持・部分Pending・Model参照/Markdownリンク保持・厳格View投影 | 追加 |
| `arn-pending::transaction` | `check_pending_artifact_transaction` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py) | pytest / 3 | Pending時もJSON/MarkdownをPASSで保存し警告保持、解消後は実ARNとリンクへ更新、両状態のMarkdown/JSON書込失敗Rollback、Model論理参照不変 | 追加 |

S3の計算可能なArn Pendingは既存test_explicit_pendingを更新。分類/表示UTは必要構成要素の待ちを証明できる合成入力へ修正し、未確認値/矛盾はReferenceResolutionErrorとして維持。Import strict、ARN組立、JSON整合性、Model/IaC比較は既存関連UTを利用。長時間ITと全ITは実行しない。

## Issues Scan failure isolation

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `issues-isolation::references` | `check_reference_diagnostic_isolation` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 6 | 参照診断全体/個別・PLAINTEXT全体/個別・Issue候補のValueError隔離、正常ID/重複排除、資料→IaC→mock raw lint→artifact v5保存の順序、ERROR/終了2、既存Issue不変 | 追加 |
| `issues-isolation::view` | `check_view_failure_isolation` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 3 | View構築・展開・表示ValueErrorのファイル別隔離、原因とNOT_RUN、独立した保存済みリンク検査 | 追加 |
| `issues-isolation::stage` | `check_scan_stage_failures` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 6 | mechanical/Model/lint/naming/既存Issue/レビュー/View事前読取り/診断対応付けの障害隔離、取得済み診断保持、独立比較/lint継続、CLI artifact v5保存とERROR終了、既存Issue読取り失敗時の報告保存・解消禁止 | 拡張 |
| `issues-isolation::materials` | `check_material_service_isolation` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 3 | naming/レビューのサービス別失敗・秘匿化、別サービス資料と比較/lintの継続、通常の命名資料・context同等性、Scan/SaveでHuman原文不変と2レポート保存 | 追加 |
| `issues-isolation::worker` | `check_service_worker_isolation` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 2 | service内部/workerの想定外例外、別service結果回収、既存診断とModel/observed検査、非cacheとNOT_RUN | 追加 |

## Markdown生成と保存済み参照の検証責務

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `saved-markdown-links::boundary` | `check_candidate_saved_reference_boundary` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 3 | 現行/旧reference-rows/旧reference-value参照先の局所解析、意味検証不能の警告、候補の旧形式拒否、対象外Markdown不変 | 追加 |
| `saved-markdown-links::typed-display` | `check_saved_typed_reference_display_difference` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 1 | typed Model参照を含む保存済みCodePipelineの表示差分をwrite候補の参照先として許容し、read-onlyではERROR/NOT_RUNへ隔離。headings単独は生成せず、展開では厳密拒否 | 追加 |
| `saved-markdown-links::indexed-model` | `check_candidate_indexed_saved_reference` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 8 | Glue配列・RotationSchedule親子配列、選択前生成・Snapshot再利用、別Resource/注記/見出し差分除外、参照対象改変FAIL、Model欠落NOT_RUN、実IAM候補の全必須検証と保存可否 | 追加 |
| `s3-replication::markdown` | `check_s3_replication_rules_markdown` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 1 | S3 ReplicationConfiguration の全項目と複数ルールの Model から Markdown への表示 | 追加 |
| `saved-markdown-links::import-sg` | `check_scoped_import_security_group_reference` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 1 | IMPORTのmode/bound anchorを維持し、SG親のみ参照では水平ruleを照合/解析前に除外、参照View再利用 | 追加 |
| `saved-markdown-links::sg-model-scope` | `check_scoped_security_group_model_reference` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py) | pytest / 10 | Model生成SGの親限定Viewでinline Ingress/EgressとTagsを除外、基本属性改変検出、明示子ルール展開/改変検出、対象外SG差分の分離、design.linksのPASS/FAIL | 追加 |
| `saved-markdown-links::candidate-completion` | `check_candidate_completion_matches_executed_view_checks` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 14 | 7品質checkのFAIL/NOT_RUNを通常生成が呼ばず、候補bytesを保持 | 拡張 |
| `saved-markdown-links::new-warning` | `check_saved_link_snapshot_and_new_warnings` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 1 | 旧形式参照元の軽量Snapshot、既存破損の除外、新規anchor破損と保存先限定警告、コメント内リンク除外、対象外不変 | 追加 |
| `saved-markdown-links::fallback` | `check_publication_failure_preserves_success` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 2 | JSON書込み失敗時の対象サービス復元と他サービスの保存維持。品質Validatorの再実行なし | 追加 |

既存 `check_stage_dependency_selection` のwrite/read-only 2条件を拡張し、旧形式の保存済み参照元が生成準備を阻害しないことを実軽量検査で確認する。`check_readonly_stale_views` に旧形式差分を追加する。候補のProperty/値/anchor等の改変拒否は既存model-reference-display UT::`check_actual_markdown_must_match`、旧形式拒否は同`check_obsolete_metadata_requires_regeneration`で維持し重複追加しない。

生成・保存・参照・Rollbackのコンポーネント接続は既存sync-model IT::`check_incoming_reference_models` / `check_changed_sidecar_publication_rollback` / `check_multiple_targets_barrier` / `check_publication_boundary`、bound-anchor-name-change ITの確認対象。ローカルIT・全IT・性能測定は実施しない。

## Issue 17 Model Designの検証責務

分類は 1=既存UT/別ITで保証済み、2=未検証の単体判定、3=接続/保存/部分失敗。
開始時の29関数・30 pytest条件を下表で網羅する（同じ責務の関数は同じ行に併記）。
ITは7関数・7条件へ縮小する。件数は静的登録数で、実行時間の測定値ではない。
UTは合成入力と既存関数を直接使用し、Sync/実CLI/Git/全Frameworkコピー/全Model生成を使わない。

| 旧IT関数 | 分類 | 実装判断 | assertionの現在の責務 |
|---|---|---|---|
| `check_route53_endpoint_dns_roundtrip` | 3 | IT保持 | Endpoint/Route53参照の正常値とID・service・region・record type・targetの不一致 |
| `check_import_optional_name_label` | 1/2/3 | IT縮小＋既存UT拡張 | 任意Nameとlabelの生成連携のみIT。欠落/未確定名/正式名優先はdesign_layout::check_resource_display_names、hidden ID/label/ResourceType不一致はcheck_authoritative_display_identity、必須Roleはcheck_one_way_model_contract |
| `check_firehose_import_pending_roundtrip / check_config_import_pending_roundtrip` | 1/2 | IT削除・既存UT/別ITへ集約 | check_import_pending_propertiesでIMPORT/CREATE・Pendingの形式と入力不変。Pending行の表示検証と別形式/参照先拒否はdesign_layout IT::check_config_firehose_references |
| `check_desired_only_identifier_reference` | 1/2 | IT削除・UT不足分のみ移管 | check_desired_only_identifier_referenceのdesired/observed投影不変。誤group label/targetはdesign_layout IT::check_quicksight_group_principal_reference、警告分類はmodel-reference-warnings UT |
| `check_catalog_display_order` | 2 | UT移管 | 同名UTで元row ID・配列の隣接順・QuickSight/S3/CodeBuild特別位置・SG例外。文字/説明/欠落/未知rowのstale判定はcheck_readonly_stale_viewsへ集約 |
| `check_kms_policy_execution_account` | 2/3 | IT縮小＋UT移管 | check_kms_policy_accountsでroot/Macie・scalar/array・cross-account comment・IMPORT免除・fallback・Service principal。KMS生成と保存拒否だけIT |
| `check_glue_argument_display` | 2 | UT移管 | 同名UTで順序・空/特殊文字・JSON原文・missing/duplicate key・value/comment改変・metadata/count欠落・不正JSON。display_rows/expanded_display_rowsを直接使用 |
| `check_ec2_compact_display` | 1/2 | UT移管 | 同名UTで1/5 block devices・任意VolumeType・Name圧縮・他tags・0/欠番/重複/先頭0・metadata改変・IMPORT Nameなし。汎用配列判定は既存array_display |
| `check_vpc_endpoint_name_display` | 2 | UT移管 | 同名UTでCREATE/IMPORTの単一Name・混在tags・metadata欠落/改変・IMPORT Nameなし |
| `check_subnet_lambda_roundtrip / check_subnet_model_validation` | 1 | IT重複削除 | 既存check_subnet_list_displayがLambdaを含む全16 propertyの配列/JSON・欠落/不正index/空配列を直接検証。正本/旧View保護は残す部分失敗IT、staleはcheck_readonly_stale_views |
| `check_athena_configuration_display` | 2 | UT移管 | 同名UTが全catalog行の表示aliasとformal_propertyへの復元を直接照合 |
| `check_config_typed_anchors` | 1/2/3 | IT縮小＋既存UT拡張 | Config typed/cross-serviceリンクはIT。anchorの型/大小文字/slashはdesign_layout::check_fixed_identity_anchors、重複logical IDは既存model-identity::main |
| `check_kms_alias_display` | 1/2 | IT削除・既存UT拡張 | design_layout::check_resource_display_namesに複数alias/選択label/不正alias/aliasなしの不足分。heading/anchor/grouped表示は既存design_layout IT::check_resource_name_headings / check_workflowと残すStack IT |
| `check_nameless_type_display` | 1/2 | IT削除・既存UT拡張 | design_layout::check_resource_display_namesでsingle/multiple・label・Name tagとnamed type区別。hidden ID/heading/labelはcheck_authoritative_display_identity、link labelはcheck_navigation_display_labels。観測値が名前/labelを上書きしないこともcheck_authoritative_display_identityで直接確認 |
| `check_nameless_logical_id_label` | 1/2 | IT削除・UT不足分移管 | check_authoritative_display_identityで2 Resourceの個別label欠落/未確定/不一致・hidden ID欠落/型とID不一致・entry番号独立・入力不変。unsupported formatは既存model-format-v2 |
| `check_optional_naming_suffix` | 2 | UT移管 | 同名UTで10規約の本文と命名対象・IAM suffixあり/なしのSchemaと表示選択 |
| `check_stack_policy` | 2 | UT移管 | 同名UTでstack_modelの整列・名前/parameter/template・comment・既定1・非正整数/欠落/旧mapping拒否とstack Markdownの直接往復。保存と正本保護はStack IT |
| `check_stack_mapping_roundtrip` | 1/2/3 | IT縮小＋UT移管 | Stack/CFn identity・grouped index/partsの接続だけIT。CFn文字形式と旧mapping拒否はcheck_stack_policy、missing CFn IDは既存model-identity::check_cfn_and_outputs、Terraform禁止・CFn形式/未宣言Stackはcheck_cfn_identity_inputs |
| `check_secret_naming_values` | 2 | UT移管 | 同名UTで規約本文・有効path全組合せ/末尾suffix・formal/short Name・未確定名・IMPORT免除・規約欠落 |
| `check_naming_exclusions` | 1/2 | UT移管 | 同名UTで11種のformal/short naming免除・未確定値/Name tag境界・Schema・未知property。Glue生成IDと設定名区別は既存design_layout::check_resource_display_names、check_generated_identifierのNOT_DEPLOYED拒否は既存validation_checks/design |
| `check_codebuild_required_name / check_iam_role_name` | 1/2 | IT削除・UT不足分移管 | check_required_resource_namesで欠落/重複/誤property/Name tag代用/12未確定値、formal/short。正常名優先は既存design_layout UT、link/headingはcheck_navigation_display_labelsと既存design_layout IT::check_resource_name_headings |
| `check_required_name_tag（2条件）` | 1/2 | IT削除・UT不足分移管 | 同名UTでEndpoint/InstanceのName tag欠落/不完全/大小文字/重複/非正式形式/非連続/12未確定値と共有診断。linkの名前/物理ID区別はcheck_navigation_display_labels、ID変換は既存observed/identity UT |
| `check_service_failure_protection` | 1/2/3 | IT最小化＋UT不足分移管 | IAM Markdown失敗によるJSON/旧View保護と独立Logs成功のみIT。詳細内訳は下記 |
| `check_service_displays` | 1 | IT重複削除 | 既存design_layout IT::check_codebuild_variable_display / check_guardduty_feature_display / check_cloudtrail_data_resources / check_codepipeline_display / check_workflow、security_group_tables IT::check_workflowへ集約。汎用配列はarray_display UT |
| `check_observed_arn_authority` | 2 | UT移管 | 同名UTでIMPORTの取得済ARNのみ許可、CREATE正本/表示に生成ARN禁止。in-memory design_sourcesで実Model保存不要 |
| `check_dynamic_reference_candidates` | 1/3 | IT縮小・既存UT重複削除 | 実Model候補生成のみIT。Username/Password上限・SecretBinary・ssm label・不正Dynamic Reference全条件は既存cloudformation_schema::main |

`check_service_failure_protection` の旧assertion群の分担:

| 旧検証 | 現在の責務 |
|---|---|
| VPC/Logs/IAM生成・入力不変、IAM保存失敗・JSON/Markdown保持、独立Logs保存 | 残す同名IT。正常生成1回＋IAMのみ失敗注入1回。例外はValueErrorと元のtest IAM write failure、対象はiam.md |
| 重複Model field・不正LogGroupName・RetentionInDays=31/not-a-number | 既存check_invalid_model、check_loggroup_invalid_values、validation_checks/designのSchema行検証 |
| read-only stale・欠落/未知row・View/Model非書込 | sync-model UT::check_readonly_stale_views、既存Loop IT::check_task_service_validation |
| JSON正本のdocument欠落・既存View/Model保護 | sync-model UT::check_generate_views_missing_authoritative_json。JSONリンクを維持しdocumentだけを削除して実generate_viewsの欠落判定を確認 |
| 独立serviceの継続、変更sidecar保存失敗/復旧 | sync-model IT::check_multiple_targets_barrier / check_changed_sidecar_publication_rollback / check_required_preflight、残す部分失敗IT |
| source/target rename・保持View・既存broken link・参照警告・観測値不変 | 既存model-reference-warnings UTのcheck_reference_view_retained_but_io_still_fails / check_generation_warning_keeps_independent_error、bound-anchor-name-change ITとsync-model IT::check_incoming_reference_models |
| planning後の入力変更、Task契約、CLI失敗伝播 | 既存sync-model IT::check_publication_boundary / check_two_consumer_cli、sync-model UT::check_snapshot_conflict、task-contract UT |
| 複数ファイルrollback | 既存sync-model IT::check_changed_sidecar_publication_rollback / check_multiple_targets_barrier。fixture writer自体の再試験は削除 |

Path.write_textの差替えは既存BoundCallback descriptorを再利用する。汎用descriptorは既存check_callback_binding、実Path/データ/encoding・instance/class呼出し・OSError伝播と旧file保持だけをcheck_path_write_text_bindingに追加する。
Fixtureのmodel/text/roundtrip/project/root/mainの公開APIは維持。projectのStack View初期化は1回、roundtripは同一Stack Viewの再書込と末尾の再読込を省略する。
pytest/direct/module completionとreceipt形式は変更しない。下記7 ITのpytest receiptは各1件を要求する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `model-design-17::check_route53_endpoint_dns_roundtrip` | `check_route53_endpoint_dns_roundtrip` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L54) | pytest / 1 | Endpointのobserved ID・ServiceName・region・TypeとRoute53生成View参照の照合 | 接続保証を保持 |
| `model-design-17::check_import_optional_name_label` | `check_import_optional_name_label` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L97) | pytest / 1 | Config IMPORT任意Nameなし/ありの生成View・保存anchor・linked_resource・正本不変 | 接続保証を保持 |
| `model-design-17::check_kms_policy_execution_account` | `check_kms_policy_execution_account` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L131) | pytest / 1 | Execution AccountのKMS policy生成・不正accountの保存拒否とMarkdown/JSON保護 | 接続保証を保持 |
| `model-design-17::check_config_typed_anchors` | `check_config_typed_anchors` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L184) | pytest / 1 | 同名の異型Config Resourceのtyped link・anchorと他serviceの参照 | 接続保証を保持 |
| `model-design-17::check_stack_mapping_roundtrip` | `check_stack_mapping_roundtrip` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L247) | pytest / 1 | Model→Stack→View→再読込、独立番号のKMS子Resource・index/parts入力不変 | 接続保証を保持 |
| `model-design-17::check_service_failure_protection` | `check_service_failure_protection` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L315) | pytest / 1 | VPC/Logs/IAM正常生成後のIAM書込失敗、旧Markdown/JSON保護・Logs部分成功・VPC/全正本不変 | 接続保証を保持 |
| `model-design-17::check_dynamic_reference_candidates` | `check_dynamic_reference_candidates` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L353) | pytest / 1 | Dynamic Referenceを含むQuickSight実Model生成・View保存・read-only検証・正本不変 | 接続保証を保持 |
| `model-design-17::check_glue_argument_display` | `check_glue_argument_display` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L414) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_ec2_compact_display` | `check_ec2_compact_display` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L454) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_vpc_endpoint_name_display` | `check_vpc_endpoint_name_display` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L511) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_athena_configuration_display` | `check_athena_configuration_display` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L555) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_catalog_display_order` | `check_catalog_display_order` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L576) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_optional_naming_suffix` | `check_optional_naming_suffix` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L618) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_secret_naming_values` | `check_secret_naming_values` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L643) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_kms_policy_accounts` | `check_kms_policy_accounts` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L680) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_required_resource_names` | `check_required_resource_names` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L729) | pytest / 2 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_required_name_tag` | `check_required_name_tag` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L747) | pytest / 2 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_naming_exclusions` | `check_naming_exclusions` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L777) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_import_pending_properties` | `check_import_pending_properties` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L813) | pytest / 2 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_stack_policy` | `check_stack_policy` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L829) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_observed_arn_authority` | `check_observed_arn_authority` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L867) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_desired_only_identifier_reference` | `check_desired_only_identifier_reference` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L886) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_loggroup_invalid_values` | `check_loggroup_invalid_values` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L897) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_authoritative_display_identity` | `check_authoritative_display_identity` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L906) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_navigation_display_labels` | `check_navigation_display_labels` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L966) | pytest / 4 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_cfn_identity_inputs` | `check_cfn_identity_inputs` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1005) | pytest / 1 | TerraformのCFn ID禁止/なし許可、CFn形式と未宣言Stack拒否の直接判定 | 不足分だけ移管 |
| `model-design-17::check_readonly_stale_views` | `check_readonly_stale_views` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L771) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |
| `model-design-17::check_generate_views_missing_authoritative_json` | `check_generate_views_missing_authoritative_json` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L720) | pytest / 1 | JSONリンクを保持してdocumentだけを削除、実欠落判定・生成結果なし・新規不正Viewなし・既存Markdown/JSONとModel正本不変 | Issue #17 回帰保証の復元 |
| `function-wrapper::callback` | `check_callback_binding` | UT | [units/function_wrapper-unit.checks.py](units/function_wrapper-unit.checks.py#L54) | pytest / 1 | 既存BoundCallback descriptorのinstance/class/直接呼出し | 既存登録の補完 |
| `model-design-17::check_path_write_text_binding` | `check_path_write_text_binding` | UT | [units/function_wrapper-unit.checks.py](units/function_wrapper-unit.checks.py#L71) | pytest / 1 | 合成入力による直接判定（対応は上表） | 不足分だけ移管 |


## Cleanup途中削除の復旧と状態表示

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `cleanup::missing` | `check_cleanup_missing_worktree` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L173) | pytest / 15 | 消失checkoutのHEAD/branch/merge/verified・管理領域の一意性/common/index/lock・未完了操作・index差分/読取失敗 | 追加 |
| `cleanup::safety` | `check_cleanup_stops_before_removal` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L212) | pytest / 9 | 未統合/履歴変更/HEAD変更/dirty/setup/リンク/locked/ignored/branch消失で削除前停止、状態と理由を保持 | 追加 |
| `cleanup::preflight` | `check_cleanup_preflight_diagnostics` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L244) | pytest / 2 | cleanup/finalizeのpreflight失敗でも残存4項目・停止理由をJSONへ表示 | 追加 |

既存 `check_cli_failure_diagnostics` にcleanup診断の同一引渡しを追加。既存 `check_cleanup_failure_and_retry` の1入口を拡張し、checkout削除後の失敗→Git登録のみ残存→CLI再実行で当該登録/branch/状態を削除、他Taskを保持する実Gitケースを追加する。既存のignored data・branch削除待ち・他Task証跡保持も維持する。ローカルではこの短時間ITだけを選択し、全IT/性能比較は実行しない。

## Git変更パス収集の共通化 / 1024

NUL解析・特殊文字・3分類・Git失敗は共通UTへ集約する。sync UTの旧NUL解析・Git終了コードMockは削除し、公開git_pathsの委譲と例外伝播だけを残す。Loopの旧subprocess失敗Mockも共通API委譲へ置換する。Worktreeの改行入りディレクトリはidle_gitのbatched出力fallbackを検証するため維持する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `git-changes::execution` | `check_readonly_execution` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L20) | pytest / 1 | cwd・Git環境継承・非グローバル変更・UTF-8/CRLF保持 | 追加 |
| `git-changes::paths` | `check_read_paths` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L38) | pytest / 4 | 空出力・NUL・日本語/空白/改行・重複排除・独立set | sync UTから移管・拡張 |
| `git-changes::working` | `check_working_paths` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L47) | pytest / 1 | 3コマンド引数・分類・統合・元集合からの独立 | 追加 |
| `git-changes::runner` | `check_collection_runner` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L66) | pytest / 1 | 明示runnerとrootの伝達・既定runner非実行 | 追加 |
| `git-changes::failure` | `check_fail_closed` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L79) | pytest / 6 | 各コマンド失敗・途中結果非採用・既定/注入runner | sync/Loop UTから移管・拡張 |
| `git-changes::exception` | `check_exception_propagation` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L94) | pytest / 4 | runner/path readerからのOSError/ValueError同一例外伝播 | 追加 |
| `git-changes::readonly` | `check_reject_mutations` | UT | [units/git-changes-unit.checks.py](units/git-changes-unit.checks.py#L107) | pytest / 9 | 書込コマンド・alias・出力指定等を実行前に拒否 | 追加 |
| `task-git::collection` | `check_scope_git_collection` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L498) | pytest / 4 | baseline/unborn/candidateのfinal対permission・issuesのGit集計なし・lock除外・存在/symlink・5/0/4/0回・検証間非cache・必須契約確認 | 追加 |

`check_final_git_paths` のbaseline固有4条件は維持。`select_checks` はmasterの全UT収集方式を維持し、既存 `check_regression_discovery` に新規UTの検出確認を追加する。変更ファイル依存マッピングは既に廃止されているため復元しない。`check_idle_git_paths_and_state` の6条件にはWorktree固有の委譲・GIT_*隔離・Blocked維持の確認を追加する。

## Python structure and callback compatibility

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `python-structure::module` | `test_module_imports_and_methods` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | モジュールImportと通常メソッドを許可 | Python品質 |
| `python-structure::nested` | `test_function_import_and_nested_definition` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | 関数内Importとネスト関数の位置を検出 | Python品質 |
| `python-structure::async` | `test_async_and_method_bodies` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | asyncとメソッド内違反を検出 | Python品質 |
| `python-structure::cli` | `test_cli_reports_location_and_failure` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | パス・行番号・終了コードと正常終了 | Python品質 |
| `function-wrapper::metadata` | `check_wrapper` | UT | [units/function_wrapper-unit.checks.py](units/function_wrapper-unit.checks.py#L25) | pytest / 1 | 呼出結果・署名・メタデータ保持 | Python品質 |
| `function-wrapper::method` | `check_method_binding` | UT | [units/function_wrapper-unit.checks.py](units/function_wrapper-unit.checks.py#L43) | pytest / 1 | instance/class経由のメソッド束縛 | Python品質 |

| `model-cli::entrypoints` | `check_cli_entrypoints` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L53) | pytest / 1 | 直接起動と公開mainのhelp一致・既存Module起動結果保持 | Python品質 |

## Issues package, artifact v5 and isolated cfn-lint

「元ID」の `issues-v2::` / `issues-v4::` は履歴上の識別子であり、現行Scan Artifactのversionではない。ID・関数名・検証責務は維持する。

既存deploy lint廃止は復元しない。旧workerの設定/schema/custom rule状態隔離とscope回収契約をutils入口で検証する。Framework定義は読取専用、一時HOME/config/rule/schemaは独立fixtureとする。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `issues-v2::check_classification` | `check_classification` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 9 | severity・E0000 provenance・特殊Error分類 | Issues Artifact v5 |
| `issues-v2::check_stack_parameter_jobs_and_invalid_inputs` | `check_stack_parameter_jobs_and_invalid_inputs` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | パラメータ構造・fallback・計画内読込再利用・ジョブ分離 | Issues parameter handling |
| `issues-v2::check_parameter_file_cli_and_redaction` | `check_parameter_file_cli_and_redaction` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 1 | 実 CLI パラメータ適用・fallback・機密値保護 | Issues parameter handling |
| `issues-v2::check_explicit_plan` | `check_explicit_plan` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | Stack parametersと独立した対象・共有dedup・owner・対象外 | Issues Artifact v5 |
| `issues-artifact::check_artifact_index_and_status` | `check_artifact_index_and_status` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | 一次集計・page先行・未対応形式拒否・status・bounded notice・review照合 | Issues Artifact v5 |
| `issues-v2::check_deferred_cache_finalization` | `check_deferred_cache_finalization` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | 最終入力確認まで候補保留・変更時不採用 | Issues Artifact v5 |
| `issues-v2::check_scan_changes_without_cache` | `check_scan_changes_without_cache` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | codepipeline.md変更中も集計完了・PASS cacheと監視artifactフィールドなし・例外をERRORへ隔離し中断は伝播 | Issues Artifact v5 |
| `issues-v2::check_worker_protocol_and_fatal` | `check_worker_protocol_and_fatal` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | protocol拒否・共通runtime失敗後not_run | Issues Artifact v5 |
| `issues-v2::check_cli_equivalence` | `check_cli_equivalence` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py#L63) | pytest / 2 | 実行環境のCLIの正常/異常代表各1入力、Rule/Level/Location/MessageとRegion一致 | Issues Artifact v5 |
| `issues-v2::check_plan_without_stack` | `check_plan_without_stack` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 4 | IMPORT/API-only先行分類・混在CREATE未検証・Stack loader回数 | Issues Artifact v5 |
| `issues-v2::check_processing_coverage_keeps_matches` | `check_processing_coverage_keeps_matches` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 3 | schema障害時の診断0件/混在の未完了coverageと通常/未知type診断保持・exit 2・分類途中例外でも取得済診断を保持 | Issues Artifact v5 |
| `issues-v2::check_view_read_failure_policy` | `check_view_read_failure_policy` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | issues局所View障害・独立service/source診断・実チェック件数・非cache・変更後再読取許容・通常Validatorの読取障害隔離 | Issues Artifact v5 |
| `issues-v4::check_child_builtin_packets_preserve_progress` | `check_child_builtin_packets_preserve_progress` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 2 | JSON組込み型へのIPC正規化・途中例外でも取得済み全channel/dependencies保持 | Issues residual repair |


## Issue 21 issues-lintの検証責務

現行登録は **4関数・5 pytest条件**（CLI同等性2、設定隔離1、schema復旧1、Timeout回収1）。
開始時の9関数・17条件の全assertionを次表に対応づける。重複条件は再追加しない。

| 旧IT（条件数） | 元のassertionが保証した内容 | 現在の保証先 |
| --- | --- | --- |
| check_cli_equivalence (4) | 正常/属性異常/YAML不正/非object、診断tuple・要求/実効Region・依存hash | 正常/属性異常の各代表1件は同名IT、YAML/非objectと抑制後decode不完全はcheck_config_input_branches UT。入力変更による依存guardは廃止 |
| check_config_exclusion_and_outputs (1) | config除外、ignore_bad/E0000抑制でも未検証、output非書込、deployment_files競合 | 分岐はcheck_config_input_branches UT、実output非書込・config再読込はcheck_worker_config_isolation IT |
| check_noecho_and_dependencies (1) | NoEcho秘密値非漏洩、依存入力照合、HOME候補追加/config変更のstale拒否 | 実redactionは設定隔離IT、Default/parameter検出はcheck_noecho_redaction UT、候補追加/内容/HOME変更によるstale拒否は仕様廃止 |
| check_rule_schema_state_and_reaping (1) | custom globalを要求間で持越さない、registry/override再設定、Worker正常終了、異常child後の継続/回収 | 設定隔離ITの4連続要求。異常childはschema復旧ITでfatal/not_runと回収を確認し、再使用せず新Workerへ。終了の分岐はshutdown UT |
| check_offline_schema (2) | mapping/schema欠落でschema_unavailable、fatal/not_run、ネットワークで修復しない | 代表の実schema障害/非書換えはcheck_schema_failure_recovery IT、欠落組合せはcheck_schema_failure_classification、通信/書込拒否はcheck_offline_and_write_guards UT |
| check_timeout (1) | Timeout結果とWorker終了 | check_timeout_reaping ITへ強化。30秒sleepを廃止し、起動確認後0.2秒の要求期限で実fork childのTERM無視・KILL・join・group消滅を検証。起動確認はfixture内だけでproduction IPC追加なし。Windowsは実onceのkill/wait/pipe解放 |
| check_scan_publication_and_missing_view (2) | Scan→Lint→Artifact→Review→Save、変更後保存と非cache、共有template一度decode、再集計禁止、review拒否と入力変更許容、欠落/UTF-8 Viewでも独立ServiceとLint継続 | 実接続は既存issues_scan::check_scan_publish_mismatch、変更中Scanはcheck_scan_changes_without_cache、review拒否は既存check_save_review_rejections、View/source独立性は既存check_view_read_failure_policyとcheck_dependency_view_failure_branches UT |
| check_corrupt_provider_schema (2) | JSON/構築障害分類、通常文字列resource_type、通常/未知type診断とdecode/dependencies保持、fatal/not_run、0診断でも未完了、override非誤分類、子回収 | 実IPCと混在診断/dependenciesはschema復旧IT。分岐はschema分類UT、0/混在診断のcoverageは拡張check_processing_coverage_keeps_matches、組込み型と途中例外保持は既存check_child_builtin_packets_preserve_progress UT |
| check_scan_dependency_view_failure (3) | scope外依存ViewのUTF-8/欠落/PermissionError分類、consumer、独立Logs差分/Lint、非Cache、チェック件数、秘密本文非漏洩、読取失敗診断保持と入力変更後保存許容、通常Validator伝播 | 3分岐の未保証分はcheck_dependency_view_failure_branches UT。通常Validatorと独立Model/source検証は既存check_view_read_failure_policy UT。実Scan/Lint接続は既存check_scan_publish_mismatch IT |

削除したScanケースを別ITへ移動しない。当該Issue #21移管時点ではIssuesのproduction Scan/Hash/Cache/保存処理は変更しなかった。その後、Issue専用の変更監視は廃止し、下記UTで入力/Git変更許容を検証する。
本番変更はWorkerの要求期限、既存progress packetの中継と読み取り、fatal時の再使用禁止、終了と回収だけ。
10秒目標の検証はGitHub Actionsの実測で行う。ローカルIT・Full IT・時間測定は実行しない。

| ID | Function | Kind | Source | Mode / Count | Guarantee | Provenance |
| --- | --- | --- | --- | --- | --- | --- |
| `issues21::check_child_shutdown_escalation` | `check_child_shutdown_escalation` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 3 | 終了済child非terminate・TERM後終了/残存だけKILL・join/close | Issue 21 |
| `issues21::check_config_input_branches` | `check_config_input_branches` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 6 | 実行環境のconfig/decoderの直接呼出し・除外/ignore_bad/ignore_checks/deployment競合/壊れたYAML/非object、Workerなし | Issue 21 |
| `issues21::check_noecho_redaction` | `check_noecho_redaction` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | NoEcho Default/parameter上書き検出・nested診断redaction・Rule保持 | Issue 21 |
| `issues21::check_offline_and_write_guards` | `check_offline_and_write_guards` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | socket.connectとoutput書込のaudit拒否、実ネットワークなし | Issue 21 |
| `issues21::check_schema_failure_classification` | `check_schema_failure_classification` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 7 | mapping/schema欠落・JSON/構築エラー・未知/removed/registry typeの非誤分類とfatal | Issue 21 |
| `issues21::check_windows_once_contract` | `check_windows_once_contract` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 4 | Windows --once継続・timeout/異常終了/protocol不正の途中診断保持と再使用禁止 | Issue 21 |
| `issues21::check_worker_deadline_and_response` | `check_worker_deadline_and_response` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 6 | 単調時計期限・断片stdout/無応答/異常JSON/EOF・途中診断保持・再使用禁止・session起動 | Issue 21 |
| `issues21::check_worker_shutdown_escalation` | `check_worker_shutdown_escalation` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 5 | 正常EOF待機と強制回収の分離・TERM後残存だけKILL・終了済leaderの残存group・pipe閉鎖・二重close | Issue 21 |
| `issues21::check_dependency_view_failure_branches` | `check_dependency_view_failure_branches` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 4 | 選択View欠落とUTF-8/欠落/PermissionError依存View分類・consumer重複排除・独立Service/lint継続・非Cache・入力読取障害の診断保持、Workerなし | Issue 21 |
| `issues21::check_schema_failure_recovery` | `check_schema_failure_recovery` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py#L126) | pytest / 1 | 実cfn-lintの壊れたschemaと正常/未知type診断保持・fatal/not_run・新Worker復旧・異常child再使用禁止・offline/回収 | Issue 21 |
| `issues21::check_timeout_reaping` | `check_timeout_reaping` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py#L184) | pytest / 1 | 実OSの短いTimeout・POSIX実serve/forkとTERM無視childのkill/join・専用group消滅・pipe解放・Windows実onceプロセス回収 | Issue 21 |
| `issues21::check_worker_config_isolation` | `check_worker_config_isolation` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py#L79) | pytest / 1 | 実HOME/cwd設定・4連続要求のcustom rule/registry/override状態隔離と再読込・NoEcho非漏洩・output非書込・正常終了 | Issue 21 |


## Ordinary receiving-property reference contracts

既存の `units/model-markdown-reference.checks.py::main` に、Glue.Connection 001/002の2要素配列、各位置のS3型違反、不在・曖昧警告、明示契約なし、document除外、Name/observedとIMPORT契約、通常配列と明示JSON禁止の境界、保存・生成・再読取の値と順序不変を追加。入口数は変更しない。

## JSON Resource ARN projection

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|

## Independent AWS JSON

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `standalone-json::expressions` | `check_standalone_expressions` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L105) | pytest / 15 | 設計intrinsic/文字列化式は保持またはローカル解決、未解決WARNINGとPointer escape、AWS JSON/hashは拒否、裸pseudo/dynamicはERROR、入力不変 | JSON projection |
| `standalone-json::generation` | `check_standalone_generation` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L145) | pytest / 1 | 正常IAM変数・JSON/表示/hash一致、後続JSONの不正GetAtt構造で先行成果物を保存せず既存成果物/Model保持 | JSON projection |
| `standalone-json::cfn-boundary` | `check_standalone_and_cfn_boundaries` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L189) | pytest / 1 | 通常値/型とIAM変数保持、CFn YAMLタグと既存式評価維持 | JSON projection |
| `design-json::pending-intrinsics` | `check_pending_intrinsic_generation` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L219) | pytest / 17 | Ref/Fn全般とネスト、未対応関数はWARNING、Model保存/生成/表示成功、原式保持、AWS直接適用拒否 | Synthetic Model JSON |
| `design-json::api-intrinsics` | `check_api_json_intrinsics` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L275) | pytest / 1 | API設定JSONでも式だけ保留、リテラルの型・制約と不正構造のERRORを維持 | Synthetic JSON |
| `design-json::policy-siblings` | `check_pending_policy_siblings` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L286) | pytest / 1 | 未解決Sid/Resourceを保留し、隣接Effect/Resource/Sidの不正とAWS適用拒否を維持 | Synthetic policy |
| `design-json::invalid-intrinsics` | `check_invalid_intrinsic_structure` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py#L262) | pytest / 9 | 既存intrinsic構造契約と評価器で証明された不正構造、JSON構文不正はERROR | Synthetic Model JSON |
| `issues-iac::intrinsic-warnings` | `IntrinsicWarningTests.test_unresolved_leaves_keep_other_comparisons_and_report_counts` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 未解決式は未比較と警告、同じ式でもMATCH禁止、隣接確定値の一致/差分、未比較集計とAWS境界 | Synthetic CFn |
| `issues-iac::intrinsic-local` | `IntrinsicWarningTests.test_local_functions_resolve_with_proven_stack_inputs` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | Ref/Sub/Join/Split/Select/If/FindInMapは確定入力だけで評価、構造不正はERROR | Synthetic CFn |
| `standalone-json::resource-types` | `check_resource_types` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L91) | pytest / 12 | Resource/NotResourceのobject・混合配列・非string scalar拒否 | Policy |
| `standalone-json::valid-resources` | `check_valid_resource_types` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L99) | pytest / 4 | string/string配列、Statement object、Principal/NotAction/Condition、IAM変数を維持 | Policy |

## Framework定義不変による削除

定義ファイルはコピー先も含めて変更・追加・削除しない。現行定義の共有参照、メモリ上の入力辞書・既存Mockによるコード検証、独立した読取例外は維持する。同期処理の仮txt・Frameworkコードは固定Framework定義に含めない。

| 全体削除 | 関数 |
|---|---|
| `integrations/model_design.checks.py` | `check_design_naming_preflight` |
| `units/aws_definitions.checks.py` | `check_lazy_parallel_and_mutation` |
| `units/aws_mapping-unit.checks.py` | `check_ownership_errors` |
| `units/aws_mapping_compare-unit.checks.py` | `check_missing_catalog_field` |
| `units/aws_mapping_display-unit.checks.py` | `check_group_projection` |
| `units/aws_mapping_display-unit.checks.py` | `check_mapping_display_rows` |
| `units/aws_mapping_display-unit.checks.py` | `check_validation_projection_semantics` |
| `units/validation_checks/design.py` | `check_catalog_display_order` |

| 部分削除 | 残す責務 |
|---|---|
| sync-model `check_publication_boundary[mapping]` | source/project/part/consumer/extra/contractの6条件 |
| design_catalog `main` のMapping・命名規則・Schema書換え依存経路 | 現行QuickSight表示・Macie Schema正常値と異常値23件、S3リンクlabel・bucketCriteria/JSON競合 |
| design_layout `check_workflow` の架空Resource/Layout変更 | 現行layout、正常/異常文書、group child・参照・親移動 |
| blueprint-loop のRule変更・移動シナリオ | Model/Task/IaCのscope、空白検証、Frameworkコード変更の回帰選択 |
| deploy_preparation `check_stale_and_conflicts[input]` | runtime/契約候補/Model/生成物の変更・削除は拒否 |
| cloudformation-deploy `check_session_cli` のRule変更条件 | IaC/Model/契約/コード・project変更、resume・保存保護 |
| aws_mapping `check_runtime_cache`、`check_runtime_failures[parse]` | root/scopeの再利用、独立したread/runtime例外 |
| aws_mapping `check_readonly_defaults` のMapping default差替え | Field.copy_defaultのstandalone埋込互換性 |
| aws_mapping_catalog `schema_checks` のファイル作成・変更 | メモリ上の不正Mapping入力と現行Mappingの正常性 |
| aws_definitions の定義編集・架空Schema/Catalog | SDK lifetime、現行定義の読取例外・依存分離・stage生存 |
| validation_cache のFramework定義編集 | 実行内PASS・fresh・Project/Model/Taskの変更・権限・最終比較 |
| validation_checks/design のCatalog/Schema破損・架空Catalog | 現行定義の整合性、通常の設計値と行順・名前・CIDR検証 |
| validation_checks/contracts のRule/Prompt編集 | 現行のPrompt/Rule/リンク・節・回帰選択 |
| model_design `check_service_scoped_naming` の仮Rule | 現行service限定の読取と命名検証 |
| deploy_preparation `check_rule_section_boundaries` の仮Ruleファイル | 文字列による節・anchor・重複・境界検証 |
| policy_tables `mapping_cache_checks` の改名・破損Mapping | 同一定義のroot別cache分離と再利用 |
| update-catalog-lock `main` のCatalogファイル生成・改変 | POSIX/Windowsのcatalogファイル順序 |

IMPORTのLogGroup限定ケースは既存の `resource_types=['Logs.LogGroup']` を明示し、Mappingを縮小せずに従来の取得対象・assertionを維持する。

Fixture整理：`aws_mapping_display_fixtures.change`、`aws_definitions.write/fixture`、各削除経路内の専用helperを削除。所有一覧の絞込み、Logs Mapping縮小、仮の命名Rule・縮小Catalog作成を削除し、通常検証に必要な既存定義は実Frameworkを共有参照する。

台帳登録/展開数：UT 260/590 → 255/585（削除分）→ 397/959（未登録142件の補完・既存parameter件数1件訂正後）→ 398/960（CodeCommit返却属性1件追加）、IT 371/590 → 370/588。直接実行内部の部分削除は入口1件のままとし、検証地点・内部パターンを更新した。

## IMPORT optional-name display

The existing `units/design_layout-unit.checks.py::check_resource_display_names` excludes catalog IDENTIFIER_OUTPUT fields from confirmed-value checks and configured-name selection, using Glue self-references, PENDING_DEPLOY and physical names in short/formal rows. CREATE missing names, IMPORT labels and UNSET configured names retain their checks. Existing `integrations/model_design.checks.py::check_naming_exclusions` also checks Glue identifier observations and Markdown rows without changing desired references, plus identifier-specific validation. Definitions and entrypoint counts remain unchanged.

The existing `units/design_layout-unit.checks.py::check_resource_display_names` also checks shared selection for optional IMPORT names, CREATE rejection, missing labels, unconfirmed selected names, schema-required names and IAM/CodeBuild exceptions. Framework definitions remain unchanged.
The existing type-display constraint cases accept the shared selection error for missing required names; the anchor/reference unit isolates presentation at its current boundary without mocking the moved naming validator. Expansion counts remain unchanged.
Existing Import publication cases retain selected self-reference names and resolve only their own saved observations for presentation. Existing anchor-tampering cases retain warning severity. The CREATE Security Group heading fixture now selects its formal GroupName; no Framework definitions are changed.
The Security Group table IT also selects an independent formal GroupName for its second CREATE resource, retaining tag-scalar cases introduced on the latest base.

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|

## Static fixture cases

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `fixture-cases::loading` | `check_loading_and_independence` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py#L34) | pytest / 1 | base浅い上書き、複数ケース、独立性、cache保護と再読込一致 | Fixture |
| `fixture-cases::schema` | `check_invalid_schema` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py#L68) | pytest / 1 | 重複キー、schema/version/ID/値型/再帰データ拒否 | Fixture |
| `fixture-cases::files` | `check_materialize_files` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py#L94) | pytest / 1 | 複数ファイル、UTF-8/空白/改行保持、逸脱/symlink/衝突拒否 | Fixture |
| `fixture-cases::authored` | `check_authored_suite` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py#L132) | pytest / 1 | issues_scanの2ケース読込、service順序、malformed末尾改行 | Fixture |

## SecurityGroup tag scalar / Markdown metadata

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `sg-tags-scalar` | `check_tag_scalars` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#L66) | pytest / 1 | YAML 7条件のscalar/引用符/backslash/日本語/JSON風/数値風/コメント境界/backtick、複数タグの順序・ペア・SG所有、GroupName分離、選択状態、既存IaC比較との一致 | 新規 |
| `sg-tags-invalid` | `check_invalid_tag_metadata` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#L108) | pytest / 1 | YAML 10条件の不正JSON、配列/ペア/string型違反、生コメント境界を拒否 | 新規 |

既存IT `integrations/security_group_tables.checks.py::main` 内で、同じ7条件をproperties v2で保存・読取し、正式rendererでMarkdown生成・検証用展開する。Model authorityの不変を確認し、通常scalarの引用符期待値を訂正する。既存の正常系・不正metadata・配置・ルール・所有関係チェックは保持。静的データは `fixtures/security_group_tables.yaml` のみ、Framework定義は変更しない。入口は既存direct_group / 1のまま。

## Generation-local resource row reuse

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `resource-row-reuse::edits` | `check_resource_row_reuse_and_edits` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L628) | pytest / 1 | 遅延解析、mapping分離、変更・追加・削除・順序、空入力、返却list保護、次回scope | sync |
| `resource-row-reuse::legacy` | `check_resource_row_legacy_and_invalid_entries` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L676) | pytest / 1 | legacy prefix重複、不正rowの例外と評価タイミング | sync |
| `resource-row-reuse::lifetime` | `check_resource_row_scope_restoration` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L701) | pytest / 1 | 入れ子scopeと実generate_viewsの正常・例外終了時復元 | sync |

## Limited Route53 ImportValue expressions

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `route53-import-expression::syntax` | `check_limited_import_expression` | UT | [units/route53-import-expression.checks.py](units/route53-import-expression.checks.py#L24) | pytest / 1 | 限定式・file-level linkの形式、境界、通常literal制約 | Route53 |
| `route53-import-expression::validation` | `check_route53_import_expression_validation` | UT | [units/route53-import-expression.checks.py](units/route53-import-expression.checks.py#L71) | pytest / 1 | 合成Model入力と生成Markdownの正常・異常判定一致 | Route53 |

## Import conversational consent and integrity

`units/import-approval-unit.checks.py` uses synthetic data only. The LLM owns explicit
final consent in chat; Python validates Review/candidate/receipt integrity without Host
mocks. The Import IT exercises the normal unpatched CLI publisher across processes,
source transactions, rollback, receipt guards and display generation. These fixtures do
not establish actual agent conversation quality or Human identity authentication.
Display structure failures reject before saving; display I/O failures and recovery
remain separate. Dry-run/incomplete/display-failed sessions are retained.

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `import-approval::typed-review` | `check_complete_typed_before_after_and_digest` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L62) | pytest / 1 | Before/After・型・論理参照・物理値・digest | Import Review |
| `import-approval::inventory` | `check_full_inventory_required` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L77) | pytest / 3 | 全取得レコード・リスク・取得Typeの欠落拒否 | Import Review |
| `import-approval::changed-review` | `check_changed_review_needs_new_review` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L90) | pytest / 11 | 反映先・操作・値・参照・リスク・基準・Scope・Task・Worktree・型・valueShapeの変更 | Import Review |
| `import-approval::duplicate-risk` | `check_unknown_identity_risk_is_bound` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L110) | pytest / 1 | 既存ID不明の重複リスク | Import Review |
| `import-approval::type-status` | `check_inventory_status_and_exclusions_remain_visible` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L127) | pytest / 5 | 取得失敗・権限・filter・empty・completeの区別 | Import Review |
| `import-approval::native-values` | `check_array_boolean_name_and_unreflected_values` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L138) | pytest / 1 | 配列・Boolean・Name tag・未反映値 | Import Review |
| `import-approval::composite-secret` | `check_composite_identity_and_secret_omission` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L157) | pytest / 1 | 複合識別子・機密値非出力 | Import Review |
| `import-approval::observed` | `check_configuration_is_not_observed` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L177) | pytest / 3 | 通常設定のobserved保存拒否 | Pre-save |
| `import-approval::warning` | `check_valid_observation_and_nonblocking_reference_warning` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L184) | pytest / 1 | 識別子observed許可・Reference warning非ブロック・無関係既存行保持 | Pre-save |
| `import-approval::no-trusted-approval` | `check_local_claim_cannot_replace_review_binding` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L199) | pytest / 6 | 自己申告JSON・flag・HMACはReview bindingの代替にならない、証跡保持 | Fail-closed |
| `import-approval::alternate-writer` | `check_alternate_source_guard_rejects_legacy_receipt` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L209) | pytest / 1 | 既存receipt経由のModel保存拒否 | Fail-closed |
| `import-approval::expiry` | `check_expiry_and_digest_tampering` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L225) | pytest / 1 | 7日有効期限・digest改ざん拒否 | Import Review |
| `import-approval::unselected` | `check_unselected_reference_changes_are_not_reviewed_as_selected` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L236) | pytest / 1 | 非選択Resourceの変更拒否 | Import Review |
| `import-approval::review-command` | `check_review_command_is_read_only` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L272) | pytest / 4 | Review出力・baseline競合・承認flag・機密候補拒否、Model未変更 | Import Review |
| `import-approval::display` | `check_preflight_before_any_save` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L304) | pytest / 12 | Review一致・値/反映先/baseline/provenance不一致、候補value/target/resource/reference差替え拒否、表示エラー時のModel/証跡保持、保存Mock未呼出 | Pre-save |
| `import-approval::required-review` | `check_missing_review_rejected_before_candidate_load` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L439) | pytest / 1 | Reviewなしの通常Publishは候補読込前に拒否 | Pre-save |
| `import-approval::reference-meaning` | `check_same_value_reference_meaning_is_bound` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L458) | pytest / 6 | 同一展開値でもselector・Definition参照宣言・Service・Property・Definition・input名変更でReview不一致 | Import Review |
| `import-approval::reference-metadata` | `check_reference_location_and_description_are_not_meaning` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L488) | pytest / 1 | 位置・説明文と派生observed traceはReference意味から除外 | Import Review |
| `import-approval::reference-schema` | `check_reference_proposal_uses_existing_contract` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L496) | pytest / 5 | 参照提案は既存宣言/type/fixed-target契約と正規化形式で検証 | Import Review |
| `import-approval::unselected-selector` | `check_unselected_reference_selector_is_rejected` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L513) | pytest / 1 | 未選択Resourceのselector変更を拒否 | Import Review |
| `import-approval::loader-provenance` | `check_real_loader_retains_unresolved_reference_declaration` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L526) | pytest / 1 | 実loaderが未解決参照のService/type/Property/selectorを保持、Review構造検証は非ブロック | Import Review |

| `import-approval::publication-transaction` | `check_publication_transaction_without_host` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L738) | pytest / 2 | 保存計画後の候補/正本raceを実保存境界で拒否、外部編集保持・Receipt除去 | Publication |

| `import-chat::check_explicit_bind_preserves_identity` | `check_explicit_bind_preserves_identity` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L546) | pytest / 12 | bind正常、既知ID・stale・CREATE・型・重複・無効ID・Anchor/Row/未取得変更拒否 | Chat approval |
| `import-chat::check_subnet_answers_correction_and_resume` | `check_subnet_answers_correction_and_resume` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L597) | pytest / 1 | 複数SUBNET回答保持・訂正・session再開・baseline変更拒否。LLM判断品質の評価ではない | Chat approval |
| `import-chat::check_checkpoint_rejects_stale_or_competing_answers` | `check_checkpoint_rejects_stale_or_competing_answers` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L633) | pytest / 8 | 期限・基準・Task/Worktree/scope・取得差替え・競合回答拒否 | Chat approval |
| `import-chat::check_review_binding_integrity_without_host` | `check_review_binding_integrity_without_host` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L657) | pytest / 19 | HostなしのReview binding構造・全digest・期限と不要な認証fields拒否 | Chat approval |
| `import-chat::check_unanswered_review_cannot_be_approved` | `check_unanswered_review_cannot_be_approved` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L674) | pytest / 1 | 未回答を含むReviewは最終承認に渡せない | Chat approval |

| `import-chat::consent-contract` | `check_conversational_consent_contract` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L683) | pytest / 1 | 全件Review・明示同意・訂正/取消・曖昧回答・再確認・merge後確認の規約 | Chat consent |
| `import-chat::save-guard` | `check_approval_bound_save_guard` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L716) | pytest / 1 | 実Publish後の承認外候補bytesを保存guardで拒否、元正本へ復元 | Publication |

元パスは分離前の `framework/scripts/tests/` 相対。現在のリンクはこのファイルからの相対。分類は検証責務による。変更不要のケースも掲載。

共通参照target選択の診断は、欠落ID・型不一致・複数候補を区別して関連ITで検証する。model_filesのcache検証はtype/name/linkの各解決を1回に限定し、出力・終了コード一致と入力準備・parse再利用のassertを維持する。

## 数え方

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `s3-kms-reference::authority` | `check_authority_display_and_references` | UT | [units/s3-kms-reference-unit.checks.py](units/s3-kms-reference-unit.checks.py#L93) | pytest / 1 | Aliasリンクの保存再読込、schema、Markdown/表示検証、incoming、IMPORT、stale、正本バイト不変・生成ARN非保存 | Synthetic Models |
| `s3-kms-reference::iac` | `check_iac_matrix` | UT | [units/s3-kms-reference-unit.checks.py](units/s3-kms-reference-unit.checks.py#L135) | pytest / 1 | Alias参照、通常KeyリンクとCFn Ref/GetAtt比較 | Synthetic CFn |
| `issues-iac::codecommit-name` | `ImportValueResolutionTests.test_codecommit_name_uses_only_explicit_repository_name` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | Name→RepositoryName、Ref RepositoryId区別、文字列一致/差分、未解決/非文字列/欠落、Condition/Transform/型/Resource・Stack曖昧性を保留、ネットワーク禁止 | Synthetic CFn |

CodeBuild PLAINTEXTの属性参照比較は `units/test_issues_iac.py::ImportValueResolutionTests.test_resource_attributes_and_codebuild_plaintext_prohibition`
（UT / unittest 1 case）で検証する。合成Model identityとCFn定義を使用し、Key ARN/GetAtt、Alias ARN/Subと両Export値の一致、Key/Alias・別対象・別属性の不一致、未確定参照、Export名literalの非一致、既存S3 BucketName参照を確認する。実行中repoのproject/Model入力・AWSは使用しない。

同UTに非S3属性不足の専用診断、Secret/Typeコンテキスト、IMPORT受け渡し不足と具体値未証明の保留を追加。既存IT `issues_scan::check_reference_property_contract` はCodeCommit名literalのmatched/difference/uncompared、`check_aws_standard_comparison` はS3・Secret・PolicyとCFn関数の接続を検証する。IT入口数は変更しない。

`units/validation_checks/design.py::check_cidr_pending_deploy` は既存VPC fixtureで識別情報失敗の回帰も検証する。`resource_logical_ids` のValueError、`design_model_values` のOSErrorを単独ファイル／後続正常サービスありの各条件で注入し、元診断・ファイルパスの完全一致、当該ファイルの後続展開停止、正常サービスのName検証到達、集約結果FAILを確認する。CREATE正常／Name欠落、IMPORTのName省略と両展開関数へのmodes伝達も確認する。実Model・AWS・ITは使用しない。

ケース数は実行入口の関数（unittestはメソッド）を数える。pytestは設定から静的に算出し、decoratorの直積を展開した数も併記する。直接実行の関数、callback、main/module内の検証地点は別欄。mainは複数シナリオを含むため、検証地点の明細を別表で網羅し、関数数へ水増し加算しない。ヘルパーのassertは共通検証として保持し、テストケース数に加算しない。動的ループは入力式を記載し、実行しないと決まらない件数を推測しない。

pytest件数はテスト定義・aliasと設定から算出する。直接実行入口で選択されるcallbackとpytestラッパーは重ねて合計しない。

## Lambda依存IT統合のassertion対応

下表の旧行・template/parameters/bindings という語は旧版での検証目的の記録です。properties v2 での現在の検査対象・意味変更は末尾の「Properties v2 reference and Import assertion mapping」を優先します。

旧独立Lambda依存ITの全検証地点（削除前行番号）。完全重複は既存ITへ委譲し、部分重複の環境別byte snapshotと未カバーのPassCache依存を `validation_cache.check_producer_inputs` に統合。旧2構成の全体コピー・独立fixture生成ヘルパーの移植なし。

| 旧行 / assertion・拒否目的 | 重複判定 | 継続する検証 |
|---|---|---|
| 54 / 分割Templateのpartが解析入力に含まれる | 部分 | validation_cache.mainのpart変更キー、check_producer_inputsの`part in inputs` |
| 77 / Producer source_inputsがConsumerに包含 | 完全 | attribute-reference-resolution.check_pairの`loaded.files`、eventbridge-producer-name-reference.checkの`load_model(producer).files <= files`。統合fixtureでも同じ包含を確認 |
| 84 / 全Producer入力の空白変更で共有両環境・固有環境だけdigest変化 | 部分 | check_producer_inputsの入力全件×preview/release×依存/無関係サービスdigest比較。check_fixed_labelは値不変のdigestを既存検証 |
| 85 / 同条件でConsumer service_key変化 | 未カバー | check_producer_inputs。共有index/partとpreviewのparameters/bindings/observedを順に変更し、releaseと無関係sqsの非影響もassert |
| 86 / 入力空白変更中のConsumer値完全一致 | 部分 | check_producer_inputsの各入力変更中のvalues全体一致（JSONの型・配列順も含む） |
| 91 / affectedが共有両環境・固有環境のProducer/Consumerのみ | 完全 | model_impact.check_shared_environmentsの共有/環境固有分離、check_precisionのLambda含む変更伝播・値不変snapshot、check_selectionの無関係サービス除外。attribute-reference-resolution.check_fixed_labelの値不変入力でもConsumer包含。baseline無しの保守的集合とbaseline有りの精密集合は区別 |
| 93 / 復元後Consumer値一致 | 完全 | attribute-reference-resolution.check_pairのdigest/values復元一致。統合caseは全キー復元も確認 |
| 101 / 相互参照でもConsumer filesをProducer source_inputsが包含 | 完全 | attribute-reference-resolution.check_pairの相互fixtureとProducer files追跡、eventbridge-producer-name-reference.checkのLambda.Permission→Rule逆リンクとfiles包含 |
| 102 / 相互リンクがあっても値再帰しない | 完全 | attribute-reference-resolution.check_pairのLambda/EventBridge相互参照値解決と真の属性cycle拒否、eventbridge-producer-name-reference.checkの逆リンク付きLambda値解決 |
| 110–112 / Producer parameters欠落の拒否 | 完全 | attribute-reference-resolution.check_preparation_cacheのparameters.yaml欠落拒否、eventbridge-producer-name-reference.checkのProducer欠落拒否 |
| 120–122 / Producer型破損の拒否 | 完全 | eventbridge-producer-name-reference.checkのLambda型不一致拒否、attribute-reference-resolution.checkのresourceType不一致拒否 |
| 128–130 / Producer parameters欠落の再検証 | 完全（旧内でも重複） | 同上のProducer欠落拒否 |

実行入口単位：新規1 case、旧module case 1削除、独立suiteは1減。旧module内のflat/parts 2 fixture構築を廃止し、既存cache suiteに最小2環境fixture 1構築を追加。既存のwrite_modelで合成入力だけを作成する。run_itの共有seed bundle生成は1回のまま、suite processは1減。run_it.pyとFramework IT workflowは変更不要（自動発見と本台帳の照合を継続）。

## design_catalog の検証経路

現行定義を読み取るQuickSight表示とMacie Schema正常系、異常値23件を維持する。定義変更に依存しないS3リンクlabelとbucketCriteria/JSON競合の直接検証も維持する。
Mappingのinclude/show、命名規則、Schema snapshotの書き換えに依存した生成・保存経路は削除した。
不正定義のメモリ上での検証は維持し、ファイル変更テストを別方式へ移植しない。

## blueprint-loop サービスCLI責務対応

入力は独立した合成repository。初期Model/Markdown生成後にGit commitし、保持期間30→14をTaskの変更対象とする。全実CLIは本物のValidator/Generatorを使用する。下記番号は変更前の実行順（16回）。共通runのValidator起動・Git diff起動・回帰非選択は残す各実CLIで確認する。個別Validator診断のCLI経由繰返しを減らし、停止・scope・Git結合は残す。

| 番号 | 入力条件（Model / Markdown / Task / Git） | 期待結果・成果物 | 責務 | 判断と同等assertの所在 |
|---:|---|---|---|---|
| 1 | 正常14 / 一致 / logs / 変更あり | PASS・回帰0 | orchestration | 維持：check_task_service_validation |
| 2 | 1と同じ、ローカル.lock追加 | PASS・0 executed, 1 reused | cache / Git | 維持 |
| 3 | 1と同じ、fresh/profile/jobs=1 | PASS・1 executed, 0 reused・両prof実ファイル | orchestration | 維持 |
| 4 | 正常 / 一致 / logsに未解決Issue | FAIL・suspend・原因保存 | orchestration | 維持 |
| 5 | 保持7 / 14のまま / logs | FAIL・generated Markdown is stale | Validator | 重複削除：12の同一変更・診断に集約。12で非書込もassert |
| 7 | 保持31 / 31 / logs | FAIL・schema | Validator / Generator | 移管：check_loggroup_invalid_valuesの31/not-a-numberのSchema拒否、validation_checks/designのSchema行検証、check_readonly_stale_viewsの非書込に分離 |
| 8 | 正常 / 存在しないmdへのリンク / logs | FAIL・broken design link | Validator | 既存保証：[design_document.check_links](integrations/design_document.checks.py#L61)でabsent.md#absentに対する完全一致診断配列。CLI失敗伝播は12で維持 |
| 9 | 正常 / 一致 / 未定義account | FAIL・validation target is not defined | scope | 移管：[validation_scope.main](integrations/validation_scope.checks.py#L156)の不正selectorループに同accountと診断assert追加 |
| 10 | logs変更 / logs変更 / ec2指定 | FAIL・changed design path is outside validation scope | scope / Git | 維持：Git変更の実CLI伝播は専門関数のchanged_paths代入だけでは代替しない |
| 11 | 正常logs＋commit済み不正ec2 / logs | PASS・対象外無視 | orchestration | 維持 |
| 12 | 保持7＋不正ec2 / 14 / logs | FAIL・stale | orchestration | 維持・Markdown非書込assert追加 |
| 13 | 正常logs＋不正ec2 / all | FAIL・ec2・Validation all・回帰skip | orchestration | 維持（contractのall指定。CLI --allは他の既存ケースで検証） |
| 14 | mismatchをcommit後Modelだけ修復 / 正しい14 / ModelのみAcceptance | PASS・Markdown Git diffなし・内容不変 | orchestration / Git | 維持：専門Generator単独ではGit結合を代替できない |
| 16 | 正常 / Markdown削除 / logs | FAIL・validation input missing | scope | 移管：validation_scope.mainにMarkdown削除・同診断・非再生成assert追加 |

16→9回。7回への削減よりscope変更・Modelのみ修復の実CLI結合保証を優先する。fixture構造・初期化回数は変更しない。既存の小型CLI fixtureに不足していたworktree_task.py/worktree_python.pyのコピーだけ補完する。Name/Schema/scope専門検証は既存fixture内に追加し、別ファイルへCLI処理を移していない。

`-O` は既存 `run_it.check_assertion_guards()` の全 `.checks.py` AST検証を再利用する（不明構造はFAIL）。現baseでは全ファイル個別起動は既に廃止済みであり、その削減を今回の成果に含めない。`service-parameter-inputs.checks.py` にも直接ガードが既にある。

`check_workflow` に実UT/IT代表2本の `python -O` 非ゼロ・専用診断を追加。通常モードのfixtureはAssertionErrorで検証本体到達を確認し、ガード除去fixtureは静的検査で拒否する。既存の `-O` loop→ガードなし子チェックもassert失敗・後続継続を確認する。全ファイルの動的起動保証は全ファイル静的＋代表動的へ縮小しており、同一保証とは扱わない。代表2本分の起動は現baseより2回増える。

## 配置と入口の件数（43bee83時点）

この表は追加修正前の登録スナップショット。現行Sync Modelの関数数・展開数は末尾のIssue 15表と各ケース登録を参照する。

| 種別 | Pythonファイル数 | 台帳登録pytest関数 / 展開数 | 直接関数 |
|---|---:|---:|---:|
| UT | 93 | 675 / 2081 | 31 |
| IT | 85 | 174 / 291 | 116 |
| support | 53 | 0 / 0 | 0 |

supportファイル数は共通fixture/補助のみ。UT台帳には別途unittest 4メソッドがある。登録数は場所/関数の組で重複を除く静的件数で、全テスト実行の証拠ではない。main/moduleの地点数は下表を参照。

## IT統合と到達性

公式入口は `run_it.py`。`.checks.py` は75スイートを自動検出する。上表のファイル数には補助Pythonモジュールも含む。
ケース台帳を実行時に読み、pytestの収集・成功した検証本体のパラメータ件数、直接実行関数の呼出記録と照合する。未登録の `check_*`、消えた関数、未実行・skip・パターン不足はFAIL。ケース名だけの存在確認でPASSにしない。

現在のIT台帳は309登録・426入口パターン（pytest 174/291、direct 116、direct_group 13、module 6）。内部動的ループは下表の詳細どおりで、入口パターン数には加算しない。

- `check_quicksight_group_principal_reference` と `check_incoming_reference_models` は通常pytest収集を維持する。incomingのread/write選択の細分化は直接UT、実write接続はITが担当する。各ITの手書き選択リストも廃止した。
- 全量逆変換の検証は廃止。`design_document.check_snapshot` は局所的な表・リンクsnapshotと正本からの表示・生成物比較を検証する。`validate-blueprint` の `design_document.check_links` 呼出も削除。両検証本体はdesign_documentの通常入口に存在し、同じ実装モジュールを渡して実行するため完全重複。
- Sync Modelの旧性能回帰は末尾のIssue 15分類へ再編した。実際の生成・保存・CLI・ロック待機をITに保持し、単独判定は既存UTへ集約する。
- 他ITへの16ロードは0。issues、Model、layout、worktree、blueprint-loopは既存supportを直接再利用。RotationScheduleのデータ生成だけをsupportへ抽出し、検証本体を他ITから呼ばない。
- runnerがframework・入力テンプレート・typed services・生成済みIAM policyを各1回初期化。生成イベントを実測し、共通bundleは書込禁止かつ前後の内容/modeハッシュで検査する。ケースは独立コピーを変更し、入力テンプレートの参照元のみ読み取り専用で共有する。
- `check_it_fixture_isolation` は通常/逆順で独立コピーを変更し、隣接ケースと原本の不変、書込禁止、後片付け、強制汚染時のFAILを検証する。
- assert無効化ガードは全UT/ITのAST配置・厳密な式・最適化コンパイル時のSystemExitで確認し、runner自体も実際の `python -O` で拒否を検証する。毎スイートの `python -O` 起動は不要。

## UT 全ケース

| 元ファイル : 行 | Test Case名 | 分類 | 現在の配置 | 入口 / パターン数 | 分類理由 | 変更 |
|---|---|---|---|---|---|---|
| `sync-model runner` | `check_internal_sync_concurrent_output` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L105) | pytest / 1 | 並行呼び出しのmemo・診断・heartbeat分離と後片付け | 新規 |
| `sync-model runner` | `check_internal_sync_arguments` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L127) | pytest / 4 | help・usage・引数エラーと終了状態、出力漏れ防止 | 新規 |
| `Validator runner` | `check_internal_generation_dispatch` | UT | [units/validation_scope-unit.checks.py](units/validation_scope-unit.checks.py#L33) | pytest / 4 | 比較APIへのscope・workers・definitions_root引継ぎ、エラー伝達・重複防止・空scope・hook優先・subprocess禁止 | 新規 |
| `unknown/aws_mapping.checks.py:274` | `check_payload_selection` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L54) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/aws_mapping.checks.py:54` | `check_v3_registry` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L92) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/aws_mapping.checks.py:97` | `check_registry_cache` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L175) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/aws_mapping.checks.py:121` | `check_baseline` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L193) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/aws_mapping_catalog.checks.py:73` | `initialization_checks` | UT | [units/aws_mapping_catalog.checks.py](units/aws_mapping_catalog.checks.py#L111) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/aws_mapping_catalog.checks.py:120` | `schema_checks` | UT | [units/aws_mapping_catalog.checks.py](units/aws_mapping_catalog.checks.py#L135) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:847` | `check_utf8_restart` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L52) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/model_design.checks.py:303` | `check_changed_paths_error` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L65) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/blueprint-loop.checks.py:68` | `check_process_interruption` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L99) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/blueprint-loop.checks.py:413` | `check_parallel_interruption` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L134) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/blueprint-loop.checks.py:464` | `check_fixture_independence` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L161) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:1000` | `check_regression_discovery` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L183) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `units/check-model-aws-unit.checks.py:11` | `check_summary_exit_codes` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L52) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `units/check-model-aws-unit.checks.py:19` | `check_value_normalization` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L60) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `units/check-model-aws-unit.checks.py:29` | `check_secret_redaction` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L70) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/cloudformation-deploy.checks.py:98` | `check_scheduler` | UT | [units/cloudformation-deploy-unit.checks.py](units/cloudformation-deploy-unit.checks.py#L70) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:334` | `check_workflow_contract` | UT | [units/deploy-required-readings.checks.py](units/deploy-required-readings.checks.py) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:344` | `check_dependencies_and_timing` | UT | [units/deploy_preparation-unit.checks.py](units/deploy_preparation-unit.checks.py#L40) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:382` | `check_rule_section_boundaries` | UT | [units/deploy_preparation-unit.checks.py](units/deploy_preparation-unit.checks.py#L78) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/design_catalog.checks.py:138` | `check_api_schema` | UT | [units/design_catalog-unit.checks.py](units/design_catalog-unit.checks.py#L31) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/design_document.checks.py:50` | `check_snapshots` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py#L47) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:926` | `check_resource_display_names` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L95) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/design_layout.checks.py:530` | `check_cloudtrail_expansion` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L169) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/design_layout.checks.py:621` | `check_pipeline_expansion` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L188) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/framework-input-isolation.checks.py:41` | `check_framework_input_guards` | UT | [units/framework-input-isolation-unit.checks.py](units/framework-input-isolation-unit.checks.py#L26) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/glue_datazone_catalog.checks.py:102` | `check_catalog_schema` | UT | [units/glue_datazone_catalog-unit.checks.py](units/glue_datazone_catalog-unit.checks.py#L21) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `import-agent-sources::check_null_parameter` | `check_null_parameter` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L139) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_yaml_edits` | `check_yaml_edits` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L145) | pytest / 7 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_yaml_empty_and_order` | `check_yaml_empty_and_order` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L158) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_physical_identity_wins_over_mutable_settings` | `check_physical_identity_wins_over_mutable_settings` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L168) | pytest / 2 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_invalid_candidates` | `check_invalid_candidates` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L197) | pytest / 12 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_unacquired_and_create_protection` | `check_unacquired_and_create_protection` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L204) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_duplicate_add_uses_baseline` | `check_duplicate_add_uses_baseline` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L222) | pytest / 8 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_selection_identity_duplicate` | `check_selection_identity_duplicate` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L238) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_existing_identity_ambiguity_is_local` | `check_existing_identity_ambiguity_is_local` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L248) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_unknown_identity_does_not_block_add` | `check_unknown_identity_does_not_block_add` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L264) | pytest / 4 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_new_resource_and_explicit_dispositions` | `check_new_resource_and_explicit_dispositions` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L272) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_binding_identity_and_addition` | `check_binding_identity_and_addition` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L295) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_shared_property_typed_preservation` | `check_shared_property_typed_preservation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L310) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_shared_reference_is_symbolic` | `check_shared_reference_is_symbolic` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L327) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_typed_property_values` | `check_typed_property_values` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L343) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_candidate_scope_and_changed_files` | `check_candidate_scope_and_changed_files` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L353) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_sealed_evidence_tamper` | `check_sealed_evidence_tamper` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L373) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_cli_never_falls_back` | `check_cli_never_falls_back` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L389) | pytest / 4 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_cli_phase_dispatch` | `check_cli_phase_dispatch` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L395) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_native_equality_and_singleton` | `check_native_equality_and_singleton` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L411) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_adapter_inventory_normalization` | `check_adapter_inventory_normalization` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L422) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_shared_source_preservation_boundary` | `check_shared_source_preservation_boundary` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L456) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_existing_resource_action_rejected` | `check_existing_resource_action_rejected` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L483) | pytest / 4 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_new_anchor_and_reference_preservation` | `check_new_anchor_and_reference_preservation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L490) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_authored_vpc_append_candidate` | `check_authored_vpc_append_candidate` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L511) | pytest / 2 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_foreign_candidate_scope` | `check_foreign_candidate_scope` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L548) | pytest / 7 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `integrations/issues_api_only.checks.py:62` | `check_api_type_rejection` | UT | [units/issues_api_only-unit.checks.py](units/issues_api_only-unit.checks.py#L24) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/issues_scan.checks.py:1622` | `check_mismatch_rendering` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/issues_scan.checks.py:1823` | `check_summary_scale` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/lambda_permission.checks.py:93` | `check_permission_catalog` | UT | [units/lambda_permission-unit.checks.py](units/lambda_permission-unit.checks.py#L37) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/model_design.checks.py:1208` | `check_design_naming_rules` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L93) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/model_design.checks.py:530` | `check_subnet_list_display` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L103) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1170` | `check_security_naming` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L168) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1204` | `check_service_scoped_naming` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1235` | `check_naming_target_paths` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1332` | `check_security_group_and_glue_catalog_naming` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L251) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1635` | `check_naming_coverage` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 5 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1639` | `check_naming_edges` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1651` | `check_invalid_model` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L292) | pytest / 2 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:2062` | `check_temporary_roots` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L297) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:2081` | `check_cli_result` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L315) | pytest / 3 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/model_files.checks.py:198` | `check_cfn_selector` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L44) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:276` | `check_yaml_schema` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L37) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `units/model_parameter_inputs-unit.checks.py:18` | `check_embedded_parameter_type` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L44) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/policy_tables.checks.py:42` | `check_iam_artifact_names` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L60) | pytest / 6 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:480` | `check_statement_metadata` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L67) | pytest / 4 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:493` | `check_lossless_generation` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L79) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `units/producer-identifier-reference-unit.checks.py:11` | `check_identifier_schema` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L95) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/quicksight-display.checks.py:25` | `check_alias_catalog` | UT | [units/quicksight-display-unit.checks.py](units/quicksight-display-unit.checks.py#L24) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/quicksight-display.checks.py:30` | `check_alias_rows` | UT | [units/quicksight-display-unit.checks.py](units/quicksight-display-unit.checks.py#L33) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `units/raw-bucket-name-reference-unit.checks.py:11` | `check_reference_schema` | UT | [units/raw-bucket-name-reference-unit.checks.py](units/raw-bucket-name-reference-unit.checks.py#L21) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/regression_guard.checks.py:47` | `check_password_input_diagnostics` | UT | [units/regression_guard-unit.checks.py](units/regression_guard-unit.checks.py#L27) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/resource_mode.checks.py:158` | `check_default_mode` | UT | [units/resource_mode-unit.checks.py](units/resource_mode-unit.checks.py#L34) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/resource_mode.checks.py:182` | `check_import_naming_exemption` | UT | [units/resource_mode-unit.checks.py](units/resource_mode-unit.checks.py#L39) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/resource_mode.checks.py:121` | `check_required_name_modes` | UT | [units/resource_mode-unit.checks.py](units/resource_mode-unit.checks.py#L49) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/security_group_tables.checks.py:104` | `check_rule_catalog` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#L48) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/security_group_tables.checks.py:154` | `check_service_filenames` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#L114) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/sync-model.checks.py:487` | `check_property_path_parents` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L61) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/sync-model.checks.py:265` | `check_markdown_newlines` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L73) | pytest / 4 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `units/test_issues_iac.py:14` | `ImportValueResolutionTests.test_formal_pipeline_membership_and_configuration_context` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 変更不要 |
| `units/test_issues_iac.py:63` | `ImportValueResolutionTests.test_api_managed_resource_remains_unverified_in_cloudformation_comparison` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 変更不要 |
| `units/test_issues_iac.py:81` | `ImportValueResolutionTests.test_import_value_requires_a_complete_export_search` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 変更不要 |
| `units/test_issues_iac.py:109` | `ImportValueResolutionTests.test_kms_alias_retains_identity_even_with_the_same_parent_key` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 変更不要 |
| `unknown/validation_cache.checks.py:30` | `check_cache_inputs` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L55) | pytest / 1 | fresh・Project共通入力の追加/内容/削除・Model row再評価 | 関数内抽出 |
| `unknown/validation_cache.checks.py:104` | `check_cache_location` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L91) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `support/validation_checks/cloudformation.py:8` | `check_cloudformation_yaml_rules` | UT | [units/validation_checks/cloudformation.py](units/validation_checks/cloudformation.py#L23) | direct / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `support/validation_checks/cloudformation.py:167` | `check_cloudformation_environment_parameters` | UT | [units/validation_checks/cloudformation.py](units/validation_checks/cloudformation.py#L186) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:9` | `check_optional_alias_contract` | UT | [units/validation_checks/contracts.py](units/validation_checks/contracts.py#L14) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:26` | `check_implementation_preflight_prompt` | UT | [units/validation_checks/contracts.py](units/validation_checks/contracts.py#L31) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:67` | `check_update_flow_prompt` | UT | [units/validation_checks/contracts.py](units/validation_checks/contracts.py#L159) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:165` | `check_design_handoff_prompt` | UT | [units/validation_checks/contracts.py](units/validation_checks/contracts.py#L183) | direct / 1 | 現行handoff Promptの必須記述とFramework検証 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:240` | `check_rule_reading_contract` | UT | [units/validation_checks/contracts.py](units/validation_checks/contracts.py#L195) | direct / 1 | 現行Rule参照・節の存在と回帰選択を読み取り専用で検証 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:9` | `check_catalog_inputs` | UT | [units/validation_checks/design.py](units/validation_checks/design.py#L25) | direct / 1 | 現在のCatalog/Schema/Mapping整合性を読み取り専用で検証 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:84` | `check_schema_backed_design_rows` | UT | [units/validation_checks/design.py](units/validation_checks/design.py#L32) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:221` | `check_name_tag_and_identifier_order_contract` | UT | [units/validation_checks/design.py](units/validation_checks/design.py#L77) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:277` | `check_cidr_pending_deploy` | UT | [units/validation_checks/design.py](units/validation_checks/design.py#L136) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:353` | `check_event_rule_row_order` | UT | [units/validation_checks/design.py](units/validation_checks/design.py#L244) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:397` | `check_artifact_naming` | UT | [units/validation_checks/references.py](units/validation_checks/references.py#L32) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:13` | `check_dispatch` | UT | [units/validation_checks/runner.py](units/validation_checks/runner.py#L22) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:48` | `check_boundaries` | UT | [units/validation_checks/runner.py](units/validation_checks/runner.py#L54) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `support/validation_checks/scenario.py:45` | `check_timestamp` | UT | [units/validation_checks/scenario.py](units/validation_checks/scenario.py#L10) | direct / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `support/validation_checks/task.py:226` | `check_optional_alias_targets` | UT | [units/validation_checks/task.py](units/validation_checks/task.py#L19) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:389` | `check_model_task_boundaries` | UT | [units/validation_checks/task.py](units/validation_checks/task.py#L177) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/terraform.py:13` | `check_configuration` | UT | [units/validation_checks/terraform.py](units/validation_checks/terraform.py#L28) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/validation_scope.checks.py:196` | `check_active_scope` | UT | [units/validation_scope-unit.checks.py](units/validation_scope-unit.checks.py#L46) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/worktree_python.checks.py:87` | `check_environment` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L31) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/worktree_python.checks.py:279` | `check_pdf_native_optional` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L62) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `units/task-contract-unit.checks.py:196` | `check_allowed_paths` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L43) | pytest / 4 | sync-performance: exact/glob/rejection and symlink checks | 検証本体・assertを保持 |
| `units/task-contract-unit.checks.py:214` | `check_live_selection` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L106) | pytest / 1 | sync-performance: live selection and invalidation | 検証本体・assertを保持 |
| `units/sync-model-unit.checks.py:91` | `check_progress_heartbeat_and_waits` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L157) | pytest / 1 | sync-performance: heartbeat and lock/stage diagnostics | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py` | `check_it_reachability` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L346) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py` | `check_it_assertion_guards` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L436) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py` | `check_it_fixture_isolation` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L505) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py` | `check_it_inventory` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L561) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 固定総数・種別別件数・展開件数・suite総数のassertを削除。登録整合性・重複/未登録/欠落・到達性検証を保持 |
| `units/blueprint-loop-unit.checks.py` | `check_it_run_lifecycle` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L607) | pytest / 1 | runner lifecycle: one initialization, measured events and environment restoration | 新規UT |

### UT 内部パターン

| ファイル / ケース | ループ地点・パターン数・入力 |
|---|---|
| `units/validation_cache-unit.checks.py::check_cache_inputs` | L56: 4 (('README.md', 'AGENTS.md', 'project.json', '.agents/project/SKILL.md')) |
| `units/validation_cache-unit.checks.py::check_cache_location` | 1（内部パラメータ化なし） |
| `units/validation_cache-unit.checks.py::check_cache_lifetime` | 1（内部パラメータ化なし） |
| `units/validation_cache-unit.checks.py::check_retained_common_key` | L140: 動的 (range(1000))<br>L169: 5 (('content', 'line-endings', 'addition', 'deletion', 'selector')) |
| `units/validation_cache-unit.checks.py::check_service_cache_invalidation` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_design_naming_rules` | L85: 10 (('S3.Bucket', 'EC2.Instance', 'EC2.VPCEndpoint', 'EC2.VPC', 'IAM.Role', 'SecurityHub.Hub', 'SecretsManager.Secret', 'Macie.ClassificationJob', 'SSM.Association', 'CloudFormation.Stack')) |
| `units/model_design-unit.checks.py::check_subnet_list_display` | L96: 動的 ((ROOT / 'framework/materials/aws').glob('*.properties'))<br>L97: 動的 (path.read_text(encoding='utf-8').splitlines())<br>L98: 動的 (catalog)<br>L101: 動的 (sorted(subnet_lists))<br>L105: 動的 (links)<br>L115: 動的 (inputs)<br>L117: 動的 (shown)<br>L120: 動的 (restored)<br>L121: 動的 (enumerate(rows, 1))<br>L123: 動的 ((document[:-1], [line.replace(field + '[2]', field + '[3]') for line in document], [line.replace(field + '[2]', field + '[1]') for line in document], [line.replace(field + '[1]', field + '[0]') for line in document], [line.replace(field + '[1]', field) for line in document]))<br>L125: 動的 (document)<br>L126: 動的 (document)<br>L127: 動的 (document)<br>L128: 動的 (document)<br>L136: 動的 (([line.replace('\| ' + shown[0][2] + ' \|', '\| `subnet-other` \|') for line in document], [*document[:-1], document[-1].replace(shown[-1][3], '別の説明')]))<br>L137: 動的 (document)<br>L146: 動的 (bad_values) |
| `units/model_design-unit.checks.py::check_security_naming` | L153: 動的 (naming_rule_files(ROOT))<br>L155: 動的 (text.splitlines())<br>L156: 動的 (line.strip('\|').split('\|'))<br>L160: 動的 (patterns.items())<br>L166: 動的 (variants)<br>L171: 3 ((('application', 'app'), ('environment', 'dev'), ('purpose', 'patching')))<br>L177: 動的 (enumerate(fields, 1))<br>L179: 動的 (rows)<br>L180: 動的 (fields)<br>L184: 3 (('EC2.TransitGateway', 'EC2.TransitGatewayVpcAttachment', 'EC2.TransitGatewayRouteTable')) |
| `units/model-validations-unit.checks.py::check_service_scoped_naming` | L200: 3 (('DataZone.Domain', 'DataZone.Project', 'DataZone.DataSource'))<br>L204: 動的 (selected) |
| `units/model-validations-unit.checks.py::check_naming_target_paths` | L222: 3 (('Stages[].Name', 'Stages[].Actions[].Name', 'Variables[].Name')) |
| `units/model_design-unit.checks.py::check_security_group_and_glue_catalog_naming` | L235: 動的 (naming_rule_files(ROOT))<br>L240: 5 ((('EC2.SecurityGroup', [('GroupName', 'app-dev-glue-data-sg')]), ('EC2.SecurityGroup', [('GroupName', 'app-dev-glue-data-01-sg')]), ('EC2.SecurityGroup', [('Tags[].Key', 'Name'), ('Tags[].Value', 'app-dev-glue-data-sg')]), ('EC2.SecurityGroup', [('Tags[].Key', 'Name'), ('Tags[].Value', 'app-dev-glue-data-01-sg')]), ('Glue.Catalog', [('Name', 'glct-app-dev-data')])))<br>L247: 動的 (('', kind + '.'))<br>L249: 動的 (enumerate(fields, 1)) |
| `units/model-validations-unit.checks.py::check_naming_coverage` | 1（内部パラメータ化なし） |
| `units/model-validations-unit.checks.py::check_naming_edges` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_invalid_model` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_temporary_roots` | L283: 動的 (range(2))<br>L285: 動的 (configs)<br>L287: 動的 (configs)<br>L288: 動的 (paths)<br>L290: 動的 (cleanup) |
| `units/model_design-unit.checks.py::check_cli_result` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_one_way_model_contract` | L329: 動的 (('arn:aws:iam::123:role/test', 'arn:aws:iam::123456789012:user/test', 'arn:aws:iam::123456789012:role/', 'arn:aws:iam::123456789012:role/a b', '`' + arn, arn + '`'))<br>L336: 2 (('[role](iam.md#iam-role)', '`AWSServiceRoleForConfig`'))<br>L342: 4 (('value', '`value`', '010', '  quoted "text" ')) |
| `units/model_design-unit.checks.py::check_pending_reference_is_required_input` | L361: 3 (('PENDING_DEPLOY', '`PENDING_DEPLOY`', '`vpc-current`'))<br>L366: 2 (('', '`PENDING_DEPLOY`')) |
| `units/model_design-unit.checks.py::check_selected_model_row_consumption` | L382: 動的 (output) |
| `units/model_design-unit.checks.py::check_glue_argument_display` | L408: 動的 (json.loads(arguments).items())<br>L421: 動的 (output.splitlines())<br>L424: 動的 (invalid)<br>L428: 2 (('`{}`', '`{"--one":"one"}`'))<br>L431: 3 (('`[]`', '`{"--one":true}`', '`{"--one":"first","--one":"second"}`')) |
| `units/model_design-unit.checks.py::check_ec2_compact_display` | L439: 2 ((1, 5))<br>L441: 動的 (range(1, count + 1))<br>L462: 動的 (range(1, count + 1))<br>L480: 動的 (invalid) |
| `units/model_design-unit.checks.py::check_vpc_endpoint_name_display` | L506: 2 (('CREATE', 'IMPORT'))<br>L518: 動的 ((output.replace('ec2-name-tag:', 'missing-name-tag:'), output.replace('["\\"Name\\""', '["\\"name\\""'), output.replace('\| Name \|', '\| ServiceName \|'))) |
| `units/model_design-unit.checks.py::check_athena_configuration_display` | L542: 動的 ((ROOT / 'framework/materials/aws/Athena_WorkGroup.properties').read_text(encoding='utf-8').splitlines())<br>L543: 動的 (enumerate(fields, 1))<br>L549: 動的 (zip(rows, displayed, strict=False)) |
| `units/model_design-unit.checks.py::check_catalog_display_order` | L576: 動的 (shown)<br>L579: 3 ((('QuickSight.DataSource', ['Type', 'Name', 'DataSourceParameters.AthenaParameters.WorkGroup', 'AwsAccountId', 'DataSourceId']), ('S3.Bucket', ['Tags[].Key', 'Tags[].Value', 'Region', 'BucketName']), ('CodeBuild.Project', ['VpcConfig.VpcId', 'VpcConfig.SecurityGroupIds', 'VpcConfig.Subnets', 'Name'])))<br>L582: 動的 (enumerate(fields))<br>L585: 動的 (shown)<br>L585: 動的 (rows)<br>L587: 動的 (shown[:2]) |
| `units/model_design-unit.checks.py::check_optional_naming_suffix` | L605: 動的 (patterns)<br>L606: 動的 (naming_rule_files(ROOT, kind.partition('.')[0]))<br>L610: 2 (('', '-aaaaaa')) |
| `units/model_design-unit.checks.py::check_secret_naming_values` | L619: 動的 (secret_rules)<br>L622: 12 (('`application` as the first level', '`environment` as the second level', 'one or more levels', 'no upper limit on the number of levels', 'do not force distinct purposes into the third level', 'lower-kebab-case', 'CREATE `SecretsManager.Secret.Name` must not end in ASCII `-`', 'Empty components, `//`, and leading or trailing `/` are prohibited', '1–512 characters', 'ASCII letters, numbers, and `/_+=.@-`', 'Do not reject names solely for ending in a hyphen followed by 6 characters', 'IMPORT retains actual/current names'))<br>L631: 5 (('app/dev/credentials-', 'app/dev/snowflake/keypair-', 'app/dev//keypair', '/app/dev/credentials', 'app/dev/credentials/'))<br>L635: 7 (('sample/dev/db-credentials', 'app/dev/credentials', 'app/dev/snowflake/keypair', 'app/dev/snowflake/keypair/lambda', 'app/dev/snowflake/keypair/lambda/rotation', 'app/dev/snowflake/keypair/lambda/rotation/credentials', 'app/dev/snowflake/keypair/lambda-skbm1r'))<br>L639: 2 (('Name', 'SecretsManager.Secret.Name'))<br>L643: 3 (('', 'UNSET', 'PENDING_DEPLOY')) |
| `units/model_design-unit.checks.py::check_kms_policy_accounts` | L674: 動的 (policy['Statement'])<br>L676: 2 ((0, 1))<br>L679: 2 ((False, True))<br>L685: 動的 (('キーの利用権限', f'cross-account:{root_arn}', f'cross-account:{arn}extra'))<br>L691: 動的 (target.items()) |
| `units/model_design-unit.checks.py::check_required_resource_names` | L708: 12 (('', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`', '`TBD`', '`none`', '`未確定`', '`{{application}}`', '[worker](#resource-worker)'))<br>L712: 動的 (invalid)<br>L713: 動的 (('', kind + '.'))<br>L714: 動的 (enumerate(fields, 1)) |
| `units/model_design-unit.checks.py::check_required_name_tag` | L723: 動的 (enumerate(tags, 1))<br>L735: 12 (('', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`', '`TBD`', '`none`', '`not-used`', '`{{application}}`', '[worker](#worker)'))<br>L740: 動的 (invalid)<br>L741: 動的 (enumerate(fields, 1)) |
| `units/model_design-unit.checks.py::check_naming_exclusions` | L753: 11 ((('IAM.ManagedPolicy', 'ManagedPolicyName'), ('IAM.User', 'UserName'), ('IAM.InstanceProfile', 'InstanceProfileName'), ('Config.ConfigurationRecorder', 'Name'), ('Config.DeliveryChannel', 'Name'), ('Glue.Connection', 'ConnectionInput.Name'), ('GuardDuty.Detector', 'Name'), ('Glue.Database', 'DatabaseInput.Name'), ('Glue.Table', 'TableInput.Name'), ('Route53.HostedZone', 'Name'), ('Route53.RecordSet', 'Name')))<br>L760: 動的 (('', kind + '.'))<br>L768: 3 (('', 'UNSET', 'PENDING_DEPLOY'))<br>L775: 4 ((('Config.ConfigurationRecorder', 'Name'), ('SecretsManager.Secret', 'Name'), ('Glue.Database', 'DatabaseInput.Name'), ('Glue.Table', 'TableInput.Name'))) |
| `units/model_design-unit.checks.py::check_import_pending_properties` | L788: 動的 (rows)<br>L803: 動的 (shown) |
| `units/model_design-unit.checks.py::check_stack_policy` | L808: 動的 (enumerate((('app-b-01', '20', 'app.yaml'), ('network', '10', 'network.yaml'), ('app-a', '20', 'app.yaml')), 1))<br>L809: 動的 ({'name': 'cfn-stack-app-dev-' + name, 'template': template, 'parameters': name + '.json', 'deployOrder': order, 'placementName': name}.items())<br>L816: 動的 (stacks)<br>L825: 動的 (restored)<br>L825: 動的 (stacks)<br>L825: 動的 (entry.items())<br>L826: 動的 (restored)<br>L827: 動的 (values.items())<br>L828: 6 ((('desired.stack.001.deployOrder', '0'), ('desired.stack.001.deployOrder', '-1'), ('desired.stack.001.deployOrder', 'abc'), ('desired.deployment.maxConcurrentStacks', '0'), ('desired.deployment.maxConcurrentStacks', '-1'), ('desired.deployment.maxConcurrentStacks', '1.5')))<br>L834: 動的 (values.items())<br>L837: 6 (('', 'invalid', 'stack-resource', 'stack-Bad_Id', ' stack-Resource', 'stack-Resource ')) |
| `units/model_design-unit.checks.py::check_observed_arn_authority` | L849: 2 (('IMPORT', 'CREATE'))<br>L854: 動的 (findings.errors)<br>L859: 動的 (findings.errors) |
| `units/model_design-unit.checks.py::check_desired_only_identifier_reference` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_loggroup_invalid_values` | L875: 2 (('31', 'not-a-number')) |
| `units/model_design-unit.checks.py::check_authoritative_display_identity` | L894: 動的 (enumerate(('BuildProtectionPlan', 'QuarantineProtectionPlan'), 1))<br>L908: 2 (('001', '002'))<br>L910: 動的 (values.items())<br>L911: 4 (('', 'UNSET', 'PENDING_DEPLOY', 'wrong-label'))<br>L915: 2 ((('resourceType', 'GuardDuty.Detector'), ('logicalId', 'OtherPlan')))<br>L920: 動的 (values.items())<br>L922: 動的 (candidates)<br>L932: 動的 (findings.errors) |
| `units/model_design-unit.checks.py::check_navigation_display_labels` | L949: 動的 ((name, logical, 'wrong-label', 'physical-id', '/service-role/' + name))<br>L959: 動的 (findings.warnings)<br>L963: 動的 (messages) |
| `units/model_design-unit.checks.py::check_cfn_identity_inputs` | L989: 動的 (values.items())<br>L998: 2 ((('invalid', 'invalid cfn-logicalId'), ('absent-Vpc', 'undeclared stack'))) |
| `units/model_design-unit.checks.py::check_expanded_design_and_json_digest` | L1104: 動的 (lines) |
| `units/model_design-unit.checks.py::check_required_datasource_type` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_implicit_grouped_required_property` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_required_property_parents` | L1175: 動的 (enumerate(fields, 1))<br>L1177: 動的 (values.items())<br>L1180: 動的 (values.items())<br>L1181: 動的 (rows)<br>L1195: 動的 (validator.errors)<br>L1197: 動的 (validator.errors) |
| `units/model_design-unit.checks.py::check_candidate_model_metadata` | L1207: 動的 (findings.errors) |
| `units/model_design-unit.checks.py::check_candidate_design_diagnostics` | L1221: 動的 (findings.errors)<br>L1231: 動的 (validator.errors)<br>L1233: 動的 (validator.errors) |
| `units/sync-model-unit.checks.py::check_property_path_parents` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_markdown_newlines` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_internal_sync_concurrent_output` | L109: 動的 (roots)<br>L110: 動的 (futures)<br>L111: 動的 (zip(roots, reversed(roots), results, strict=False))<br>L114: 動的 (reports)<br>L115: 動的 (reports) |
| `units/sync-model-unit.checks.py::check_internal_sync_arguments` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_progress_heartbeat_and_waits` | L174: 7 (['heartbeat', 'items=1/2', 'completed=1/1', 'lock-wait', 'stage-failed', 'remaining=unknown', 'not proof of progress']) |
| `units/sync-model-unit.checks.py::check_snapshot_conflict` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_snapshot_project_common_inputs` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_planned_outputs_and_boundary` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_stage_dependency_selection` | L333: 動的 (files.items())<br>L356: 動的 (stage.rglob('*')) |
| `units/sync-model-unit.checks.py::check_linked_attachments` | L379: 動的 (payloads.items())<br>L397: 動的 (payloads.items())<br>L412: 動的 (payloads.items()) |
| `units/sync-model-unit.checks.py::check_final_git_paths` | L456: 動的 (calls) |
| `units/sync-model-unit.checks.py::check_git_baseline_fail_closed` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_scope_git_collection` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_framework_write_does_not_discover` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_result_reuse_is_scoped` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_resource_row_reuse_and_edits` | L567: 動的 (dict(property='IAM.Role.Description', value='first', comment='fixture').items())<br>L581: 動的 (dict(property='IAM.Role.Path', value='/fixture/', comment='added').items())<br>L587: 動的 (list(values)) |
| `units/sync-model-unit.checks.py::check_resource_row_legacy_and_invalid_entries` | L614: 3 (('legacy-001', 'legacy-child-001', 'legacyish-001'))<br>L616: 動的 (dict(property='IAM.Role.Description', value=identity, comment='fixture').items())<br>L619: 動的 (rows) |
| `units/sync-model-unit.checks.py::check_resource_row_scope_restoration` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_generate_views_missing_authoritative_json` | L692: 動的 (root.rglob('*'))<br>L701: 動的 (stage.rglob('*'))<br>L702: 動的 ((design, artifact))<br>L703: 動的 (root.rglob('*')) |
| `units/sync-model-unit.checks.py::check_readonly_stale_views` | L714: 動的 ((expected, expected.replace('`14`', '`31`'), '', expected.replace('RetentionInDays', 'UnknownField')))<br>L716: 動的 ((path, source))<br>L724: 動的 (before) |
| `units/sync-model-unit.checks.py::check_snapshot_symlink_safety` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_internal_sync_selection` | L779: 動的 (sync.call_args_list)<br>L781: 動的 (sync.call_args_list) |
| `units/sync-model-unit.checks.py::check_failure_counts` | L788: 動的 (range(17))<br>L789: 動的 (paths[9:])<br>L790: 動的 (paths[:9])<br>L791: 動的 (paths)<br>L796: 動的 (range(5))<br>L810: 動的 (failures[-2:]) |
| `units/sync-model-unit.checks.py::check_guard_snapshot_candidates` | L825: 動的 (({}, {project: '{}\n'})) |
| `units/sync-model-unit.checks.py::check_definition_read_errors` | L854: 動的 (validator.errors) |
| `units/sync-model-unit.checks.py::check_sidecar_output_difference` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_missing_validation_inputs` | L898: 動的 (validator.errors) |
| `units/sync-model-unit.checks.py::check_generation_input_failures` | 1（内部パラメータ化なし） |
| `units/aws_mapping-unit.checks.py::check_payload_selection` | L40: 動的 (mapping.properties.items())<br>L48: 動的 (mapping.properties.items())<br>L51: 動的 (mapping.properties.items()) |
| `units/aws_mapping-unit.checks.py::check_v3_registry` | L61: 動的 (paths)<br>L73: 動的 (document['resourceTypes'].items())<br>L75: 動的 (mapping.getters.items())<br>L76: 動的 (adapter_getters.values())<br>L76: 動的 (resources)<br>L81: 3 (('RESOURCE_TYPES', 'IDENTITIES', 'GETTERS'))<br>L83: 動的 (mapping.identities.items())<br>L92: 3 (('RESOURCE_TYPES', 'IDENTITIES', 'GETTERS'))<br>L108: 動的 (tgw_properties.items())<br>L110: 動的 (actual.items())<br>L111: 動的 (actual.items())<br>L112: 動的 (selected)<br>L119: 動的 ([(baseline_properties, '011c38a46feabd4a28eb4619a3963a3c145f207266dfd757f4a0bbc25a02a463'), (definitions, '345c0f5691eeaf636a27f902e04831de58cd96f5506d1936c67f43edb156944b'), (metadata, '6ddf2190bf6c29c9615b5fad44deb27f8b33007f9fd8b4596be89630da10869b')]) |
| `units/aws_mapping-unit.checks.py::check_registry_cache` | L134: 動的 ((lambda: setattr(first.identities[RECORDER], 'id_path', 'other'), lambda: first.identities.__setitem__(RECORDER, None), lambda: first.getters['recorder'].__setitem__('resources', ()), lambda: setattr(first, 'service', 'other'))) |
| `units/aws_mapping-unit.checks.py::check_baseline` | L153: 動的 (BASELINE.items())<br>L153: 動的 (props.items())<br>L155: 動的 (aws_mapping.registry(ROOT, 'config').fields.items())<br>L161: 動的 (BASELINE.items())<br>L162: 動的 (enumerate(props, 1))<br>L164: 動的 (props)<br>L164: 動的 (shown)<br>L165: 動的 (rows)<br>L165: 動的 (shown) |
| `units/aws_mapping_catalog.checks.py::initialization_checks` | 1（内部パラメータ化なし） |
| `units/aws_mapping_catalog.checks.py::schema_checks` | L129: 4 ([('SNS.Topic', 'getter', 'sdk-sns-topicpolicy'), ('SNS.Topic', 'idPath', 'Unknown'), ('SNS.Topic', 'nameProperty', 'Unknown'), ('SNS.TopicPolicy', 'idPath', 'attributes')])<br>L163: 動的 (mutations)<br>L201: 動的 (invalid)<br>L210: 4 (('getter', 'default', 'source', 'transform')) |
| `units/blueprint-loop-unit.checks.py::check_utf8_restart` | L13: 4 ((0, 2, 7, 130)) |
| `units/blueprint-loop-unit.checks.py::check_changed_paths_error` | 1（内部パラメータ化なし） |
| `units/blueprint-loop-unit.checks.py::check_process_interruption` | 1（内部パラメータ化なし） |
| `units/blueprint-loop-unit.checks.py::check_parallel_interruption` | 1（内部パラメータ化なし） |
| `units/blueprint-loop-unit.checks.py::check_fixture_independence` | L144: 2 (('AGENTS.md', 'README.md'))<br>L146: 5 (('issues/dev/other/issues.md', 'model/dev/other/ec2.properties', 'docs/designs/dev/other/ec2.md', 'tasks/example.md', 'project.json')) |
| `units/blueprint-loop-unit.checks.py::check_regression_discovery` | 全UTの検出、IT除外、空集合拒否 |
| `units/check-model-aws-unit.checks.py::check_summary_exit_codes` | 1（内部パラメータ化なし） |
| `units/check-model-aws-unit.checks.py::check_value_normalization` | 1（内部パラメータ化なし） |
| `units/check-model-aws-unit.checks.py::check_secret_redaction` | 1（内部パラメータ化なし） |
| `units/cloudformation-deploy-unit.checks.py::check_scheduler` | L17: 2 ((('A', 'B'), ('B', 'C')))<br>L71: 3 (('intent', 'submitted', 'response'))<br>L?: 動的 (state.values())<br>L?: 動的 (state.values())<br>L?: 動的 (state.values())<br>L?: 動的 (enumerate(fake.events))<br>L?: 動的 (enumerate(fake.events))<br>L?: 動的 (results)<br>L?: 動的 (enumerate(fake.events)) |
| `units/deploy-required-readings.checks.py::check_workflow_contract` | Seven Rule files, exact full/section selection, selected-body and source SHA256 parity with the former reading route. |
| `units/deploy_preparation-unit.checks.py::check_dependencies_and_timing` | L26: 6 (('boto3', 'botocore', 'PyYAML', 'git')) |
| `units/deploy-required-readings.checks.py::check_rule_section_boundaries` | L65: 2 (('## Duplicate\\nsame\\n## Duplicate\\nsame\\n', '<a id="shared"></a>\\n## One\\nfirst\\n<a id="shared"></a>\\n## Two\\nsecond\\n')) |
| `units/design_catalog-unit.checks.py::check_api_schema` | L22: 3 ((MACIE_JOB, QUICKSIGHT_GROUP, 'Macie.Unknown')) |
| `units/design_document-unit.checks.py::check_snapshots` | L?: 動的 (results)<br>L?: 動的 (reads.call_args_list)<br>L?: 動的 (reads.call_args_list) |
| `units/design_layout-unit.checks.py::check_resource_display_names` | 1（内部パラメータ化なし） |
| `units/design_layout-unit.checks.py::check_cloudtrail_expansion` | 1（内部パラメータ化なし） |
| `units/design_layout-unit.checks.py::check_pipeline_expansion` | L?: 動的 (expanded.splitlines())<br>L?: 動的 (pipeline_rows(formal_rows))<br>L?: 動的 (enumerate(rows, 1))<br>L?: 動的 (line.strip('\|').split('\|')) |
| `units/framework-input-isolation-unit.checks.py::check_framework_input_guards` | L?: 動的 (consumer.errors) |
| `units/glue_datazone_catalog-unit.checks.py::check_catalog_schema` | L14: 4 (('Glue.Catalog', 'DataZone.Domain', 'DataZone.Project', 'DataZone.DataSource')) |
| `units/issues_api_only-unit.checks.py::check_api_type_rejection` | L13: 動的 (catalog.api_schemas) |
| `units/issues_scan-unit.checks.py::check_mismatch_rendering` | L27: 4 ([(None, False, 'null', 'false'), (True, 1, 'true', '1'), (1, '1', '1', '"1"'), (False, 'false', 'false', '"false"')])<br>L?: 動的 (fields({'a': 1, 'b': 2}, {'a': 3, 'b': 4}))<br>L?: 動的 (records)<br>L?: 5 (range(5))<br>L?: 動的 (duplicates)<br>L?: 動的 (entries)<br>L?: 動的 (original)<br>L?: 動的 (entries)<br>L?: 動的 (original) |
| `units/issues_scan-unit.checks.py::check_summary_scale` | L157: 4 (('first', 'second', 'confidential', 'arn:aws:'))<br>L159: 4 ([('matched', 'complete match'), ('uncompared', 'partial'), ('excluded', 'no compared records'), ('error', 'error')])<br>L117: 動的 (stats['categories'].items())<br>L122: 2 (('naming', 'judgments'))<br>L?: 動的 (actions)<br>L?: 動的 (actions)<br>L?: 動的 (entries)<br>L?: 動的 (records)<br>L?: 動的 (stats['groups'])<br>L?: 動的 (stats['categories'].items())<br>L?: 動的 (again_actions)<br>L?: 動的 (actions)<br>L?: 動的 (again_actions)<br>L?: 動的 (actions)<br>L?: 動的 (actions)<br>L?: 動的 (actions)<br>L?: 動的 (action['members'])<br>L?: 動的 (range(0, total, 50))<br>L?: 動的 (detail_payload(artifact, section, offset, 50)['items'])<br>L?: 動的 (group['members'])<br>L?: 動的 (group['members'])<br>L?: 動的 (group['members'])<br>L?: 動的 (group['members']) |
| `units/lambda_permission-unit.checks.py::check_permission_catalog` | 1（内部パラメータ化なし） |
| `units/model_files-unit.checks.py::check_cfn_selector` | 1（内部パラメータ化なし） |
| `units/model_parameter_inputs-unit.checks.py::check_yaml_schema` | L13: 4 (['a: 1\na: 2', 'a: {b: 1, b: 2}', 'a: !!python/object:bad {}', 'a: &x {b: 1}\nc: {<<: *x}']) |
| `units/model_parameter_inputs-unit.checks.py::check_embedded_parameter_type` | 1（内部パラメータ化なし） |
| `units/policy_tables-unit.checks.py::check_iam_artifact_names` | 1（内部パラメータ化なし） |
| `units/policy_tables-unit.checks.py::check_statement_metadata` | 1（内部パラメータ化なし） |
| `units/policy_tables-unit.checks.py::check_lossless_generation` | 1（内部パラメータ化なし） |
| `units/producer-identifier-reference-unit.checks.py::check_identifier_schema` | L13: 4 ([{k: v for k, v in ref.items() if k != 'property'}, {**ref, 'property': 'EC2.VPC.Arn'}, {**ref, 'property': 'EC2.Subnet.SubnetId'}, {'instance': 'main', 'resourceType': 'EC2.VPC', 'format': 'identifier', 'property': 'EC2.VPC.VpcId'}])<br>L?: 動的 (ref.items()) |
| `units/quicksight-display-unit.checks.py::check_alias_catalog` | L?: 動的 ((ROOT / 'framework/materials/aws/QuickSight_DataSource.properties').read_text(encoding='utf-8').splitlines()) |
| `units/quicksight-display-unit.checks.py::check_alias_rows` | L?: 動的 ((ROOT / 'framework/materials/aws/QuickSight_DataSource.properties').read_text(encoding='utf-8').splitlines())<br>L?: 動的 (enumerate(fields, 1))<br>L?: 動的 (source) |
| `units/raw-bucket-name-reference-unit.checks.py::check_reference_schema` | L13: 3 ([{**ref, 'format': 'unknown'}, {**ref, 'format': {}}, {'instance': 'first', 'resourceType': 'S3.Bucket', 'format': 'name'}]) |
| `units/regression_guard-unit.checks.py::check_password_input_diagnostics` | L19: 2 (((guard.GuardError('repo .lock already exists'), 'repo .lock already exists'), (ValueError('fixture-private-password-and-hash'), 'Check repo .lock'))) |
| `units/resource_mode-unit.checks.py::check_default_mode` | 1（内部パラメータ化なし） |
| `units/resource_mode-unit.checks.py::check_import_naming_exemption` | 1（内部パラメータ化なし） |
| `units/resource_mode-unit.checks.py::check_required_name_modes` | L30: 4 (('EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'))<br>L31: 2 (('CREATE', 'IMPORT'))<br>L32: 2 (([], [['1', kind + '.Name', 'PRIVATE_SUBNET_01', 'Nameタグ']])) |
| `units/security_group_tables-unit.checks.py::check_rule_catalog` | L15: 動的 (DIRECTIONS.values())<br>L20: 動的 (selected - {'GroupId', 'Id'})<br>L?: 動的 (catalog[1].items()) |
| `units/security_group_tables-unit.checks.py::check_service_filenames` | L31: 7 ((('ec2.md', 'ec2', ('EC2.SecurityGroup',)), ('ec2.properties', 'ec2', ('EC2.SecurityGroupIngress',)), ('security-group.md', 'security-group', ('EC2.Instance',)), ('security-group.md', 'security-group', ('EC2.SecurityGroup', 'EC2.VPC')), ('security_group.md', 'security_group', ('EC2.SecurityGroup',)), ('security_group.properties', 'security_group', ('EC2.SecurityGroup',)), ('other_service.md', 'other_service', ('S3.Bucket',)))) |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_formal_pipeline_membership_and_configuration_context` | L?: 動的 (enumerate(fields)) |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_api_managed_resource_remains_unverified_in_cloudformation_comparison` | 1（内部パラメータ化なし） |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_import_value_requires_a_complete_export_search` | 1（内部パラメータ化なし） |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_kms_alias_retains_identity_even_with_the_same_parent_key` | 1（内部パラメータ化なし） |
| `units/validation_checks/cloudformation.py::check_cloudformation_yaml_rules` | L59: 4 (('OtherSuffix', 'ExportVersion', 'NamePart', 'namePart2'))<br>L64: 10 (("Imported:\n        Fn::ImportValue: !Sub 'VpcId${Suffix}'", 'Imported:\n        Fn::ImportValue: !Sub "SubnetId${OtherSuffix}"', "Imported:\n        Fn::ImportValue:\n          # Import name\n          !Sub 'VpcId${NamePart}'", "Imported:\n        'Fn::ImportValue': !Sub 'VpcId${Suffix}'", 'Imported: {"Fn::ImportValue": !Sub "VpcId${Suffix}"}', "Imported: !ImportValue {Fn::Sub: 'VpcId${Suffix}'}", 'Imported: !ImportValue {Fn::Sub: "SubnetId${OtherSuffix}"}', "Imported: !ImportValue {'Fn::Sub': 'VpcId${NamePart}'}", 'Imported: !ImportValue {"Fn::Sub": "VpcId${Suffix}"}', "Imported: !ImportValue {Fn::Sub: ['VpcId${Part}', {Part: !Ref Suffix}]}"))<br>L82: 動的 ((valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", 'JobId:\n        Fn::Select:\n          - 0\n          - Ref: GlueJob'), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", 'JobId: {Fn::Select: [0, {Ref: GlueJob}]}'), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {'Fn::Select': [0, !Ref GlueJob]}"), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Join: ['-', [a, b]]}"), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Sub: '${AWS::Region}'}"), valid.replace('Imported: !ImportValue fixed-export', 'Imported:\n        Fn::ImportValue: fixed-export'), valid.replace('Imported: !ImportValue fixed-export', "Imported:\n        Fn::ImportValue: {Fn::Sub: 'VpcId${Suffix}'}"), valid.replace('Imported: !ImportValue fixed-export', "Imported:\n        Fn::ImportValue:\n        Description: !Sub 'VpcId${Suffix}'"), valid.replace('Imported: !ImportValue fixed-export', 'Imported:\n        Fn::ImportValue:\n          Ref: Suffix'), valid.replace('Imported: !ImportValue fixed-export', "Imported: !ImportValue fixed-export # Fn::ImportValue: !Sub 'text'\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: 'Fn::ImportValue: !Sub text'\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: !ImportValue {Fn::Sub: ['VpcId${Part}', {Part: {Ref: Suffix}}]}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: !ImportValue {Fn::Sub: 'VpcId${Suffix}'}\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: '!ImportValue {Fn::Sub: text}'\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', 'Imported: !ImportValue fixed-export # !ImportValue {Fn::Sub: text}\n      ExtraImport: {Fn::Sub: text}')))<br>L112: 動的 ((valid.replace('AssumeRolePolicyDocument:\n', 'AssumeRolePolicyDocument: &sharedTrustPolicy\n', 1), valid.replace('AssumeRolePolicyDocument:\n' + trust_body, 'AssumeRolePolicyDocument: *sharedTrustPolicy\n', 1), valid.replace('AssumeRolePolicyDocument:\n' + trust_body, 'AssumeRolePolicyDocument:\n        <<: {}\n', 1)))<br>L161: 3 (('AWS::EC2::SecurityGroup', 'AWS::Logs::LogGroup', 'AWS::IAM::Role'))<br>L?: 動的 (errors(suffix_import.replace('!Ref Suffix', '{Ref: Suffix}')))<br>L?: 動的 (errors(export_suffix_import.replace('!Ref ExportSuffix', '{Ref: ExportSuffix}')))<br>L?: 動的 (errors(suffix_import.replace('!Ref Suffix', '!Ref Invalid_Name')))<br>L?: 動的 (errors(suffix_import.replace("['',", "['-',")))<br>L?: 動的 (errors(valid.replace('\n  RoleB:', '  RoleB:', 1)))<br>L?: 動的 (errors(block_array))<br>L?: 動的 (errors(join_block_array))<br>L?: 動的 (errors(valid.replace(consumer, '')))<br>L?: 動的 (errors(role_only))<br>L?: 動的 (errors(marker + valid))<br>L?: 動的 (errors('Resources:\n  Logs:\n    Type: AWS::Logs::LogGroup\n'))<br>L?: 動的 (errors('Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Logs:\n    Type: AWS::Logs::LogGroup\n'))<br>L?: 動的 (errors('Resources:\n  Filter:\n    Type: AWS::Logs::SubscriptionFilter\n'))<br>L?: 動的 (errors('Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Profile:\n    Type: AWS::IAM::InstanceProfile\n'))<br>L?: 動的 (errors('Resources:\n  Group:\n    Type: AWS::EC2::SecurityGroup\n  Ingress:\n    Type: AWS::EC2::SecurityGroupIngress\n'))<br>L?: 動的 (errors(marker + ingress))<br>L?: 動的 (errors(bad))<br>L?: 動的 (errors(forbidden))<br>L?: 動的 (errors(ingress + egress + f'\n  Support:\n    Type: {support}\n')) |
| `units/validation_checks/cloudformation.py::check_cloudformation_environment_parameters` | L236: 動的 (conditions)<br>L259: 動的 (selectors)<br>L285: 動的 (permitted)<br>L?: 動的 (errors(valid_template.replace('  Environment:\n    Type: String\n', ''), valid_values))<br>L?: 動的 (errors(valid_template, valid_values[1:]))<br>L?: 動的 (errors(valid_template, [{**valid_values[0], 'ParameterValue': 'prod'}, valid_values[1]]))<br>L?: 動的 (errors(valid_template, [valid_values[0], {**valid_values[1], 'ParameterValue': 'app-dev'}]))<br>L?: 動的 (errors(valid_template.replace("!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'", '!Ref NamePrefix'), [{'ParameterKey': 'NamePrefix', 'ParameterValue': 'app-dev-role'}]))<br>L?: 動的 (errors(yaml, valid_values))<br>L?: 動的 (errors(valid_template + loop, valid_values))<br>L?: 動的 (failures)<br>L?: 動的 (validator.errors)<br>L?: 動的 (errors('Resources: [', valid_values))<br>L?: 動的 (failures)<br>L?: 動的 (failures) |
| `units/validation_checks/contracts.py::check_optional_alias_contract` | L26: 動的 (required.items()) |
| `units/validation_checks/contracts.py::check_implementation_preflight_prompt` | L37: 17 (('before active contract creation or IaC generation', 'Do not execute AWS APIs, IaC generation, or deploy', 'model.validations.schema.validate_required_properties', 'DesignSchemaCatalog.literal_errors', 'necessary dependency properties', 'authoritative stack registration', 'template/parameter mappings', 'dependency cycle', '対象file \| resource（logical ID）/stack \| property/parameter \| 不足・違反理由', 'together in one response', 'do not end the report at the first deficiency', 'If deficiencies exist, do not implement', 'without requiring additional approval', 'Do not automatically expand change scope or all-service validation', 'Japanese display Comments', 'do not automatically translate/replace invalid values', 'Do not repair designs/models/IaC here or automatically create/execute another task'))<br>L48: 18 (('Implement design inputs are only authoritative model properties', 'Do not require the Agent to compare properties and generated Markdown twice in advance', 'Do not read generated `docs/designs/<environment>/<target-directory>/*.md` bodies (including `cloudformation-stacks.md`) at Implement start, IaC generation, or reference resolution', 'Retain Markdown/JSON generation/saving and local loop consistency validation as before', 'treat them as scope selectors', 'Without reading bodies', 'path/file stem', 'If corresponding models cannot be uniquely identified, stop without guessing', 'python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py resource model/<environment>/<target-directory>/<service>.properties <resource-selector>', 'resource number', 'Selectors require exact matches for resource number (fixed entry, such as `001`) or immutable typed logicalId', 'single files and split entry indexes', 'parents, children, and siblings in the same group required by existing specifications, and service metadata/notes', 'Service-wide scope may use entire service properties', '対象accountの承認済み設計すべて', 'Reading all target Markdown as fallback is prohibited', 'desired values, resources, references, stack assignments, or human decisions', 'stop because a design task is required'))<br>L58: 動的 (reading.splitlines())<br>L61: 8 (("read only the target's runtime Model through the logical `model/<environment>/<target-directory>/cloudformation-stacks.properties`", 'desired.stack.*.name', '`.template`', '`.parameters`', '`.deployOrder`', 'desired.deployment.maxConcurrentStacks', 'effective MaxConcurrentStacks remains 1 under the existing contract', 'do not read it as Implement input'))<br>L65: 9 (('Use only authoritative model properties', '`desired.row.*`', '`.document`', 'saved Markdown Resource links', 'common parser/resolver', 'referenced Model groups', 'parentReference', 'Resolve through producer Model saved anchors, never names, cfn-logicalId or generated Markdown', 'never emit an unresolved Resource link, PENDING_DEPLOY or an inferred physical value to IaC'))<br>L69: 7 (('blueprint-loop.py --mode task', 'read-only `sync-model.py`', 'mismatches are FAIL', 'check_design_tables', 'check_design_links', 'check_stack_designs', 'do not omit/weaken these validations')) |
| `units/validation_checks/contracts.py::check_update_flow_prompt` | Independent Deploy options/scope; GROUP_COMPLETE handoff; original-operation Recovery; Human approval and Terraform saved-plan boundary. Reject obsolete CloudFormation session options. |
| `units/validation_checks/contracts.py::check_design_handoff_prompt` | 1（内部パラメータ化なし） |
| `units/validation_checks/contracts.py::check_rule_reading_contract` | L196: 動的 (sources)<br>L198: 動的 (markdown_prose(text))<br>L199: 動的 (re.findall('(?<!!)\\\\[[^\\\\]]+\\\\]\\\\(([^)]+)\\\\)', prose))<br>L212: 6 (('framework/scripts/deploy_preparation.py', 'framework/scripts/validation_cache.py', 'framework/scripts/validation/framework_contracts.py', 'README.md', '.agents/skills/worktree/SKILL.md', 'framework/rules/loop-engineering.md')) |
| `units/validation_checks/design.py::check_catalog_inputs` | 1（内部パラメータ化なし） |
| `units/validation_checks/design.py::check_schema_backed_design_rows` | L46: 動的 (validator.errors)<br>L47: 動的 (validator.errors) |
| `units/validation_checks/design.py::check_name_tag_and_identifier_order_contract` | L74: 動的 (MODULE.REQUIRED_NAME_PROPERTIES.items())<br>L96: 動的 (name_cases)<br>L102: 動的 (validator.errors)<br>L112: 動的 (identifier_cases)<br>L118: 動的 (validator.errors) |
| `units/validation_checks/design.py::check_cidr_pending_deploy` | L167: 動的 ((('CREATE', valid, None), ('CREATE', without_name, 'required Name property'), ('IMPORT', without_name, None)))<br>L183: 動的 (diagnostics)<br>L190: 動的 ((('resource_logical_ids', ValueError('識別情報が曖昧')), ('design_model_values', OSError('Model読み込み失敗'))))<br>L195: 動的 (([failed], [failed, path]))<br>L208: 動的 (names.call_args_list)<br>L211: 3 (('PENDING_DEPLOY', '`PENDING_DEPLOY`', '[PENDING_DEPLOY](#vpc-saved-original)'))<br>L213: 動的 (errors(valid.replace('`10.0.0.0/16`', pending, 1)))<br>L214: 動的 (errors(valid.replace('CidrBlock \| `10.0.0.0/16`', 'CidrBlock \| ' + pending)))<br>L215: 5 (('EC2.Subnet.CidrBlock', 'EC2.Route.CidrBlock', 'EC2.Route.DestinationCidrBlock', 'EC2.SecurityGroupIngress.CidrIp', 'EC2.TransitGateway.TransitGatewayCidrBlocks')) |
| `units/validation_checks/design.py::check_event_rule_row_order` | L254: 動的 (enumerate(selected, 1))<br>L262: 動的 ((rows[2:3] + rows[:2] + rows[3:], [rows[1], rows[0], *rows[2:]]))<br>L263: 動的 (errors(selected))<br>L264: 2 ((0, 1))<br>L265: 動的 ((rows[:index] + rows[index + 1:], rows + [rows[index]]))<br>L266: 動的 (errors(selected))<br>L267: 3 (('', 'UNSET', 'PENDING_DEPLOY'))<br>L270: 動的 (errors(selected)) |
| `units/validation_checks/references.py::check_artifact_naming` | 1（内部パラメータ化なし） |
| `units/validation_checks/runner.py::check_dispatch` | L50: 動的 (cases)<br>L?: 動的 (cases)<br>L?: 動的 (tail)<br>L60: 動的 (methods) |
| `units/validation_checks/runner.py::check_boundaries` | 1（内部パラメータ化なし） |
| `units/validation_checks/scenario.py::check_timestamp` | 1（内部パラメータ化なし） |
| `units/validation_checks/task.py::check_optional_alias_targets` | alias/path/restrict・suffix 14入力・Region・engine整合性・共通Profile判定のfindings伝播。Profile 8入力とexecution account 9入力、account不正1入力は共通Identity UTへ移管。 |
| `units/validation_checks/task.py::check_model_task_boundaries` | L190: 動的 ({'design': {'docs/designs/dev/cde/vpc.md', 'model/parameters/dev/cde/vpc/parameters.yaml'}, 'infrastructure': {'infra/cloudformation/templates/vpc.yaml', 'docs/designs/dev/cde/vpc.md', 'model/parameters/dev/cde/vpc/parameters.yaml'}}.items()) |
| `units/validation_checks/terraform.py::check_configuration` | L273: 2 (('cloudformation', 'terraform'))<br>L35: 動的 (accounts)<br>L115: 3 (('infra/cloudformation/parameters/preview/ops', 'docs/designs/preview/ops', 'model/preview/ops'))<br>L128: 動的 (saved_module.items())<br>L143: 動的 (range(2))<br>L148: 2 (('01_initialize.md', '02_add-target.md'))<br>L167: 2 (('../modules/iam/../iam', '../modules/./iam'))<br>L170: 7 (('../modules', '../modules/iam/../../stg', './copied', '../modules/iam/../../../non-cde/terraform/modules/iam', 'registry.example/module', '${var.source}', '../modules/iam${var.suffix}'))<br>L191: 7 (('infra/cde/terraform/qa/main.tf', 'infra/cde/terraform/dev/copied/main.tf', 'infra/cde/terraform/modules/main.tf', 'infra/cde/terraform/main.tf', 'infra/cde/main.tf', 'infra/terraform/modules/cde/main.tf', 'infra/unknown/terraform/modules/iam/main.tf'))<br>L223: 4 (('/* unterminated', 'locals { text = <<EOF\nunterminated\n', 'locals { text = "unfinished', 'module "application" { source = "../modules/iam"'))<br>L229: 4 ((({'resource': {'aws_iam_role': {'bad': {}}}}, True), ({'resource': {'terraform_data': {'valid': {}}}}, False), ({'module': {'extra': {'source': '../modules/missing'}}}, True), ({'module': {'extra': {'source': '../modules/iam'}}}, False)))<br>L264: 3 (('cde', 'non-cde', '123456789012'))<br>L266: 動的 (accounts.values())<br>L269: 動的 (accounts.values())<br>L36: 動的 ((f'docs/designs/{env}/{target}', f'model/{env}/{target}', f'infra/{target}/terraform/{env}', f'infra/{target}/terraform/modules/iam'))<br>L144: 動的 (accounts)<br>L?: 2 (('dev', 'stg'))<br>L?: 2 (('cde', 'non-cde'))<br>L?: 動的 (shared.parent.iterdir())<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (range(1, 18))<br>L?: 動的 (bad.errors)<br>L?: 動的 (validate().errors)<br>L?: 動的 (validate(set(), changed=module_changes, task='governance').errors)<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (blocks(path))<br>L?: 動的 (validate().errors)<br>L?: 動的 (validate().errors) |
| `units/validation_scope-unit.checks.py::check_active_scope` | L15: 3 (('', '## Validation scope\n- `dev/cde`\n', '## Validation scope\n- `ec2`\n'))<br>L?: 2 (('dev', 'stg'))<br>L?: 2 (('cde', 'non-cde'))<br>L?: 動的 (sorted(scope)) |
| `units/worktree_python-unit.checks.py::check_environment` | L?: 3 (('VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH')) |
| `units/worktree_python-unit.checks.py::check_pdf_native_optional` | L?: 動的 (imports.call_args_list)<br>L?: 動的 (versions.call_args_list) |

## IT 全ケース

| 元ファイル : 行 | Test Case名 | 分類 | 現在の配置 | 入口 / パターン数 | 分類理由 | 変更 |
|---|---|---|---|---|---|---|
| `integrations/attribute-reference-resolution.checks.py:73` | `check_pair` | IT | [integrations/attribute-reference-resolution.checks.py](integrations/attribute-reference-resolution.checks.py#L89) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:123` | `check_fixed_label` | IT | [integrations/attribute-reference-resolution.checks.py](integrations/attribute-reference-resolution.checks.py#L125) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:186` | `check_stack` | IT | [integrations/attribute-reference-resolution.checks.py](integrations/attribute-reference-resolution.checks.py#L159) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:237` | `check_preparation_cache` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L396) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:285` | `check` | IT | [integrations/attribute-reference-resolution.checks.py](integrations/attribute-reference-resolution.checks.py#L203) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/auxiliary-model-dependencies.checks.py:76` | `check` | IT | [integrations/auxiliary-model-dependencies.checks.py](integrations/auxiliary-model-dependencies.checks.py#L42) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/aws_mapping.checks.py:141` | `check_config` | IT | [integrations/aws_mapping.checks.py](integrations/aws_mapping.checks.py#L69) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/aws_mapping_compare.checks.py:32` | `check_mapping_transforms` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L447) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/aws_mapping_display.checks.py:50` | `check` | IT | [integrations/aws_mapping_display.checks.py](integrations/aws_mapping_display.checks.py#L30) | direct / 1 | 現行Logsの生成・再生成一致・検証・Model不変、CodeCommit非表示IDの正本保持 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:41` | `check_running_and_interruption` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L37) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `unknown/blueprint-loop.checks.py:108` | `check_deploy_scope_isolation` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L60) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `unknown/blueprint-loop.checks.py:235` | `check_task_service_validation` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L127) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `unknown/blueprint-loop.checks.py:382` | `check_parallel_and_selection` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L141) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `unknown/blueprint-loop.checks.py:493` | `check_staged_snapshot` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L164) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `issue-18` | `check_regression_authorization` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L654) | pytest / 1 | diagnostics / authorization / finally | 実プロセス・Gitなし |
| `unknown/blueprint-loop.checks.py:651` | `check_failure_suspension` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L237) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `issue-18` | `check_startup_diagnostics` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L741) | pytest / 11 | diagnostics / authorization / finally | 実プロセス・Gitなし |
| `unknown/blueprint-loop.checks.py:831` | `check_windows_exit_propagation` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L85) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:853` | `check_workflow` | IT | [integrations/blueprint-loop.checks.py](integrations/blueprint-loop.checks.py#L263) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 実CLI・実Git・子プロセスの代表統合保証 |
| `integrations/bound-anchor-name-change.checks.py:86` | `check` | IT | [integrations/bound-anchor-name-change.checks.py](integrations/bound-anchor-name-change.checks.py#L42) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/bound-stack-name-change.checks.py:33` | `check` | IT | [integrations/bound-stack-name-change.checks.py](integrations/bound-stack-name-change.checks.py#L32) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/check-model-aws.checks.py:345` | `cli_checks` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L69) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:449` | `batch_checks` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L153) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:582` | `common_checks` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L216) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:716` | `association_checks` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L268) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:812` | `stack_checks` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L290) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:841` | `cfn_identity_checks` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L303) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:893` | `fixture_coverage` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L330) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:934` | `check_consumer_coverage` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L372) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:229` | `check_sdk_execution` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L90) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:331` | `check_empty_rollback_recreation` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L245) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:443` | `check_template_validation` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L320) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:469` | `check_inputs` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L71) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:657` | `check_delivery` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L352) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:919` | `check_delivery_encryption` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L647) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1421` | `check_parallel_and_restart` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L1184) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1503` | `check_observed_collector` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L168) | pytest / 1 | 取得・保存、無関係な意味不備は継続／構文破損は停止、公開Task scopeを維持 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1640` | `check_shared_stack_mapping` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L357) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1803` | `check_import_implementation_mapping` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L580) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1859` | `check_integrated_child_mapping` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L646) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1957` | `check_secretsmanager_arn_identifiers` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L752) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:2051` | `check_api_timing` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L1252) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:2468` | `check_secret_runtime_bootstrap` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L1575) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:134` | `check_destroy_order_and_safety` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L2019) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:208` | `check_destroy_unused_export` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L2091) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:232` | `check_destroy_absence` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L2111) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:321` | `check_controller` | IT | [integrations/cloudformation-destroy.checks.py](integrations/cloudformation-destroy.checks.py#L159) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:426` | `check_observed` | IT | [integrations/cloudformation-destroy.checks.py](integrations/cloudformation-destroy.checks.py#L274) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:63` | `check_imports` | IT | [integrations/cloudformation-naming.checks.py](integrations/cloudformation-naming.checks.py#L76) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:102` | `check_names` | IT | [integrations/cloudformation-naming.checks.py](integrations/cloudformation-naming.checks.py#L120) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:126` | `check_flow_logs` | IT | [integrations/cloudformation-naming.checks.py](integrations/cloudformation-naming.checks.py#L149) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:172` | `check` | IT | [integrations/cloudformation-naming.checks.py](integrations/cloudformation-naming.checks.py#L208) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:180` | `check_fixtures` | IT | [integrations/cloudformation-naming.checks.py](integrations/cloudformation-naming.checks.py#L217) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `integrations/cloudtrail-input-reference.checks.py:20` | `check` | IT | [integrations/cloudtrail-input-reference.checks.py](integrations/cloudtrail-input-reference.checks.py#L30) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/deploy_preparation.checks.py:105` | `check_preparation` | IT | [integrations/deploy_preparation.checks.py](integrations/deploy_preparation.checks.py#L48) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:184` | `check_stale_and_conflicts` | IT | [integrations/deploy_preparation.checks.py](integrations/deploy_preparation.checks.py#L140) | direct / 1 | runtime/契約候補/Model/生成Markdown・JSONの変更と削除を拒否 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:233` | `check_generated_boundaries` | IT | [integrations/deploy_preparation.checks.py](integrations/deploy_preparation.checks.py#L181) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:309` | `check_service_generated_equality` | IT | [integrations/deploy_preparation.checks.py](integrations/deploy_preparation.checks.py#L250) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_document.checks.py:96` | `check_snapshot` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py#L93) | module / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_document.checks.py:145` | `check_links` | UT | [units/design_document-unit.checks.py](units/design_document-unit.checks.py#L171) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:149` | `check_secret_rotation_display` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L252) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:244` | `check_codebuild_variable_display` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L384) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:319` | `check_codebuild_vpc_display` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L461) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:406` | `check_subnet_list_links` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L562) | pytest / 16 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:458` | `check_guardduty_feature_display` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L604) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:487` | `check_cloudtrail_data_resources` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L634) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:592` | `check_codepipeline_display` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L748) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:704` | `check_config_firehose_references` | IT | [integrations/design_layout.checks.py](integrations/design_layout.checks.py#L22) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:838` | `check_resource_name_headings` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L858) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:934` | `check_quicksight_group_principal_reference` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L946) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:981` | `check_workflow` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L1004) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/framework-input-isolation.checks.py:23` | `check` | IT | [integrations/framework-input-isolation.checks.py](integrations/framework-input-isolation.checks.py#L43) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/human-inputs-group-05.checks.py:253` | `check_declared_inputs` | IT | [integrations/human-inputs-group-05.checks.py](integrations/human-inputs-group-05.checks.py#L31) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `import-agent-sources::check_cli_preflight` | `check_cli_preflight` | IT | [integrations/import-cli.checks.py](integrations/import-cli.checks.py#L35) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_logs_roundtrip` | `check_logs_roundtrip` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L103) | pytest / 1 | Acquire→Review→実保存・再読込・Markdown/Receipt、未選択CREATEと他サービス/環境保持、再取得なし | Append-only Import |
| `import-agent-sources::check_config_sources` | `check_config_sources` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L131) | pytest / 1 | Config除外Publishの正本不変とRoleARN表示接続 | Append-only Import |
| `import-agent-sources::check_vpc_eight_instances` | `check_vpc_eight_instances` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L147) | pytest / 1 | 8 Resourceの除外Publish・正本全体保持とDisposition接続 | Append-only Import |
| `import-agent-sources::check_managed_resource_addition` | `check_managed_resource_addition` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L161) | pytest / 1 | Subnet追加の実保存/再読込、VPC参照と既存Resource・他サービス/環境保持 | Append-only Import |
| `import-agent-sources::check_optional_profile` | `check_optional_profile` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L197) | pytest / 1 | profile未設定Projectから取得時にCLI引数を省略 | Append-only Import |
| `import-agent-sources::check_explicit_no_profile` | `check_explicit_no_profile` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L208) | pytest / 1 | 明示no-profileの取得から実保存まで | Append-only Import |
| `import-agent-sources::check_source_race` | `check_source_race` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L219) | pytest / 1 | 取得後の正本変更でPublish拒否、外部編集保持 | Append-only Import |
| `import-agent-sources::check_shared_property_and_bindings` | `check_shared_property_and_bindings` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L231) | pytest / 1 | 定義選択を切り替える追加Publishとstg正本・生成範囲の保持 | Append-only Import |
| `import-agent-sources::check_foreign_source_writes_rejected` | `check_foreign_source_writes_rejected` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L247) | pytest / 1 | stg候補を実Publishで保存前拒否、全ファイル不変 | Append-only Import |
| `import-agent-sources::check_repeat_without_reformat` | `check_repeat_without_reformat` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L263) | pytest / 1 | 保存済みTaskの再取得拒否と新Taskによる再Import・両Receipt保持 | Append-only Import |
| `import-agent-sources::check_empty_inventory_preserves_sources` | `check_empty_inventory_preserves_sources` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L288) | pytest / 1 | 空Inventory→Review→除外Publishで全正本不変 | Append-only Import |
| `import-agent-sources::check_consumer_set_race` | `check_consumer_set_race` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L301) | pytest / 1 | 取得後のconsumerファイル追加をPublishで検出、正本不変 | Append-only Import |
| `import-agent-sources::check_source_transaction_rollback` | `check_source_transaction_rollback` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L324) | pytest / 1 | 部分書込失敗の実Rollback・Receipt除去・同証跡から再Publish成功 | Append-only Import |
| `import-agent-sources::check_reflection_validation_boundary` | `check_reflection_validation_boundary` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L340) | pytest / 1 | 実Import保存でChange Validationを通し、全Model比較・Full Validation・AWS比較を起動しない | Append-only Import |
| `import-agent-sources::check_cross_process_evidence` | `check_cross_process_evidence` | IT | [integrations/import-cli.checks.py](integrations/import-cli.checks.py#L42) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_dry_run_cleanup` | `check_dry_run_cleanup` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L350) | pytest / 1 | Reviewとdry-run Publishのファイル不変・Task不要・証跡保持 | Append-only Import |
| `import-agent-sources::check_evidence_and_display_recovery` | `check_evidence_and_display_recovery` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L375) | pytest / 1 | 改ざん取得拒否・表示生成エラーの保存前拒否・表示保存失敗後のModel/Receipt保持、再取得/取得読込なしの実復旧 | Append-only Import |
| `integrations/issues_api_only.checks.py:27` | `main_checks` | IT | [integrations/issues_api_only.checks.py](integrations/issues_api_only.checks.py#L34) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/issues_failed_services.checks.py:21` | `main_checks` | IT | [integrations/issues_failed_services.checks.py](integrations/issues_failed_services.checks.py#L70) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_policy_equivalence.checks.py:21` | `main_checks` | IT | [integrations/issues_policy_equivalence.checks.py](integrations/issues_policy_equivalence.checks.py#L44) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/issues_ref_returns.checks.py:18` | `main_checks` | IT | [integrations/issues_ref_returns.checks.py](integrations/issues_ref_returns.checks.py#L25) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 変更不要 |
| `unknown/json-yaml-document-hash.checks.py:21` | `check` | IT | [integrations/model-document-sources.checks.py](integrations/model-document-sources.checks.py#L38) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/lambda-input-reference.checks.py:29` | `check` | IT | [integrations/lambda-input-reference.checks.py](integrations/lambda-input-reference.checks.py#L29) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/model-input-context-digest.checks.py:30` | `check` | IT | [integrations/model-input-context-digest.checks.py](integrations/model-input-context-digest.checks.py#L33) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model-test.checks.py:89` | `check` | IT | [integrations/model-test.checks.py](integrations/model-test.checks.py#L112) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_files.checks.py:38` | `check_resource_reading` | IT | [integrations/model_files.checks.py](integrations/model_files.checks.py#L66) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:115` | `check_precision` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L118) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:161` | `check_identity_and_deletion` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L152) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:180` | `check_shared_environments` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L176) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:195` | `check_identifiers` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L190) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:223` | `check_type_and_unknown` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L217) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:252` | `check_selection` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L232) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:268` | `check_cycles` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L248) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:105` | `check_human` | IT | [integrations/model_parameter_inputs.checks.py](integrations/model_parameter_inputs.checks.py#L39) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:294` | `check_declared_instance_inputs` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L336) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:353` | `check_kms_alias` | IT | [integrations/model_parameter_inputs.checks.py](integrations/model_parameter_inputs.checks.py#L69) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:413` | `check_external_instances` | IT | [integrations/model_parameter_inputs.checks.py](integrations/model_parameter_inputs.checks.py#L100) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:494` | `check_service_contracts` | IT | [integrations/model_parameter_inputs.checks.py](integrations/model_parameter_inputs.checks.py#L130) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:72` | `check_transactions` | IT | [integrations/model_templates.checks.py](integrations/model_templates.checks.py#L198) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:156` | `check_expansion` | IT | [integrations/model_templates.checks.py](integrations/model_templates.checks.py#L266) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:187` | `check_layout` | IT | [integrations/model_templates.checks.py](integrations/model_templates.checks.py#L303) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:231` | `check_reference_impact` | IT | [integrations/model_templates.checks.py](integrations/model_templates.checks.py#L339) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:361` | `check_template_snapshot` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L433) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:392` | `check_creation` | IT | [integrations/model_templates.checks.py](integrations/model_templates.checks.py#L394) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:409` | `check_explicit_row_inputs` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L683) | pytest / 11 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:434` | `check_sync` | IT | [integrations/model_templates.checks.py](integrations/model_templates.checks.py#L411) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:462` | `check_common_shape` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L639) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:47` | `check_iam` | IT | [integrations/policy_tables.checks.py](integrations/policy_tables.checks.py#L21) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:254` | `check_service_policy_checks` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L251) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:387` | `check_grouping_and_settings_checks` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L377) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/producer-identifier-reference.checks.py:31` | `check` | IT | [integrations/producer-identifier-reference.checks.py](integrations/producer-identifier-reference.checks.py#L39) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `producer-identifier-reference::reference-views` | `check_reference_views` | IT | [integrations/producer-identifier-reference.checks.py](integrations/producer-identifier-reference.checks.py#L128) | direct / 1 | 参照識別子の表示・生成・保存と正本保持 | 合成 fixture |
| `integrations/producer-name-reference.checks.py:29` | `check` | IT | [integrations/producer-name-reference.checks.py](integrations/producer-name-reference.checks.py#L33) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/raw-bucket-name-reference.checks.py:29` | `check` | IT | [integrations/raw-bucket-name-reference.checks.py](integrations/raw-bucket-name-reference.checks.py#L31) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/s3-bound-anchor.checks.py:37` | `check` | IT | [integrations/s3-bound-anchor.checks.py](integrations/s3-bound-anchor.checks.py#L37) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/security-group-input-reference.checks.py:29` | `check` | IT | [integrations/security-group-input-reference.checks.py](integrations/security-group-input-reference.checks.py#L29) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/sync-existing-files.checks.py:30` | `check_failure_safety` | IT | [integrations/sync-existing-files.checks.py](integrations/sync-existing-files.checks.py#L54) | direct / 1 | CLI/subprocessまたはGitとの連携 | 変更不要 |
| `unknown/task_contract.checks.py:155` | `check_admission_selection` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L372) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:204` | `check_completed_legacy_and_paths` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L293) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:241` | `check_shared_issue_files` | IT | [integrations/task_contract.checks.py](integrations/task_contract.checks.py#L94) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:325` | `check_suspend_and_resume` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L318) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:521` | `check_atomic_contract_reads` | IT | [integrations/task_contract.checks.py](integrations/task_contract.checks.py#L52) | pytest / 4 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/used-definition-inputs.checks.py:29` | `check` | IT | [integrations/used-definition-inputs.checks.py](integrations/used-definition-inputs.checks.py#L37) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/cloudformation.py:304` | `check_cloudformation_stack_design` | UT | [units/validation_checks/cloudformation.py](units/validation_checks/cloudformation.py#L325) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/cloudformation.py:373` | `check_stack_mapping_targets` | UT | [units/validation_checks/cloudformation.py](units/validation_checks/cloudformation.py#L394) | module / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:130` | `check_description_design_constraints` | UT | [units/validation_checks/design.py](units/validation_checks/design.py#L299) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:19` | `check_identifier_propagation` | UT | [units/validation_checks/references.py](units/validation_checks/references.py#L45) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:88` | `check_array_role_links` | UT | [units/validation_checks/references.py](units/validation_checks/references.py#L129) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:125` | `check_s3_bucket_policy_grouping` | UT | [units/validation_checks/references.py](units/validation_checks/references.py#L164) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:228` | `check_subnet_association_overview` | UT | [units/validation_checks/references.py](units/validation_checks/references.py#L267) | module / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:330` | `check_resource_overview` | UT | [units/validation_checks/references.py](units/validation_checks/references.py#L370) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:105` | `check_module_inputs` | IT | [integrations/validation_checks/runner.py](integrations/validation_checks/runner.py#L17) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `support/validation_checks/scenario.py:6` | `check_records` | UT | [units/validation_checks/scenario.py](units/validation_checks/scenario.py#L15) | module / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/scope.py:13` | `check_deployment_iac_scope` | IT | [integrations/validation_checks/scope.py](integrations/validation_checks/scope.py#L21) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:12` | `check_task_contract` | IT | [integrations/validation_checks/task.py](integrations/validation_checks/task.py#L23) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:68` | `check_idle_without_active_task` | IT | [integrations/validation_checks/task.py](integrations/validation_checks/task.py#L84) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:97` | `check_destroy_phase` | IT | [integrations/validation_checks/task.py](integrations/validation_checks/task.py#L120) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:143` | `check_task_type_dispatch` | IT | [integrations/validation_checks/task.py](integrations/validation_checks/task.py#L169) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:157` | `check_task_type_cases` | UT | [units/validation_checks/task.py](units/validation_checks/task.py#L194) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:191` | `check_cli` | IT | [integrations/validation_checks/terraform.py](integrations/validation_checks/terraform.py#L16) | direct / 1 | CLI/subprocessまたはGitとの連携 | 関数内抽出 |
| `unknown/validation_scope.checks.py:39` | `check_single_target_cache` | IT | [integrations/validation_scope.checks.py](integrations/validation_scope.checks.py#L64) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/validation_scope.checks.py:124` | `check_template_consumers` | IT | [integrations/validation_scope.checks.py](integrations/validation_scope.checks.py#L156) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_python.checks.py:54` | `check_setup` | IT | [integrations/worktree_python.checks.py](integrations/worktree_python.checks.py#L48) | direct / 1 | 初回install失敗の実Task/Branch/partial環境保持とsetup再実行の永続化 | 統合境界のみ |
| `unknown/worktree_python.checks.py:162` | `check_venv_fallback` | IT | [integrations/worktree_python.checks.py](integrations/worktree_python.checks.py#L65) | direct / 1 | 実venv初回生成・2 Task再利用、wrapper/CLI PATHとcleanup後の共有環境保持 | 統合境界のみ |
| `unknown/worktree_python.checks.py:236` | `check_parallel_fallback` | IT | [integrations/worktree_python.checks.py](integrations/worktree_python.checks.py#L96) | direct / 1 | 独立Python 2プロセスの実Lock競合確認・一度だけinstall・同一環境再利用 | 統合境界のみ |
| `unknown/worktree_python.checks.py:307` | `check_symlink_safety` | IT | [integrations/worktree_python.checks.py](integrations/worktree_python.checks.py#L162) | direct / 1 | 実共有環境Symlinkを拒否し外部ディレクトリの全contentsを保持 | 統合境界のみ |
| `unknown/worktree_task.checks.py:103` | `check_success_and_empty` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L146) | direct / 1 | 実CLIの通常変更とindex取消後の空変更、commit有無・cleanup | 統合境界のみ |
| `unknown/worktree_task.checks.py:132` | `check_finalize_line_endings` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L177) | direct / 1 | CRLFの実Git反映とstaged末尾空白拒否・Git設定保持（2条件） | 統合境界のみ |
| `unknown/worktree_task.checks.py:157` | `check_incomplete_and_git_safety` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L198) | direct / 1 | 実WorktreeのMERGE_HEAD検出とcommit前停止・checkout保持 | 統合境界のみ |
| `unknown/worktree_task.checks.py:204` | `check_dirty_base_and_retry` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L213) | direct / 1 | dirty Baseの実index保護と解消後の安全なRebase停止 | 統合境界のみ |
| `unknown/worktree_task.checks.py:225` | `check_ahead_and_rebase_conflict` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L236) | direct / 1 | 実Rebase競合・abort・reviewed recovery・Base再更新からの復旧 | 統合境界のみ |
| `unknown/worktree_task.checks.py:252` | `check_collisions_and_base_selection` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L302) | direct / 1 | 実Branch・Path・stale Worktree衝突時の既存データ保護 | 統合境界のみ |
| `unknown/worktree_task.checks.py:284` | `check_directory_layout` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L323) | direct / 1 | 実Git ignore契約違反時のCreate停止・Branch未作成 | 統合境界のみ |
| `unknown/worktree_task.checks.py:312` | `check_metadata_storage` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L334) | direct / 1 | 複数実Worktreeの状態分離・永続化・共通Lockとsibling保持 | 統合境界のみ |
| `unknown/worktree_task.checks.py:365` | `check_cleanup_failure_and_retry` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L380) | direct / 1 | Merge後cleanup失敗・安全な再試行・ignoredデータと他Task証跡保持 | 統合境界のみ |
| `unknown/worktree_task.checks.py:403` | `check_merge_retry_and_commit_failure` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L463) | direct / 1 | 実Merge失敗からの再試行とCommit改変拒否（2経路） | 統合境界のみ |
| `unknown/worktree_task.checks.py:454` | `check_human_approved_validation_failure` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L507) | direct / 1 | 承認付き実Merge・suspend/FAIL保持・承認永続化とcleanup再試行 | 統合境界のみ |
| `unknown/worktree_task.checks.py:493` | `check_real_loop_integration` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L530) | direct / 1 | 実Loop失敗からTask suspend永続化・finalize停止への接続 | 統合境界のみ |

| `integrations/check-model-aws.checks.py:644` | `check_domains` | IT | [integrations/check-model-aws.checks.py](integrations/check-model-aws.checks.py#L364) | pytest / 7 | 既存callbackを実行するパラメータ化入口。callbackと重複加算しない | 現在の入口 |

### IT 内部パターン

| ファイル / ケース | ループ地点・パターン数・入力 |
|---|---|
| `integrations/sync-model.checks.py::check_stage_definition_sources` | L99: 動的 ((design, artifact))<br>L100: 動的 ((definition_root(root) / 'framework').rglob('*'))<br>L112: 動的 (originals)<br>L123: 動的 (unrelated)<br>L130: 動的 (definitions)<br>L136: 動的 (range(4))<br>L162: 動的 (fields.items())<br>L174: 2 ((1, 4))<br>L179: 動的 (models)<br>L184: 動的 (zip(sources, models, strict=False))<br>L188: 動的 (generated.values())<br>L188: 動的 (files)<br>L198: 動的 (generated.values())<br>L198: 動的 (files)<br>L201: 動的 (models) |
| `integrations/sync-model.checks.py::check_stage_candidate_isolation` | L208: 動的 ((model, design, artifact))<br>L223: 動的 (errors)<br>L224: 動的 (errors)<br>L225: 動的 (validator.errors)<br>L227: 動的 (originals) |
| `integrations/sync-model.checks.py::check_stage_cloudformation_definitions` | L260: 2 (('iam', 'cloudformation-stacks'))<br>L273: 動的 (metadata.items())<br>L287: 動的 (validator.errors) |
| `integrations/sync-model.checks.py::check_publication_boundary` | L306: 動的 ((design, artifact))<br>L315: 動的 (originals) |
| `integrations/sync-model.checks.py::check_normal_writer_contents` | L341: 4 (('check_design_service_ownership', 'check_resource_names', 'check_observed_values', 'check_policy_tables'))<br>L346: 動的 (checks)<br>L356: 動的 (expand.call_args_list)<br>L358: 動的 (counters)<br>L358: 動的 (counters)<br>L361: 7 (('snapshot', 'dependency-model', 'stage-placement', 'candidate-generation', 'candidate-validation', 'publication', 'completed=1/1')) |
| `integrations/sync-model.checks.py::check_unchanged_sidecar` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_changed_sidecar_publication` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_publication_rechecks_excluded_outputs` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_changed_sidecar_publication_rollback` | L443: 動的 ((design, artifact)) |
| `integrations/sync-model.checks.py::check_unchanged_sidecar_validation` | L470: 動的 ((design, artifact))<br>L476: 動的 (before) |
| `integrations/sync-model.checks.py::check_incoming_reference_models` | L492: 2 (('s3', 'kms')) |
| `integrations/sync-model.checks.py::check_required_preflight` | L529: 動的 (values.items())<br>L537: 2 ((False, True)) |
| `integrations/sync-model.checks.py::check_required_property_parents` | L582: 動的 (enumerate((('ConnectionInput.Name', '`sample`'), ('Name', '[Connection](#glue-sample)'), ('CatalogId', '`123456789012`'), ('ConnectionInput.ConnectionType', '`JDBC`'), ('ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone', '`ap-northeast-1a`'), ('ConnectionInput.ValidateCredentials', '`true`')), 1))<br>L596: 動的 (values.items()) |
| `integrations/sync-model.checks.py::check_publication_lock_wait` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_two_consumer_cli` | L657: 3 ([('init', '-q'), ('add', '.'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline')])<br>L668: 2 (('dev', 'stg'))<br>L678: 動的 (outputs)<br>L681: 動的 (outputs)<br>L688: 動的 ((outputs[0], outputs[2])) |
| `integrations/sync-model.checks.py::check_internal_sync_isolation` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_internal_sync_real_diagnostics` | L772: 2 (('dev', 'stg'))<br>L773: 動的 (sorted(scope))<br>L773: 動的 (('--scope', '/'.join(entry)))<br>L786: 動的 (validator.errors) |
| `integrations/sync-model.checks.py::check_integrated_validator` | L826: 3 (('AGENTS.md', 'README.md', 'docs/system-overview.md'))<br>L830: 3 (('infra/cloudformation/parameters/dev/123456789012', 'tests/scenarios', 'tests/results'))<br>L836: 動的 ((design, artifact))<br>L842: 動的 (load_model(model).files)<br>L866: 動的 (expand.call_args_list)<br>L873: 動的 (source_bytes) |
| `integrations/sync-model.checks.py::check_integrated_validator_publication_failure` | L882: 動的 ((design, artifact))<br>L887: 3 (('AGENTS.md', 'README.md', 'docs/system-overview.md'))<br>L891: 3 (('infra/cloudformation/parameters/dev/123456789012', 'tests/scenarios', 'tests/results'))<br>L894: 3 ([('init', '-q'), ('add', '.'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Fixture')])<br>L904: 動的 (originals)<br>L905: 動的 (failed.errors)<br>L906: 動的 (failed.acceptance_results) |
| `integrations/sync-model.checks.py::check_multiple_targets_barrier` | 1（内部パラメータ化なし） |
| `integrations/attribute-reference-resolution.checks.py::check_pair` | 1（内部パラメータ化なし） |
| `integrations/attribute-reference-resolution.checks.py::check_fixed_label` | L?: 動的 (root.rglob('*'))<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (content.splitlines()) |
| `integrations/attribute-reference-resolution.checks.py::check_stack` | 1（内部パラメータ化なし） |
| `integrations/attribute-reference-resolution.checks.py::check_preparation_cache` | L249: 2 ([('first', '001'), ('second', '002')])<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (values.items()) |
| `integrations/attribute-reference-resolution.checks.py::check` | L292: 2 ([('s3', 'cloudtrail'), ('lambda', 'eventbridge')]) |
| `integrations/auxiliary-model-dependencies.checks.py::check` | 1（内部パラメータ化なし） |
| `integrations/aws_mapping.checks.py::check_config` | L38: 動的 (['framework/mappings/aws/config.yaml', 'framework/mappings/aws/owners.json', schema + 'index.json', *[schema + index['AWS::' + kind.replace('.', '::')] for kind in (RECORDER, CHANNEL)], *['framework/materials/aws/' + kind.replace('.', '_') + '.properties' for kind in (RECORDER, CHANNEL)]])<br>L39: 動的 ((RECORDER, CHANNEL))<br>L40: 動的 ((RECORDER, CHANNEL))<br>L52: 動的 ([('001', RECORDER, recorder), ('002', CHANNEL, channel)])<br>L54: 動的 ({'resourceType': kind, 'resourceMode': 'IMPORT', 'logicalId': kind.replace('.', '_') + '_001'}.items())<br>L56: 動的 (enumerate(BASELINE[kind].items(), 1))<br>L67: 動的 ({'property': kind + '.' + prop, 'value': raw, 'comment': 'fixture'}.items())<br>L90: 動的 (m.compare_resource(ctx, resource))<br>L90: 動的 (model.resources)<br>L91: 動的 (model.resources)<br>L92: 動的 (range(2))<br>L94: 動的 (calls)<br>L98: 動的 (match)<br>L99: 動的 (match)<br>L100: 動的 (difference)<br>L103: 動的 ([(RECORDER, 'recorder', recorder), (CHANNEL, 'channel', channel)])<br>L107: 動的 (normalized)<br>L110: 動的 (normalized)<br>L110: 動的 (record['properties'].values())<br>L113: 動的 (model.resources)<br>L126: 動的 ((RECORDER, CHANNEL)) |
| `integrations/aws_mapping_compare.checks.py::mapping_checks` | L24: 動的 (cases)<br>L56: 2 (({'projects': [{}]}, {'projects': [{'webhook': None}]})) |
| `integrations/aws_mapping_display.checks.py::check` | 1（内部パラメータ化なし） |
| `integrations/bound-anchor-name-change.checks.py::check` | L109: 3 ((root / 'model/preview/team/vpc.properties', build_path, kms_path))<br>L?: 2 (('model', 'docs/designs'))<br>L?: 動的 ((root / base).rglob('*'))<br>L?: 動的 (before)<br>L?: 3 (('model', 'model/parameters', 'docs/designs'))<br>L?: 動的 ((root / base).rglob('*'))<br>L?: 動的 (saved.items())<br>L?: 動的 (saved.items())<br>L?: 4 (('definition', 'resources', 'rows', 'labels'))<br>L?: 動的 (entries(after, 'desired.resource.')) |
| `integrations/bound-stack-name-change.checks.py::check` | L50: 2 ([('017', 'network', 'Network'), ('083', 'empty', 'Empty')])<br>L86: 3 (('-changed', '', '-second'))<br>L120: 4 ([('999', 'cfn-stack-app-preview-unknown', 'exactly'), ('017', 'bad_name', 'invalid fixed stack'), ('083', fixed, 'conflicting'), ('017', None, 'invalid fixed stack')])<br>L?: 動的 (vpc.items())<br>L?: 動的 (load_model(vpc_path).files)<br>L?: 4 ((directory / 'parameters.yaml', directory / 'bindings.json', root / 'docs/designs/preview/team/cloudformation-stacks.md', root / 'docs/designs/preview/team/vpc.md'))<br>L?: 動的 (bindings['instances'].items())<br>L?: 動的 (baseline.items())<br>L?: 動的 (vpc_bytes.items())<br>L?: 動的 (item.items())<br>L?: 2 ([('other', '210987654321'), ('team', '123456789012')]) |
| `integrations/check-model-aws.checks.py::cli_checks` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::batch_checks` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::common_checks` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::association_checks` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::stack_checks` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::cfn_identity_checks` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::fixture_coverage` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `integrations/check-model-aws.checks.py::check_consumer_coverage` | Issue #20: 以下の責務対応表参照。細分条件はUTへ移管 |
| `units/deploy-runtime-unit.checks.py::check_sdk_execution` | L19: 動的 (scoped)<br>L24: 動的 (backend.calls)<br>L29: 動的 (backend.calls)<br>L46: 動的 (enumerate(backend.calls))<br>L47: 動的 (enumerate(backend.calls))<br>L48: 2 (((['NetworkVpcId'], 'COMPLETE'), ([], 'STOPPED')))<br>L55: 動的 (backend.calls)<br>L64: 動的 (backend.calls)<br>L70: 動的 (state.values())<br>L71: 動的 (backend.calls)<br>L83: 動的 (backend.calls)<br>L89: 動的 (backend.calls)<br>L95: 2 (('True', 'Conditional')) |
| `units/deploy-runtime-unit.checks.py::check_empty_rollback_recreation` | L127: 動的 (self.current)<br>L159: 2 (('A', 'B'))<br>L160: 動的 (enumerate(backend.calls))<br>L161: 動的 (enumerate(backend.calls))<br>L168: 2 (('A', 'B'))<br>L174: 動的 (items)<br>L179: 動的 (saved.values())<br>L185: 2 (([], [{'ResourceStatus': 'DELETE_COMPLETE'}]))<br>L190: 5 (('CREATE_COMPLETE', 'DELETE_SKIPPED', 'CREATE_FAILED', 'DELETE_FAILED', None))<br>L195: 3 (({'EnableTerminationProtection': True}, {'ParentId': 'parent'}, {'StackId': 'other'}))<br>L210: 3 (('DELETE_IN_PROGRESS', 'DELETE_COMPLETE', None)) |
| `units/deploy-runtime-unit.checks.py::check_template_validation` | 1（内部パラメータ化なし） |
| `integrations/cloudformation-deploy.checks.py::check_inputs` | L257: 動的 (enumerate(units(20, 10, 10), 1))<br>L258: 動的 (unit.items())<br>L260: 6 ((('desired.deployment.maxConcurrentStacks', '0'), ('desired.deployment.maxConcurrentStacks', '-1'), ('desired.deployment.maxConcurrentStacks', 'abc'), ('desired.stack.001.deployOrder', '0'), ('desired.stack.001.deployOrder', '-1'), ('desired.stack.001.deployOrder', 'abc')))<br>L270: 4 (('dependsOn', 'AfterStack', 'DependsOnStack', 'Dependencies'))<br>L280: 動的 (values.items())<br>L282: 動的 (scoped)<br>L327: 2 ((None, 'configured')) |
| `units/deploy-runtime-unit.checks.py::check_delivery` | L368: 動的 (((51200, '--template-body'), (51201, '--template-url'), (1024 * 1024, '--template-url')))<br>L373: 動的 (backend.calls)<br>L374: 動的 (backend.calls)<br>L379: 動的 (backend.calls)<br>L381: 動的 (backend.calls)<br>L389: 動的 (backend.calls)<br>L400: 3 ((('First', 'app-dev-assets'), ('Second', 'app-dev-assets'), ('Third', 'app-dev-other')))<br>L411: 3 (('First', 'Second', 'Third'))<br>L414: 動的 (backend.calls)<br>L415: 動的 (backend.calls)<br>L418: 動的 (enumerate(backend.calls))<br>L422: 動的 (resumed.calls)<br>L439: 2 (({'bucket': 'wrong-bucket'}, {'keyPrefix': 'wrong/'}))<br>L443: 動的 (resumed.calls)<br>L450: 動的 (fresh.calls)<br>L483: 動的 (unit.items())<br>L487: 動的 (artifact('First').items())<br>L501: 動的 (values.items())<br>L503: 動的 (deployment_settings(values)[1])<br>L503: 動的 (files)<br>L510: 動的 (values.items())<br>L518: 4 ((('source', '../secret'), ('keyPrefix', '../'), ('stack', 'unknown'), ('property', 'Other')))<br>L520: 動的 (values.items())<br>L529: 動的 (values.items())<br>L536: 動的 (stack_delivery(design).items())<br>L537: 動的 (values.items())<br>L542: 動的 (stack_delivery(design).items())<br>L547: 動的 (values.items())<br>L562: 動的 (entries(approved, 'desired.resource.'))<br>L566: 動的 (entries(approved, 'desired.row.'))<br>L584: 動的 (backend.calls)<br>L591: 動的 (zip(scoped, (20, 51201)))<br>L597: 動的 (scoped)<br>L613: 動的 (bootstrap.calls)<br>L615: 動的 (bootstrap.calls) |
| `units/deploy-runtime-unit.checks.py::check_delivery_encryption` | L641: 動的 (backend.calls)<br>L645: 動的 (backend.calls)<br>L646: 動的 (backend.session['placementPreflight'].values())<br>L655: 動的 (backend.calls)<br>L668: 2 (('[KMS_Key_001](kms.md#kms-app-dev-key)', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)'))<br>L688: 2 ((('AES256', None), ('aws:kms', 'test-key')))<br>L693: 動的 (backend.calls)<br>L701: 動的 (backend.calls)<br>L711: 動的 (({'Principal': {'AWS': TARGET['awsAccountId']}}, {'NotResource': '*'}))<br>L742: 動的 (((lambda b: setattr(b, 'default_algorithm', 'aws:kms'), 'MISMATCH'), (lambda b: setattr(b, 'region', 'us-east-1'), 'MISMATCH')))<br>L747: 動的 (backend.calls)<br>L748: 5 (('head-bucket', 'get-bucket-location', 'get-bucket-encryption', 'get-bucket-policy', 'describe-key'))<br>L759: 動的 (backend.calls)<br>L784: 動的 (resumed.calls)<br>L800: 動的 (scoped)<br>L812: 動的 (enumerate(backend.calls))<br>L814: 動的 (enumerate(backend.calls))<br>L830: 動的 (backend.calls)<br>L836: 動的 (backend.calls) |
| `units/deploy-runtime-unit.checks.py::check_session_cli` | L856: 動的 (enumerate(units(10, 20), 1))<br>L857: 動的 (unit.items())<br>L861: 動的 (values.items())<br>L870: 2 (('a', 'b'))<br>L931: 動的 (run.call_args_list)<br>L938: 動的 ((base / 'timing.jsonl').read_text().splitlines())<br>L939: 動的 (timing)<br>L948: 動的 (stopped['states'].values())<br>L949: 動的 (errors.items())<br>L957: 動的 (session['states'].values())<br>L963: 動的 (backends[-1].calls)<br>L978: 動的 (backends[-1].deployment_input_paths(units(10, 20)))<br>L989: 動的 (((params / 'a.json', '[{"ParameterKey":"Name","ParameterValue":"changed"}]'), (template, 'Resources: {}\\n# shared dev/stg template changed\\n'), (source, read_model(source) + 'display.deployment.comment=changed\\n'), (consumer, read_model(consumer) + 'desired.row.002.value=changed\\n'), (reference, 'desired.row.001.value=changed\\n'), (contract, contract.read_text() + '\\n# contract changed\\n'), (root / 'framework/scripts/check-deploy-context.py', '# controller dependency changed\\n')))<br>L1007: 4 ((('awsAccountId', '999999999999'), ('awsRegion', 'us-east-1'), ('awsProfile', 'other-profile'), ('iacEngine', 'terraform')))<br>L1026: 動的 (artifact.items())<br>L1027: 動的 (with_artifact.items())<br>L1037: 動的 (saved_source.items())<br>L1052: 動的 ((((10,), 1), ((10,) * 4, 4), ((10,) * 4 + (20,) * 4, 4)))<br>L1055: 動的 (enumerate(selected, 1))<br>L1056: 動的 (unit.items())<br>L1059: 動的 (values.items())<br>L1061: 動的 (contract.read_text().splitlines())<br>L1062: 動的 (selected)<br>L1065: 動的 (selected)<br>L1072: 動的 (session['states'].values())<br>L1073: 動的 (backends[-1].calls)<br>L1079: 5 (('version', 'validationStatus', 'validationDigest', 'validationTemplates', 'validationTemplatesDigest'))<br>L1121: 動的 (selected[:4]) |
| `units/deploy-runtime-unit.checks.py::check_parallel_and_restart` | L1139: 動的 (scoped[2:])<br>L1151: 動的 (selected)<br>L1152: 動的 (selected)<br>L1159: 動的 (scoped)<br>L1160: 動的 (enumerate(backend.events))<br>L1161: 動的 (backend.events[:first_poll])<br>L1166: 動的 (selected)<br>L1171: 動的 (backend.calls)<br>L1186: 動的 (backend.calls) |
| `integrations/cloudformation-deploy.checks.py::check_observed_collector` | L1298: 動的 (values.items())<br>L1345: 動的 (observed.items())<br>L1345: 動的 (values.items())<br>L1360: 動的 (range(1, 621))<br>L1367: 動的 ([template, *parts])<br>L1372: 動的 (before_parts.items())<br>L1377: 動的 (part_document.values.items())<br>L1379: 動的 (changes) |
| `integrations/cloudformation-deploy.checks.py::check_shared_stack_mapping` | L1410: 動的 (enumerate(('ism', 'ced', 'sd'), 1))<br>L1417: 動的 (unit.items())<br>L1423: 動的 (enumerate((('Name', '`' + name + '`'), ('VpcId', f"[{identity}](#{values[f'desired.resource.{identity}.anchor']})"), ('CidrBlock', f'`10.{index}.0.0/16`')), 1))<br>L1446: 動的 (scoped)<br>L1449: 動的 (enumerate(scoped, 1))<br>L1457: 動的 (scoped)<br>L1481: 動的 (scoped)<br>L1482: 動的 (((mappings, (root, 'dev', '123456789012', backend.templates, scoped), 6, 5), (preflight, (root, 'dev', '123456789012', [u['name'] for u in scoped]), 7, 5)))<br>L1484: 動的 (scoped)<br>L1531: 動的 ((scoped[0]['name'], 'missing'))<br>L1533: 動的 (((preflight.__wrapped__, mappings.__wrapped__), (preflight, mappings)))<br>L1557: 動的 (enumerate(scoped, 1))<br>L1559: 動的 (actual.items())<br>L1573: 動的 (scoped)<br>L1585: 3 (({'Ref': 'Unknown'}, {'Condition': 'Active'}, 'yes'))<br>L1588: 動的 (scoped)<br>L1598: 動的 (enumerate(('AllocationId', 'PublicIp'), 1)) |
| `integrations/cloudformation-deploy.checks.py::check_import_implementation_mapping` | L1656: 動的 (unit.items())<br>L1659: 2 ((('001', 'EC2.VPC'), ('002', 'EC2.Subnet')))<br>L1660: 動的 ((('resourceType', kind), ('resourceMode', 'IMPORT'), ('logicalId', kind.replace('.', '_') + '_001')))<br>L1689: 4 ((('Vpc', {'Type': 'AWS::EC2::VPC', 'Condition': 'Unknown'}, 'Condition'), ('Association', {'Type': 'AWS::EC2::SubnetRouteTableAssociation', 'Properties': {'SubnetId': {'Ref': 'Vpc'}}}, 'formal CFn type mismatch'), ('Unknown', {'Type': 'AWS::S3::Bucket'}, 'explicit mapping required'), ('Repository', {'Type': 'AWS::S3::Bucket'}, 'formal CFn type mismatch'))) |
| `integrations/cloudformation-deploy.checks.py::check_integrated_child_mapping` | L1720: 2 ((('S3.BucketPolicy', 'S3.Bucket', 'Bucket', 'PolicyDocument', 11), ('EC2.SubnetRouteTableAssociation', 'EC2.Subnet', 'SubnetId', 'RouteTableId', 5)))<br>L1725: 動的 (range(1, count + 1))<br>L1745: 動的 (values.items())<br>L1750: 動的 (unit.items())<br>L1757: 動的 (child_ids)<br>L1788: 動的 (model.rglob('*.properties'))<br>L1790: 動的 ([*child_ids, 'Repository'])<br>L1794: 動的 (children)<br>L1799: 動的 (children)<br>L1801: 動的 (before) |
| `integrations/cloudformation-deploy.checks.py::check_secretsmanager_arn_identifiers` | L1819: 2 ((('001', 'Secret1'), ('002', 'Secret1Rotation')))<br>L1821: 動的 ({'property': 'SecretsManager.Secret.KmsKeyId', 'value': '[KMS_Key_001](kms.md#kms-app-dev-key)', 'comment': 'secretの暗号化鍵'}.items())<br>L1829: 動的 (enumerate(selected, 1))<br>L1830: 動的 (unit.items())<br>L1831: 動的 (((model / 'secretsmanager.properties', secrets), (model / 'kms.properties', key), (model / 'cloudformation-stacks.properties', stacks)))<br>L1850: 動的 (document['Resources'].items())<br>L1857: 2 ((False, True))<br>L1861: 2 (('SecretArn', 'RotationArn'))<br>L1865: 動的 (saved.values())<br>L1869: 動的 (current.values())<br>L1872: 動的 ((model, root / 'docs/designs'))<br>L1872: 動的 (parent.rglob('*'))<br>L1874: 動的 (model.rglob('*.properties'))<br>L1885: 動的 (before)<br>L1891: 7 (('root', 'environment', 'directory', 'target', 'templates', 'mapping_plan', 'aws')) |
| `units/deploy-runtime-unit.checks.py::check_api_timing` | L1911: 動的 (path.read_text().splitlines())<br>L1912: 動的 (events)<br>L1913: 動的 (events) |
| `units/deploy-runtime-unit.checks.py::check_controlled_repair` | Original failure safety/provenance, retained/custom Resource and empty-shell rules; authoritative source bytes unchanged; legacy candidates never applied |
| `units/deploy-runtime-unit.checks.py::check_secret_runtime_bootstrap` | L2329: 4 ([('SecretOwner', 1), ('A', 2), ('B', 2), ('C', 3)])<br>L2338: 動的 (enumerate(selected, 1))<br>L2338: 動的 (unit.items())<br>L2339: 2 ([('secretsmanager', 'SecretsManager.Secret', 'SecretOwner', 'Secret'), ('quicksight', 'QuickSight.DataSource', 'B', 'Consumer')])<br>L2345: 動的 (selected)<br>L2363: 動的 (enumerate(active, 1))<br>L2363: 動的 (u.items())<br>L2371: 動的 (docs.items())<br>L2372: 動的 (active)<br>L2377: 動的 (active)<br>L2381: 動的 (active)<br>L2399: 動的 ((root / 'infra', modeldir))<br>L2399: 動的 (parent.rglob('*'))<br>L2401: 動的 (before.items())<br>L2410: 動的 (versions.items())<br>L2416: 動的 (versions.items())<br>L2421: 動的 (versions.items())<br>L2447: 動的 (versions.values())<br>L2499: 動的 (items)<br>L2518: 動的 (f.calls)<br>L2528: 動的 (f.before.items())<br>L2534: 動的 (f.calls)<br>L2536: 12 (('current', 'denied', 'kms', 'absent', 'import', 'crossAccount', 'crossRegion', 'unknownOwner', 'unknownVersions', 'invalidResponse', 'rotation', 'listDenied'))<br>L2552: 動的 (f.calls)<br>L2554: 7 (('opaque', 'mixed', 'pinned', 'multiple', 'unresolved', 'badExport', 'inactive'))<br>L2572: 2 ((True, False))<br>L2576: 2 ((('Username', 'username'), ('Password', 'password')))<br>L2590: 動的 (pair.values())<br>L2606: 6 (('BOOTSTRAP_INTENT', 'VALUE_CHECKED_MISSING', 'PUT_SUBMITTED', 'afterPut', 'BOOTSTRAP_CONFIRMED', 'RETRY_READY'))<br>L2639: 動的 (f.calls)<br>L2641: 動的 (f.calls)<br>L2644: 動的 (f.calls)<br>L2645: 2 (('race', 'promotionRace'))<br>L2653: 動的 (f.versions.values())<br>L2664: 4 (('denied', 'missing', 'timeout', 'invalid')) |
| `integrations/cloudformation-destroy.checks.py::check_order_and_safety` | L158: 2 (({'A': 20, 'B': 10}, {'A': 20, 'B': 20}))<br>L170: 2 (('list-exports', 'list-imports'))<br>L202: 動的 (({'StackId': stack_id('Other')}, {'StackName': 'Other'}, {'StackId': stack_id('A').replace('123456789012', '999999999999')}, {'StackId': stack_id('A').replace('ap-northeast-1', 'us-east-1')}))<br>L?: 2 (('C', 'D'))<br>L?: 動的 (fake.calls)<br>L?: 動的 (fake.calls) |
| `integrations/cloudformation-destroy.checks.py::check_unused_export` | L222: 動的 ((diagnostic.replace('ValidationError', 'AccessDenied'), diagnostic.replace('is not imported by any stack', 'does not exist'), 'An error occurred (ValidationError) when calling the ListImports operation: Invalid export name')) |
| `integrations/cloudformation-destroy.checks.py::check_absence` | L246: 動的 (({}, {'StackId': stack_id('A'), 'status': 'DELETE_INTENT'})) |
| `integrations/cloudformation-destroy.checks.py::check_controller` | L408: 2 (('task', 'issue'))<br>L?: 動的 (fake.calls)<br>L?: 動的 (fake.calls)<br>L?: 4 (('validate-template', 'create-change-set', 'execute-change-set', 'get-template'))<br>L?: 動的 (fake.calls) |
| `integrations/cloudformation-destroy.checks.py::check_observed` | L435: 動的 (list(values.items()))<br>L475: 2 (('A', 'B'))<br>L?: 動的 (plan['observed']['owners'].values())<br>L?: 動的 (owners)<br>L?: 動的 (plan['observed']['updates'].values())<br>L?: 動的 (changes.values())<br>L?: 動的 (updates)<br>L?: 動的 (before.items())<br>L?: 動的 (after.items())<br>L?: 動的 (pending['observed']['unmappedResources'])<br>L?: 2 (('A', 'B'))<br>L?: 動的 (values.items()) |
| `integrations/cloudformation-naming.checks.py::check_imports` | L81: 動的 (collection.items())<br>L69: 動的 (producer['Outputs'].items())<br>L82: 動的 (walk(consumer))<br>L?: 動的 (collection.items())<br>L?: 動的 (producer['Outputs'].items())<br>L90: 4 (('omitted', 'empty', 'configured', 'alternate'))<br>L?: 動的 (exports) |
| `integrations/cloudformation-naming.checks.py::check_names` | L107: 動的 (collection.items())<br>L108: 動的 (doc.get('Resources', {}).values())<br>L?: 動的 (entries(iam, 'desired.row.'))<br>L118: 3 (('omitted', 'empty', 'alternate'))<br>L110: 動的 (walk(resource)) |
| `integrations/cloudformation-naming.checks.py::check_flow_logs` | L129: 2 (('', '/example'))<br>L?: 動的 (collection.items()) |
| `integrations/cloudformation-naming.checks.py::check` | 1（内部パラメータ化なし） |
| `integrations/cloudformation-naming.checks.py::check_fixtures` | L185: 動的 (paths)<br>L?: 動的 (model_paths(ROOT)) |
| `integrations/cloudtrail-input-reference.checks.py::check` | L68: 2 ([original + '# annotation\n', original.replace('audit-preview', 'audit-next')])<br>L72: 5 ([(original.replace('resourceType=CloudTrail.Trail', 'resourceType=S3.Bucket'), 'type-mismatched'), (original.replace('017', '018'), 'type-mismatched'), (original.replace('CloudTrail.Trail.TrailName', 'CloudTrail.Trail.Description'), 'exactly one name'), (original.replace('`audit-preview`', '``'), 'exactly one name'), (original + 'desired.row.017-004.property=CloudTrail.Trail.TrailName\ndesired.row.017-004.value=`duplicate`\n', 'exactly one name')])<br>L?: 動的 (values.items()) |
| `integrations/deploy_preparation.checks.py::check_preparation` | L21: 動的 (root.rglob('*'))<br>L28: 動的 (root.rglob('*'))<br>L36: 動的 (model_parts(root / 'model/dev/123456789012/ec2.properties'))<br>L39: 動的 (declared)<br>L40: 動的 (declared)<br>L46: 動的 (plan['documents'])<br>L47: 動的 (document['chunks'])<br>L48: 動的 (plan['documents'])<br>L50: 4 (('ec2.md', 'iam.md', 'cloudformation-stacks.md', 'iam/worker-role-trust-policy.json'))<br>L54: 動的 (plan['inputs'].items())<br>L56: 動的 ((run / 'documents').iterdir())<br>L56: 動的 (d['chunks'])<br>L56: 動的 (plan['documents'])<br>L59: 動的 (source_inputs(entrance))<br>L61: 動的 (iam['chunks'])<br>L62: 2 ((1, 2))<br>L64: 動的 (STACKS)<br>L66: 動的 (model_rules['chunks'])<br>L83: 動的 ((run / 'timing.jsonl').read_text().splitlines())<br>L84: 動的 (events)<br>L85: 動的 (events)<br>L86: 動的 (events) |
| `integrations/deploy_preparation.checks.py::check_stale_and_conflicts` | L95: 8 (('issue', 'runtime', 'candidate', 'model', 'markdown-change', 'markdown-delete', 'json-change', 'json-delete')) |
| `integrations/deploy_preparation.checks.py::check_generated_boundaries` | L135: 動的 (original.splitlines())<br>L139: 4 (('authoritative JSON document missing', 'resource 001', 'row 001-002', 'iam/worker-role-trust-policy.json'))<br>L172: 動的 (plan['documents'])<br>L177: 動的 (plan['inputs'].items()) |
| `integrations/deploy_preparation.checks.py::check_service_generated_equality` | L223: 2 (('iam.md', 'iam/iam-role-001-trust-policy.json')) |
| `integrations/design_document.checks.py::check_snapshot` | L55: 2 (('CREATE', 'IMPORT'))<br>L?: 動的 (reads.call_args_list) |
| `integrations/design_document.checks.py::check_links` | L90: 動的 (cases)<br>L107: 3 ([(alias_text, []), (alias_text.replace(observed, 'different'), ['different']), (alias_text.replace(f'[{observed}](kms.md#kms-aliastwo)', f'[{observed}](kms.md#kms-aliasthree)'), [observed])])<br>L?: 80 (range(80))<br>L?: 動的 (zip(expected, validator.errors))<br>L?: 動的 (reads.call_args_list) |
| `integrations/design_layout.checks.py::check_secret_rotation_display` | L118: 動的 (values.items())<br>L132: 動的 (((text.replace('### SecretsManager.Secret: app-dev-key', '### SecretsManager.RotationSchedule: app-dev-key'), 'independent heading'), (text.replace('### SecretsManager.Secret: app-dev-key', '### S3.Bucket: app-dev-key'), 'wrong parent'), (text.replace('[app-dev-key](#secretsmanager-app-dev-key)', '[app-dev-token](#secretsmanager-app-dev-token)'), 'must reference enclosing'), (text.replace('RotationRules.AutomaticallyAfterDays', 'RotateImmediatelyOnUpdate'), 'duplicate property'), (text.replace('`30`', '`invalid`'), 'provider schema violation'), (text.replace('### SecretsManager.Secret\\n', '### SecretsManager.RotationSchedule\\n'), 'resource overview types')))<br>L141: 動的 (failures) |
| `integrations/design_layout.checks.py::check_codebuild_variable_display` | L181: 動的 (errors(short.replace('\| 2 \| Id \|', '\| 2 \| CodeBuild.Project.Id \|')))<br>L186: 動的 ((codebuild.replace('`hello:world`', '`PLAINTEXT:cde`'), codebuild.replace('<!-- codebuild-variable-type: SECRETS_MANAGER --> ', ''), codebuild.replace('SECRETS_MANAGER -->', 'UNKNOWN -->'), codebuild.replace('SECRETS_MANAGER -->', 'PARAMETER_STORE -->'), codebuild.replace(secret_link, '`venus-dev-snowflake-cicd-keypair-cde`'), codebuild.replace(secret_link, f'`{secret_link}`'), codebuild.replace(secret_link, '[secret](secretsmanager.md)'), codebuild.replace('#secretsmanager-snowflakekey', '#missing'), codebuild.replace('(secretsmanager.md#', '(missing.md#'), codebuild.replace('[venus-dev-snowflake-cicd-keypair-cde]', '[wrong-name]'))) |
| `integrations/design_layout.checks.py::check_codebuild_vpc_display` | L287: 動的 ((design_text.replace('Subnets[1]', 'Subnets[0]'), design_text.replace('Subnets[2]', 'Subnets[3]'), design_text.replace('Subnets[2]', 'Subnets[1]'), design_text.replace('SecurityGroupIds[1]', 'SecurityGroupIds[2]'), design_text.replace('VpcConfig.Subnets[1]', 'VpcConfig.Subnets'), design_text.replace('[subnet-00000000000000001](vpc.md#vpc-sbnt-one)', '`[subnet-00000000000000001](vpc.md#vpc-sbnt-one)`'), design_text.replace('[subnet-00000000000000001](vpc.md#vpc-sbnt-one)', '`["[subnet-00000000000000001](vpc.md#vpc-sbnt-one)"]`'), design_text.replace('[subnet-00000000000000001](vpc.md#vpc-sbnt-one)', '[PENDING_DEPLOY](security-group.md#security-group-codebuild-sg)'))) |
| `integrations/design_layout.checks.py::check_subnet_list_links` | 1（内部パラメータ化なし） |
| `integrations/design_layout.checks.py::check_guardduty_feature_display` | 1（内部パラメータ化なし） |
| `integrations/design_layout.checks.py::check_cloudtrail_data_resources` | L456: 5 (('All current and future S3 buckets', '`All current and future S3 bucket`', '`arn:aws:s3`', '`["arn:aws:s3"]`', '`[data-bucket](s3.md#s3-data-bucket)`'))<br>L468: 動的 ((trail.replace('DataResources[1]', 'DataResources[0]'), trail.replace('DataResources[2]', 'DataResources[3]'), trail.replace('DataResources[2]', 'DataResources[1]'), trail.replace('DataResources[1].S3', 'DataResources[1].Object'), trail.replace('[data-bucket](s3.md#s3-data-bucket) \| S3 object', '`data-bucket` \| S3 object'), trail.replace('DataResources[1].S3', 'EventSelectors[].DataResources[].Type'), trail.replace('[data-bucket](s3.md#s3-data-bucket) \| S3 object', '[function-one](lambda.md#lambda-function-one) \| S3 object'))) |
| `integrations/design_layout.checks.py::check_codepipeline_display` | L487: 動的 (enumerate(rows, 1))<br>L542: 動的 ((pipeline.replace('Stages[1]', 'Stages[]'), pipeline.replace('Stages[1]', 'Stages[0]'), pipeline.replace('Stages[2]', 'Stages[3]'), pipeline.replace('Stages[2]', 'Stages[1]'), pipeline.replace('Stages[1].Actions.', 'Stages[1].Actions[1].'), pipeline.replace('Stages[1].Actions.', 'Stages[1].Actions[].'), pipeline.replace('Actions[2]', 'Actions[3]'), pipeline.replace('Actions[2]', 'Actions[1]'), pipeline.replace('Actions[1]', 'Actions'), pipeline.replace('Configuration.BranchName', 'Configuration'), pipeline.replace('Configuration.PollForSourceChanges', 'Configuration.BranchName'), pipeline.replace('`dev`', '`{"Fn::ImportValue":"branch-export"}`'), pipeline.replace('`dev`', '`!ImportValue branch-export`'), pipeline.replace('[build](codebuild.md#codebuild-build)', '`{"Fn::ImportValue":"CdeDevApplicationBuildProjectName"}`'), pipeline.replace('[build](codebuild.md#codebuild-build)', '`build`'), pipeline.replace('[build](codebuild.md#codebuild-build)', '[repo](codecommit.md#codecommit-repo)'), pipeline.replace('[build](codebuild.md#codebuild-build)', '[wrong](codebuild.md#codebuild-build)'), pipeline.replace('[build](codebuild.md#codebuild-build)', '[build](codebuild.md#codebuild-missing)'), pipeline.replace('[build](codebuild.md#codebuild-build)', '`[build](codebuild.md#codebuild-build)`'), pipeline.replace('[repo](codecommit.md#codecommit-repo)', '[wrong](codecommit.md#codecommit-repo)')))<br>L565: 2 ((('Stages[1].Name', '`DuplicateStage`'), ('Stages[2].Actions[2].Name', '`DuplicateAction`'))) |
| `integrations/design_layout.checks.py::check_config_firehose_references` | L594: 動的 (enumerate(rows, 1))<br>L641: 動的 ((config.replace('RoleName \|', 'RoleARN \|'), config.replace(role_link, '`config-role`'), config.replace(role_link, '[wrong](iam.md#iam-resource)'), config.replace(role_link, '[alias/two](kms.md#resource-AliasTwo)'), config.replace(role_link, '[config-role](iam.md#iam-missing)')))<br>L649: 動的 (('[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)', '[app-data](s3.md#s3-app-data)', role_link))<br>L653: 動的 (('`!ImportValue resource-export`', '`arn:aws:s3:::app-data`', '[wrong](s3.md#s3-app-data)', '[alias/two](kms.md#resource-AliasTwo)', '`' + link + '`'))<br>L664: 3 (('AWSServiceRoleForConfig', '`AWSServiceRoleForConfig`', '`AWSServiceCustom`'))<br>L671: 動的 (('`config-role`', '`AWSService`', '`AWSServiceRoleForConfig/path`', '`arn:aws:iam::123456789012:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig`', '`AWSServiceRoleForConfig', 'awsServiceRoleForConfig', 'AWSService' + 'x' * 55))<br>L679: 2 ((('KeyARN', '[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)'), ('BucketARN', '[app-data](s3.md#s3-app-data)')))<br>L722: 動的 (values.items()) |
| `integrations/design_layout.checks.py::check_resource_name_headings` | L781: 動的 (((text.replace(f'### Scheduler.Schedule: {name}', f'### Scheduler.Schedule: {logical_id}'), 'heading must display resource name'), (text.replace(f'[{name}]', f'[{logical_id}]'), 'must not display internal logical ID'), (text.replace(f'\| `{name}` \|', '\| `PENDING_DEPLOY` \|'), 'display name must be confirmed'), (text.replace(anchor, 'scheduler-internal-id'), 'anchor must match saved Model anchor'), (text.replace(marker, '<!-- resource-logical-id: -->'), 'invalid resource identity'), (text + '\\n' + marker, 'invalid resource identity')))<br>L790: 動的 (failures)<br>L796: 3 (('one', 'two', 'three')) |
| `integrations/design_layout.checks.py::check_quicksight_group_principal_reference` | 1（内部パラメータ化なし） |
| `integrations/design_layout.checks.py::check_workflow` | L868: 動的 (LAYOUTS)<br>L933: 2 ((('BucketEncryption.BucketKeyEnabled', 'BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled'), ('LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays', 'LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays')))<br>L937: 動的 (errors(KMS, s3_with_shortened_properties.replace(display, formal)))<br>L954: 動的 (bad_designs)<br>L956: 動的 (failures)<br>L957: 3 (('[alias/one](kms.md#resource-AliasTwo)', '[alias/two](kms.md#kms-keyone)', '[alias/two](kms.md#kms-missing)'))<br>L960: 動的 (errors(KMS, S3.replace('BucketEncryption[].KMSMasterKeyID', formal_kms)))<br>L963: 動的 (KMS.splitlines()) |
| `integrations/framework-input-isolation.checks.py::check` | L17: 5 (('stat', 'open', 'glob', 'rglob', 'iterdir')) |
| `integrations/human-inputs-group-05.checks.py::check_declared_inputs` | L?: 動的 (specs.items())<br>L?: 動的 (inputs.items())<br>L?: 動的 (text)<br>L?: 動的 (inputs) |
| `integrations/issues_api_only.checks.py::main_checks` | L21: 動的 (catalog.api_schemas)<br>L49: 3 (({'resourceType': 'Macie.Unknown'}, {}, {'resourceType': []}))<br>L37: 2 ((records, [api]))<br>L?: 動的 (baseline)<br>L?: 動的 (baseline)<br>L?: 動的 (baseline)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records) |
| `integrations/issues_failed_services.checks.py::main_checks` | L34: 動的 (enumerate(rows, 1))<br>L66: 動的 (models.items())<br>L78: 動的 (KMS_COMPARISON_FORMS.items())<br>L112: 3 ([('Log', 'arn:aws:logs:ap-northeast-1:123456789012:log-group:/fixture/log:*'), ('Build', 'arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build'), ('Rule', 'arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule')])<br>L145: 2 ([('Missing', 'Arn'), ('Queue', 'MissingAttribute')])<br>L81: 4 ([('KeyId', key_id), ('KeyArn', key_arn), ('AliasName', 'alias/fixture'), ('AliasArn', alias_arn)])<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (selected)<br>L?: 動的 (records)<br>L?: 動的 (values.items()) |
| `integrations/issues_policy_equivalence.checks.py::main_checks` | L48: 動的 (actual['Statement'])<br>L68: 2 ((same, selected_same))<br>L79: 3 ([('IAM.Role', 'AssumeRolePolicyDocument.Statement[].Action'), ('IAM.ManagedPolicy', 'PolicyDocument.Statement[].Action'), ('IAM.User', action_path)])<br>L89: 2 (((reference, arn), (sub, arn + '/results/*')))<br>L99: 4 ((Expression('Sub', ['${Missing}', {}]), Expression('Sub', ['${Value}', {'Value': {'$resource': ['s3', '002'], '$attribute': 'Arn'}}]), Expression('Sub', ['${Value}', {'Value': Expression('Join', ['', [reference, '/*']])}]), Expression('Join', ['', [reference, '/*']])))<br>L109: 2 ([('Action', ['s3:PutObject']), ('Effect', 'Deny')])<br>L129: 4 ((None, 'invalid/path', 'wildcard-*', {'Ref': 'Bucket'}))<br>L71: 5 (([], ['s3:PutObject'], ['s3:GetObject', 's3:GetObject'], [True], [['s3:GetObject']]))<br>L74: 4 (('Tags[].Value', 'Policies[].Action', 'Policies[].PolicyDocument.Statement[].Condition.Action', 'Policies[].PolicyDocument.Statement[].Resource'))<br>L92: 3 ((text + '-other', text.replace('aws:', 'aws-cn:'), text.replace('data2', 'data1')))<br>L?: 動的 (records)<br>L?: 動的 (comparison.display_differences[identifier(result)])<br>L?: 動的 (values.items()) |
| `integrations/issues_ref_returns.checks.py::main_checks` | L29: 動的 (specs)<br>L31: 動的 (enumerate((consumer, producer), 1))<br>L46: 動的 (specs)<br>L?: 動的 (model.items()) |
| `integrations/model-document-sources.checks.py::check` | L38: 2 ([('preview', human), ('release', human)])<br>L46: 動的 (paths.items())<br>L?: 動的 (first.items())<br>L?: 動的 (paths.items()) |
| `integrations/lambda-input-reference.checks.py::check` | L83: 5 ([(original.replace('resourceType=Lambda.Function', 'resourceType=S3.Bucket'), 'type-mismatched'), (original.replace('052', '053'), 'type-mismatched'), (original.replace('Lambda.Function.FunctionName', 'Lambda.Function.Description'), 'exactly one name'), (original.replace('`app-preview-one`', '``'), 'exactly one name'), (original + 'desired.row.052-004.property=Lambda.Function.FunctionName\ndesired.row.052-004.value=`duplicate`\n', 'exactly one name')])<br>L?: 2 ([('default-label', '021', {}), ('existing-label', '083', {'Function': 'PENDING_DEPLOY'})])<br>L?: 動的 (values.items()) |
| `integrations/model-input-context-digest.checks.py::check` | L75: 4 (([], [target, target], [{**target, 'awsExecutionAccountId': 123}], [{**target, 'awsExecutionAccountId': 'bad'}]))<br>L?: 動的 (values.items()) |
| `integrations/model-test.checks.py::check` | L143: 動的 (ordinary)<br>L200: 2 (('Action', 'Condition'))<br>L218: 3 ([({'Fn::GetAtt': ['role', 'Arn']}, 'match'), ({'Fn::GetAtt': ['role', 'RoleId']}, 'design_unresolved'), ({'Fn::Sub': '${role.RoleId}'}, 'design_unresolved')])<br>L231: 3 ([('property', 'IAM.Role.MaxSessionDuration'), ('value', '`3600`'), ('comment', 'fixture')])<br>L112: 2 ([('vpc', vpc), ('iam', iam)])<br>L115: 動的 (sources.items())<br>L?: 動的 (sources.items())<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 2 (('vpc', 'iam'))<br>L?: 動的 (failed)<br>L?: 動的 (rt['audit'](configured, 'wrong', cli)[2])<br>L?: 動的 (rt['audit'](vpc, '', cli)[2])<br>L?: 動的 (rt['audit'](vpc, None, cli)[2])<br>L?: 動的 (cli.calls)<br>L?: 動的 (result)<br>L?: 動的 (resolved)<br>L?: 動的 (result)<br>L?: 動的 (result)<br>L?: 動的 (result)<br>L?: 動的 (changed)<br>L?: 動的 (logs[0].parent.glob('vpc-*.log'))<br>L?: 動的 (findings.errors)<br>L?: 2 ([('cde', '123456789012'), ('other', '210987654321')])<br>L?: 2 (('completed', 'suspend')); 既存/未作成出力の不変、running保存、契約変更/契約なし拒否 |
| `integrations/model_files.checks.py::check_resource_reading` | L19: 60 (range(1, 61))<br>L60: 2 ((text, '# padding\n' * 540 + text))<br>L99: 3 ((text.replace('desired.resource.002.logicalId=Resource2', 'desired.resource.002.logicalId=Resource1'), text.replace('[Resource1](#kms-resource-001)', '[Missing](#missing)'), text.replace('[Resource1](#kms-resource-001)', '[Other](other.md#kms-resource-001)')))<br>L65: 5 (('001', 'Resource1', 'kms-resource-001', 'Resource2', '003'))<br>L93: 4 (('', 'Resource', '999', 'Resource61'))<br>L57: 動的 (sorted(values.items()))<br>L70: 動的 (result.stdout.splitlines())<br>L45: 動的 (values.items())<br>L63: 動的 (loaded.values.items())<br>L64: 動的 (loaded.files)<br>L52: 3 (('001', '002', '003'))<br>L52: 4 ((f'desired.resource.{identity}.', f'display.resource.{identity}.', f'desired.row.{identity}-', f'observed.row.{identity}-'))<br>L97: 動的 (snapshot.items())<br>L87: 動的 (loaded.locations.values()) |
| `integrations/model_impact.checks.py::check_precision` | L138: 動的 (data['instances'].values())<br>L?: 3 (('uses-first', 'fixed-export', 'continues'))<br>L?: 動的 (validator.errors)<br>L?: 動的 (template.read_text().replace('{"setting":"<<Setting>>"}', '{"fixed":true}').splitlines())<br>L?: 6 (('uses-first', 'uses-second', 'fixed-export', 'continues', 'stops-here', 'disabled')) |
| `integrations/model_impact.checks.py::check_identity_and_deletion` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_shared_environments` | L183: 2 (('dev', 'stg')) |
| `integrations/model_impact.checks.py::check_identifiers` | L203: 2 ((1, 2)) |
| `integrations/model_impact.checks.py::check_type_and_unknown` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_import_scope` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_selection` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_cycles` | 1（内部パラメータ化なし） |
| `integrations/model_parameter_inputs.checks.py::check_human` | L26: 動的 (records.items())<br>L64: 2 (('main-vpc', 'service'))<br>L113: 動的 (environments)<br>L120: 動的 (selected['instances'].items())<br>L123: 2 (('missing', 'private-c'))<br>L140: 動的 (extbindings['instances'].values())<br>L146: 動的 (selected['instances'].items())<br>L157: 10 ([(lambda p: p['instances']['main-vpc']['parameters'].update(Name='obsolete'), 'unknown parameter'), (lambda p: p['instances']['main-vpc']['parameters'].update(EnableDnsSupport=True), 'unknown parameter'), (lambda p: p['instances']['main-vpc']['parameters'].pop('CidrBlock'), 'missing required'), (lambda p: p['instances']['main-vpc']['parameters'].update(CidrBlock=10), 'type mismatch'), (lambda p: p['instances']['main-vpc']['parameters'].update(CidrBlock='10.10.0.1/23'), 'constraint cidr'), (lambda p: p['parameters'].update(Suffix=True), 'type mismatch'), (lambda p: p['parameters'].update(Environment='invented'), 'unknown parameter'), (lambda p: p['parameters'].pop('Suffix'), 'missing required'), (lambda p: p['instances']['private-a']['parameters'].update(Suffix='override'), 'ambiguous parameter source'), (lambda p: p['instances']['private-a']['parameters'].update(NameSuffix='bad'), 'constraint enum')])<br>L14: 動的 (environments)<br>L28: 動的 (human['instances'].items())<br>L34: 動的 (environments)<br>L38: 動的 (environments)<br>L67: 2 (('unknown', 17))<br>L?: 動的 (environments)<br>L?: 動的 ((root / 'docs/designs').rglob('*'))<br>L?: 4 (('model', 'model/parameters', 'model/templates', 'docs/designs'))<br>L?: 動的 ((root / base).rglob('*'))<br>L?: 動的 (baseline.items())<br>L?: 動的 (all_bytes.items())<br>L?: 動的 (params['instances'].values())<br>L?: 動的 (bindings['instances'].values())<br>L?: 動的 (before['preview'])<br>L?: 動的 (before['preview'])<br>L?: 3 (('017', '042', '083'))<br>L?: 動的 (environments)<br>L?: 動的 (kinds)<br>L?: 動的 (kinds.items()) |
| `integrations/model_parameter_inputs.checks.py::check_declared_instance_inputs` | L207: 2 (('service', 'Legal_42-name'))<br>L227: 7 ([(lambda h: h['instances'].update(unregistered={'parameters': {}}), 'binding mismatch'), (lambda h: h['instances'][identity]['parameters'].update(ValueUnknown=1), 'unknown parameter'), (lambda h: h['instances']['required']['parameters'].pop('Enabled'), 'missing required parameter'), (lambda h: h['instances'][identity]['parameters'].update(Value1=True), 'parameter type mismatch'), (lambda h: h['instances']['required']['parameters'].update(Hidden='override'), 'internal information'), (lambda h: h['instances'].update({'bindings-only': {'parameters': {}}}), 'input-free instances belong in bindings'), (lambda h: h['instances'].pop(identity), 'input-bearing instances require YAML')])<br>L244: 2 (('dev', 'stg'))<br>L?: 動的 (instances['instances']) |
| `integrations/model_parameter_inputs.checks.py::check_kms_alias` | L303: 3 ([(original.replace('KMS.Alias', 'KMS.Key'), 'type-mismatched'), (original.replace('KMS.Alias.AliasName', 'KMS.Alias.TargetKeyId'), 'exactly one name'), (original + 'desired.row.012-003.property=KMS.Alias.AliasName\ndesired.row.012-003.value=`alias/duplicate`\n', 'exactly one name')])<br>L?: 動的 (values.items()) |
| `integrations/model_parameter_inputs.checks.py::check_external_instances` | L347: 2 ([('dev', '017'), ('stg', '083')])<br>L334: 動的 ([identity, '099'] if duplicate else [identity]) |
| `integrations/model_parameter_inputs.checks.py::check_service_contracts` | 1（内部パラメータ化なし） |
| `integrations/model_templates.checks.py::check_transactions` | 1（内部パラメータ化なし） |
| `integrations/model_templates.checks.py::check_expansion` | L59: 動的 (models.items())<br>L62: 動的 (models.items())<br>L79: 動的 (models)<br>L62: 動的 (load_model(root / 'model' / env / 'team/iam.properties').values.values()) |
| `integrations/model_templates.checks.py::check_layout` | L90: 5 (('model/templates/team/iam.properties', 'model/parameters/team/iam.properties', 'model/parameters/dev/team/iam/parameters.yaml', 'model/dev/team/iam.json', 'model/dev/team/iam.properties/part-001.properties'))<br>L104: 2 (('dev', 'stg'))<br>L109: 4 (('model/templates/team/unrelated.properties.tpl', 'model/templates/team/iam.json', 'model/parameters/dev/team/iam.json', 'docs/unrelated.md'))<br>L114: 2 (('dev', 'stg'))<br>L118: 4 ((({part.relative_to(root).as_posix()}, True), ({'model/parameters/dev/team/iam/parameters.yaml'}, False), ({'model/parameters/stg/team/iam/parameters.yaml'}, True), ({'model/dev/team/iam.properties'}, False)))<br>L106: 3 (('parameters.yaml', 'bindings.json', 'observed.json'))<br>L87: 2 (('dev', 'stg')) |
| `integrations/model_templates.checks.py::check_reference_impact` | L156: 2 ([('codepipeline', 'codebuild', 'CodeBuild.Project', 'CodePipeline.Pipeline'), ('lambda', 'codepipeline', 'CodePipeline.Pipeline', 'Lambda.Function')])<br>L176: 2 (('codepipeline', 'lambda'))<br>L223: 動的 (impact.dependencies(root).values())<br>L246: 動的 (original.splitlines(keepends=True)) |
| `integrations/model_templates.checks.py::check_template_snapshot` | L279: 動的 (files) |
| `integrations/model_templates.checks.py::check_creation` | L295: 2 (range(2))<br>L301: 動的 (root.rglob('*'))<br>L303: 動的 (root.rglob('*')) |
| `integrations/model_templates.checks.py::check_invalid` | L311: 4 ((lambda p: p.update(unknown=1), lambda p: p['instances']['role_011']['parameters'].pop('Name'), lambda p: p['instances']['role_011']['parameters'].update(Name=True), lambda p: p['instances']['role_011'].update(definition='Role')))<br>L313: 3 ((lambda b: b['instances']['role_011'].update(definition='missing'), lambda b: b['instances']['role_018']['resources'].update(role='011'), lambda b: b['instances']['role_011']['rows'].update(name='099-004')))<br>L316: 9 (('<<Missing>>', '<<#Name>>x<</Name>>', '<<^Name>>x<</Name>>', '<<>partial>>', '<<&Name>>', '<<{Name}>>', '<<= x y =>>', '{{#Name}}', '{{>partial}}'))<br>L319: 4 (('a"b\\日本語=終', '', '<<not-reparsed>>', '${AWS::Region} {{resolve:ssm:literal}}'))<br>L325: 2 (('parameters.yaml', 'bindings.json')) |
| `integrations/model_templates.checks.py::check_sync` | L347: 1 ((('\r\n', False),))<br>L335: 動的 (root.rglob('*'))<br>L339: 動的 (before.items()) |
| `integrations/model_templates.checks.py::check_common_shape` | L368: 動的 (minimal) |
| `integrations/policy_tables.checks.py::check_iam` | L51: 2 (('RoleA', 'RoleB'))<br>L110: 4 (('Property：', 'JSON：', 'Version：', 'Id：'))<br>L124: 動的 (reversed(resources_in(indexed_lines)))<br>L178: 3 ((('S' * 16, True), ('S' * 17, False), (17, False)))<br>L53: 3 ((('trust-policy', trust), ('logging', inline), ('extra', inline)))<br>L?: 動的 (rendered.splitlines())<br>L?: 動的 (indexed_lines[start:resource.table_end])<br>L?: 動的 (shown)<br>L?: 動的 (errors(rendered))<br>L?: 動的 (line.strip('\|').split('\|'))<br>L?: 動的 (minimal.splitlines())<br>L?: 2 (('\| RoleName \|', '\| Policies[]')) |
| `integrations/policy_tables.checks.py::check_service_policies` | L226: 動的 ((repository / 'framework/materials/aws').glob('*.properties'))<br>L239: 動的 (POLICY_FORMATS.items())<br>L346: 5 (('ApiGateway.RestApi.SecurityPolicy', 'ElasticLoadBalancingV2.Listener.SslPolicy', 'NetworkFirewall.FirewallPolicy.FirewallPolicy.StatefulEngineOptions.StreamExceptionPolicy', 'S3.Bucket.PublicAccessBlockConfiguration.BlockPublicPolicy', 'SSO.PermissionSet.ManagedPolicies'))<br>L228: 動的 (catalog.read_text(encoding='utf-8').splitlines())<br>L268: 2 (('sample-a', 'sample-b'))<br>L288: 4 (('Property：', 'JSON：', 'Version：', 'Id：'))<br>L325: 4 ((f'Property：`{prop}`', f'JSON：[Access]({service}/access.json)', 'Version：`2012-10-17`', 'Id：`access-policy`'))<br>L276: 動的 (enumerate(rows, 1))<br>L?: 動的 (catalog.read_text(encoding='utf-8').splitlines())<br>L?: 動的 (types)<br>L?: 動的 (original.splitlines()) |
| `integrations/policy_tables.checks.py::check_grouping_and_settings` | L429: 4 (({'LifecyclePolicyText': {}}, {'LifecyclePolicyText': 'not-json'}, {'LifecyclePolicyText': '[]'}, {'LifecyclePolicyText': '{"rules":[],"rules":[]}'})) |
| `integrations/producer-identifier-reference.checks.py::check` | L60: 2 (['`vpc-fixture-two`', '`PENDING_DEPLOY`'])<br>L66: 2 (((producer_text.replace('row.id.property=EC2.VPC.VpcId', 'row.id.property=EC2.Subnet.SubnetId'), observed['values']), (producer_text.replace('row.name.property=EC2.VPC.Name', 'row.name.property=EC2.VPC.VpcId'), {**observed['values'], 'observed.row.001-001.value': '`duplicate`'})))<br>L75: 6 ([({}, 'matching observed identifier'), ({'observed.row.001-002.property': 'EC2.Subnet.SubnetId', 'observed.row.001-002.value': '`subnet-one`'}, 'invalid observed key/value'), ({**observed['values'], 'observed.row.001-001.property': 'EC2.VPC.VpcId', 'observed.row.001-001.value': '`duplicate`'}, 'invalid observed key/value'), ({**observed['values'], 'observed.row.001-002.value': False}, 'invalid observed key/value'), ({**observed['values'], 'observed.row.001-002.value': '``'}, 'nonempty non-ARN string'), ({**observed['values'], 'observed.row.001-002.value': 'arn:aws:fixture'}, 'nonempty non-ARN string')])<br>L85: 3 ([({'resource': '002'}, 'type-mismatched'), ({'resourceType': 'EC2.Subnet', 'property': 'EC2.Subnet.SubnetId'}, 'type-mismatched'), ({'property': 'EC2.VPC.Name'}, 'not a catalog identifier')])<br>L?: 動的 (observed['values'].items())<br>L?: 動的 ({**desired, **observed['values']}.items())<br>L?: 動的 (values.items())<br>L?: 動的 (desired.items()) |
| `integrations/producer-name-reference.checks.py::check` | L71: 2 ([('preview', '-Case_01'), ('later', '')])<br>L132: 6 ([(original.replace('resourceType=IAM.Role', 'resourceType=IAM.Policy'), 'type-mismatched'), (original.replace('054', '055'), 'type-mismatched'), (original.replace('IAM.Role.RoleName', 'IAM.Role.Path'), 'exactly one name'), (original.replace('IAM.Role.RoleName', 'Glue.SecurityConfiguration.Name'), 'exactly one name'), (original.replace('`venusinf-preview-IfInbound1802Role-Case_01`', '``'), 'exactly one name'), (original + 'desired.row.054-002.property=IAM.Role.RoleName\ndesired.row.054-002.value=`duplicate`\n', 'exactly one name')])<br>L73: 動的 (refs.items())<br>L?: 動的 (producer_texts)<br>L?: 動的 (load_model(producer).files)<br>L?: 動的 (refs.items())<br>L?: 動的 (values.items()) |
| `integrations/raw-bucket-name-reference.checks.py::check` | L63: 5 ([(original.replace('resourceType=S3.Bucket', 'resourceType=IAM.Role'), 'type-mismatched'), (original.replace('017', '018'), 'type-mismatched'), (original.replace('S3.Bucket.BucketName', 'S3.Bucket.Description'), 'exactly one name'), (original.replace('`app-preview-RAW-one`', '``'), 'exactly one name'), (original + 'desired.row.017-002.property=S3.Bucket.BucketName\ndesired.row.017-002.value=`duplicate`\n', 'exactly one name')])<br>L?: 2 ([('first', '003'), ('second', '088')])<br>L?: 動的 (values.items()) |
| `integrations/s3-bound-anchor.checks.py::check` | L?: 動的 (updated)<br>L?: 動的 (values)<br>L?: 動的 (values.items()) |
| `integrations/security-group-input-reference.checks.py::check` | L90: 5 ([(original.replace('resourceType=EC2.SecurityGroup', 'resourceType=EC2.Subnet'), 'type-mismatched'), (original.replace('052', '053'), 'type-mismatched'), (original.replace('EC2.SecurityGroup.GroupName', 'EC2.SecurityGroup.GroupDescription'), 'exactly one name'), (original.replace('`app-preview-one`', '``'), 'exactly one name'), (original + 'desired.row.052-004.property=EC2.SecurityGroup.GroupName\ndesired.row.052-004.value=`duplicate`\n', 'exactly one name')])<br>L?: 2 ([('default-label', '021', {}), ('existing-label', '083', {'SecurityGroup': 'PENDING_DEPLOY'})])<br>L?: 動的 (values.items()) |
| `integrations/service_contracts.py::check_kms` | L26: 動的 (cases('kms'))<br>L41: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L30: 動的 (before.keys() | after.keys())<br>L36: 動的 (before.items())<br>L31: 動的 (before.items())<br>L37: 動的 (before)<br>L39: 動的 (alias_rows) |
| `integrations/service_contracts.py::check_security_group` | L53: 動的 (cases('security-group'))<br>L66: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L60: 動的 (before.keys() | after.keys())<br>L54: 動的 (original['instances'].items())<br>L54: 動的 (item['parameters']) |
| `integrations/service_contracts.py::check_route53` | L78: 動的 (cases('route53'))<br>L101: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L87: 動的 (before.keys() | after.keys())<br>L81: 動的 (original['instances'].items())<br>L81: 動的 (item['parameters'])<br>L97: 動的 (before.keys() | changed_name.keys())<br>L99: 動的 (differences)<br>L100: 動的 (changed_name)<br>L100: 動的 (before) |
| `integrations/service_contracts.py::check_iam` | L114: 動的 (cases('iam'))<br>L115: 動的 (before.items())<br>L132: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L128: 動的 (before.keys() | after.keys())<br>L130: 動的 (differences)<br>L129: 動的 (differences) |
| `integrations/service_contracts.py::check_s3` | L146: 動的 (cases('s3'))<br>L157: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L171: 動的 (before.items())<br>L153: 動的 (before.keys() | changed.keys())<br>L147: 動的 (human['instances'].items())<br>L175: 動的 (t.model_paths(ROOT)) |
| `integrations/service_contracts.py::check_glue` | L180: 動的 (cases('glue'))<br>L189: 動的 (resource_row_index(renamed).values())<br>L190: 動的 (rows)<br>L184: 動的 (resource_row_index(before).values())<br>L184: 動的 (rows)<br>L183: 動的 (defs.values())<br>L185: 動的 (timeouts)<br>L195: 動的 (arguments.values()) |
| `integrations/service_contracts.py::check_cloudwatch_logs` | L204: 動的 (cases('cloudwatch-logs'))<br>L206: 動的 (defs.values())<br>L210: 動的 (resource_row_index(before).values())<br>L212: 動的 (rows)<br>L207: 動的 (d.parameters.values())<br>L209: 動的 (defs.values())<br>L211: 動的 (rows) |
| `integrations/service_contracts.py::check_lambda` | L220: 動的 (cases('lambda'))<br>L221: 動的 (resource_row_index(before).items())<br>L225: 動的 (rows)<br>L236: 動的 (before.keys() | after.keys())<br>L231: 動的 (human['instances'].items()) |
| `integrations/service_contracts.py::check_eventbridge` | L246: 動的 (cases('eventbridge'))<br>L247: 動的 (resource_row_index(before).items())<br>L264: 動的 (fixed_retry.items())<br>L251: 動的 (rows)<br>L266: 動的 (resource_row_index(before).values())<br>L266: 動的 (rows)<br>L265: 動的 (human['instances'].values())<br>L268: 動的 (retry_rows) |
| `integrations/service_contracts.py::check_codepipeline` | L279: 動的 (cases('codepipeline'))<br>L280: 動的 (resource_row_index(before).items())<br>L285: 動的 (rows)<br>L294: 動的 (before.keys() | after.keys())<br>L282: 動的 (rows)<br>L291: 動的 (human['instances'].items())<br>L284: 動的 (restored)<br>L284: 動的 (formal)<br>L288: 動的 (doc.values()) |
| `integrations/service_contracts.py::check_responsibilities` | L317: 動的 (sorted(services))<br>L319: 動的 (cases(service))<br>L327: 動的 (before.items())<br>L343: 動的 (trace.values())<br>L350: 動的 (slots)<br>L344: 動的 (source.get('inputs', {}).values())<br>L351: 動的 (params.items())<br>L349: 動的 (human['instances'].items())<br>L323: 動的 (entries(before, 'desired.stack.'))<br>L326: 動的 (bindings['instances'].values())<br>L342: 動的 (trace.values())<br>L382: 動的 (before)<br>L357: 動的 (spec.items())<br>L390: 動的 (before.items())<br>L385: 動的 (before.items())<br>L389: 動的 (difference) |
| `integrations/service_contracts.py::check` | 1（内部パラメータ化なし） |
| `integrations/service_contracts.py::check_fixtures` | 1（内部パラメータ化なし） |
| `integrations/sync-existing-files.checks.py::check_failure_safety` | L40: 4 (('framework/a.txt', 'framework/b.txt', 'AGENTS.md', 'README.md'))<br>L53: 動的 (target.rglob('*'))<br>L70: 動的 (target.rglob('*')) |
| `integrations/task_contract.checks.py::check_admission_selection` | 1（内部パラメータ化なし） |
| `integrations/task_contract.checks.py::check_completed_legacy_and_paths` | L56: 動的 ((old, new))<br>L69: 9 (('../escape', '/tmp/escape', './file', 'a//file', 'a/../file', '*.md', 'a/**', '.git/config', '.')) |
| `integrations/task_contract.checks.py::check_shared_issue_files` | L?: 2 (('retained issue', 'second issue')) |
| `integrations/task_contract.checks.py::check_suspend_and_resume` | 1（内部パラメータ化なし） |
| `integrations/task_contract.checks.py::check_atomic_contract_reads` | L161: 動的 (during.values()) |
| `integrations/used-definition-inputs.checks.py::check` | L37: 2 ([('Plain', '`fixed`'), ('Endpoint', '`<<EndpointIngressCidr>>`')])<br>L63: 4 ([({}, 'missing required parameter'), ({'Value1': 'old'}, 'unknown parameter'), ({'EndpointIngressCidr': 3}, 'type mismatch'), ({'EndpointIngressCidr': '10.0.0.1/24'}, 'constraint cidr')])<br>L?: 2 ((1, 2))<br>L?: 動的 (range(1, count + 1))<br>L?: 動的 (before.items()) |
| `integrations/validation_checks/cloudformation.py::check_cloudformation_stack_design` | L40: 2 (('job-01', 'job-02'))<br>L56: 5 ((('<!-- max-concurrent-stacks: 2 -->', '<!-- max-concurrent-stacks: 0 -->'), ('<!-- max-concurrent-stacks: 2 -->', '<!-- max-concurrent-stacks: -1 -->'), ('\| 1 \| 10 \|', '\| 1 \| 0 \|'), ('\| 1 \| 10 \|', '\| 1 \| -1 \|'), ('\| 1 \| 10 \|', '\| 1 \| abc \|')))<br>L63: 7 ((('\| 2 \| 10 \| stack-job-02 \| job.yaml', '\| 2 \| 10 \| stack-job-01 \| job.yaml', 'duplicate stack name'), ('job-02.json', 'job-01.json', 'parameter file belongs to multiple stacks'), ('\| job.yaml \|', '\| ../job.yaml \|', 'invalid stack template filename'), ('\| No. \| Deploy<br>Order \| StackName \| Template \| Parameters \| Comment \|', '\| StackName \| Template \| Parameters \|', 'invalid CloudFormation stack design header'), ('\| 2 \| 10 \| stack-job-02', '\| 3 \| 10 \| stack-job-02', 'No. must be sequential'), ('\| 月次jobを配置するstack \|', '\| \|', 'invalid CloudFormation stack design row'), ('月次jobを配置するstack', 'monthly job', 'stack Comment must describe its purpose in Japanese')))<br>L?: 動的 (errors())<br>L?: 動的 (errors())<br>L?: 動的 (errors()) |
| `integrations/validation_checks/cloudformation.py::check_stack_mapping_targets` | L?: 動的 (errors())<br>L?: 動的 (errors())<br>L?: 動的 (values.items()) |
| `integrations/validation_checks/design.py::check_description_design_constraints` | L87: 3 ((('RoleOne', 'IAM.Role.Description', 'iam.md', iam_text.replace('Application role', '日本語の説明'), sg_text), ('GroupOne', 'EC2.SecurityGroup.GroupDescription', 'security-group.md', iam_text, sg_text.replace('Application access', '日本語の説明')), ('GroupOne', 'EC2.SecurityGroup.GroupDescription', 'security-group.md', iam_text, sg_text.replace('Application access', 'Why?'))))<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 4 ((filename, resource, prop, 'must match')) |
| `integrations/validation_checks/references.py::check_identifier_propagation` | L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors) |
| `integrations/validation_checks/references.py::check_array_role_links` | L?: 動的 (errors('wrong-role'))<br>L?: 動的 (rows) |
| `integrations/validation_checks/references.py::check_s3_bucket_policy_grouping` | L?: 動的 (errors(wrong_order))<br>L?: 動的 (errors(unset_region))<br>L?: 動的 (errors(literal_alias))<br>L?: 動的 (errors(wrong_alias))<br>L?: 動的 (errors(wrong_heading))<br>L?: 動的 (errors(explicit_bucket))<br>L?: 動的 (errors(separate_heading)) |
| `integrations/validation_checks/references.py::check_subnet_association_overview` | L238: 3 (range(1, 4))<br>L266: 動的 (subnet_rows)<br>L310: 2 (('rtb-00000001', *(f'subnet-{number:08d}' for number in range(1, 4))))<br>L319: 動的 (bad_designs)<br>L?: 3 (range(1, 4))<br>L?: 動的 (validator.errors)<br>L?: 3 (range(1, 4))<br>L?: 動的 (failures) |
| `integrations/validation_checks/references.py::check_resource_overview` | L380: 動的 (invalid_sections)<br>L?: 動的 (errors(valid.replace('\| 1 \| [app-dev-data', '\| 2 \| [app-dev-data', 1)))<br>L?: 動的 (errors(valid.replace('アプリケーションのデータを保管するbucket \|', 'resource \|', 1)))<br>L?: 動的 (errors(valid.replace('アプリケーションのデータを保管するbucket \|', 'バケット（app-dev-data-123456789012）の設定 \|', 1)))<br>L?: 動的 (errors(sg))<br>L?: 動的 (errors(valid.replace('\| No. \| ResourceName \|', '\| ResourceName \|', 1)))<br>L?: 動的 (errors(extra))<br>L?: 動的 (errors(valid.replace('\| ResourceName \|', '\| BucketName \|', 1)))<br>L?: 動的 (errors(missing_row))<br>L?: 動的 (failures) |
| `integrations/validation_checks/runner.py::check_module_inputs` | 1（内部パラメータ化なし） |
| `integrations/validation_checks/scenario.py::check_records` | L30: 動的 (cases) |
| `integrations/validation_checks/scope.py::check_deployment_iac_scope` | L41: 2 (('dev', 'stg'))<br>L46: 2 ((('dev', 'deploy'), ('stg', 'update')))<br>L54: 動的 (values.items())<br>L86: 2 (('dev', 'stg'))<br>L97: 動的 (validator.errors)<br>L100: 動的 (validator.errors)<br>L107: 動的 (validator.errors)<br>L111: 動的 (validator.errors)<br>L114: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_task_contract` | L?: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_idle_without_active_task` | L?: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_destroy_phase` | L143: 16 (('check_structure', 'check_task_scope', 'check_tasks', 'check_project_topology', 'check_validation_scope', 'check_model_files', 'check_task_type_requirements', 'check_initialized_paths', 'check_catalog', 'check_resource_layout', 'check_scoped_designs', 'check_designs', 'check_observed_values', 'check_acceptance_checks', *banned))<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_task_type_dispatch` | L160: 2 ((('vpc', 'EC2.VPC', 'Name'), ('cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName'))) |
| `integrations/validation_checks/task.py::check_task_type_cases` | L180: 動的 (valid.items())<br>L223: 6 (({'model/parameters/dev/cde/cloudwatch-logs/parameters.yaml'}, {'model/templates/cde/cloudwatch-logs.properties.tpl'}, {'model/parameters/dev/cde/cloudwatch-logs/parameters.yaml', 'model/parameters/dev/cde/vpc/parameters.yaml', 'docs/designs/dev/cde/vpc.md'}, {'docs/designs/dev/cde/vpc.md'}, {'docs/designs/dev/cde/iam/role01-policy.json'}, set()))<br>L?: 動的 (validator.errors)<br>L?: 動的 (changed) |
| `integrations/validation_checks/terraform.py::check_cli` | L37: 2 (('dev', 'stg'))<br>L42: 4 ((['fmt'], ['fmt', '-check'], ['init', '-backend=false', '-input=false'], ['validate'])) |
| `integrations/validation_scope.checks.py::check_single_target_cache` | L16: 動的 (services.items())<br>L24: 動的 (enumerate(sorted(model_projection.identifier_outputs(root).get(kind, set())), 2))<br>L32: 2 (['ec2', *services])<br>L90: 動的 (invalid.errors)<br>L31: 動的 (values.items())<br>L35: 動的 (sorted(scope))<br>L37: 動的 (sorted(scope)) |
| `integrations/validation_scope.checks.py::check_template_consumers` | L99: 2 (('dev', 'stg'))<br>L108: 5 (((['--scope', 'dev/team/config', '--scope', 'stg/team/config'], 0), (['--scope', 'dev/team/config'], 1), (['--scope', 'dev/other/config'], 1), (['--scope', '../team/config'], 1), (['--scope', 'dev/team/config', '--all'], 2)))<br>L101: 2 (('dev', 'stg'))<br>L142: 動的 (args)<br>L104: 動的 (sorted(scope)) |
| `integrations/worktree_python.checks.py::check_setup` | 初回install失敗の実Task/Branch/partial環境保持とsetup再実行の永続化 |
| `integrations/worktree_python.checks.py::check_venv_fallback` | 実venv初回生成・2 Task再利用、wrapper/CLI PATHとcleanup後の共有環境保持 |
| `integrations/worktree_python.checks.py::check_parallel_fallback` | 独立Python 2プロセスの実Lock競合確認・一度だけinstall・同一環境再利用 |
| `integrations/worktree_python.checks.py::check_symlink_safety` | 実共有環境Symlinkを拒否し外部ディレクトリの全contentsを保持 |
| `integrations/worktree_task.checks.py::check_success_and_empty` | 実CLIの通常変更とindex取消後の空変更、commit有無・cleanup |
| `integrations/worktree_task.checks.py::check_finalize_line_endings` | CRLFの実Git反映とstaged末尾空白拒否・Git設定保持（2条件） |
| `integrations/worktree_task.checks.py::check_incomplete_and_git_safety` | 実WorktreeのMERGE_HEAD検出とcommit前停止・checkout保持 |
| `integrations/worktree_task.checks.py::check_dirty_base_and_retry` | dirty Baseの実index保護と解消後の安全なRebase停止 |
| `integrations/worktree_task.checks.py::check_ahead_and_rebase_conflict` | 実Rebase競合・abort・reviewed recovery・Base再更新からの復旧 |
| `integrations/worktree_task.checks.py::check_collisions_and_base_selection` | 実Branch・Path・stale Worktree衝突時の既存データ保護 |
| `integrations/worktree_task.checks.py::check_directory_layout` | 実Git ignore契約違反時のCreate停止・Branch未作成 |
| `integrations/worktree_task.checks.py::check_metadata_storage` | 複数実Worktreeの状態分離・永続化・共通Lockとsibling保持 |
| `integrations/worktree_task.checks.py::check_cleanup_failure_and_retry` | Merge後cleanup失敗・安全な再試行・ignoredデータと他Task証跡保持 |
| `integrations/worktree_task.checks.py::check_merge_retry_and_commit_failure` | 実Merge失敗からの再試行とCommit改変拒否（2経路） |
| `integrations/worktree_task.checks.py::check_human_approved_validation_failure` | 承認付き実Merge・suspend/FAIL保持・承認永続化とcleanup再試行 |
| `integrations/worktree_task.checks.py::check_real_loop_integration` | 実Loop失敗からTask suspend永続化・finalize停止への接続 |

| `integrations/check-model-aws.checks.py::check_domains` | callback/subdirectory: 7組（common、associations、batch、cli、stacks、cfn-identity、coverage） |

## main / module 直接実行シナリオ明細

以下は関数ケース表と別の検証地点台帳。ひとつのシナリオに複数地点があるため、各行を独立テスト件数としては合算しない。元の各地点を同一ASTで対応付ける。コメントに依存せずassert、明示的失敗、Mock/unittest検証を網羅する。

| 元ファイル : 行 / シナリオ | 分類 | 現在の配置 / シナリオ | 検証条件 |
|---|---|---|---|
| `integrations/compact-model-sources.checks.py:36` / `module` | IT | `integrations/compact-model-sources.checks.py:36` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:38` / `module` | IT | `integrations/compact-model-sources.checks.py:38` | `assert observed in t.input_snapshot(path)` |
| `integrations/compact-model-sources.checks.py:40` / `module` | IT | `integrations/compact-model-sources.checks.py:40` | `assert not any((k.startswith('observed.') for k in t.reference_values(path, '017', 'S3.Bucket', 'identifier').values))` |
| `integrations/compact-model-sources.checks.py:70` / `module` | IT | `integrations/compact-model-sources.checks.py:70` | `assert observed.read_bytes() == original and marker.read_text() == 'before'` |
| `integrations/compact-model-sources.checks.py:73` / `module` | IT | `integrations/compact-model-sources.checks.py:73` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:76` / `module` | IT | `integrations/compact-model-sources.checks.py:76` | `assert 'labels' not in binding['instances']['fixture']` |
| `integrations/compact-model-sources.checks.py:78` / `module` | IT | `integrations/compact-model-sources.checks.py:78` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:84` / `module` | IT | `integrations/compact-model-sources.checks.py:84` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:44` / `module` | IT | `integrations/compact-model-sources.checks.py:44` | `assert values[key] == value and values[key.removesuffix('value') + 'property'] == desired['desired.row.017-023.property']` |
| `integrations/compact-model-sources.checks.py:45` / `module` | IT | `integrations/compact-model-sources.checks.py:45` | `assert values[key.removesuffix('value') + 'comment'] == desired['desired.row.017-023.comment']` |
| `integrations/compact-model-sources.checks.py:51` / `module` | IT | `integrations/compact-model-sources.checks.py:51` | `assert load_model(path).locations[key][0] == observed` |
| `integrations/compact-model-sources.checks.py:53` / `module` | IT | `integrations/compact-model-sources.checks.py:53` | `assert t.json_read(output[observed]) == {'version': 1, 'values': {key: value}}` |
| `integrations/compact-model-sources.checks.py:55` / `module` | IT | `integrations/compact-model-sources.checks.py:55` | `assert t.json_read(observed.read_text())['values'] == {key: value}` |
| `integrations/compact-model-sources.checks.py:49` / `module` | IT | `integrations/compact-model-sources.checks.py:49` | `assert expansion.provenance[metadata]['derivedFrom'] == 'desired.' + metadata.removeprefix('observed.')` |
| `integrations/compact-model-sources.checks.py:50` / `module` | IT | `integrations/compact-model-sources.checks.py:50` | `assert load_model(path).locations[metadata][0].is_relative_to(root / 'model/templates')` |
| `integrations/compact-model-sources.checks.py:104` / `module` | IT | `integrations/compact-model-sources.checks.py:104` | `assert after['desired.resource.017.anchor'] == before[path]['desired.resource.017.anchor']` |
| `integrations/compact-model-sources.checks.py:105` / `module` | IT | `integrations/compact-model-sources.checks.py:105` | `assert set(after) == set(before[path])` |
| `integrations/compact-model-sources.checks.py:106` / `module` | IT | `integrations/compact-model-sources.checks.py:106` | `assert (after != before[path]) == (path.parent.parent.name != 'independent')` |
| `integrations/runtime-model.checks.py:38` / `module` | IT | `integrations/runtime-model.checks.py:38` | `assert model_paths(root) == [path] and model_paths(root, 'prod') == []` |
| `integrations/runtime-model.checks.py:60` / `module` | IT | `integrations/runtime-model.checks.py:58` | `assert design_source_digest(path) != old and affected(root, [yaml.relative_to(root)]) == {('preview', 'team', 'example')}` |
| `integrations/runtime-model.checks.py:63` / `module` | IT | `integrations/runtime-model.checks.py:61` | `assert set(model_paths(root)) == {path, other}` |
| `integrations/runtime-model.checks.py:64` / `module` | IT | `integrations/runtime-model.checks.py:62` | `assert affected(root, [template.relative_to(root)]) == {('preview', 'team', 'example'), ('release', 'team', 'example')}` |
| `integrations/runtime-model.checks.py:65` / `module` | IT | `integrations/runtime-model.checks.py:63` | `assert load_model(other).values == values and design_source_digest(path) != old` |
| `integrations/runtime-model.checks.py:68` / `module` | IT | `integrations/runtime-model.checks.py:66` | `print('Runtime Models: PASS (source discovery; binding-only resources; fixed identities; creation/rerun; missing/corrupt/unknown rejection; input invalidation)')` |
| `integrations/runtime-model.checks.py:43` / `module` | IT | `integrations/runtime-model.checks.py:42` | `assert snapshot_model(path) == before and load_model(path).values == values` |
| `integrations/runtime-model.checks.py:47` / `module` | IT | `integrations/runtime-model.checks.py:45` | `assert model_paths(root) == [path]` |
| `integrations/sync-existing-files.checks.py:25` / `module` | IT | `integrations/sync-existing-files.checks.py:25` | `assert SPEC and SPEC.loader` |
| `integrations/sync-existing-files.checks.py:94` / `main` | IT | `integrations/sync-existing-files.checks.py:93` | `assert result.returncode == 0, result.stderr` |
| `integrations/sync-existing-files.checks.py:95` / `main` | IT | `integrations/sync-existing-files.checks.py:94` | `assert (target / 'framework' / 'scripts' / SCRIPT.name).is_file()` |
| `integrations/sync-existing-files.checks.py:97` / `main` | IT | `integrations/sync-existing-files.checks.py:96` | `assert (target / '.agents/skills/initialize/SKILL.md').read_bytes() == skill.read_bytes()` |
| `integrations/sync-existing-files.checks.py:104` / `main` | IT | `integrations/sync-existing-files.checks.py:103` | `assert preview.returncode == 0, preview.stderr` |
| `integrations/sync-existing-files.checks.py:105` / `main` | IT | `integrations/sync-existing-files.checks.py:104` | `assert 'pending=2' in preview.stdout, preview.stdout` |
| `integrations/sync-existing-files.checks.py:110` / `main` | IT | `integrations/sync-existing-files.checks.py:109` | `assert updated.returncode == 0, updated.stderr` |
| `integrations/sync-existing-files.checks.py:111` / `main` | IT | `integrations/sync-existing-files.checks.py:110` | `assert 'copied=2 added=0 pending=0' in updated.stdout, updated.stdout` |
| `integrations/sync-existing-files.checks.py:115` / `main` | IT | `integrations/sync-existing-files.checks.py:114` | `assert repeated.returncode == 0, repeated.stderr` |
| `integrations/sync-existing-files.checks.py:116` / `main` | IT | `integrations/sync-existing-files.checks.py:115` | `assert 'pending=0' in repeated.stdout, repeated.stdout` |
| `integrations/sync-existing-files.checks.py:117` / `main` | IT | `integrations/sync-existing-files.checks.py:116` | `assert 'scope=framework,.agents,AGENTS.md,README.md' in repeated.stdout` |
| `integrations/sync-existing-files.checks.py:118` / `main` | IT | `integrations/sync-existing-files.checks.py:117` | `assert 'excluded=project.json,docs,infra,model,tasks,tests' in repeated.stdout` |
| `integrations/sync-existing-files.checks.py:100` / `main` | IT | `integrations/sync-existing-files.checks.py:99` | `assert (target / name).read_bytes() == (root / name).read_bytes()` |
| `integrations/sync-existing-files.checks.py:107` / `main` | IT | `integrations/sync-existing-files.checks.py:106` | `assert f'WOULD COPY: {name}' in preview.stdout` |
| `integrations/sync-existing-files.checks.py:108` / `main` | IT | `integrations/sync-existing-files.checks.py:107` | `assert (target / name).read_text(encoding='utf-8') == 'outdated'` |
| `integrations/sync-existing-files.checks.py:113` / `main` | IT | `integrations/sync-existing-files.checks.py:112` | `assert (target / name).read_bytes() == (root / name).read_bytes()` |
| `integrations/sync-existing-files.checks.py:120` / `main` | IT | `integrations/sync-existing-files.checks.py:119` | `assert (target / relative).read_text(encoding='utf-8') == 'target-specific'` |
| `integrations/sync-existing-files.checks.py:122` / `main` | IT | `integrations/sync-existing-files.checks.py:121` | `assert {path.relative_to(target).as_posix() for path in (target / relative.split('/')[0]).rglob('*') if path.is_file()} == {relative}` |
| `units/script_loader.checks.py:38` / `main` | UT | `units/script_loader.checks.py:38` | `assert result.ready` |
| `units/script_loader.checks.py:29` / `main` | UT | `units/script_loader.checks.py:29` | `assert release.wait(5)` |
| `units/script_loader.checks.py:44` / `main` | UT | `units/script_loader.checks.py:44` | `assert started.wait(5)` |
| `units/script_loader.checks.py:51` / `main` | UT | `units/script_loader.checks.py:51` | `assert first.result(timeout=5) is waiting.result(timeout=5)` |
| `units/script_loader.checks.py:52` / `main` | UT | `units/script_loader.checks.py:52` | `assert locate.call_count == 1` |
| `units/script_loader.checks.py:47` / `main` | UT | `units/script_loader.checks.py:47` | `assert entered.wait(5)` |
| `units/script_loader.checks.py:48` / `main` | UT | `units/script_loader.checks.py:48` | `assert not returned.wait(0.1), 'partially initialized module escaped'` |
| `unknown/array_display.checks.py:50` / `main` | UT | `units/array_display.checks.py:50` | `assert verified_rows(shown, source, 'S3.Bucket') == source` |
| `unknown/array_display.checks.py:52` / `main` | UT | `units/array_display.checks.py:52` | `assert fields[1:5] == ['LifecycleConfiguration.Rules[1].Transitions[1].StorageClass', 'LifecycleConfiguration.Rules[1].Transitions[1].TransitionInDays', 'LifecycleConfiguration.Rules[1].Transitions[2].StorageClass', 'LifecycleConfiguration.Rules[1].Transitions[2].TransitionInDays']` |
| `unknown/array_display.checks.py:53` / `main` | UT | `units/array_display.checks.py:53` | `assert fields[7] == 'LifecycleConfiguration.Rules[2].Transitions[1].StorageClass'` |
| `unknown/array_display.checks.py:54` / `main` | UT | `units/array_display.checks.py:54` | `assert fields[-4:] == ['Tags[1].Key', 'Tags[1].Value', 'Tags[2].Key', 'Tags[2].Value']` |
| `unknown/array_display.checks.py:71` / `main` | UT | `units/array_display.checks.py:71` | `assert [row[1] for row in output] == ['Stages[1].Actions[1].InputArtifacts[1].Name', 'Stages[1].Actions[1].InputArtifacts[2].Name', 'Stages[2].Actions[1].Name']` |
| `unknown/array_display.checks.py:72` / `main` | UT | `units/array_display.checks.py:72` | `assert verified_rows(output, original, 'CodePipeline.Pipeline') == original` |
| `unknown/array_display.checks.py:75` / `main` | UT | `units/array_display.checks.py:75` | `assert [row[1] for row in output] == ['Tasks[1].Name', 'Tasks[1].Subnets[1]', 'Tasks[1].Subnets[2]', 'Tasks[2].Name', 'Tasks[2].Subnets[1]']` |
| `unknown/array_display.checks.py:76` / `main` | UT | `units/array_display.checks.py:76` | `assert verified_rows(output, original, 'Example.Resource') == original` |
| `unknown/array_display.checks.py:65` / `main` | UT | `units/array_display.checks.py:65` | `assert len(output) == count and verified_rows(output, original, 'EC2.Instance') == original` |
| `unknown/array_display.checks.py:83` / `main` | UT | `units/array_display.checks.py:83` | `assert [row[1] for row in output] == expected` |
| `unknown/array_display.checks.py:84` / `main` | UT | `units/array_display.checks.py:84` | `assert verified_rows(output, original, kind) == original` |
| `unknown/array_display.checks.py:89` / `main` | UT | `units/array_display.checks.py:89` | `assert output[0][1] == expected` |
| `unknown/array_display.checks.py:90` / `main` | UT | `units/array_display.checks.py:84` | `assert verified_rows(output, original, kind) == original` |
| `unknown/array_display.checks.py:67` / `main` | UT | `units/array_display.checks.py:67` | `assert output[0][1] == 'SecurityGroupIds[1]'` |
| `unknown/array_display.checks.py:107` / `main` | UT | `units/array_display.checks.py:107` | `assert '[]' not in output[0][1] and '[1]' in output[0][1], (kind, prop)` |
| `unknown/array_display.checks.py:108` / `main` | UT | `units/array_display.checks.py:108` | `assert verified_rows(output, original, kind) == original, (kind, prop)` |
| `unknown/array_display.checks.py:101` / `main` | UT | `units/array_display.checks.py:101` | `assert len(output) == 2 and output[0][1].endswith('[1]') and output[1][1].endswith('[2]'), (kind, prop)` |
| `unknown/array_display.checks.py:102` / `main` | UT | `units/array_display.checks.py:84` | `assert verified_rows(output, original, kind) == original` |
| `aws-context::main:70` / `main` | UT | `units/check-deploy-context.checks.py:70` | `assert target == {'alias': 'cde', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'terraform'}` |
| `aws-context::main:76` / `main` | UT | `units/check-deploy-context.checks.py:76` | `assert run.call_args.args[0][:3] == ['/mock/aws', '--profile', 'deploy']` |
| `aws-context::main:77` / `main` | UT | `units/check-deploy-context.checks.py:77` | `assert run.call_args.args[0][3:5] == ['--region', 'ap-northeast-1']` |
| `aws-context::main:90` / `main` | UT | `units/check-deploy-context.checks.py:90` | `assert commands == ['aws']` |
| `aws-context::main:91` / `main` | UT | `units/check-deploy-context.checks.py:91` | `assert '--profile' not in run.call_args.args[0]` |
| `aws-context::main:106` / `main` | UT | `units/check-deploy-context.checks.py:106` | `assert commands == ['aws']` |
| `aws-context::main:111` / `main` | UT | `units/check-deploy-context.checks.py:111` | `assert 'topology target must exist exactly once' in str(error)` |
| `aws-context::main:113` / `main` | UT | `units/check-deploy-context.checks.py:113` | `raise AssertionError('aliased target was selected without its alias')` |
| `aws-context::main:126` / `main` | UT | `units/check-deploy-context.checks.py:126` | `assert target['awsProfile'] == 'stg-cde'` |
| `aws-context::main:127` / `main` | UT | `units/check-deploy-context.checks.py:127` | `assert run.call_args.args[0][:3] == ['/mock/aws', '--profile', 'stg-cde']` |
| `aws-context::main:134` / `main` | UT | `units/check-deploy-context.checks.py:134` | `assert error is failure` |
| `aws-context::main:136` / `main` | UT | `units/check-deploy-context.checks.py:136` | `raise AssertionError('identity rejection ignored')` |
| `aws-context::main:143` / `main` | UT | `units/check-deploy-context.checks.py:143` | `assert 'profile not found' in str(error)` |
| `aws-context::main:145` / `main` | UT | `units/check-deploy-context.checks.py:145` | `raise AssertionError('failed configured profile was accepted')` |
| `aws-context::main:146` / `main` | UT | `units/check-deploy-context.checks.py:146` | `assert run.call_count == 1` |
| `aws-context::main:147` / `main` | UT | `units/check-deploy-context.checks.py:147` | `assert run.call_args.args[0][2] == 'stg-cde'` |
| `aws-context::main:158` / `main` | UT | `units/check-deploy-context.checks.py:158` | `assert target['awsAccountId'] == '123456789012'` |
| `aws-context::main:159` / `main` | UT | `units/check-deploy-context.checks.py:159` | `assert target['awsExecutionAccountId'] == '999999999999'` |
| `aws-context::main:164` / `main` | UT | `units/check-deploy-context.checks.py:164` | `assert error is failure` |
| `aws-context::main:166` / `main` | UT | `units/check-deploy-context.checks.py:166` | `raise AssertionError('STS identity rejection ignored')` |
| `aws-context::main:169` / `main` | UT | `units/check-deploy-context.checks.py:169` | `assert MODULE.load_target(root, 'production', account_id='210987654321')['awsAccountId'] == '210987654321'` |
| `aws-context::main:175` / `main` | UT | `units/check-deploy-context.checks.py:175` | `assert 'AWS region ID is invalid' in str(error)` |
| `aws-context::main:177` / `main` | UT | `units/check-deploy-context.checks.py:177` | `raise AssertionError('invalid AWS region ID was accepted')` |
| `aws-context::main:182` / `main` | UT | `units/check-deploy-context.checks.py:182` | `assert MODULE.main() == 1` |
| `aws-context::main:183` / `main` | UT | `units/check-deploy-context.checks.py:183` | `assert 'Deploy context: FAIL: identity rejected' in errors.getvalue()` |
| `unknown/cloudformation_schema.checks.py:21` / `main` | UT | `units/cloudformation_schema.checks.py:21` | `assert snapshot_errors(root) == []` |
| `unknown/cloudformation_schema.checks.py:40` / `main` | UT | `units/cloudformation_schema.checks.py:40` | `assert catalog.literal_errors('EC2.SecurityGroup', 'Tags[].Value', '日本語') == []` |
| `unknown/cloudformation_schema.checks.py:41` / `main` | UT | `units/cloudformation_schema.checks.py:41` | `assert catalog.literal_errors('EC2.SecurityGroupIngress', 'Description', '日本語') == []` |
| `unknown/cloudformation_schema.checks.py:43` / `main` | UT | `units/cloudformation_schema.checks.py:43` | `assert catalog.property_schema('Events.Rule', 'EventPattern')['type'] == ['string', 'object']` |
| `unknown/cloudformation_schema.checks.py:69` / `main` | UT | `units/cloudformation_schema.checks.py:69` | `assert 'BearerTokenAuthenticationEnabled' in logs['properties']` |
| `unknown/cloudformation_schema.checks.py:70` / `main` | UT | `units/cloudformation_schema.checks.py:70` | `assert catalog.literal_errors('Logs.LogGroup', 'KmsKeyId', 'arn:aws:kms:ap-northeast-1:123456789012:key/11111111-2222-3333-4444-555555555555') == []` |
| `unknown/cloudformation_schema.checks.py:75` / `main` | UT | `units/cloudformation_schema.checks.py:75` | `assert catalog.literal_errors('Logs.LogGroup', 'KmsKeyId', 'not-used')` |
| `unknown/cloudformation_schema.checks.py:76` / `main` | UT | `units/cloudformation_schema.checks.py:76` | `assert catalog.literal_errors('Logs.LogGroup', 'RetentionInDays', '30') == []` |
| `unknown/cloudformation_schema.checks.py:77` / `main` | UT | `units/cloudformation_schema.checks.py:77` | `assert catalog.literal_errors('Logs.LogGroup', 'RetentionInDays', '31')` |
| `unknown/cloudformation_schema.checks.py:85` / `main` | UT | `units/cloudformation_schema.checks.py:85` | `assert catalog.required_properties('Athena.WorkGroup') == {'Name'}` |
| `unknown/cloudformation_schema.checks.py:86` / `main` | UT | `units/cloudformation_schema.checks.py:86` | `assert catalog.literal_errors('Athena.WorkGroup', 'State', 'ENABLED') == []` |
| `unknown/cloudformation_schema.checks.py:87` / `main` | UT | `units/cloudformation_schema.checks.py:87` | `assert catalog.literal_errors('Athena.WorkGroup', 'State', 'unexpected')` |
| `unknown/cloudformation_schema.checks.py:88` / `main` | UT | `units/cloudformation_schema.checks.py:88` | `assert catalog.property_schema('DynamoDB.Table', 'KeySchema[].AttributeName')['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:127` / `main` | UT | `units/cloudformation_schema.checks.py:127` | `assert catalog.property_schema('IAM.User', 'UserName')['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:128` / `main` | UT | `units/cloudformation_schema.checks.py:128` | `assert catalog.property_schema('IAM.User', 'LoginProfile.PasswordResetRequired')['type'] == 'boolean'` |
| `unknown/cloudformation_schema.checks.py:129` / `main` | UT | `units/cloudformation_schema.checks.py:129` | `assert 'object' in catalog.property_schema('IAM.User', 'Policies[].PolicyDocument')['type']` |
| `unknown/cloudformation_schema.checks.py:130` / `main` | UT | `units/cloudformation_schema.checks.py:130` | `assert catalog.required_properties('GuardDuty.MalwareProtectionPlan') == {'ProtectedResource', 'Role'}` |
| `unknown/cloudformation_schema.checks.py:131` / `main` | UT | `units/cloudformation_schema.checks.py:131` | `assert 'GuardDuty.MalwareProtectionPlan.MalwareProtectionPlanId=IDENTIFIER_OUTPUT' in (materials / 'GuardDuty_MalwareProtectionPlan.properties').read_text(encoding='utf-8').splitlines()` |
| `unknown/cloudformation_schema.checks.py:134` / `main` | UT | `units/cloudformation_schema.checks.py:134` | `assert catalog.property_schema('GuardDuty.MalwareProtectionPlan', 'MalwareProtectionPlanId')['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:135` / `main` | UT | `units/cloudformation_schema.checks.py:135` | `assert catalog.schema('GuardDuty.MalwareProtectionPlan')['primaryIdentifier'] == ['/properties/MalwareProtectionPlanId']` |
| `unknown/cloudformation_schema.checks.py:138` / `main` | UT | `units/cloudformation_schema.checks.py:138` | `assert catalog.literal_errors('GuardDuty.MalwareProtectionPlan', 'Actions.Tagging.Status', 'ENABLED') == []` |
| `unknown/cloudformation_schema.checks.py:140` / `main` | UT | `units/cloudformation_schema.checks.py:140` | `assert 'EC2.EIP.AllocationId=IDENTIFIER_OUTPUT' in eip` |
| `unknown/cloudformation_schema.checks.py:141` / `main` | UT | `units/cloudformation_schema.checks.py:141` | `assert 'EC2.EIP.PublicIp=IDENTIFIER_OUTPUT' in eip` |
| `unknown/cloudformation_schema.checks.py:142` / `main` | UT | `units/cloudformation_schema.checks.py:142` | `assert 'Glue.Database.DatabaseName=' in (materials / 'Glue_Database.properties').read_text(encoding='utf-8')` |
| `unknown/cloudformation_schema.checks.py:145` / `main` | UT | `units/cloudformation_schema.checks.py:145` | `assert 'SNS.Topic.TopicArn' not in (materials / 'SNS_Topic.properties').read_text(encoding='utf-8')` |
| `unknown/cloudformation_schema.checks.py:160` / `main` | UT | `units/cloudformation_schema.checks.py:160` | `assert 'LakeFormation.PrincipalPermissions.PrincipalIdentifier=IDENTIFIER_OUTPUT' in lake` |
| `unknown/cloudformation_schema.checks.py:161` / `main` | UT | `units/cloudformation_schema.checks.py:161` | `assert 'LakeFormation.PrincipalPermissions.ResourceIdentifier=IDENTIFIER_OUTPUT' in lake` |
| `unknown/cloudformation_schema.checks.py:170` / `main` | UT | `units/cloudformation_schema.checks.py:170` | `assert len(scheduler) == 43` |
| `unknown/cloudformation_schema.checks.py:171` / `main` | UT | `units/cloudformation_schema.checks.py:171` | `assert 'Scheduler.Schedule.Arn=' not in scheduler` |
| `unknown/cloudformation_schema.checks.py:172` / `main` | UT | `units/cloudformation_schema.checks.py:172` | `assert DesignSchemaCatalog(root).cloudformation_type('Scheduler.Schedule') == 'AWS::Scheduler::Schedule'` |
| `unknown/cloudformation_schema.checks.py:173` / `main` | UT | `units/cloudformation_schema.checks.py:173` | `assert catalog.required_properties('Scheduler.Schedule') == {'FlexibleTimeWindow', 'ScheduleExpression', 'Target'}` |
| `unknown/cloudformation_schema.checks.py:182` / `main` | UT | `units/cloudformation_schema.checks.py:182` | `assert catalog.literal_errors('Scheduler.Schedule', 'FlexibleTimeWindow.Mode', 'OFF') == []` |
| `unknown/cloudformation_schema.checks.py:183` / `main` | UT | `units/cloudformation_schema.checks.py:183` | `assert catalog.literal_errors('Scheduler.Schedule', 'FlexibleTimeWindow.Mode', 'WRONG')` |
| `unknown/cloudformation_schema.checks.py:214` / `main` | UT | `units/cloudformation_schema.checks.py:214` | `assert catalog.literal_errors('SSM.MaintenanceWindowTask', 'TaskType', 'RUN_COMMAND') == []` |
| `unknown/cloudformation_schema.checks.py:215` / `main` | UT | `units/cloudformation_schema.checks.py:215` | `assert catalog.literal_errors('Config.ConfigRule', 'Source.Owner', 'AWS') == []` |
| `unknown/cloudformation_schema.checks.py:216` / `main` | UT | `units/cloudformation_schema.checks.py:216` | `assert resource_name_fields('SSM.Association') == ['AssociationName']` |
| `unknown/cloudformation_schema.checks.py:219` / `main` | UT | `units/cloudformation_schema.checks.py:219` | `assert resource_display_name('SSM.Association', rows) == 'patch-scan'` |
| `unknown/cloudformation_schema.checks.py:220` / `main` | UT | `units/cloudformation_schema.checks.py:220` | `assert resource_display_name('SSM.Association', rows[:1]) is None` |
| `unknown/cloudformation_schema.checks.py:32` / `main` | UT | `units/cloudformation_schema.checks.py:32` | `assert catalog.property_schema(resource_type, property_path)['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:50` / `main` | UT | `units/cloudformation_schema.checks.py:50` | `assert catalog.literal_errors(resource_type, property_path, 'not-used')` |
| `unknown/cloudformation_schema.checks.py:83` / `main` | UT | `units/cloudformation_schema.checks.py:83` | `raise AssertionError('non-schema Logs.LogGroup.Encryption was accepted')` |
| `unknown/cloudformation_schema.checks.py:180` / `main` | UT | `units/cloudformation_schema.checks.py:180` | `assert f'Scheduler.Schedule.{path}=' in scheduler` |
| `unknown/cloudformation_schema.checks.py:181` / `main` | UT | `units/cloudformation_schema.checks.py:181` | `assert catalog.property_schema('Scheduler.Schedule', path)` |
| `unknown/cloudformation_schema.checks.py:197` / `main` | UT | `units/cloudformation_schema.checks.py:197` | `assert DesignSchemaCatalog(root).cloudformation_type(kind) == 'AWS::' + kind.replace('.', '::', 1)` |
| `unknown/cloudformation_schema.checks.py:198` / `main` | UT | `units/cloudformation_schema.checks.py:198` | `assert LAYOUTS[kind] == 'independent'` |
| `unknown/cloudformation_schema.checks.py:204` / `main` | UT | `units/cloudformation_schema.checks.py:204` | `assert all((not line.partition('=')[0].split('.')[-1].lower().endswith('arn') for line in lines if line.endswith('=IDENTIFIER_OUTPUT')))` |
| `unknown/cloudformation_schema.checks.py:212` / `main` | UT | `units/cloudformation_schema.checks.py:212` | `assert catalog.literal_errors(kind, prop, value) == [], (kind, prop)` |
| `unknown/cloudformation_schema.checks.py:213` / `main` | UT | `units/cloudformation_schema.checks.py:213` | `assert catalog.literal_errors(kind, prop, 'INVALID_ENUM'), (kind, prop)` |
| `unknown/cloudformation_schema.checks.py:49` / `main` | UT | `units/cloudformation_schema.checks.py:49` | `assert catalog.literal_errors(resource_type, property_path, raw_value) == []` |
| `unknown/cloudformation_schema.checks.py:64` / `main` | UT | `units/cloudformation_schema.checks.py:64` | `assert catalog.literal_errors('Test.Union', 'Value', raw_value) == [], (node, raw_value)` |
| `unknown/cloudformation_schema.checks.py:66` / `main` | UT | `units/cloudformation_schema.checks.py:66` | `assert catalog.literal_errors('Test.Union', 'Value', raw_value), (node, raw_value)` |
| `unknown/cloudformation_schema.checks.py:122` / `main` | UT | `units/cloudformation_schema.checks.py:122` | `assert f'{resource_type}.{property_path}=' in lines, property_path` |
| `unknown/cloudformation_schema.checks.py:124` / `main` | UT | `units/cloudformation_schema.checks.py:124` | `assert 'type' in node` |
| `unknown/cloudformation_schema.checks.py:157` / `main` | UT | `units/cloudformation_schema.checks.py:157` | `assert f'{resource_type}.{path}=' in lines, path` |
| `unknown/cloudformation_schema.checks.py:158` / `main` | UT | `units/cloudformation_schema.checks.py:158` | `assert catalog.property_schema(resource_type, path)` |
| `unknown/cloudformation_schema.checks.py:168` / `main` | UT | `units/cloudformation_schema.checks.py:168` | `raise AssertionError(f'unsupported Athena.WorkGroup path: {path}')` |
| `unknown/cloudformation_schema.checks.py:202` / `main` | UT | `units/cloudformation_schema.checks.py:202` | `assert f'{kind}.{path}' in selected, (kind, path)` |
| `unknown/cloudformation_schema.checks.py:203` / `main` | UT | `units/cloudformation_schema.checks.py:203` | `assert catalog.property_schema(kind, path)` |
| `unknown/cloudformation_schema.checks.py:35` / `main` | UT | `units/cloudformation_schema.checks.py:35` | `assert catalog.literal_errors(spelling, property_path, value) == [], (spelling, value)` |
| `unknown/cloudformation_schema.checks.py:38` / `main` | UT | `units/cloudformation_schema.checks.py:38` | `assert any(('must match' in error for error in errors)), (spelling, value, errors)` |
| `unknown/cloudformation_schema.checks.py:126` / `main` | UT | `units/cloudformation_schema.checks.py:126` | `assert node['type'] == 'string'` |
| `unknown/comparison_core.checks.py:39` / `module` | UT | `units/comparison_core-unit.checks.py:39` | `assert projected == trail_expected, projected` |
| `unknown/comparison_core.checks.py:40` / `module` | UT | `units/comparison_core-unit.checks.py:40` | `assert all((row['property'] == trail_kind + prop for (_, row), (prop, _) in zip(trail_rows, trail_fields)))` |
| `unknown/comparison_core.checks.py:49` / `module` | UT | `units/comparison_core-unit.checks.py:49` | `raise AssertionError('unproven CloudTrail membership accepted')` |
| `unknown/comparison_core.checks.py:47` / `module` | UT | `units/comparison_core-unit.checks.py:47` | `assert 'array membership unresolved' in str(error)` |
| `unknown/comparison_core.checks.py:62` / `module` | UT | `units/comparison_core-unit.checks.py:62` | `assert tree == expected, (rows, tree)` |
| `unknown/comparison_core.checks.py:85` / `module` | UT | `units/comparison_core-unit.checks.py:85` | `assert tree == {'Stages': stages}, tree` |
| `unknown/comparison_core.checks.py:94` / `module` | UT | `units/comparison_core-unit.checks.py:94` | `raise AssertionError('ambiguous membership accepted: ' + path)` |
| `unknown/comparison_core.checks.py:91` / `module` | UT | `units/comparison_core-unit.checks.py:91` | `assert path in str(error)` |
| `unknown/comparison_core.checks.py:92` / `module` | UT | `units/comparison_core-unit.checks.py:92` | `assert tree == {'Existing': 1}, 'unresolved rows must not partially mutate the tree'` |
| `unknown/comparison_core.checks.py:105` / `module` | UT | `units/comparison_core-unit.checks.py:105` | `assert same(ref, dict(ref)) is False and same(ref, ResourceReference(ref)) is True` |
| `unknown/comparison_core.checks.py:107` / `module` | UT | `units/comparison_core-unit.checks.py:107` | `assert same(expression, safe_value(expression)) is False` |
| `unknown/comparison_core.checks.py:108` / `module` | UT | `units/comparison_core-unit.checks.py:108` | `assert safe_value({'Password': 'one', 'Arn': 'arn:aws:s3:::private'}) == {'Password': '<masked>', 'Arn': '<masked ARN/secret>'}` |
| `unknown/comparison_core.checks.py:150` / `module` | UT | `units/comparison_core-unit.checks.py:150` | `assert same(evaluate(chain), expected)` |
| `unknown/comparison_core.checks.py:151` / `module` | UT | `units/comparison_core-unit.checks.py:151` | `assert same(evaluate(chain), evaluate(select('0', split)))` |
| `unknown/comparison_core.checks.py:152` / `module` | UT | `units/comparison_core-unit.checks.py:152` | `assert evaluator.string_operand(evaluate(first))` |
| `unknown/comparison_core.checks.py:153` / `module` | UT | `units/comparison_core-unit.checks.py:153` | `assert not same(evaluate(chain), safe_value(expected))` |
| `unknown/comparison_core.checks.py:154` / `module` | UT | `units/comparison_core-unit.checks.py:154` | `assert not same(evaluate(chain), evaluate(select(0, {'Fn::Split': [',', first]})))` |
| `unknown/comparison_core.checks.py:155` / `module` | UT | `units/comparison_core-unit.checks.py:155` | `assert evaluator.string_operand(evaluate(select(0, getatt('Numbers')))) is False` |
| `unknown/comparison_core.checks.py:156` / `module` | UT | `units/comparison_core-unit.checks.py:156` | `assert evaluate(select(1, ['a', 'b'])) == 'b'` |
| `unknown/comparison_core.checks.py:157` / `module` | UT | `units/comparison_core-unit.checks.py:157` | `assert evaluate(select(1, {'Fn::Split': [':', 'zone:dns']})) == 'dns'` |
| `unknown/comparison_core.checks.py:158` / `module` | UT | `units/comparison_core-unit.checks.py:158` | `assert evaluate({'Fn::Split': [':', '']}) == ['']` |
| `unknown/comparison_core.checks.py:180` / `module` | UT | `units/comparison_core-unit.checks.py:157` | `assert evaluate(select(1, {'Fn::Split': [':', 'zone:dns']})) == 'dns'` |
| `unknown/design_catalog.checks.py:138` / `main` | UT | `units/design_catalog-unit.checks.py:12` | `assert not api_snapshot_errors(ROOT)` |
| `unknown/design_catalog.checks.py:140` / `main` | UT | `units/design_catalog-unit.checks.py:14` | `assert catalog.cloudformation_type('Macie.Session') == 'AWS::Macie::Session'` |
| `unknown/design_catalog.checks.py:142` / `main` | UT | `units/design_catalog-unit.checks.py:16` | `assert group['identityProperties'] == ['AwsAccountId', 'Namespace', 'GroupName']` |
| `unknown/design_catalog.checks.py:143` / `main` | UT | `units/design_catalog-unit.checks.py:17` | `assert group['identifierOutputs'] == ['Arn', 'PrincipalId']` |
| `unknown/design_catalog.checks.py:144` / `main` | UT | `units/design_catalog-unit.checks.py:18` | `assert group['source']['readOperations'] == ['ListGroups', 'DescribeGroup']` |
| `unknown/design_catalog.checks.py:145` / `main` | UT | `units/design_catalog-unit.checks.py:19` | `assert group['source']['updateOperation'] == 'UpdateGroup'` |
| `unknown/design_catalog.checks.py:146` / `main` | UT | `units/design_catalog-unit.checks.py:20` | `assert group['source']['deleteOperation'] == 'DeleteGroup'` |
| `unknown/design_catalog.checks.py:147` / `main` | UT | `units/design_catalog-unit.checks.py:21` | `assert catalog.required_design_properties(QUICKSIGHT_GROUP) == {'AwsAccountId', 'Namespace', 'GroupName'}` |
| `unknown/design_catalog.checks.py:160` / `main` | UT | `units/design_catalog-unit.checks.py:34` | `raise AssertionError('API design leaked into the CFn catalog')` |
| `unknown/design_catalog.checks.py:164` / `main` | IT | `integrations/issues_api_only.checks.py:46` | `assert result.returncode == 1 and 'CloudFormation unsupported' in result.stdout` |
| `unknown/design_catalog.checks.py:154` / `main` | UT | `units/design_catalog-unit.checks.py:28` | `raise AssertionError(f'unsupported CFn type accepted: {resource_type}')` |
| `unknown/export-design-pdf.checks.py:22` / `module` | IT | `integrations/export-design-pdf.checks.py:22` | `assert SPEC and SPEC.loader` |
| `unknown/export-design-pdf.checks.py:77` / `main` | IT | `integrations/export-design-pdf.checks.py:77` | `assert expected == {'dev-cde-vpc-a': 2, 'dev-cde-iam-role': 2, 'dev-cde-iam-role-two': 1, 'dev-cde-iam-policy': 1, 'appendix-dev-cde-vpc-policy': 2, 'stg-non-cde-vpc-a': 2}, expected` |
| `unknown/export-design-pdf.checks.py:85` / `main` | IT | `integrations/export-design-pdf.checks.py:85` | `assert '[Role](#dev-cde-iam-role)' in merged` |
| `unknown/export-design-pdf.checks.py:86` / `main` | IT | `integrations/export-design-pdf.checks.py:86` | `assert '[A](#dev-cde-vpc-a)' in merged` |
| `unknown/export-design-pdf.checks.py:87` / `main` | IT | `integrations/export-design-pdf.checks.py:87` | `assert '[A](#stg-non-cde-vpc-a)' in merged` |
| `unknown/export-design-pdf.checks.py:88` / `main` | IT | `integrations/export-design-pdf.checks.py:88` | `assert merged.count('{#appendix-dev-cde-vpc-policy}') == 1` |
| `unknown/export-design-pdf.checks.py:89` / `main` | IT | `integrations/export-design-pdf.checks.py:89` | `assert merged.count('](#appendix-dev-cde-vpc-policy)') == 2` |
| `unknown/export-design-pdf.checks.py:90` / `main` | IT | `integrations/export-design-pdf.checks.py:90` | `assert '[example](missing.md#example)' in merged` |
| `unknown/export-design-pdf.checks.py:91` / `main` | IT | `integrations/export-design-pdf.checks.py:91` | `assert '# 詳細設計書' not in merged` |
| `unknown/export-design-pdf.checks.py:92` / `main` | IT | `integrations/export-design-pdf.checks.py:92` | `assert '# dev / cde {#target-dev-cde .target-title .first-target}' in merged` |
| `unknown/export-design-pdf.checks.py:93` / `main` | IT | `integrations/export-design-pdf.checks.py:93` | `assert '# stg / non-cde {#target-stg-non-cde .target-title}' in merged` |
| `unknown/export-design-pdf.checks.py:94` / `main` | IT | `integrations/export-design-pdf.checks.py:94` | `assert '## IAM 詳細設計 {#service-dev-cde-iam .service-title .first-service}' in merged` |
| `unknown/export-design-pdf.checks.py:95` / `main` | IT | `integrations/export-design-pdf.checks.py:95` | `assert '## VPC 詳細設計 {#service-dev-cde-vpc .service-title}' in merged` |
| `unknown/export-design-pdf.checks.py:96` / `main` | IT | `integrations/export-design-pdf.checks.py:96` | `assert '## VPC 詳細設計 {#service-stg-non-cde-vpc .service-title .first-service}' in merged` |
| `unknown/export-design-pdf.checks.py:97` / `main` | IT | `integrations/export-design-pdf.checks.py:97` | `assert '\| No. \| Role \|\n\| ---: \| --- \|\n\| 1 \| [Role](#dev-cde-iam-role) \|\n\| 2 \| [RoleTwo](#dev-cde-iam-role-two) \|' in merged` |
| `unknown/export-design-pdf.checks.py:98` / `main` | IT | `integrations/export-design-pdf.checks.py:98` | `assert '\| No. \| Policy \|\n\| ---: \| --- \|\n\| 1 \| [Policy](#dev-cde-iam-policy) \|' in merged` |
| `unknown/export-design-pdf.checks.py:99` / `main` | IT | `integrations/export-design-pdf.checks.py:99` | `assert '\| No. \| Property \|\n\| ---: \| --- \|\n\| 1 \| RoleName \|' in merged` |
| `unknown/export-design-pdf.checks.py:100` / `main` | IT | `integrations/export-design-pdf.checks.py:100` | `assert '<a id="dev-cde-vpc-a"></a>\n\n#### EC2.VPC: A' in merged` |
| `unknown/export-design-pdf.checks.py:114` / `main` | IT | `integrations/export-design-pdf.checks.py:114` | `assert run.call_count == 1 and run.call_args.args[0] == ['weasyprint', '--info']` |
| `unknown/export-design-pdf.checks.py:115` / `main` | IT | `integrations/export-design-pdf.checks.py:115` | `assert output.read_bytes() == b'existing PDF'` |
| `unknown/export-design-pdf.checks.py:113` / `main` | IT | `integrations/export-design-pdf.checks.py:113` | `raise AssertionError('missing native libraries must stop PDF export')` |
| `unknown/export-design-pdf.checks.py:111` / `main` | IT | `integrations/export-design-pdf.checks.py:111` | `assert 'README.md#pdf-dependencies' in str(error) and missing_native in str(error)` |
| `unknown/glue_datazone_catalog.checks.py:102` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:12` | `assert snapshot_errors(ROOT) == []` |
| `unknown/glue_datazone_catalog.checks.py:111` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:21` | `assert catalog.required_properties('Glue.Catalog') == {'Name'}` |
| `unknown/glue_datazone_catalog.checks.py:112` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:22` | `assert catalog.required_properties('DataZone.Domain') == {'Name'}` |
| `unknown/glue_datazone_catalog.checks.py:113` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:23` | `assert catalog.required_properties('DataZone.Project') == {'DomainIdentifier', 'Name'}` |
| `unknown/glue_datazone_catalog.checks.py:114` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:24` | `assert catalog.required_properties('DataZone.DataSource') == {'DomainIdentifier', 'Name', 'ProjectIdentifier', 'Type'}` |
| `unknown/glue_datazone_catalog.checks.py:120` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:30` | `assert catalog.literal_errors('DataZone.Domain', 'DomainVersion', 'V2') == []` |
| `unknown/glue_datazone_catalog.checks.py:121` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:31` | `assert catalog.literal_errors('DataZone.DataSource', 'Type', 'GLUE') == []` |
| `unknown/glue_datazone_catalog.checks.py:110` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:20` | `assert catalog.schema(resource_type)['typeName'] == 'AWS::' + resource_type.replace('.', '::', 1)` |
| `unknown/glue_datazone_catalog.checks.py:130` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:19` | `assert CatalogId current value in Glue view` |
| `unknown/glue_datazone_catalog.checks.py:131` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:20` | `assert acquired Glue Catalog link in DataZone view` |
| `unknown/glue_datazone_catalog.checks.py:132` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:21` | `assert 'desired.resource.001.resourceType=Glue.Catalog' in glue_model` |
| `unknown/glue_datazone_catalog.checks.py:133` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:22` | `assert 'desired.row.001-001.value=[FederatedCatalog](#glue-federatedcatalog)' in glue_model` |
| `unknown/glue_datazone_catalog.checks.py:134` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:23` | `assert 'observed.row.001-001.value=PENDING_DEPLOY' in glue_model` |
| `unknown/glue_datazone_catalog.checks.py:135` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:24` | `assert 'desired.service.datazone.ownedCatalogResourceTypes=DataZone.Domain,DataZone.Project,DataZone.DataSource' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:136` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:25` | `assert 'desired.resource.003.resourceType=DataZone.DataSource' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:137` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:26` | `assert 'desired.row.003-003.value=[FederatedCatalog](glue.md#glue-federatedcatalog)' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:138` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:27` | `assert 'observed.row.003-003.value=federated-catalog' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:139` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:28` | `assert 'desired.row.003-007.value=GLUE' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:152` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:41` | `assert original == {path: path.read_bytes() for path in (glue, datazone)}` |
| `unknown/glue_datazone_catalog.checks.py:151` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:40` | `raise AssertionError('legacy model with internal-ID headings was silently adopted')` |
| `unknown/glue_datazone_catalog.checks.py:149` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:38` | `assert 'anchor must be unique and match its name' in str(error)` |
| `unknown/lambda_permission.checks.py:93` / `main` | UT | `units/lambda_permission-unit.checks.py:12` | `assert not layout_errors(ROOT)` |
| `unknown/lambda_permission.checks.py:94` / `main` | UT | `units/lambda_permission-unit.checks.py:13` | `assert formal_property('Permission.Action', FUNCTION) == PERMISSION + '.Action'` |
| `unknown/lambda_permission.checks.py:149` / `main` | IT | `integrations/lambda_permission.checks.py:66` | `assert properties(read_model(source)) == properties(HELPERS.text(values))` |
| `unknown/lambda_permission.checks.py:155` / `main` | IT | `integrations/lambda_permission.checks.py:72` | `assert path.read_bytes() == saved` |
| `unknown/lambda_permission.checks.py:109` / `main` | IT | `integrations/lambda_permission.checks.py:26` | `assert len(grouped) == parents * children` |
| `unknown/lambda_permission.checks.py:110` / `main` | IT | `integrations/lambda_permission.checks.py:27` | `assert '### Lambda.Permission' not in output` |
| `unknown/lambda_permission.checks.py:112` / `main` | IT | `integrations/lambda_permission.checks.py:29` | `assert 'Permission.Id' not in visible and 'Permission.FunctionName' not in visible` |
| `unknown/lambda_permission.checks.py:113` / `main` | IT | `integrations/lambda_permission.checks.py:30` | `assert visible.count('Permission.Action') == parents * children` |
| `unknown/lambda_permission.checks.py:114` / `main` | IT | `integrations/lambda_permission.checks.py:31` | `assert 'Permission.Principal' in visible or children == 0` |
| `unknown/lambda_permission.checks.py:115` / `main` | IT | `integrations/lambda_permission.checks.py:32` | `assert output.count('\| No. \| Property \| Value \| Source / Comment \|') == parents` |
| `unknown/lambda_permission.checks.py:117` / `main` | IT | `integrations/lambda_permission.checks.py:34` | `assert model_projection.linked_resource(path, '[permission-1-1](#lambda-app-dev-invoke-1-1)') == (PERMISSION, 'Invoke1_1')` |
| `unknown/model_files.checks.py:182` / `main` | IT | `integrations/model_files.checks.py:154` | `assert limit == 2 and len(units) == 1` |
| `unknown/model_files.checks.py:193` / `main` | IT | `integrations/model_files.checks.py:165` | `assert load_model(stack).values == values` |
| `unknown/model_files.checks.py:160` / `main` | IT | `integrations/model_files.checks.py:132` | `assert combined == text` |
| `unknown/model_files.checks.py:161` / `main` | IT | `integrations/model_files.checks.py:133` | `assert list(properties(combined).items()) == list(properties(text).items())` |
| `unknown/model_files.checks.py:162` / `main` | IT | `integrations/model_files.checks.py:134` | `assert all((len(content.splitlines()) <= 600 for content in output.values()))` |
| `unknown/model_files.checks.py:163` / `main` | IT | `integrations/model_files.checks.py:135` | `assert len(output) == (1 if count <= 600 else 1 + (count + 549) // 550)` |
| `unknown/model_files.checks.py:191` / `main` | IT | `integrations/model_files.checks.py:163` | `raise AssertionError('missing projection part accepted')` |
| `unknown/quicksight-display.checks.py:25` / `main` | UT | `units/quicksight-display-unit.checks.py:16` | `assert len(fields) == 15` |
| `unknown/quicksight-display.checks.py:30` / `main` | UT | `units/quicksight-display-unit.checks.py:29` | `assert shown == [[identity, prop.removeprefix(KIND + '.').removeprefix('DataSourceParameters.'), value, comment] for identity, prop, value, comment in source]` |
| `unknown/quicksight-display.checks.py:35` / `main` | IT | `integrations/quicksight-display.checks.py:22` | `assert not children` |
| `unknown/quicksight-display.checks.py:36` / `main` | IT | `integrations/quicksight-display.checks.py:23` | `assert restored[3:] == ['\| ' + ' \| '.join(row) + ' \|' for row in source]` |
| `unknown/regression_guard.checks.py:50` / `main` | IT | `integrations/regression_guard.checks.py:30` | `assert record['version'] == 1 and len(bytes.fromhex(record['salt'])) == 16` |
| `unknown/regression_guard.checks.py:51` / `main` | IT | `integrations/regression_guard.checks.py:31` | `assert bytes.fromhex(record['hash']) == guard.password_hash(password, bytes.fromhex(record['salt']))` |
| `unknown/regression_guard.checks.py:42` / `main` | IT | `integrations/regression_guard.checks.py:22` | `assert [path.name for path in root.iterdir()] == ['.lock'], 'service_source created extra files/directories'` |
| `unknown/regression_guard.checks.py:44` / `main` | IT | `integrations/regression_guard.checks.py:24` | `assert password not in saved` |
| `unknown/regression_guard.checks.py:48` / `main` | IT | `integrations/regression_guard.checks.py:28` | `assert lock.read_text(encoding='utf-8') == saved, 'service_source overwrote existing .lock'` |
| `unknown/regression_guard.checks.py:77` / `main` | IT | `integrations/regression_guard.checks.py:57` | `assert entry.call_count == 2` |
| `unknown/regression_guard.checks.py:91` / `main` | UT | `units/regression_guard-unit.checks.py:25` | `assert visible in output.getvalue() and 'fixture-private-password-and-hash' not in output.getvalue()` |
| `unknown/regression_guard.checks.py:47` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/regression_guard.checks.py:69` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/regression_guard.checks.py:81` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/regression_guard.checks.py:90` / `main` | UT | `units/regression_guard-unit.checks.py:24` | `assert guard.main() == 2` |
| `unknown/regression_guard.checks.py:66` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/resource_mode.checks.py:100` / `main` | IT | `integrations/resource_mode.checks.py:40` | `assert not (error := check(model())), error` |
| `unknown/resource_mode.checks.py:101` / `main` | IT | `integrations/resource_mode.checks.py:41` | `assert 'lower-kebab-case' in check(model(name='PRIVATE_SUBNET_01'))` |
| `unknown/resource_mode.checks.py:103` / `main` | IT | `integrations/resource_mode.checks.py:43` | `assert not (error := check(imported)), error` |
| `unknown/resource_mode.checks.py:104` / `main` | IT | `integrations/resource_mode.checks.py:44` | `assert 'PRIVATE_SUBNET_01' in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:105` / `main` | IT | `integrations/resource_mode.checks.py:45` | `assert not (error := check(model(name=None, mode='IMPORT'))), error` |
| `unknown/resource_mode.checks.py:107` / `main` | IT | `integrations/resource_mode.checks.py:47` | `assert '\| Name \|' not in output and 'Tags[]' not in output` |
| `unknown/resource_mode.checks.py:108` / `main` | IT | `integrations/resource_mode.checks.py:48` | `assert '### EC2.VPC\n' in output and '\| resourceMode \|' not in output` |
| `unknown/resource_mode.checks.py:109` / `main` | IT | `integrations/resource_mode.checks.py:49` | `assert 'lower-kebab-case' in check(model(name='PRIVATE_SUBNET_01', mode=None))` |
| `unknown/resource_mode.checks.py:110` / `main` | IT | `integrations/resource_mode.checks.py:50` | `assert not (error := check(model(mode=None))), error` |
| `unknown/resource_mode.checks.py:111` / `main` | IT | `integrations/resource_mode.checks.py:51` | `assert 'resource-mode:' not in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:132` / `main` | IT | `integrations/resource_mode.checks.py:65` | `assert not (error := check(tagged)), error` |
| `unknown/resource_mode.checks.py:133` / `main` | IT | `integrations/resource_mode.checks.py:66` | `assert '\| Tags[1].Key \| name \|' in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:140` / `main` | IT | `integrations/resource_mode.checks.py:73` | `assert 'lower-kebab-case' in check(mixed)` |
| `unknown/resource_mode.checks.py:144` / `main` | IT | `integrations/resource_mode.checks.py:77` | `assert 'provider schema violation' in check(bad)` |
| `unknown/resource_mode.checks.py:145` / `main` | IT | `integrations/resource_mode.checks.py:78` | `assert 'display Mapping property missing: EC2.VPC.Unknown' in check({**bad, 'desired.row.001-004.property': 'EC2.VPC.Unknown'})` |
| `unknown/resource_mode.checks.py:146` / `main` | IT | `integrations/resource_mode.checks.py:79` | `assert 'invalid resource row' in check({key: value for key, value in imported.items() if key != 'desired.row.001-001.comment'})` |
| `unknown/resource_mode.checks.py:148` / `main` | IT | `integrations/resource_mode.checks.py:81` | `assert 'requires the corresponding Tags[].Value' in check({key: value for key, value in model('EC2.Instance', 'LEGACY', 'IMPORT').items() if not key.startswith('desired.row.001-005.')})` |
| `unknown/resource_mode.checks.py:152` / `main` | IT | `integrations/resource_mode.checks.py:85` | `assert 'requires the corresponding Tags[].Key' in check({key: value for key, value in model('EC2.Instance', 'LEGACY', 'IMPORT').items() if not key.startswith('desired.row.001-004.')})` |
| `unknown/resource_mode.checks.py:158` / `main` | UT | `units/resource_mode-unit.checks.py:12` | `assert resource_mode({}) == 'CREATE'` |
| `unknown/resource_mode.checks.py:159` / `main` | IT | `integrations/resource_mode.checks.py:43` | `assert not (error := check(imported)), error` |
| `unknown/resource_mode.checks.py:171` / `main` | IT | `integrations/resource_mode.checks.py:103` | `assert resource_modes(stale.splitlines(), imported)['ec2-private_subnet_01'] == 'IMPORT'` |
| `unknown/resource_mode.checks.py:182` / `main` | UT | `units/resource_mode-unit.checks.py:19` | `assert naming_errors(root, 'CloudFront.CachePolicy', rows)` |
| `unknown/resource_mode.checks.py:183` / `main` | UT | `units/resource_mode-unit.checks.py:20` | `assert not naming_errors(root, 'CloudFront.CachePolicy', rows, 'IMPORT')` |
| `unknown/resource_mode.checks.py:184` / `main` | UT | `units/resource_mode-unit.checks.py:21` | `assert naming_errors(root, 'IAM.Role', [], 'IMPORT')` |
| `unknown/resource_mode.checks.py:185` / `main` | UT | `units/resource_mode-unit.checks.py:22` | `assert naming_errors(root, 'CodeBuild.Project', [], 'IMPORT')` |
| `unknown/resource_mode.checks.py:186` / `main` | IT | `integrations/resource_mode.checks.py:43` | `assert not (error := check(imported)), error` |
| `unknown/resource_mode.checks.py:188` / `main` | IT | `integrations/resource_mode.checks.py:115` | `assert SYNC.sync(root, True, 'dev', '123456789012', services=['ec2']) == 0` |
| `unknown/resource_mode.checks.py:189` / `main` | IT | `integrations/resource_mode.checks.py:116` | `assert SYNC.sync(root, False, 'dev', '123456789012', services=['ec2']) == 0` |
| `unknown/resource_mode.checks.py:190` / `main` | IT | `integrations/resource_mode.checks.py:117` | `assert snapshot_model(source) == before` |
| `unknown/resource_mode.checks.py:191` / `main` | IT | `integrations/resource_mode.checks.py:44` | `assert 'PRIVATE_SUBNET_01' in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:220` / `main` | IT | `integrations/resource_mode.checks.py:147` | `assert saved KMS view equals generated Markdown` |
| `unknown/resource_mode.checks.py:223` / `main` | IT | `integrations/resource_mode.checks.py:150` | `assert '### KMS.Alias' not in kms_path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:92` / `main` | IT | `integrations/resource_mode.checks.py:32` | `assert read_model(source) == original` |
| `unknown/resource_mode.checks.py:94` / `main` | IT | `integrations/resource_mode.checks.py:34` | `assert projected == {key: value for key, value in values.items() if not key.startswith('display.')}` |
| `unknown/resource_mode.checks.py:95` / `main` | IT | `integrations/resource_mode.checks.py:51` | `assert 'resource-mode:' not in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:96` / `main` | IT | `integrations/resource_mode.checks.py:36` | `assert 'resource-entry:' not in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:125` / `main` | IT | `integrations/resource_mode.checks.py:58` | `assert check(model(kind, None, 'CREATE', '表示名'))` |
| `unknown/resource_mode.checks.py:126` / `main` | IT | `integrations/resource_mode.checks.py:59` | `assert not (error := check(model(kind, 'LEGACY_NAME_01', 'IMPORT'))), error` |
| `unknown/resource_mode.checks.py:157` / `main` | IT | `integrations/resource_mode.checks.py:90` | `assert 'resourceMode must be CREATE or IMPORT' in check({**imported, 'desired.resource.001.resourceMode': invalid})` |
| `unknown/resource_mode.checks.py:179` / `main` | IT | `integrations/resource_mode.checks.py:111` | `raise AssertionError('stale generated view accepted')` |
| `unknown/resource_mode.checks.py:124` / `main` | IT | `integrations/resource_mode.checks.py:57` | `assert not (error := check(model(kind, None, 'IMPORT', label))), error` |
| `unknown/resource_mode.checks.py:168` / `main` | IT | `integrations/resource_mode.checks.py:100` | `raise AssertionError('invalid resourceMode metadata accepted')` |
| `unknown/resource_mode.checks.py:177` / `main` | IT | `integrations/resource_mode.checks.py:109` | `assert 'stale or missing' in str(error), error` |
| `unknown/resource_mode.checks.py:121` / `main` | UT | `units/resource_mode-unit.checks.py:35` | `assert bool(validator.errors) == (mode == 'CREATE'), (kind, mode, validator.errors)` |
| `unknown/rotation_schedule.checks.py:112` / `main` | IT | `integrations/rotation_schedule.checks.py:112` | `assert '\| SecretsManager.RotationSchedule.ExternalSecretRotationMetadata' not in metadata_output` |
| `unknown/rotation_schedule.checks.py:197` / `main` | IT | `integrations/rotation_schedule.checks.py:197` | `assert path.read_text().count('[key-current](kms.md#kms-app-dev-key)') == 2` |
| `unknown/rotation_schedule.checks.py:205` / `main` | IT | `integrations/rotation_schedule.checks.py:205` | `assert path.read_bytes() == saved[path]` |
| `unknown/rotation_schedule.checks.py:206` / `main` | IT | `integrations/rotation_schedule.checks.py:206` | `assert (path.parent / 'kms.md').read_bytes() != saved[path.parent / 'kms.md']` |
| `unknown/rotation_schedule.checks.py:207` / `main` | IT | `integrations/rotation_schedule.checks.py:207` | `assert 'kms-app-dev-renamed' in (path.parent / 'kms.md').read_text()` |
| `unknown/rotation_schedule.checks.py:208` / `main` | IT | `integrations/rotation_schedule.checks.py:208` | `assert properties(read_model(models / 'secretsmanager.properties')) == properties(HELPERS.text(values))` |
| `unknown/rotation_schedule.checks.py:215` / `main` | IT | `integrations/rotation_schedule.checks.py:215` | `assert 'kms-app-dev-key' not in path.read_text()` |
| `unknown/rotation_schedule.checks.py:216` / `main` | IT | `integrations/rotation_schedule.checks.py:216` | `assert path.read_text().count('[key-current](kms.md#kms-app-dev-renamed)') == 2` |
| `unknown/rotation_schedule.checks.py:88` / `main` | IT | `integrations/rotation_schedule.checks.py:88` | `assert len(children) == count` |
| `unknown/rotation_schedule.checks.py:90` / `main` | IT | `integrations/rotation_schedule.checks.py:90` | `assert '### SecretsManager.RotationSchedule' not in output` |
| `unknown/rotation_schedule.checks.py:91` / `main` | IT | `integrations/rotation_schedule.checks.py:91` | `assert 'app-dev-secret-1_rotate：属性の設定値' in output` |
| `unknown/rotation_schedule.checks.py:93` / `main` | IT | `integrations/rotation_schedule.checks.py:93` | `assert model_projection.linked_resource(path, '[PENDING_DEPLOY](#secretsmanager-app-dev-secret-1_rotate)') == (ROTATION, 'Secret1Rotation')` |
| `unknown/rotation_schedule.checks.py:111` / `main` | IT | `integrations/rotation_schedule.checks.py:111` | `assert f'\| RotationSchedule.ExternalSecretRotationMetadata[{index // 2 + 1}].{field} \| `{value}` \|' in metadata_output` |
| `unknown/rotation_schedule.checks.py:166` / `main` | IT | `integrations/rotation_schedule.checks.py:166` | `assert '\| Id \|' not in rendered` |
| `unknown/security_group_tables.checks.py:104` / `main` | UT | `units/security_group_tables-unit.checks.py:12` | `assert not layout_errors(REPOSITORY)` |
| `unknown/security_group_tables.checks.py:109` / `main` | UT | `units/security_group_tables-unit.checks.py:17` | `assert LAYOUTS[resource_type]['display'] == 'rule-table'` |
| `unknown/security_group_tables.checks.py:111` / `main` | UT | `units/security_group_tables-unit.checks.py:19` | `assert selected - {'GroupId'} <= COMMENTS.keys()` |
| `unknown/security_group_tables.checks.py:133` / `main` | IT | `integrations/security_group_tables.checks.py:32` | `assert not errors(DESIGN), errors(DESIGN)` |
| `unknown/security_group_tables.checks.py:136` / `main` | IT | `integrations/security_group_tables.checks.py:35` | `assert path.read_bytes() == original` |
| `unknown/security_group_tables.checks.py:141` / `main` | IT | `integrations/security_group_tables.checks.py:40` | `assert validator.model_service_metadata(model_path, catalog[0]) == metadata[path]` |
| `unknown/security_group_tables.checks.py:142` / `main` | IT | `integrations/security_group_tables.checks.py:41` | `assert not validator.errors, validator.errors` |
| `unknown/security_group_tables.checks.py:156` / `main` | IT | `integrations/security_group_tables.checks.py:43` | `assert not errors(short_design), errors(short_design)` |
| `unknown/security_group_tables.checks.py:157` / `main` | IT | `integrations/security_group_tables.checks.py:44` | `assert expanded_design(short_design) == expanded_design(DESIGN)` |
| `unknown/security_group_tables.checks.py:158` / `main` | IT | `integrations/security_group_tables.checks.py:45` | `assert not errors(DESIGN)` |
| `unknown/security_group_tables.checks.py:159` / `main` | IT | `integrations/security_group_tables.checks.py:46` | `assert 'observed.row.002-001.comment=一意に識別するID\n' in generated` |
| `unknown/security_group_tables.checks.py:160` / `main` | IT | `integrations/security_group_tables.checks.py:47` | `assert 'desired.row.001-004.comment=所属するVPCのID\n' in generated` |
| `unknown/security_group_tables.checks.py:161` / `main` | IT | `integrations/security_group_tables.checks.py:48` | `assert 'desired.row.002-005.comment=通信元として許可するSecurity GroupのID\n' in generated` |
| `unknown/security_group_tables.checks.py:162` / `main` | IT | `integrations/security_group_tables.checks.py:49` | `assert 'comment=通信先として許可するSecurity GroupのID\n' in generated` |
| `unknown/security_group_tables.checks.py:163` / `main` | IT | `integrations/security_group_tables.checks.py:50` | `assert 'comment=Security Group' not in generated` |
| `unknown/security_group_tables.checks.py:164` / `main` | IT | `integrations/security_group_tables.checks.py:51` | `assert 'desired.row.001-002.property=EC2.SecurityGroup.GroupDescription\n' in generated` |
| `unknown/security_group_tables.checks.py:165` / `main` | IT | `integrations/security_group_tables.checks.py:52` | `assert 'desired.row.001-002.value=`Application access`\n' in generated` |
| `unknown/security_group_tables.checks.py:166` / `main` | IT | `integrations/security_group_tables.checks.py:53` | `assert 'desired.row.001-004.property=EC2.SecurityGroup.VpcId\n' in generated` |
| `unknown/security_group_tables.checks.py:167` / `main` | IT | `integrations/security_group_tables.checks.py:54` | `assert 'desired.row.001-004.value=[vpc-app-dev](vpc.md#vpc-vpc-app-dev)\n' in generated` |
| `unknown/security_group_tables.checks.py:168` / `main` | IT | `integrations/security_group_tables.checks.py:55` | `assert 'observed.row.001-004.value=vpc-00000001\n' in generated` |
| `unknown/security_group_tables.checks.py:169` / `main` | IT | `integrations/security_group_tables.checks.py:56` | `assert generated.count('.property=EC2.SecurityGroup.GroupDescription\n') == 2` |
| `unknown/security_group_tables.checks.py:170` / `main` | IT | `integrations/security_group_tables.checks.py:57` | `assert 'desired.row.006-004.value=Project\n' in generated` |
| `unknown/security_group_tables.checks.py:171` / `main` | IT | `integrations/security_group_tables.checks.py:58` | `assert 'desired.row.006-007.value=dev\n' in generated` |
| `unknown/security_group_tables.checks.py:172` / `main` | IT | `integrations/security_group_tables.checks.py:59` | `assert 'desired.resource.002.resourceType=EC2.SecurityGroupIngress' in generated` |
| `unknown/security_group_tables.checks.py:173` / `main` | IT | `integrations/security_group_tables.checks.py:60` | `assert 'desired.resource.002.logicalId=IngressOne' in generated` |
| `unknown/security_group_tables.checks.py:174` / `main` | IT | `integrations/security_group_tables.checks.py:61` | `assert 'desired.resource.002.parentProperty=EC2.SecurityGroupIngress.GroupId' in generated` |
| `unknown/security_group_tables.checks.py:175` / `main` | IT | `integrations/security_group_tables.checks.py:62` | `assert 'desired.resource.002.parentReference=[GroupOne](#security-group-groupone)' in generated` |
| `unknown/security_group_tables.checks.py:176` / `main` | IT | `integrations/security_group_tables.checks.py:63` | `assert 'desired.resource.005.parentProperty=EC2.SecurityGroupEgress.GroupId' in generated` |
| `unknown/security_group_tables.checks.py:177` / `main` | IT | `integrations/security_group_tables.checks.py:64` | `assert 'desired.resource.006.logicalId=GroupTwo' in generated` |
| `unknown/security_group_tables.checks.py:178` / `main` | IT | `integrations/security_group_tables.checks.py:65` | `assert 'desired.row.002-001.value=[IngressOne](#security-group-ingressone)' in generated` |
| `unknown/security_group_tables.checks.py:179` / `main` | IT | `integrations/security_group_tables.checks.py:66` | `assert 'observed.row.002-001.value=`sgr-00000001`' in generated` |
| `unknown/security_group_tables.checks.py:180` / `main` | IT | `integrations/security_group_tables.checks.py:67` | `assert 'desired.row.002-005.value=[GroupTwo](#security-group-grouptwo)' in generated` |
| `unknown/security_group_tables.checks.py:181` / `main` | IT | `integrations/security_group_tables.checks.py:68` | `assert 'observed.row.002-005.value=PENDING_DEPLOY' in generated` |
| `unknown/security_group_tables.checks.py:182` / `main` | IT | `integrations/security_group_tables.checks.py:69` | `assert 'SecurityGroupRuleId' not in generated and '<!--' not in generated` |
| `unknown/security_group_tables.checks.py:183` / `main` | IT | `integrations/security_group_tables.checks.py:70` | `assert 'desired.note.' not in generated and '=—' not in generated` |
| `unknown/security_group_tables.checks.py:184` / `main` | IT | `integrations/security_group_tables.checks.py:71` | `assert model_projection.linked_resource(path, '[sgr-00000001](#security-group-ingressone)') == ('EC2.SecurityGroupIngress', 'IngressOne')` |
| `unknown/security_group_tables.checks.py:185` / `main` | IT | `integrations/security_group_tables.checks.py:72` | `assert VALIDATOR.rendered_policy_design(path) == DESIGN` |
| `unknown/security_group_tables.checks.py:188` / `main` | IT | `integrations/security_group_tables.checks.py:75` | `assert len(children) == 4` |
| `unknown/security_group_tables.checks.py:189` / `main` | IT | `integrations/security_group_tables.checks.py:76` | `assert children['security-group-ingressthree']['logicalId'] == 'IngressThree'` |
| `unknown/security_group_tables.checks.py:190` / `main` | IT | `integrations/security_group_tables.checks.py:77` | `assert [row[2] for row in children['security-group-ingresstwo']['rows']] == ['`PENDING_DEPLOY`', '`icmpv6`', '`128`', '`0`', '`2001:db8::/64`']` |
| `unknown/security_group_tables.checks.py:192` / `main` | IT | `integrations/security_group_tables.checks.py:79` | `assert inline == [['EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol', '`-1`'], ['EC2.SecurityGroup.SecurityGroupEgress[].CidrIp', '`0.0.0.0/0`'], ['EC2.SecurityGroup.SecurityGroupEgress[].Description', '`IPv4 outbound`'], ['EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol', '`-1`'], ['EC2.SecurityGroup.SecurityGroupEgress[].CidrIp', '`10.1.0.0/16`']]` |
| `unknown/security_group_tables.checks.py:201` / `main` | IT | `integrations/security_group_tables.checks.py:88` | `assert not errors(inbound_only), errors(inbound_only)` |
| `unknown/security_group_tables.checks.py:202` / `main` | IT | `integrations/security_group_tables.checks.py:89` | `assert '### EC2.SecurityGroup: GroupTwo' in DESIGN` |
| `unknown/security_group_tables.checks.py:205` / `main` | IT | `integrations/security_group_tables.checks.py:92` | `assert not errors(no_tags), errors(no_tags)` |
| `unknown/security_group_tables.checks.py:206` / `main` | IT | `integrations/security_group_tables.checks.py:93` | `assert 'EC2.SecurityGroup.Tags[]' not in '\n'.join(security_group_table_lines(no_tags.splitlines()))` |
| `unknown/security_group_tables.checks.py:211` / `main` | IT | `integrations/security_group_tables.checks.py:98` | `assert not errors(inline_peer), errors(inline_peer)` |
| `unknown/security_group_tables.checks.py:212` / `main` | IT | `integrations/security_group_tables.checks.py:99` | `assert any(('EC2.SecurityGroup.SecurityGroupIngress[].SourceSecurityGroupId \| [PENDING_DEPLOY](#security-group-grouptwo)' in line for line in security_group_table_lines(inline_peer.splitlines())))` |
| `unknown/security_group_tables.checks.py:235` / `main` | IT | `integrations/security_group_tables.checks.py:122` | `assert not errors(moved), errors(moved)` |
| `unknown/security_group_tables.checks.py:237` / `main` | IT | `integrations/security_group_tables.checks.py:124` | `assert moved_children['security-group-egressone']['parentLogicalId'] == 'GroupTwo'` |
| `unknown/security_group_tables.checks.py:238` / `main` | IT | `integrations/security_group_tables.checks.py:125` | `assert moved_children['security-group-egressone']['logicalId'] == 'EgressOne'` |
| `unknown/security_group_tables.checks.py:240` / `main` | IT | `integrations/security_group_tables.checks.py:127` | `assert '\| FromPort \|' not in DESIGN and '\| ToPort \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:241` / `main` | IT | `integrations/security_group_tables.checks.py:128` | `assert '.property=Port\n' not in generated` |
| `unknown/security_group_tables.checks.py:249` / `main` | IT | `integrations/security_group_tables.checks.py:136` | `assert port_properties('—', '-1') == {}` |
| `unknown/security_group_tables.checks.py:250` / `main` | IT | `integrations/security_group_tables.checks.py:137` | `assert port_properties('—', 'icmpv6') == {}` |
| `unknown/security_group_tables.checks.py:251` / `main` | IT | `integrations/security_group_tables.checks.py:138` | `assert 'SecurityGroupRuleId' not in DESIGN` |
| `unknown/security_group_tables.checks.py:252` / `main` | IT | `integrations/security_group_tables.checks.py:139` | `assert '\| SourceSecurityGroupId \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:253` / `main` | IT | `integrations/security_group_tables.checks.py:140` | `assert '\| DestinationSecurityGroupId \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:254` / `main` | IT | `integrations/security_group_tables.checks.py:141` | `assert '.property=EC2.SecurityGroupIngress.SourceSecurityGroupId\n' in generated` |
| `unknown/security_group_tables.checks.py:255` / `main` | IT | `integrations/security_group_tables.checks.py:142` | `assert '.property=EC2.SecurityGroupEgress.DestinationSecurityGroupId\n' in generated` |
| `unknown/security_group_tables.checks.py:256` / `main` | IT | `integrations/security_group_tables.checks.py:143` | `assert 'rule-id:' not in generated` |
| `unknown/security_group_tables.checks.py:257` / `main` | IT | `integrations/security_group_tables.checks.py:144` | `assert 'アプリケーションの通信を制御するSG' not in generated` |
| `unknown/security_group_tables.checks.py:258` / `main` | IT | `integrations/security_group_tables.checks.py:145` | `assert '\| Tags \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:259` / `main` | IT | `integrations/security_group_tables.checks.py:146` | `assert 'security-group-tags' not in generated` |
| `unknown/security_group_tables.checks.py:113` / `main` | UT | `units/security_group_tables-unit.checks.py:21` | `assert 'EC2.SecurityGroup' in catalog[1][f'EC2.SecurityGroup.SecurityGroup{direction}[].{prop}']` |
| `unknown/security_group_tables.checks.py:154` / `main` | UT | `units/security_group_tables-unit.checks.py:42` | `assert invalid.errors, (filename, service, kinds)` |
| `unknown/security_group_tables.checks.py:220` / `main` | IT | `integrations/security_group_tables.checks.py:107` | `assert not errors(text), errors(text)` |
| `unknown/security_group_tables.checks.py:223` / `main` | IT | `integrations/security_group_tables.checks.py:110` | `assert path.read_bytes() == source` |
| `unknown/security_group_tables.checks.py:224` / `main` | IT | `integrations/security_group_tables.checks.py:111` | `assert model.count('.resourceType=EC2.SecurityGroup\n') == 2` |
| `unknown/security_group_tables.checks.py:225` / `main` | IT | `integrations/security_group_tables.checks.py:112` | `assert 'desired.resource.002.anchor=security-group-grouptwo\n' in model` |
| `unknown/security_group_tables.checks.py:226` / `main` | IT | `integrations/security_group_tables.checks.py:113` | `assert '.resourceType=EC2.SecurityGroupIngress' not in model` |
| `unknown/security_group_tables.checks.py:227` / `main` | IT | `integrations/security_group_tables.checks.py:114` | `assert '.resourceType=EC2.SecurityGroupEgress' not in model` |
| `unknown/security_group_tables.checks.py:228` / `main` | IT | `integrations/security_group_tables.checks.py:115` | `assert 'desired.note.' not in model` |
| `unknown/security_group_tables.checks.py:229` / `main` | IT | `integrations/security_group_tables.checks.py:116` | `assert ('.property=EC2.SecurityGroup.Tags[].Key' in model) == (tag_line in text)` |
| `unknown/security_group_tables.checks.py:248` / `main` | IT | `integrations/security_group_tables.checks.py:135` | `assert port_properties(display, protocol) == {'FromPort': f'`{first}`', 'ToPort': f'`{last}`'}` |
| `unknown/security_group_tables.checks.py:309` / `main` | IT | `integrations/security_group_tables.checks.py:196` | `assert any((message in error for error in failures)), (message, failures)` |
| `unknown/security_group_tables.checks.py:317` / `main` | IT | `integrations/security_group_tables.checks.py:204` | `raise AssertionError('invalid horizontal rule must not generate a model')` |
| `unknown/validation_cache.checks.py:88` / `main` | IT | `integrations/validation_cache.checks.py:25` | `assert PassCache(root, directory=directory).service_key(entry) != before` |
| `unknown/validation_cache.checks.py:98` / `main` | IT | `integrations/validation_cache.checks.py:25` | `assert PassCache(root, directory=directory).service_key(entry) != before` |
| `unknown/validation_scope.checks.py:197` / `main` | UT | `units/validation_scope-unit.checks.py:23` | `assert active_scope(root, True) is None` |
| `unknown/validation_scope.checks.py:199` / `main` | UT | `units/validation_scope-unit.checks.py:25` | `assert active_scope(root) is None` |
| `unknown/validation_scope.checks.py:203` / `main` | UT | `units/validation_scope-unit.checks.py:29` | `assert active_scope(root) == scope` |
| `unknown/validation_scope.checks.py:260` / `main` | IT | `integrations/validation_scope.checks.py:219` | `assert len(scoped_files(root, 'model', '.properties', scope)) == 4` |
| `unknown/validation_scope.checks.py:264` / `main` | IT | `integrations/validation_scope.checks.py:223` | `assert not validator.errors, validator.errors` |
| `unknown/validation_scope.checks.py:275` / `main` | IT | `integrations/validation_scope.checks.py:234` | `assert len(workers) == 4 and (not validator.errors), validator.errors` |
| `unknown/validation_scope.checks.py:276` / `main` | IT | `integrations/validation_scope.checks.py:235` | `assert validator.generated_models_checked` |
| `unknown/validation_scope.checks.py:286` / `main` | IT | `integrations/validation_scope.checks.py:247` | `assert any(('outside validation scope' in error for error in validator.errors))` |
| `unknown/validation_scope.checks.py:294` / `main` | IT | `integrations/validation_scope.checks.py:262` | `assert any(('missing design anchor' in error for error in rejected.errors)), rejected.errors` |
| `unknown/validation_scope.checks.py:316` / `main` | IT | `integrations/validation_scope.checks.py:284` | `assert any(('invalid design JSON' in error for error in rejected.errors))` |
| `unknown/validation_scope.checks.py:321` / `main` | IT | `integrations/validation_scope.checks.py:289` | `assert full.errors and 'logs' in '\n'.join(full.errors)` |
| `unknown/validation_scope.checks.py:325` / `main` | IT | `integrations/validation_scope.checks.py:293` | `assert result.returncode and 'validation scope missing' in result.stderr` |
| `unknown/validation_scope.checks.py:329` / `main` | IT | `integrations/validation_scope.checks.py:297` | `assert result.returncode and 'outside active task validation scope' in result.stderr` |
| `unknown/validation_scope.checks.py:283` / `main` | IT | `integrations/validation_scope.checks.py:242` | `assert rejected.errors` |
| `unknown/validation_scope.checks.py:196` / `main` | UT | `units/validation_scope-unit.checks.py:22` | `raise AssertionError('missing/incomplete scope accepted')` |
| `unknown/validation_scope.checks.py:308` / `main` | IT | `integrations/validation_scope.checks.py:276` | `raise AssertionError('selected invalid design accepted')` |
| `unknown/validation_scope.checks.py:306` / `main` | IT | `integrations/validation_scope.checks.py:274` | `assert token in str(error), error` |

main/module検証地点の現在配置: integrations=305, units=232。

| `units/update-catalog-lock.checks.py:21` / `module` | UT | `units/update-catalog-lock.checks.py:21` | `assert SPEC and SPEC.loader` |
| `units/update-catalog-lock.checks.py:12` / `module` | UT | `units/update-catalog-lock.checks.py:12` | `raise SystemExit('Focused checks require assertions; run without -O')` |
| `units/update-catalog-lock.checks.py:32` / `main` | UT | `units/update-catalog-lock.checks.py:32` | `assert [path.name for path in MODULE.catalog_files()] == sorted(names)` |
| `units/validation-units.checks.py:7` / `module` | UT | `units/validation-units.checks.py:7` | `raise SystemExit('Focused checks require assertions; run without -O')` |
| `units/validation-units.checks.py:34` / `main` | UT | `units/validation-units.checks.py:34` | `assert MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch('01_initialize.md')` |
| `units/validation-units.checks.py:35` / `main` | UT | `units/validation-units.checks.py:35` | `assert not MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch('initialize.md')` |
| `units/validation_cache-unit.checks.py:7` / `module` | UT | `units/validation_cache-unit.checks.py:7` | `raise SystemExit('Focused checks require assertions; run without -O')` |
| `units/validation_cache-unit.checks.py:163` / `module` | UT | `units/validation_cache-unit.checks.py:163` | `raise SystemExit(run(__file__))` |
| `units/validation_cache-unit.checks.py:16` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:16` | `assert cache.load(key) is None` |
| `units/validation_cache-unit.checks.py:18` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:18` | `assert cache.load(key) == 17` |
| `units/validation_cache-unit.checks.py:19` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:19` | `assert PassCache(root, fresh=True, directory=directory).load(key) is None` |
| `units/validation_cache-unit.checks.py:26` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:26` | `assert PassCache(root, directory=directory).key('catalog') == key` |
| `units/validation_cache-unit.checks.py:28` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:28` | `assert PassCache(root, directory=directory).key('catalog') == key` |
| `units/validation_cache-unit.checks.py:30` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:30` | `assert cache.load(key) is None` |
| `units/validation_cache-unit.checks.py:49` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:49` | `assert read_inputs(values)[0][1]['value'] == 'first'` |
| `units/validation_cache-unit.checks.py:51` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:51` | `assert read_inputs(values)[0][1]['value'] == 'second', 'later invocations must see edits'` |
| `units/validation_cache-unit.checks.py:62` / `check_cache_location` | UT | `units/validation_cache-unit.checks.py:62` | `raise AssertionError('cache directory inside repository accepted')` |
| `units/validation_cache-unit.checks.py:158` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:158` | `assert tasks.contracts(project)['tasks/first.md'] == original` |
| `units/validation_cache-unit.checks.py:23` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:23` | `assert cache.load(key) is None` |
| `units/validation_cache-unit.checks.py:37` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:37` | `assert added != before` |
| `units/validation_cache-unit.checks.py:39` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:39` | `assert PassCache(root, directory=directory).key('catalog') != added` |
| `units/validation_cache-unit.checks.py:41` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:41` | `assert PassCache(root, directory=directory).key('catalog') == before` |
| `units/validation_cache-unit.checks.py:44` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:44` | `assert design_material_files(root) is design_material_files(root)` |
| `units/validation_cache-unit.checks.py:130` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:130` | `assert scans.call_count == 2` |
| `units/validation_cache-unit.checks.py:156` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:156` | `assert import_scope.selected(project) == ('dev', 'cde', 'iam')` |
| `units/validation_cache-unit.checks.py:104` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:104` | `assert scans.call_count == 1` |
| `units/validation_cache-unit.checks.py:105` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:105` | `assert selections.call_count == 1` |
| `units/validation_cache-unit.checks.py:108` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:108` | `assert import_scope.selected(project) == ('dev', 'cde', 'sqs')` |
| `units/validation_cache-unit.checks.py:129` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:129` | `assert read(path) is cached` |
| `units/validation_cache-unit.checks.py:149` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:149` | `raise AssertionError(f'contract {change} was not detected')` |
| `units/validation_cache-unit.checks.py:103` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:103` | `assert import_scope.selected(project) == ('dev', 'cde', 'sqs')` |
| `units/validation_cache-unit.checks.py:107` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:107` | `assert import_scope.selected(project) == ('dev', 'cde', 's3')` |
| `units/validation_cache-unit.checks.py:116` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:116` | `assert import_scope.read_context(project) == before` |
| `units/validation_cache-unit.checks.py:117` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:117` | `assert read(path) is cached` |
| `units/validation_cache-unit.checks.py:119` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:119` | `assert read(path) is not cached` |
| `units/validation_cache-unit.checks.py:134` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:134` | `assert import_scope.selected(project) == ('dev', 'cde', 'sqs')` |
| `units/validation_cache-unit.checks.py:147` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:147` | `assert 'changed during validation' in str(error)` |
| `units/validation_cache-unit.checks.py:114` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:114` | `assert import_scope.read_context(project)[2] == path.absolute()` |
| `units/validation_cache-unit.checks.py:115` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:115` | `assert read(path) is not cached` |
| `units/validation_cache-unit.checks.py:126` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:126` | `raise AssertionError('cached result bypassed Task read permission')` |
| `units/validation_cache-unit.checks.py:128` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:128` | `assert read(path) is not cached` |
| `units/validation_cache-unit.checks.py:124` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:124` | `assert 'outside selected' in str(error)` |

| `integrations/design_catalog.checks.py:77` / `main` | IT | `integrations/design_catalog.checks.py:77` | `assert len(bad_values) == len(expected_errors) == 23` |
| `integrations/design_catalog.checks.py:80` / `main` | IT | `integrations/design_catalog.checks.py:80` | `assert not schema.api_value_errors(MACIE_JOB, job_schema, VALUES, '')` |
| `integrations/design_catalog.checks.py:81` / `main` | IT | `integrations/design_catalog.checks.py:81` | `assert not schema.job_errors(VALUES)` |
| `integrations/design_catalog.checks.py:22` / `main` | IT | `integrations/design_catalog.checks.py:22` | `assert '### QuickSight.Group: reader-group' in group_model` |
| `integrations/design_catalog.checks.py:23` / `main` | IT | `integrations/design_catalog.checks.py:23` | `assert '\| QuickSight.Group.PrincipalId \| `PENDING_DEPLOY` \|' in group_model` |
| `integrations/design_catalog.checks.py:24` / `main` | IT | `integrations/design_catalog.checks.py:24` | `assert 'QuickSight.Group.Arn' not in group_model and 'arn:' not in group_model` |
| `integrations/design_catalog.checks.py:88` / `main` | IT | `integrations/design_catalog.checks.py:88` | `assert all((any((message in error for error in errors)) for message in expected)), (values, expected, errors)` |
| `integrations/design_catalog.checks.py:104` / `main` | IT | `integrations/design_catalog.checks.py:104` | `raise AssertionError('wrong S3 link label accepted')` |
| `integrations/design_catalog.checks.py:113` / `main` | IT | `integrations/design_catalog.checks.py:113` | `raise AssertionError('bucketCriteria accepted with a fixed bucket table')` |
| `integrations/design_catalog.checks.py:102` / `main` | IT | `integrations/design_catalog.checks.py:102` | `assert 'label must match its S3 Bucket' in str(error)` |
| `integrations/design_catalog.checks.py:111` / `main` | IT | `integrations/design_catalog.checks.py:111` | `assert 'conflicts with bucketCriteria' in str(error)` |

## 共通fixture・検証補助

| 現在のファイル | 内容 |
|---|---|
| `support/aws_mapping_compare_fixtures.py` | outcome |
| `support/aws_mapping_display_fixtures.py` | fixture |
| `support/aws_mapping_fixtures.py` | import/定数/共通fixture |
| `support/blueprint_loop_fixtures.py` | events, make_project_fixture, make_loop_fixture |
| `support/check_model_aws_fixtures.py` | check, expect, shape_value, remove_tokens, set_path, Offline, FakeResource, acquired, model_text, offline_network |
| `support/cloudformation_deploy_fixtures.py` | units, states, rejects, Fake, starts, finish, StubAws, DeliveryAws |
| `support/compare_environments_fixtures.py` | path, copy_inputs, cli |
| `support/deploy_preparation_fixtures.py` | fixture, arguments, invoke |
| `support/design_catalog_fixtures.py` | markdown, quicksight_group_markdown |
| `support/design_document_fixtures.py` | reference_fixture |
| `support/design_layout_fixtures.py` | catalog |
| `support/framework_input_isolation_fixtures.py` | import/定数/共通fixture |
| `support/glue_datazone_catalog_fixtures.py` | write_designs |
| `support/import_model_fixtures.py` | check, AwsCli, project_fixture, spec, metadata, binding, declaration, save_service, build_seed, fixture, aws, stage, correspondence, exclusions, logs_edit, publish_fixture, snapshot |
| `support/issues_api_only_fixtures.py` | cli_exit |
| `support/issues_scan_fixtures.py` | write, write_report, render_iac, fixture, task, compare, mutate_template, expect_error, concurrency, summary_fixture, protected_sources, scan_project |
| `support/json_yaml_document_hash_fixtures.py` | import/定数/共通fixture |
| `support/lambda_permission_fixtures.py` | fixture, rejects |
| `support/it_fixture_bundle.py` | fingerprint, protect, build, bundle, source |
| `support/it_workspace.py` | _copy_tree, populate（可変Project seedのみ） |
| `support/rotation_schedule_fixtures.py` | fixture |
| `support/model_design_fixtures.py` | model, text, roundtrip, root, project, main |
| `support/model_files_fixtures.py` | import/定数/共通fixture |
| `support/model_parameter_inputs_fixtures.py` | rejected, declaration, fixture, root |
| `support/model_sources.py` | write_model, write_fixture_files, snapshot_model, catalog_display |
| `support/model_templates_fixtures.py` | rejected, fixture, role_model, config_model, write_fixture, install_candidate, root, common_shape_template |
| `support/policy_tables_fixtures.py` | import/定数/共通fixture |
| `support/producer_identifier_reference_fixtures.py` | rejected |
| `support/pytest_cli.py` | Diagnostics, run |
| `support/quicksight_display_fixtures.py` | import/定数/共通fixture |
| `support/raw_bucket_name_reference_fixtures.py` | rejected |
| `support/regression_guard_fixtures.py` | rejected |
| `support/resource_mode_fixtures.py` | model |
| `support/security_group_tables_fixtures.py` | import/定数/共通fixture |
| `support/service_fixtures.py` | input_spec, service, build_typed_services, build_input_templates, typed_services, input_templates |
| `support/sync_model_fixtures.py` | build_generated_policy, generated_policy |
| `support/validation_cache_fixtures.py` | import/定数/共通fixture |
| `support/validation_scope_fixtures.py` | import/定数/共通fixture |
| `support/validator.py` | load, project, git_project, commit, write, schema_validator |
| `support/worktree_python_fixtures.py` | blocked |
| `support/worktree_task_fixtures.py` | git, contract, fixture, cli, start, finish_contract, retained |



## main/moduleの内部パターン

| ファイル / 入口 | ループ入力（パターン数） |
|---|---|
| `integrations/compact-model-sources.checks.py:41` | 5: `('false', '0', '', 'null', '`PENDING_DEPLOY`')` |
| `integrations/compact-model-sources.checks.py:57` | 3: `(False, 0, None)` |
| `integrations/compact-model-sources.checks.py:59` | 3: `({key: 'x', 'observed.row.017-023.property': 'wrong'}, {'observed.row.999-001.value': 'x'}, {'observed.row.017-023.state': 'unknown'})` |
| `integrations/compact-model-sources.checks.py:72` | 動的: `range(2)` |
| `integrations/compact-model-sources.checks.py:79` | 4: `('definition', 'resources', 'rows', 'parameters')` |
| `integrations/compact-model-sources.checks.py:81` | 3: `(None, [], {'Unknown': 'x'})` |
| `integrations/compact-model-sources.checks.py:47` | 2: `('property', 'comment')` |
| `integrations/compact-model-sources.checks.py:54` | 動的: `range(2)` |
| `integrations/compact-model-sources.checks.py:95` | 3: `(('preview', 'Common'), ('release', 'Common'), ('independent', 'Independent'))` |
| `integrations/compact-model-sources.checks.py:102` | 動的: `paths` |
| `integrations/comparison_core.checks.py:68` | 2: `[('utils.comparison_rows', 'utils.iac_values', 'iac_evaluation'), ('iac_evaluation', 'utils.iac_values', 'utils.comparison_rows')]` |
| `integrations/eventbridge-producer-name-reference.checks.py:105` | 3: `[('lambda', 'Lambda.Function', 'FunctionName'), ('sqs', 'SQS.Queue', 'QueueName'), ('iam', 'IAM.User', 'UserName')]` |
| `integrations/glue_datazone_catalog.checks.py:29` | 2: `((glue, glue_model), (datazone, datazone_model))` |
| `integrations/group-03-input-references.checks.py:128` | 2: `[('iam', 'IAM.InstanceProfile', 'IAM.InstanceProfile.InstanceProfileName'), ('kms', 'KMS.Key', None)]` |
| `integrations/human-inputs-group-05.checks.py:289` | 動的: `sorted(SERVICES)` |
| `integrations/lambda_permission.checks.py:20` | 4: `((1, 0, False), (1, 1, False), (2, 2, False), (2, 2, True))` |
| `integrations/lambda_permission.checks.py:38` | 2: `('parentProperty', 'parentReference')` |
| `integrations/lambda_permission.checks.py:48` | 10: `((output.replace('Permission.Action', 'Permission.Id', 1), 'must not be displayed'), (output.replace('Permission.Action', 'Permission.FunctionName', 1), 'must not be displayed'), (output.replace('<!-- lambda-permission: [', '<!-- lambda-permission: broken[', 1), 'invalid Lambda Permission metadata'), (output.replace('Permission.Action', 'Lambda.Permission.Action', 1), 'Permission.*'), (output.replace('<!-- lambda-permission:', '<!-- invalid-permission:', 1), 'complete identity'), (output.replace('<!-- logical-id: Invoke1_1 -->', '', 1), 'complete identity'), (output.replace('<!-- logical-id: Invoke1_2 -->', '<!-- logical-id: Invoke1_1 -->', 1), 'duplicate grouped'), (output.replace('Permission.Principal', 'Permission.Action', 1), 'duplicate Lambda Permission'), (output.replace('[Worker1]\\u0028#lambda-app-dev-worker-1\\u0029', '[Wrong]\\u0028#lambda-wrong\\u0029', 1), 'must reference enclosing'), (output.replace('"Lambda.Permission.Id"', '"Wrong.Id"', 1), 'invalid Lambda Permission metadata'))` |
| `integrations/model_files.checks.py:124` | 4: `(0, 600, 601, 1700)` |
| `integrations/model_files.checks.py:136` | 動的: `model_parts(source)` |
| `integrations/model_files.checks.py:142` | 動的: `range(1, 111)` |
| `integrations/model_files.checks.py:155` | 動的: `__import__('model_templates').source_inputs(stack) - {root / 'project.json'}` |
| `integrations/model_files.checks.py:129` | 動的: `old - output.keys() - {source}` |
| `integrations/model_impact.checks.py:279` | 3: `[('iam', 'IAM.Role', 'RoleName'), ('s3', 'S3.Bucket', 'BucketName'), ('lambda', 'Lambda.Function', 'FunctionName')]` |
| `integrations/model_impact.checks.py:283` | 5: `[('identifiers', check_identifiers), ('type', check_type_and_unknown), ('import', check_import_scope), ('selection', check_selection), ('cycles', check_cycles)]` |
| `integrations/regression_guard.checks.py:42` | 4: `('{}', 'not JSON', '{"version":1,"salt":"00","hash":"00"}', '{"version":1,"salt":null,"hash":"00"}')` |
| `integrations/resource_mode.checks.py:55` | 3: `('EC2.VPC', 'EC2.VPCEndpoint', 'EC2.Instance')` |
| `integrations/resource_mode.checks.py:89` | 4: `('', 'REFERENCE', 'create', 'IMPORT ')` |
| `integrations/resource_mode.checks.py:94` | 3: `(marker + '\n' + marker, marker.replace('IMPORT', 'REFERENCE'), marker.replace('private_subnet_01', 'missing'))` |
| `integrations/resource_mode.checks.py:56` | 3: `(None, '取得済みresource', 'InternalId')` |
| `integrations/rotation_schedule.checks.py:84` | 2: `(1, 2)` |
| `integrations/rotation_schedule.checks.py:101` | 動的: `list(metadata)` |
| `integrations/rotation_schedule.checks.py:105` | 動的: `enumerate((('Key', 'first'), ('Value', 'one'), ('Key', 'second'), ('Value', 'two')), 1)` |
| `integrations/rotation_schedule.checks.py:110` | 動的: `enumerate((('Key', 'first'), ('Value', 'one'), ('Key', 'second'), ('Value', 'two')))` |
| `integrations/rotation_schedule.checks.py:118` | 2: `('parentReference', 'parentProperty')` |
| `integrations/rotation_schedule.checks.py:122` | 4: `('[Missing](#missing)', '[Secret1](elsewhere.md#secretsmanager-app-dev-secret-1)', '[WrongLogicalId](#secretsmanager-app-dev-secret-1)', '[Secret1Rotation](#secretsmanager-app-dev-secret-1_rotate)')` |
| `integrations/rotation_schedule.checks.py:127` | 3: `(('desired.resource.002.parentProperty', ROTATION + '.Id'), ('desired.row.002-003.value', '[Secret2](#secretsmanager-app-dev-secret-2)'), ('desired.row.002-003.value', '[Wrong](#secretsmanager-app-dev-secret-1)'))` |
| `integrations/rotation_schedule.checks.py:132` | 1: `('002-003',)` |
| `integrations/rotation_schedule.checks.py:136` | 動的: `list(values.items())` |
| `integrations/rotation_schedule.checks.py:154` | 動的: `invalid_views` |
| `integrations/rotation_schedule.checks.py:161` | 2: `((SECRET, '001'), (ROTATION, '002'))` |
| `integrations/rotation_schedule.checks.py:179` | 2: `('001', '003')` |
| `integrations/rotation_schedule.checks.py:193` | 2: `('001', '003')` |
| `integrations/rotation_schedule.checks.py:180` | 2: `(('desired', '[Key](kms.md#kms-app-dev-key)'), ('observed', 'PENDING_DEPLOY'))` |
| `integrations/runtime-model.checks.py:39` | 動的: `range(2)` |
| `integrations/runtime-model.checks.py:43` | 3: `(template, source / 'parameters.yaml', source / 'bindings.json')` |
| `integrations/runtime-model.checks.py:52` | 3: `('instances: [', 'instances: {}\nunknown: true\n', 'instances: null\n')` |
| `integrations/security_group_tables.checks.py:106` | 2: `(no_rules, no_rules.replace(tag_line + '\n', ''))` |
| `integrations/security_group_tables.checks.py:129` | 8: `(('tcp', '443', 443, 443), ('udp', '1000-2000', 1000, 2000), ('6', '0-65535', 0, 65535), ('17', '53', 53, 53), ('icmp', 'Type=8, Code=0', 8, 0), ('58', 'Type=128, Code=0', 128, 0), ('1', 'Type=-1, Code=-1', -1, -1), ('icmpv6', 'Type=128, Code=-1', 128, -1))` |
| `integrations/security_group_tables.checks.py:194` | 動的: `bad` |
| `integrations/security_group_tables.checks.py:197` | 3: `(DESIGN.replace('\| Inbound \|', '\| invalid \|', 1), DESIGN.replace(' \| `tcp` \|', ' \| — \|', 1), DESIGN + '\n\| Direction \| IpProtocol \| Port \|\n\| --- \| --- \| --- \|\n')` |
| `integrations/service-parameter-inputs.checks.py:9` | 5: `('athena', 'codecommit', 'datazone', 'security-hub', 'sqs')` |
| `integrations/sync-existing-files.checks.py:83` | 動的: `protected` |
| `integrations/sync-existing-files.checks.py:98` | 2: `('AGENTS.md', 'README.md')` |
| `integrations/sync-existing-files.checks.py:105` | 2: `('AGENTS.md', 'README.md')` |
| `integrations/sync-existing-files.checks.py:111` | 2: `('AGENTS.md', 'README.md')` |
| `integrations/sync-existing-files.checks.py:118` | 動的: `protected` |
| `integrations/validation_scope.checks.py:164` | 3: `('dev', 'prod', 'stg')` |
| `integrations/validation_scope.checks.py:238` | 2: `({('unknown', 'cde', 'ec2')}, {('dev', 'cde', 'missing')})` |
| `integrations/validation_scope.checks.py:267` | 2: `((source.replace('EC2.Instance.InstanceType', 'EC2.Instance.EbsOptimized'), 'EbsOptimized'), (source.replace('`dev-app-cde-01`', '`UNSET`'), 'Name'))` |
| `integrations/validation_scope.checks.py:165` | 2: `('cde', 'non-cde')` |
| `integrations/validation_scope.checks.py:217` | 動的: `sorted(scope)` |
| `integrations/validation_scope.checks.py:198` | 動的: `enumerate((('InstanceId', f'[AppInstance](#ec2-{name})'), ('ImageId', '`ami-0123456789abcdef0`'), ('InstanceType', '`t3.micro`'), ('SubnetId', f'[subnet-app-{env}-{target}](vpc.md#{anchor})'), ('Tags[].Key', '`Name`'), ('Tags[].Value', f'`{name}`')), 1)` |
| `integrations/worktree_task.checks.py::main` | 19: `(check_sync_base_preserves_candidate, check_old_workflow_registry_is_ignored, check_success_and_empty, check_finalize_line_endings, check_incomplete_and_git_safety, check_dirty_base_and_retry, check_ahead_and_rebase_conflict, check_collisions_and_base_selection, check_directory_layout, check_metadata_storage, check_cleanup_failure_and_retry, check_merge_retry_and_commit_failure, check_human_approved_validation_failure, check_real_loop_integration, check_final_candidate_staleness, check_approved_model_reads, check_registered_normal_model_guard, check_model_operation_integration, check_model_refactor_integration)` |
| `units/array_display.checks.py:55` | 5: `('[0]', '[2]', '[01]', '[]', '[x]')` |
| `units/array_display.checks.py:62` | 3: `(('`[ "sg-one", "sg-two" ]`', 2), ('`["sg-one"]`', 1), ('`[]`', 1))` |
| `units/array_display.checks.py:77` | 2: `(('GuardDuty.Detector', [('Features.ONE', '`ENABLED`'), ('Features[].AdditionalConfiguration[].Name', '`nested`'), ('Features[].AdditionalConfiguration[].Status', '`ENABLED`'), ('Features.TWO', '`DISABLED`')], ['Features[1].ONE', 'Features[1].AdditionalConfiguration[1].Name', 'Features[1].AdditionalConfiguration[1].Status', 'Features[2].TWO']), ('CloudTrail.Trail', [('EventSelectors.DataResources[1].S3', '[one](#one)'), ('EventSelectors.DataResources[2].Lambda', '[two](#two)'), ('EventSelectors.IncludeManagementEvents', '`true`'), ('EventSelectors.IncludeManagementEvents', '`false`'), ('EventSelectors.DataResources[3].S3', '[three](#three)')], ['EventSelectors[1].DataResources[1].S3', 'EventSelectors[1].DataResources[2].Lambda', 'EventSelectors[1].IncludeManagementEvents', 'EventSelectors[2].IncludeManagementEvents', 'EventSelectors[2].DataResources[1].S3']))` |
| `units/array_display.checks.py:86` | 2: `(('CloudTrail.Trail', 'EventSelectors.IncludeManagementEvents', 'EventSelectors[1].IncludeManagementEvents'), ('S3.Bucket', 'BucketEncryption.BucketKeyEnabled', 'BucketEncryption[1].BucketKeyEnabled'))` |
| `units/array_display.checks.py:93` | 動的: `design_material_files(ROOT)` |
| `units/array_display.checks.py:95` | 動的: `path.read_text().splitlines()` |
| `units/check-deploy-context.checks.py:184` | 9: `(None, 123456789012, '', 'UNSET', '123', '1234567890123', ' 123456789012', '123456789012\n', '１２３４５６７８９０１２')` |
| `units/check-deploy-context.checks.py:196` | 8: `(None, 123, '', ' ', ' padded ', 'UNSET', 'bad\nprofile', 'bad\x00profile')` |
| `units/check-deploy-context.checks.py:139` | 2: `('cde', 'non-cde')` |
| `units/check-deploy-context.checks.py:169` | 2: `(False, True)` |
| `units/check-deploy-context.checks.py:140` | 2: `(False, True)` |
| `units/cloudformation_schema.checks.py:24` | 2: `(('IAM.Role', 'Description', ('Role for application logs', 'Cafe café ¡ÿ', 'tab\tline\nreturn\r', 'quotes \'" and ?%\\'), ('日本語の説明', 'emoji 😀', 'bad\x00', 'bad\x1f', 'bad\x7f', 'bad\x80', 'bad\xa0', 'badĀ', 'text\n日本語')), ('EC2.SecurityGroup', 'GroupDescription', ('Application access', 'aZ09 ._-:/()#,@[]+=&;{}!$*'), ('日本語の説明', 'café', 'tab\t', 'line\n', 'return\r', "quote'", 'quote"', 'question?', 'percent%', 'backslash\\', 'pipe\|', 'text\n日本語')))` |
| `units/cloudformation_schema.checks.py:44` | 2: `(('Events.Rule', 'EventPattern'), ('IAM.User', 'Policies[].PolicyDocument'))` |
| `units/cloudformation_schema.checks.py:53` | 7: `(({'type': ['object', 'array']}, ('{}', '[]'), ('42', 'true', '"text"', '{invalid')), ({'type': ['boolean', 'null']}, ('false', 'true', 'null'), ('0', '"null"', '{}')), ({'type': ['string', 'integer'], 'minimum': 2, 'minLength': 3}, ('2', 'abc'), ('1', 'ab')), ({'type': ['string', 'boolean'], 'enum': [False]}, ('false',), ('true', 'text')), ({'type': ['integer', 'number'], 'maximum': 3}, ('2', '2.5'), ('4', 'true')), ({'type': ['object', 'string'], 'const': {'enabled': True}}, ('{"enabled":true}',), ('{}', 'text')), ({'type': ['object', 'string'], 'pattern': '^allowed$'}, ('{}', 'allowed'), ('other',)))` |
| `units/cloudformation_schema.checks.py:91` | 動的: `{'IAM.User': ('UserName', 'Groups', 'LoginProfile.Password', 'LoginProfile.PasswordResetRequired', 'ManagedPolicyArns', 'Path', 'PermissionsBoundary', 'Policies[].PolicyName', 'Policies[].PolicyDocument', 'Tags[].Key', 'Tags[].Value'), 'SecretsManager.Secret': ('Type',), 'SecretsManager.RotationSchedule': ('ExternalSecretRotationMetadata[].Key', 'ExternalSecretRotationMetadata[].Value', 'ExternalSecretRotationRoleArn'), 'GuardDuty.MalwareProtectionPlan': ('Actions.Tagging.Status', 'ProtectedResource.S3Bucket.BucketName', 'ProtectedResource.S3Bucket.ObjectPrefixes[]', 'Role', 'Tags[].Key', 'Tags[].Value')}.items()` |
| `units/cloudformation_schema.checks.py:148` | 動的: `{'Glue.Connection': 'ConnectionInput ConnectionInput.AuthenticationConfiguration ConnectionInput.PhysicalConnectionRequirements ConnectionInput.AthenaProperties', 'Glue.Catalog': 'FederatedCatalog', 'Athena.WorkGroup': 'WorkGroupConfiguration WorkGroupConfiguration.EngineVersion WorkGroupConfiguration.ResultConfiguration WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration', 'LakeFormation.PrincipalPermissions': 'Catalog Permissions PermissionsWithGrantOption Principal Resource Principal.DataLakePrincipalIdentifier Resource.Catalog Resource.Database Resource.Table Resource.TableWithColumns Resource.Database.CatalogId Resource.Database.Name Resource.Table.CatalogId Resource.Table.DatabaseName Resource.Table.Name Resource.Table.TableWildcard Resource.TableWithColumns.CatalogId Resource.TableWithColumns.DatabaseName Resource.TableWithColumns.Name Resource.TableWithColumns.ColumnNames Resource.TableWithColumns.ColumnWildcard Resource.TableWithColumns.ColumnWildcard.ExcludedColumnNames', 'QuickSight.DataSource': 'Credentials.KeyPairCredentials Credentials.KeyPairCredentials.KeyPairUsername Credentials.KeyPairCredentials.PrivateKey Credentials.KeyPairCredentials.PrivateKeyPassphrase'}.items()` |
| `units/cloudformation_schema.checks.py:162` | 2: `('DataCatalog.DatabaseName', 'DataCatalog.TableName')` |
| `units/cloudformation_schema.checks.py:176` | 8: `('Name', 'FlexibleTimeWindow.Mode', 'ScheduleExpression', 'ScheduleExpressionTimezone', 'Target.Arn', 'Target.RoleArn', 'Target.Input', 'Target.RetryPolicy.MaximumRetryAttempts')` |
| `units/cloudformation_schema.checks.py:185` | 動的: `{'EC2.VPCBlockPublicAccessOptions': 'AccountId InternetGatewayBlockMode', 'EC2.VPCBlockPublicAccessExclusion': 'ExclusionId InternetGatewayExclusionMode VpcId SubnetId Tags[].Key Tags[].Value', 'Organizations.Policy': 'Id Name Type Content TargetIds', 'FMS.Policy': 'Id PolicyName IncludeMap.ACCOUNT IncludeMap.ORGUNIT ExcludeMap.ACCOUNT ExcludeResourceTags RemediationEnabled SecurityServicePolicyData.Type SecurityServicePolicyData.ManagedServiceData', 'SSM.PatchBaseline': 'Id Name OperatingSystem DefaultBaseline PatchGroups ApprovalRules.PatchRules[].ApproveAfterDays ApprovalRules.PatchRules[].PatchFilterGroup.PatchFilters[].Key', 'SSM.Association': 'AssociationId AssociationName Name Parameters Targets[].Key ScheduleExpression', 'SSM.MaintenanceWindow': 'WindowId Name Schedule ScheduleTimezone Duration Cutoff AllowUnassociatedTargets', 'SSM.MaintenanceWindowTarget': 'WindowTargetId WindowId Name ResourceType Targets[].Key', 'SSM.MaintenanceWindowTask': 'WindowTaskId WindowId Name TaskArn TaskType Targets[].Key TaskInvocationParameters.MaintenanceWindowRunCommandParameters.Parameters', 'Config.ConfigRule': 'ConfigRuleId ConfigRuleName Source.Owner Source.SourceIdentifier Source.CustomPolicyDetails.PolicyText Scope.ComplianceResourceTypes InputParameters EvaluationModes[].Mode'}.items()` |
| `units/cloudformation_schema.checks.py:206` | 4: `(('EC2.VPCBlockPublicAccessOptions', 'InternetGatewayBlockMode', 'block-bidirectional'), ('EC2.VPCBlockPublicAccessExclusion', 'InternetGatewayExclusionMode', 'allow-egress'), ('Organizations.Policy', 'Type', 'SERVICE_CONTROL_POLICY'), ('SSM.PatchBaseline', 'OperatingSystem', 'AMAZON_LINUX_2023'))` |
| `units/cloudformation_schema.checks.py:33` | 2: `(resource_type, catalog.canonical_type(resource_type))` |
| `units/cloudformation_schema.checks.py:48` | 3: `('{"source":["aws.ec2"]}', 'plain string', '{invalid json')` |
| `units/cloudformation_schema.checks.py:63` | 動的: `accepted` |
| `units/cloudformation_schema.checks.py:65` | 動的: `rejected` |
| `units/cloudformation_schema.checks.py:121` | 動的: `properties` |
| `units/cloudformation_schema.checks.py:156` | 動的: `paths.split()` |
| `units/cloudformation_schema.checks.py:201` | 動的: `paths.split()` |
| `units/cloudformation_schema.checks.py:34` | 動的: `accepted` |
| `units/cloudformation_schema.checks.py:36` | 動的: `rejected` |
| `units/comparison_core-unit.checks.py:37` | 3: `(trail_rows, trail_rows[::-1], trail_rows[::2] + trail_rows[1::2])` |
| `units/comparison_core-unit.checks.py:41` | 4: `(trail_rows[:3], trail_rows + [(trail_rows[0][0], dict(trail_rows[0][1], value='`false`'))], [('unknown', trail_rows[0][1]), *trail_rows[1:]], [(trail_rows[0][0], dict(trail_rows[0][1], property=trail_kind + 'EventSelectors[1].IncludeManagementEvents')), *trail_rows[1:]])` |
| `units/comparison_core-unit.checks.py:51` | 6: `[([('A', 1), ('B.C', None)], {'A': 1, 'B': {'C': None}}), ([('A[].K', 'a'), ('A[].V', 1), ('A[].K', 'a'), ('A[].V', 2)], {'A': [{'K': 'a', 'V': 1}, {'K': 'a', 'V': 2}]}), ([('A[2].K', 'b'), ('A[1].K', 'a')], {'A': [{'K': 'a'}, {'K': 'b'}]}), ([('A[]', [1, 1]), ('A[]', 2), ('B', 1), ('B', [2, 2])], {'A': [1, 1, 2], 'B': [1, 2, 2]}), ([('A[1].B[]', [1, 1]), ('A[2].B[]', [])], {'A': [{'B': [1, 1]}, {'B': []}]}), ([('A[2]', 'same'), ('A[1]', 'same')], {'A': ['same', 'same']})]` |
| `units/comparison_core-unit.checks.py:60` | 動的: `rows` |
| `units/comparison_core-unit.checks.py:81` | 3: `(rows, list(reversed(rows)), sorted(rows))` |
| `units/comparison_core-unit.checks.py:83` | 動的: `ordered` |
| `units/comparison_core-unit.checks.py:86` | 5: `('A[].B[].K', 'A[].B[1].K', 'A[1].B[].K', 'A[].B[]', 'A[0].K')` |
| `units/comparison_core-unit.checks.py:98` | 7: `[(True, 1), (1, 1.0), ('1', 1), (None, ''), ({}, []), ([1, 2], [2, 1]), ([1, 1], [1])]` |
| `units/comparison_core-unit.checks.py:159` | 6: `[(select(0, getatt('UnknownLength')), 'index 0, symbolic array minItems=0'), (select(1, getatt('DnsEntries')), 'index 1, symbolic array minItems=1'), (select(0, getatt('UnknownType')), 'array type is unproven'), (select(1, split), 'index 1, symbolic array minItems=1'), (select(getatt('Name'), ['a']), 'index is unproven'), ({'Fn::Split': [':', select(0, getatt('UnknownElement'))]}, 'string type is unproven')]` |
| `units/comparison_core-unit.checks.py:168` | 18: `[select(2, getatt('DnsEntries')), select(0, getatt('Name')), select(True, ['a']), select(-1, ['a']), select(1.0, ['a']), select('x', ['a']), select(1, ['a']), select(0, []), select(0, [None]), select(0, {}), {'Fn::Select': [0]}, {'Fn::Split': [':', getatt('DnsEntries')]}, {'Fn::Split': [':', select(0, getatt('Numbers'))]}, {'Fn::Split': ['', 'text']}, {'Fn::Split': [1, 'text']}, {'Fn::Split': [':', None]}, {'Fn::Split': [':']}, {'Fn::Join': ['', [select(0, getatt('Numbers'))]]}]` |

| `units/update-catalog-lock.checks.py:28` | 動的: `(PurePosixPath, PureWindowsPath)` |
| `units/update-catalog-lock.checks.py:29` | 動的: `names` |
| `units/update-catalog-lock.checks.py:32` | 動的: `MODULE.catalog_files()` |

| `integrations/design_catalog.checks.py:82` | 動的: `zip(bad_values, expected_errors, strict=True)` |
| `integrations/design_catalog.checks.py:84` | 動的: `values.items()` |
| `integrations/design_catalog.checks.py:28` | 動的: `VALUES.items()` |
| `integrations/design_catalog.checks.py:29` | 動的: `VALUES.items()` |
| `integrations/design_catalog.checks.py:88` | 動的: `expected` |
| `integrations/design_catalog.checks.py:88` | 動的: `errors` |

## IT 実行グループの完了記録

279関数・357パターンとは別の19実行グループ。direct_groupは既存main入口、moduleは既存トップレベルの最終到達地点を記録する。独立検証関数数には加算しない。

| 元パス | 入口 | 分類 | 現在の配置 | 実行方式 / グループ数 |
| --- | --- | --- | --- | --- |
| `compact-model-sources.checks.py` | `__module__` | IT | [integrations/compact-model-sources.checks.py](integrations/compact-model-sources.checks.py) | module / 1 |
| `comparison_core.checks.py` | `__module__` | IT | [integrations/comparison_core.checks.py](integrations/comparison_core.checks.py) | module / 1 |
| `design_catalog.checks.py` | `check_macie_inputs_and_tables` | UT | [units/design_catalog-unit.checks.py](units/design_catalog-unit.checks.py#L61) | pytest / 1 |
| `eventbridge-producer-name-reference.checks.py` | `__module__` | IT | [integrations/eventbridge-producer-name-reference.checks.py](integrations/eventbridge-producer-name-reference.checks.py) | module / 1 |
| `export-design-pdf.checks.py` | `main` | IT | [integrations/export-design-pdf.checks.py](integrations/export-design-pdf.checks.py#L41) | direct_group / 1 |
| `glue_datazone_catalog.checks.py` | `main` | IT | [integrations/glue_datazone_catalog.checks.py](integrations/glue_datazone_catalog.checks.py#L26) | direct_group / 1 |
| `group-03-input-references.checks.py` | `__module__` | IT | [integrations/group-03-input-references.checks.py](integrations/group-03-input-references.checks.py) | module / 1 |
| `lambda_permission.checks.py` | `main` | IT | [integrations/lambda_permission.checks.py](integrations/lambda_permission.checks.py#L29) | direct_group / 1 |
| `regression_guard.checks.py` | `check_install_and_verify` | UT | [units/regression_guard-unit.checks.py](units/regression_guard-unit.checks.py#L49) | pytest / 1 |
| `resource_mode.checks.py` | `main` | IT | [integrations/resource_mode.checks.py](integrations/resource_mode.checks.py#L50) | direct_group / 1 |
| `rotation_schedule.checks.py` | `main` | IT | [integrations/rotation_schedule.checks.py](integrations/rotation_schedule.checks.py#L50) | direct_group / 1 |
| `runtime-model.checks.py` | `check_loader_rejects_corrupt_and_unreadable_sources` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L88) | pytest / 1 |
| `security_group_tables.checks.py` | `main` | IT | [integrations/security_group_tables.checks.py](integrations/security_group_tables.checks.py#L27) | direct_group / 1 |
| `service-parameter-inputs.checks.py` | `__module__` | IT | [integrations/service-parameter-inputs.checks.py](integrations/service-parameter-inputs.checks.py) | module / 1 |
| `validate-blueprint.checks.py` | `main` | IT | [integrations/validate-blueprint.checks.py](integrations/validate-blueprint.checks.py#L22) | direct_group / 1 |
| `validation_cache::check_producer_inputs` | `check_producer_inputs` | IT | [integrations/attribute-reference-resolution.checks.py](integrations/attribute-reference-resolution.checks.py#L216) | direct_group / 1 | Producer parts→Consumer dependencies→PassCache; environment isolation | 統合先移管 |
| `validation_cache.checks.py` | `check_link_and_part_inputs` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L250) | pytest / 1 |
`model_templates.checks.py::check_expansion` also checks a substantive shared trust-policy change in both consumer outputs and unchanged regeneration bytes/exit status.

## 契約・公開処理の通常責務

| 元パス | ケース | 分類 | 現在の配置 | 実行方式 / 展開数 | 検証責務 | 変更 |
|---|---|---|---|---|---|---|
| `units/task-contract-unit.checks.py:96` | `check_task_change_rolls_back_publication` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L132) | pytest / 3 | scope/completed/suspendへの処理中変更とrollbackを確認 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:114` | `check_publication_preserves_contract` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L153) | pytest / 3 | running/completed/suspendの3条件で拒否時の既存・新規・削除対象不変を確認 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:131` | `check_source_guard_keeps_plan_consistency` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L192) | pytest / 1 | 通常の契約・保存・変更検出を維持 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:148` | `check_scope_change_during_planning` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L207) | pytest / 1 | 通常の契約・保存・変更検出を維持 | 予約専用検証を除去し既存assertを整理 |


| `model-validation-reuse` | `check_common_conditions_preserved` | IT | [integrations/model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py#L122) | pytest / 7 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_read_scope_lifetime` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L288) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_deferred_guard_and_cleanup` | IT | [integrations/model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py#L181) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_generation_failures_never_pass` | IT | [integrations/model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py#L217) | pytest / 4 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_authorization_before_memo_and_publication` | IT | [integrations/model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py#L261) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_scoped_validation_threads_and_failures` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L374) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |

## Static Mapping sharing acceptance

| Source | Case | Layer | Implementation | Execution / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `static-aws-mappings` | `check_import_and_owners_are_lazy` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L221) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_runtime_cache` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L267) | pytest / 1 | 現行Mappingの遅延読取・provider/root/scope分離・再利用（ファイル破損条件を削除） | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_parallel_services` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L302) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_runtime_full_reuse` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L323) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_runtime_failures` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L363) | pytest / 1 | 独立したread/runtime例外のsingle-flight・保持・再利用（parse破損条件を削除） | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_full_failure_isolation` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L394) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_stage_alias` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L452) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_readonly_defaults` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L536) | pytest / 1 | standalone監査へ埋込むField.copy_defaultの独立性（Mapping default差し替えを削除） | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_sync_mapping_lifetime` | IT | [integrations/model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py#L292) | pytest / 4 | 実syncのstage作成前登録・正常/例外解除・source共有 | 新規合成回帰 |

## Integrated generation and validation cases

| Origin | Case | Class | Location | Entry / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `units/sync-model-unit.checks.py` | `check_snapshot_conflict` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L195) | pytest / 13 | raw bytes矛盾・不存在・sealに加えentry/part/独立other-model/sidecar/Taskの差分と集合変更・外部bytes保持。Taskはconstructor自身の収集を検証 | 既存UTへ集約 |
| `units/sync-model-unit.checks.py` | `check_framework_write_does_not_discover` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L581) | pytest / 2 | framework writeをModel探索前に拒否 | 新仕様の回帰 |
| `units/sync-model-unit.checks.py` | `check_result_reuse_is_scoped` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L595) | pytest / 1 | CheckResultの状態・キー・候補scope再利用境界 | 新仕様の回帰 |
| `units/blueprint-loop-unit.checks.py` | `check_write_validator_stops_followups` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L632) | pytest / 2 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `units/blueprint-loop-unit.checks.py` | `check_staged_write_rejected` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L647) | pytest / 1 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `units/validation_cache-unit.checks.py` | `check_retained_common_key` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L139) | pytest / 1 | Task読取cacheの選択・権限分離、契約内容/改行/追加/削除/selectorの最終比較 | 新仕様の回帰 |

## Framework definitions outside sync candidates

| Original | Case | Layer | Current | Execution | Responsibility | Preservation |
| --- | --- | --- | --- | --- | --- | --- |

## Generation publication boundary assertion mapping

- `check_generation_counts` の回数・内容assertionはIT `check_normal_writer_contents` に統合。通常生成を別ケースで繰り返さない。
- `check_batch_input_change` はIT `check_input_mutation` と `check_publication_boundary`（契約変更を追加）へ統合。
- `check_stage_inputs_without_framework` の通常write保証はIT `check_stage_definition_sources` に統合。
- UT `check_file_rollback`、`check_publish_callback_rollback`、`check_generation_transaction_recovery` はIT `model_templates.check_transactions` の固有assertionへ統合。
- internal syncの実Git・生成・再読込はITへ移動。Fake runnerのContext/output・停止と軽量reader/Git差分判定はUTに残す。
- generated_policy seedは共有definitions_rootから1回生成。通常ケースはproject/Model/出力/契約だけをコピーし、定義変更ケースだけ専用rootを用意する。

| 元パス | 関数 | 分類 | 現在の配置 | 実行 / 条件数 | 検証責務 | 対応 |
|---|---|---|---|---|---|---|
| `units/sync-model-unit.checks.py` | `check_planned_outputs_and_boundary` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L296) | pytest / 1 | 保存bytesのno-op選別と明示パスTask境界 | 軽量判定 |
| `units/sync-model-unit.checks.py` | `check_final_git_paths` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L451) | pytest / 4 | Fake Gitの固定基準・正味差分とindex許可集合 | 軽量判定 |

| `units/sync-model-unit.checks.py` | `check_stage_dependency_selection` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L325) | pytest / 2 | Fake Model file listで入出向き依存と最小stageを選別 | 軽量依存選択 |

| `units/sync-model-unit.checks.py` | `check_git_baseline_fail_closed` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L469) | pytest / 1 | 公開git_pathsの共通reader委譲・同一例外伝播 | NUL解析・終了コード検証は共通UTへ移管 |

## IMPORT Model-only統合・削除と外部証跡

Model操作の値・承認・保存判定は既存UTへ集約する。Worktree側はMergeの最終候補統合と専用Delete Transactionの失敗修復を検証する。

| 元ケース | 現在の関数 | 種別 | 配置 | 入口 / 件数 | 検証責務 | 変更理由 |
|---|---|---|---|---|---|---|
| `import-resource-consolidation::check_model_operation_preserves_consumers` | `check_model_operation_preserves_consumers` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L562) | pytest / 2 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_rejects_unproved_changes` | `check_model_operation_rejects_unproved_changes` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L592) | pytest / 9 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_contract_scope` | `check_model_operation_contract_scope` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L625) | pytest / 8 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_row_correspondence` | `check_model_operation_row_correspondence` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L656) | pytest / 1 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_shape_preservation` | `check_model_operation_shape_preservation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L699) | pytest / 5 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_external_completion_proof` | `check_external_completion_proof` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L733) | pytest / 10 | read_proofの署名/期限/Task/Base/Scope、binding Task/worktree照合とrisk digest改ざん拒否、証跡保持/除去 | Import Receipt |
| `import-resource-consolidation::check_snapshot_proof_resigning_and_cleanup` | `check_snapshot_proof_resigning_and_cleanup` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L799) | pytest / 1 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_only_publication` | `check_model_only_publication` | IT | [integrations/model-operation-publication.checks.py](integrations/model-operation-publication.checks.py#L74) | pytest / 6 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `issue-18` | `check_import_snapshot_evidence` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L826) | pytest / 2 | diagnostics / authorization / finally | 実プロセス・Gitなし |
| `import-resource-consolidation::check_model_operation_integration` | `check_model_operation_integration` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L751) | direct / 1 | Import Mergeの実candidate検証・一意HEADのMergeとcleanup（Deleteは専用Transaction IT） | 統合境界のみ |

| `sync attachment staging` | `check_linked_attachments` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L370) | pytest / 2 | ローカル添付のバイト保持、欠落リンク失敗、復元と入力変更検出 | 新規 |

## Import Inventory 汎用取得

| `import-inventory::check_partial_acquisition_cannot_complete` | `check_partial_acquisition_cannot_complete` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L412) | pytest / 1 | 部分取得→Review→Publishで既存正本保持、未完了Receiptと追加AWS呼出なし | Import Inventory |
| `import-inventory::check_generic_acquisition_roundtrip` | `check_generic_acquisition_roundtrip` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L431) | pytest / 1 | DataZoneのCloudControl取得証跡→Review→dry-run Publish、複合IDと正本不変 | Import Inventory |
| `import-inventory::check_inventory_singleflight_and_isolation` | `check_inventory_singleflight_and_isolation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L843) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_context_api_singleflight_and_failures` | `check_context_api_singleflight_and_failures` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L877) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_cloudtrail_all_model_properties` | `check_cloudtrail_all_model_properties` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L894) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_tgw_provider_and_composite_identity` | `check_tgw_provider_and_composite_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L907) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_inventory_status_and_partial_retention` | `check_inventory_status_and_partial_retention` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L932) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_cloudcontrol_json_and_readonly_boundary` | `check_cloudcontrol_json_and_readonly_boundary` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L961) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_composite_identity_same_resource_only` | `check_composite_identity_same_resource_only` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L989) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_inventory_capability_outcomes` | `check_inventory_capability_outcomes` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1029) | pytest / 4 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_fetch_singleflight_and_trace` | `check_fetch_singleflight_and_trace` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1051) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_tgw_compare_provider_evaluation` | `check_tgw_compare_provider_evaluation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1079) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_legacy_adapter_api_counts` | `check_legacy_adapter_api_counts` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1116) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_acquisition_account_region_isolation` | `check_acquisition_account_region_isolation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1136) | pytest / 2 | Context隔離・CLI選択・Identity不明の拒否 | Import Inventory |
| `import-inventory::check_resource_type_cli_selection` | `check_resource_type_cli_selection` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1150) | pytest / 1 | Context隔離・CLI選択・Identity不明の拒否 | Import Inventory |
| `import-inventory::check_unknown_acquired_identity_rejected` | `check_unknown_acquired_identity_rejected` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1158) | pytest / 1 | Context隔離・CLI選択・Identity不明の拒否 | Import Inventory |

Athena ResultConfiguration EncryptionConfiguration.KmsKey regression in `integrations/issues_failed_services.checks.py::main_checks` uses synthetic Model loading, Key Arn selection, GetAtt/ImportValue, same/different keys, rejected KeyId/AliasName/AliasArn literals on either/both sides, rejected Alias Model references reported as uncompared on the authored leaf, and unresolved form/identity cases. The KMS matrix expects Alias reference construction to fail for KeyArn-only receiving contracts. Other KMS contracts retain their existing expectations.

## Atomic Model operation contracts and API boundaries

- `units/task-contract-unit.checks.py::check_batch_operation_contract`: five pairs,
  immutable normalized contract, duplicate/mixed/
  missing/malformed declarations and JSON/pointer/scope rejection.
- `units/import-model-unit.checks.py::check_batch_model_operation`: simultaneous five-pair
  semantic comparison and failure for a single missing observed transfer.
- `units/import-model-unit.checks.py::check_intermediate_source_context`: explicit parent
  despite a different environment selector, raw read/save without expansion or staging,
  one-use/no-op/fresh context behavior, concurrent input change and path/syntax rejection.
- Existing operation preservation/rejection cases retain their assertions; verification
  now lives in `model.operations`. Existing loop scheduler tests
  import validation.loop and exercise the compatibility CLI separately. Validator shared
  fixture imports validation.runner; no test cases were deleted for module movement.
- Production source helpers now live at `framework/scripts/model/sources.py`; the existing
  fixture stays `framework/scripts/tests/support/model_sources.py`. Shared dependency
  changes conservatively select all UTs through the existing mapping fallback.

| Original case | Case | Class | Current location | Execution / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `atomic/worktree_task` | `check_final_candidate_staleness` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L561) | direct / 1 | 実commit/rebase・検証後HEAD変更による最終Merge拒否 | 統合境界のみ |
| `atomic/import-model` | `check_intermediate_model_sources` | IT | [integrations/model-operation-publication.checks.py](integrations/model-operation-publication.checks.py#L123) | pytest / 1 | Git-free Model raw writes, prior-leaf retention on I/O error and real journal recovery before snapshot; managed authorization is checked separately | Added |

`units/import-model-unit.checks.py::check_explicit_reference_operation` (6 parameter cases)
covers typed local value/JSON/parentReference, external name/identifier and explicit D→D
reevaluation; undeclared changes and reference literalization fail. Existing test bodies
are retained. New IT cases use the existing Framework IT discovery/receipt runner;
no new runner or live AWS/consumer inputs are introduced.

| `atomic/batch-saves` | `check_batch_leaf_saves` | IT | [integrations/model-operation-publication.checks.py](integrations/model-operation-publication.checks.py#L161) | pytest / 1 | transfer saves retain all five sources, empty-reference retarget is no-op, delete removes all and final semantic check passes; base unchanged | Added |

| `import/references` | `check_reference_publication` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L467) | pytest / 3 | scalar/JSON Pointer参照の実保存再読込・表示復旧、権限contextごとのproducer読込、保存中raceのRollbackとReview後producer変更拒否 | Added |

## Generic Model dependency detach

| Original case | Case | Class | Current location | Execution / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `dependency/contract` | `check_dependency_detach_contract` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L266) | pytest / 1 | exact JSON/keys/IDs/scope, malformed/duplicate/conflicting declarations; ordinary design unchanged | Added |
| `dependency/stack-usage` | `check_stack_reference_usage` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1367) | pytest / 7 | synthetic Stack and Resource references, pointers/provenance, unrelated deletion meaning check, collision/missing/type/format/name/shape rejection | Added |
| `dependency/usage` | `check_generic_reference_usage` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1426) | pytest / 1 | service-a/service-b cycle, identical names with distinct IDs, source line and value, read-only state | Added |
| `dependency/shape` | `check_reference_active_shapes_and_documents` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1446) | pytest / 2 | active choice, inactive optional JSON/unused Definition, escaped JSON pointer, separate display links | Added |
| `dependency/unresolved` | `check_reference_fail_closed` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1470) | pytest / 4 | unknown fixed ID, cyclic name expansion, broken internal link and missing input fail closed | Added |
| `dependency/delete` | `check_value_preserving_detach_and_single_deletions` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1499) | pytest / 1 | independent value-preserving detach followed by two unchanged single-delete checks; other environment preserved | Added |
| `dependency/preservation` | `check_refactor_rejects_changes` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1523) | pytest / 10 | changed value/mode/anchor/observed/foreign consumer, identical-name retarget, scope, retained/undeclared reference and CREATE reject | Added |
| `dependency/integration` | `check_model_refactor_integration` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L796) | direct / 1 | 通常Model publicationとBase producer更新後の実Rebase・最終候補検証・Merge | 統合境界のみ |
| `dependency/bounded-read` | `check_reference_readonly_and_bounded_expansion` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1564) | pytest / 1 | one selected-service expansion for outgoing, selected target only for incoming, pending journal refusal without Model writes | Added |
| `dependency/structure` | `check_reference_structural_and_remaining_delete` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1623) | pytest / 1 | parentReference identity/role, structural detach and deletion with remaining name reference rejected | Added |
| `dependency/json-types` | `check_dependency_json_types_and_exact_detach` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1648) | pytest / 1 | declared JSON leaf detach, retained sibling reference, undeclared change, boolean/number type changes, escaped marker impersonation rejection | Added |
| `dependency/link-label` | `check_reference_embedded_link_label` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1683) | pytest / 1 | typed name in Markdown label and link target remain distinct fixed-ID usages | Added |

The existing IT cases retain their assertions and registrations after the runtime extraction:
blueprint-loop orchestration uses the CLI and validator API boundaries; deployment fixtures
copy the complete runtime; publication races are injected at GenerationInputs.verify;
Model-only imports avoid the presentation dependency; cache comparisons unwrap both CLI
and read API scopes; saved-validation tracing excludes candidate validators; publication
failure checks allow candidate validation; shared-input saves register a synthetic Task;
partial-cache validation spies on compare_generation with the full consumer scope.

## Approved suspend integration

| 元パス | ケース | 区分 | 現在の入口 | 実行 / 件数 | 責務 | 保持内容 |
| --- | --- | --- | --- | --- | --- | --- |
| `worktree_task.checks.py` | `check_approved_model_reads` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L600) | direct / 1 | 承認済suspendのModel実Git統合とIMPORT証跡欠落時のcommit前拒否（2条件） | 統合境界のみ |

既存 `check_suspend_and_resume` に状態非依存の契約参照、通常実行拒否、selector・構造・symlink拒否を追加。

承認入力の判定はWorktree guard UT、値保存判定はImport UT、実承認Mergeは専用ITへ集約する。Deleteの最終候補検証は承認で迂回できないことをWorktree model guard UTで検証する。
## User-selected IMPORT add / refresh / replace

| Origin | Case | Class | Location | Entry / conditions | Responsibility | Scope |
|---|---|---|---|---|---|---|
| `import-selected::check_selected_overwrite` | `check_selected_overwrite` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1716) | pytest / 2 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_identity_and_mode_boundary` | `check_overwrite_identity_and_mode_boundary` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1735) | pytest / 4 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_does_not_grant_unrelated_edits` | `check_overwrite_does_not_grant_unrelated_edits` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1745) | pytest / 8 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_refresh_new_rows_and_missing_properties` | `check_refresh_new_rows_and_missing_properties` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1768) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_duplicate_selection_and_destination_identity` | `check_overwrite_duplicate_selection_and_destination_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1786) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_selected_binding_switch_preserves_fixed_maps` | `check_selected_binding_switch_preserves_fixed_maps` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1798) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_reference_permission_is_property_scoped` | `check_overwrite_reference_permission_is_property_scoped` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1811) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_import_llm_choice_contract` | `check_import_llm_choice_contract` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1829) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_user_selected_overwrite_publication` | `check_user_selected_overwrite_publication` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L568) | pytest / 2 | bind/replaceの実保存と再読込、Review操作・Receipt一致、非選択Resource・他環境保持 | User-selected Import |
| `import-selected::check_mixed_add_refresh_single_publication` | `check_mixed_add_refresh_single_publication` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L611) | pytest / 2 | Add/Refreshの一括保存・再読込、単一saveと部分失敗Rollback、再取得なし | User-selected Import |
| `import-selected::check_replace_warns_incoming_references` | `check_replace_warns_incoming_references` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L641) | pytest / 1 | VPC replaceの実保存とincoming reference impact警告の連携 | User-selected Import |
| `import-selected::check_first_resource_uses_existing_source_format` | `check_first_resource_uses_existing_source_format` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L662) | pytest / 2 | 空入口/他環境なしと入口欠落/他環境ありの初回実保存、v2再読込・他環境不変 | User-selected Import |
| `import-selected::check_refresh_switches_definition_without_foreign_changes` | `check_refresh_switches_definition_without_foreign_changes` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L696) | pytest / 1 | Refreshの定義選択変更を実保存、非選択Resourceとstg定義保持 | User-selected Import |

## Resource Delete parent transaction units

`units/resource-delete-unit.checks.py` retains source deletion, identity/raw-value preservation,
Its authored Model helpers are shared by `support/resource_delete_fixtures.py`.
The pre-commit incomplete-leaf assertion is in Worktree guard UT; actual failed-candidate
repair, one final check, one ff-only merge and cleanup are in Worktree operation IT.
Business tests use ordinary Git or file snapshots and never create lifecycle records.


## 保存・通常統合ガード

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `guard-cache/equivalence` | `check_guard_cache_equivalence` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1890) | pytest / 12 | 最終候補のキャッシュcontext有無による結果一致、旧Model不変性を要求しない検証 | Added |
| `guard-runtime/process` | `check_registered_guard_process` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L47) | pytest / 8 | 明示Task・通常/承認contract_file、warning・非ゼロstdout/stderr、起動/runtime失敗 | Added |
| `guard-runtime/preconditions` | `check_prepare_rejects_before_git_write` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L112) | pytest / 11 | 安価な前提違反、ガード拒否、ガード中のTask/HEAD/変更をGit書込み前に拒否 | Added |
| `guard-runtime/json` | `check_cli_failure_diagnostics` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L146) | pytest / 1 | CLI JSONと子診断の分離 | Added |
| `guard-runtime/integration` | `check_registered_normal_model_guard` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L654) | direct / 1 | Model依存なし親と登録済実venv子、guardから実commit/merge/cleanup | 統合境界のみ |

既存の承認付きsuspendのガード・証跡テストは子プロセスで実行し、拒否理由と状態保持を継続する。
dirty baseは高コスト解析・commit前に拒否するため、既存テストは未コミット内容の保持を確認する。

## Model properties v2

観測保存の単体ケースは既存 capability 型の模擬 context を使用し、Task/worktree からの権限付与を実証しない。現行 IT は合成 properties と実管理 Task による保存・Import・Deploy の経路を検査する。Import の会話品質の実証とは区別する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `model-v2::check_scalar_spelling_and_patch` | `check_scalar_spelling_and_patch` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L67) | pytest / 1 | scalar の原文と部分更新 | Model v2 |
| `model-v2::check_json_continuation_and_types` | `check_json_continuation_and_types` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L82) | pytest / 1 | 明示 JSON 継続・native type・配列順序 | Model v2 |
| `model-v2::check_invalid_properties` | `check_invalid_properties` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L94) | pytest / 12 | 重複キー・不正定数・不正継続・暗黙継続の拒否 | Model v2 |
| `model-v2::check_unsupported_version` | `check_unsupported_version` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L100) | pytest / 2 | 必須ヘッダと未知形式の入力妥当性 | Model v2 |
| `model-v2::check_discovery_alias_and_account` | `check_discovery_alias_and_account` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L307) | pytest / 1 | 任意環境・複数 Alias・account・未作成 Model | Model v2 |
| `model-v2::check_runtime_metadata_is_not_authority` | `check_runtime_metadata_is_not_authority` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L308) | pytest / 1 | 観測 metadata の導出・空・不存在・PENDING_DEPLOY | Model v2 |
| `model-v2::check_parts_and_large_resource` | `check_parts_and_large_resource` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L339) | pytest / 1 | 所有 block・巨大 Resource・parts 欠番 | Model v2 |
| `model-v2::check_unsafe_parts` | `check_unsafe_parts` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L422) | pytest / 7 | 欠落・重複・未登録・逸脱・symlink・block 分割 | Model v2 |
| `model-v2::check_reference_schema_and_pointer` | `check_reference_schema_and_pointer` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L323) | pytest / 1 | 参照 schema・既存 JSON string leaf・WARNING | Model v2 |
| `model-v2::check_cli_subprocess_and_canonical_imports` | `check_cli_subprocess_and_canonical_imports` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L62) | pytest / 1 | 新 CLI の別プロセス起動・恒久 PYTHONPATH 不要・型 identity | Model v2 |
| `model-v2::check_stack_metadata_is_not_runtime_input` | `check_stack_metadata_is_not_runtime_input` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L348) | pytest / 1 | 固定 placementName と変更可能 name・不変 snapshot | Model v2 |
| `model-v2::check_observed_byte_preservation_and_one_use` | `check_observed_byte_preservation_and_one_use` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L84) | pytest / 1 | 観測のみの原文差替え・一回使い切り保存 context | Model v2 |
| `model-v2::check_source_save_conflict_and_rollback` | `check_source_save_conflict_and_rollback` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L110) | pytest / 3 | source/Task 競合の保持・I/O 失敗 rollback | Model v2 |
| `model-v2::check_observed_cannot_bypass_import_or_change_authority` | `check_observed_cannot_bypass_import_or_change_authority` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L402) | pytest / 1 | IMPORT 物理 ID 保護・非観測と未登録書込・承認 flag 拒否 | Model v2 |
| `model-v2::check_declared_and_direct_links_coalesce_or_retain_conflicts` | `check_declared_and_direct_links_coalesce_or_retain_conflicts` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L451) | pytest / 1 | 直接リンク統合・意味競合の保持・incoming・読取非破壊 | Model v2 |
| `model-v2::check_reference_occurrence_identifies_overlapping_text` | `check_reference_occurrence_identifies_overlapping_text` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L376) | pytest / 1 | 重なりを含む参照断片の厳密な出現位置 | Model v2 |
| `model-v2::check_observed_insertion_is_local_without_reflow` | `check_observed_insertion_is_local_without_reflow` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L107) | pytest / 1 | 観測キー追加削除と CRLF・無関係な原文の不変 | Model v2 |
| `model-v2::check_import_observation_foreign_reference_and_identity_spoof` | `check_import_observation_foreign_reference_and_identity_spoof` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L124) | pytest / 1 | IMPORT の外部参照観測更新・自身 ID 保護・偽装リンク拒否 | Model v2 |
| `model-v2::check_properties_import_review_operations` | `check_properties_import_review_operations` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L480) | pytest / 4 | add/refresh/bind/replace の全件 Review と固定 identity | Model v2 |
| `model-v2::check_properties_reference_review_after_map_and_ownership` | `check_properties_reference_review_after_map_and_ownership` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L508) | pytest / 4 | 完全 after map・空削除・旧新 owner・非選択保護 | Model v2 |
| `model-v2::check_runtime_projection_validation_and_metadata_separation` | `check_runtime_projection_validation_and_metadata_separation` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L390) | pytest / 1 | 正本全体と派生投影・Stack metadata の分離 | Model v2 |
| `model-v2::check_stack_render_cli_uses_only_canonical_modules` | `check_stack_render_cli_uses_only_canonical_modules` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L150) | pytest / 1 | Stack render 別プロセス・model.* の型一貫性 | Model v2 |
| `model-v2::check_incoming_missing_producer_does_not_match_unrelated_metadata` | `check_incoming_missing_producer_does_not_match_unrelated_metadata` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L623) | pytest / 1 | 不在 producer の incoming が無関係な宣言を含めない | Model v2 |
| `model-v2::check_properties_normal_generation_uses_new_authority` | `check_properties_normal_generation_uses_new_authority` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L187) | pytest / 1 | 新正本からの通常生成・原文保持・stage 入力完全性 | Model v2 |
| `model-v2::check_managed_properties_save` | `check_managed_properties_save` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L248) | pytest / 13 | 実 Task・HEAD・原文・集合競合・一回保存・rollback・中断 journal | Model v2 |
| `model-v2::check_properties_context_requires_managed_running_task` | `check_properties_context_requires_managed_running_task` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L547) | pytest / 1 | 管理 worktree と running Task の保存権限 | Model v2 |
| `model-v2::check_deploy_preparation_separates_producer_reads_from_writes` | `check_deploy_preparation_separates_producer_reads_from_writes` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py) | pytest / 1 | 準備ではproducerを読まず、consumer初回ロード時にproducer依存とmanifestを記録する。producerとprojectは許可書込先に含めない | Model v2 |
| `model-v2::check_properties_import_acquire_review_publish` | `check_properties_import_acquire_review_publish` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L733) | pytest / 2 | 実取得/ReviewからReview改ざんの保存前拒否とReceipt失敗時の実Rollback | Model v2 |
| `model-v2::check_properties_standalone_audit_has_no_framework_runtime` | `check_properties_standalone_audit_has_no_framework_runtime` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L352) | pytest / 1 | 独立 audit の生成・Framework import 不要・未取得 ERROR | Model v2 |
| `model-v2::check_properties_model_operation_preservation` | `check_properties_model_operation_preservation` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L556) | pytest / 6 | merge/delete の固定 identity・観測・native type・非選択保持 | Model v2 |
| `model-v2::check_properties_retarget_keeps_other_fragments_and_reference_ids` | `check_properties_retarget_keeps_other_fragments_and_reference_ids` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L591) | pytest / 6 | retarget の literal 断片・context・format・固定 refid 保持 | Model v2 |
| `model-v2::check_managed_observation_preserves_exact_authority` | `check_managed_observation_preserves_exact_authority` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L390) | pytest / 8 | 実 Task の Row whitelist・非観測不変・IMPORT 物理 ID 保護 | Model v2 |
| `model-v2::check_ordinary_properties_edit_uses_real_task_guard` | `check_ordinary_properties_edit_uses_real_task_guard` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L476) | pytest / 6 | 通常 design 編集と作成・固定 ID・IMPORT 構成・Task 保護 | Model v2 |

旧 check_other_definition_input_dependencies（8 variants）は Model の Definition／optional／choice／default／template owner が廃止されたため終了した。非選択 Resource／環境の値・identity・reference の保持は check_overwrite_does_not_grant_unrelated_edits と新 canonical snapshot/Task/Review 回帰に引き継ぐ。旧 YAML 部分編集ケースは properties の原文保持・native 値・no-op へ移管し、ケースと parameter matrix を保持する。

旧 Import approval の細かな入力条件・異常系は import-model-unit / import-approval-unit / import-references-unit が保証する。import-model IT は取得 evidence・全件 Review・代表的なPublication・Rollback・Recoveryを検査し、CLI・Git・Worktree境界は専用ITへ分離済み。削除・縮小した検証と既存UT・代表ITの対応は「Issue 14: Import IT responsibility reduction」の対応表を正とし、旧ケースID・parameter数の全維持を前提にしない。

| `model-v2::review-complete-canonical-changes` | `check_review_reports_every_canonical_change` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L699) | pytest / 1 | 全正本キー・Row comment・display・service の Before/After と存在性を全件 Review に表示 | Model v2 |

Properties v2 の検査移管（検査目的を維持し、Importのparameter削減と責務分担はIssue 14節に従う）:

- model_files の検索・Resource group・trace・scope・Task 選択・原文不変・競合・publication cache 無効化を新 CLI／reader で検査する。旧 template parser 呼出し回数は廃止し、同一 snapshot の canonical reader 再利用と権限再確認を検査する。600 行は header を含む初回の目安になり、Resource block の途中分割をしない。
- Import の value／approval／reference の単体ケースは model.* と明示 properties fixture へ移管する。参照の selector／template provenance は固定 producer identity／consumerKey／pointer／format／property／labelPolicy に置き換える。別環境への暗黙展開や未使用 Definition の生成は存在しない。
- Model merge の optional／choice／optional-json は、対応する明示 Row／document の完全転送と他環境不変を検査する。Stack の Resource 混在は Stack schema の構造不正、形式不正は失敗、producer 不在・名前不一致は WARNING として区別する。
- 保存値を再展開しないため参照の循環自体は失敗ではない。有限の読取りと値の不変を検査する。内部 marker は文字列ではないため、JSON の NUL 文字列が marker を偽装できないことと、native 値の変更禁止を検査する。
- retarget／delete の固定 identity、同値の表示でも異なる producer、JSON sibling・型・配列順序、複数 leaf、one-use、第五保存 rollback、親 Task の未完・最新 base・修復後一回統合のケースを新共通保存 API に移管する。旧 bindings は固定 metadata、unused input は未申告の正本情報へ置換する。

サービス fixture は共有入力や tpl を生成せず、環境ごとに全値を明記した properties を作る。サービス別の型・Policy・配列・投影・変更箇所の検査は継続し、廃止された入力 grammar の負例は正本キー／必須 Row／strict JSON／正式 schema の検査へ移管する。文字列の正式 Property（例: Route53 TTL）は数値風の表記から型推測しない。producer／context の変更は参照 WARNING と保存値不変を検査し、必要な値・metadata の変更を明示した候補で照合する。


## Properties v2 reference and Import assertion mapping

固定 Resource/Row IDと検証目的を維持し、Importの関数・条件数はIssue 14節の削減を反映する。旧展開文法だけの検査は
普通の properties と `desired.reference` の構造・所有者・使用位置の検査へ置き換える。
無効な構文・未知形式・範囲違反・I/O を参照 WARNING に読み替えない。

| 既存ケース | 現在の検査対象・保持する assertion |
| --- | --- |
| `import-model` IT（47関数・104条件 → 29関数・37条件、67条件削減） | 代表的な取得・全件Review・add／refresh／bind／replace／混在のPublication、非選択/CREATE/別環境保持、保存前拒否・保存中race、source/ReceiptのRollbackと表示Recovery |
| `import-cli` IT | 別プロセスCLI・実HEAD変更とsource/Receipt/displayの強制終了・復旧境界 |
| `import-worktree-contract` IT | 実Git・Worktreeの所有権・Task・取得証跡と保存権限の境界 |
| `model-operation-publication` IT | Model-only Publication、一回使い切りcontext・leaf保存・journal復旧・batch保存 |
| 関連UT（import-model-unit / import-approval-unit / import-references-unit） | 入力・条件分岐・Identity・Scope・Approval・拒否判定。削除条件ごとの保証先はIssue 14節の対応表を参照 |
| `check_model_only_publication` / `check_intermediate_model_sources` / `check_batch_leaf_saves` | Gitなしの状態Providerと一回使い切り context / prepare/publish API、限定操作・通常編集の境界、一次保存と最終検証の分離、5組の転送→未削除状態→削除完了、base 不変、journal 復旧。親の完了は final-candidate の別ケースで検査 |
| `check_reference_publication` | scalar保存リンクとJSON物理値＋外部name参照のJSON Pointer、宣言/直接リンクの重複排除、read_context ごとの producer 読取再利用、読取依存の競合で source/receipt 復元、producer 外部変更の保持、再取得なしの表示復旧 |
| raw-bucket / producer-identifier と各 schema UT | 正式 Property、固定 ID、backtick・JSON native type/順序、raw name と observed identifier、空/不存在/PENDING の区別、labelPolicy と必要/禁止フィールド。型・名前・識別子の不一致や producer 不在は値を保持して WARNING |
| CloudTrail / Lambda / Security Group / Group 03 / EventBridge / producer-name | 旧サービス/Resource/Row と case・suffix・固定ラベル・親子/逆リンクを保持。producer の変更による consumer 値の自動展開を廃止し、保存値不変・WARNING・producer 原文依存 hash の変化を検査 |
| attribute `check_pair` / `check_fixed_label` / `check_stack` | 相互保存リンク・固定ラベル・厳密 JSON・Stack name と placementName の区別、参照 trace、未知形式/重複キーの読取時エラーと書込ゼロ、欠落 producer の WARNING、固定 snapshot の再利用と fresh 照合 |
| attribute `check_preparation_cache` | 同一 snapshot の2 Resource読取で物理 parser 1回、途中外部変更で旧 snapshot 不変、次の snapshot で変更可視、欠落入口の I/O エラーと原文復元 |
| 旧属性展開 cycle の拒否 | 展開 engine を廃止したため evaluator cycle は存在しない。相互に保存された Resource/Stack/name 参照が再帰せず、値・原文を自動変更しないことへ移行 |
| 旧 producer 変更による design digest 変化 | 設計 digest は対象 Model の observed を除く全正本。producer/comment/observed の変更は完全な読取依存 snapshot の hash/照合で検知し、consumer の設計 digest と保存値は不変 |
| producer-name の CodeBuild→Logs 直接リンク | 直接 Markdown リンクも依存として追跡するため、IAM→Logs→CodeBuild の affected 集合を検査する |

旧 template selector/input schema の廃止と実保存保護の削除を混同しない。
ここでの Review と対話規約検査は合成 fixture／文書契約の検査であり、実際の LLM と
Human の対話品質・全件提示・最終保存同意を実証したという意味ではない。


旧 `units/model_templates-unit.checks.py::check_template_syntax` は template DSL 専用のため廃止した。
7入力のうち旧 optional/choice/boolean 宣言文法3件は削除済み engine と共に廃止し、
JSON Pointer の負数・先頭0・不正escape・非文字列は model-format v2 と reference schema
UT/IT で引き続き拒否する。transaction、競合、固定 identity、親子、保存権限のケースは
この廃止対象に含めない。

`model-document-sources` は parameters 保存を廃止し、同じ2環境・Resource/Rowと
JSON型/配列順序を実管理 worktree の prepare/publish、no-op bytes、派生hash traceで確認する。
`used-definition-inputs` は暗黙の共有入力の廃止を、同値の Resource を別々に編集する保存検査へ移行した。
`compact-model-sources` の rollback は共有 journal transaction の機械的検査であり、
公開保存権限は別の実管理 context ITで検査する。`runtime-model` は実在入口だけの discovery と
登録targetからの自動生成不存在、原文snapshot、環境独立性、旧形式拒否を検査する。


Properties v2 の scope/discovery は登録環境名 `templates` / `parameters` も通常の環境名として扱い、現行propertiesのパス・形式・part集合を検証する。

`model_templates` IT の9入口は properties v2 へ移行した。実 journal の部分書込・callback・
process-death・復元失敗・CRLF/no-op、固定 Role 数2/5・Row ID・JSONポリシー生成、parts/scope、
参照 chain と旧 graph、immutable snapshot、明示作成、scalar原文、sync/newline/driftを保持する。
旧 optional/choice engine の振舞いは、明示的な最小/完全 authority の JSON型・配列順・
派生hashと構造異常へ置き換える。共通 transaction の fixture は公開保存権限を発行しない。


Properties v2 の追加移行対応（model-properties-v2）:
- `model_impact` の8入口は保存済み参照の保守的な推移閉包を検査する。旧展開 engine の
  attribute 単位の最小 scope 最適化は廃止し、実際の宣言／直接リンクだけを追う。
  固定 producer の不在、削除前 graph、環境独立、循環、IMPORT の Resource 単位の差分検査は維持する。
- `model-validation-reuse` は原文変更・権限取消・各 validator・thread isolation・例外後の cleanup を維持する。
  view だけの保存後は同じ正本 snapshot を再利用し、同一 permission/input context 内の再解析を抑止する。
- `validation_cache` は新 index/parts の原文と依存 Model・project の bytes を検査する。
  コメントや observed の変更は完全 snapshot を変え、設計 digest は canonical な非 observed 値だけを使う。
- `human-inputs-group-05` は3サービスの明示 properties、native JSON、固定 ID、環境独立、
  派生 hash と実管理 Task の保存／no-op／拒否を検査する。廃止した template 入力 enum/default/choice
  の旧検査を新 properties の型推測・暗黙値展開として残さない。
- `model_design` の既存表示・命名・サービス単位の失敗保持／rollback と `issues_scan` の
  全件比較／保存失敗／マスク／参照・配列の意味の検査は canonical fixture へ移行する。
- `sync-model` は saved reference の意味・stage の producer 観測値・cold worker・原文不変と
  source/Task/file-set 競合・複数対象の保存 barrier を維持する。
- `check_shared_snapshot_parses_each_producer_once_and_rechecks_permission` は相互参照を持つ合成 Model を
  同じ入力 snapshot で一回ずつ解析し、権限 context 変更時は分離、取消後は cached read も拒否する。

これらは開発中の focused/offline 検査であり、最終 Full／全体 IT／local integration の代用ではない。

| Case ID | Function | Level | Source | Mode / Count | Responsibility | Group |
| --- | --- | --- | --- | --- | --- | --- |
| `model-v2::macie-authority` | `check_macie_renders_current_document_without_artifact_reads` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L153) | pytest / 6 | Inline bucketCriteria and missing/stale/broken JSON never overrides the current document or changes properties bytes | Model v2 |
| `model-v2::display-diagnostics` | `check_shared_display_selection_and_diagnostics` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L198) | pytest / 5 | Nameless IMPORT type, root name, explicit fallback label, rule-table and grouped KMS alias share final display selection | Model v2 |

## Shared JSON contracts

| Case ID | Entry | Class | File | Execution | Responsibility | Origin |
| --- | --- | --- | --- | --- | --- | --- |
| json-format/parse | check_parse | UT | [JSON](units/json-format.checks.py) | pytest / 4 | Model/Policy native values and Unicode | Added |
| json-format/errors | check_errors | UT | [JSON](units/json-format.checks.py) | pytest / 12 | Exact duplicate/constant/syntax messages | Added |
| json-format/overflow | check_model_overflow_only | UT | [JSON](units/json-format.checks.py) | pytest / 3 | Model rejects overflow; Policy retains infinity | Added |
| json-format/bytes | check_output_bytes_and_hashes | UT | [JSON](units/json-format.checks.py) | pytest / 1 | Fixed pre-refactor UTF-8 bytes and distinct hashes | Added |
| json-format/exports | check_compatibility_exports | UT | [JSON](units/json-format.checks.py) | pytest / 1 | Existing public exports remain identical | Added |
| json-format/isolation | check_isolated_imports_and_standalone_audit | UT | [JSON](units/json-format.checks.py) | pytest / 4 | Fresh isolated imports and standalone audit parser | Added |

| `model-v2::type-display-constraints` | `check_type_display_constraints` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L232) | pytest / 4 | Multiple resources, required names and grouped resources retain type-display restrictions | Model v2 |
| `model-v2::resource-acquisition-scope` | `check_resource_acquisition_scope` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L259) | pytest / 12 | Adapter, SDK and Cloud Control guard direct and cached access across environment and Alias | Model v2 |

## Invocation-local reference diagnostic parsing

| 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 |
|---|---|---|---|---|
| `existing-ut-inventory` | `check_diagnose_lazy_parsing_and_exact_results` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L711) | pytest / 2 | name/identifier の解析回数、警告順序・内容・依存全体、戻り値の変更分離 |
| `existing-ut-inventory` | `check_diagnose_producers_are_separate` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L739) | pytest / 1 | 実 producer 解決で snapshot/prefix 分離 |
| `existing-ut-inventory` | `check_diagnose_does_not_parse_unused_rows` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L765) | pytest / 6 | 空入力・不存在・早期分岐で不正 row を先行解析しない |
| `existing-ut-inventory` | `check_diagnose_errors_propagate` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L806) | pytest / 1 | 不正宣言・使用 row・解析例外の伝播 |
| `existing-ut-inventory` | `check_diagnose_fresh_inputs_in_outer_context` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L823) | pytest / 1 | outer input_context 内の診断間変更・削除・追加と snapshot 保持 |
| `existing-ut-inventory` | `check_diagnose_display_name_uses_real_projection` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L850) | pytest / 1 | 実 display-name 投影の警告と依存全体 |


## Environment context retirement

| ケース | 層 | ファイル | 実行 | 検証目的 |
| --- | --- | --- | --- | --- |
| `existing-ut-inventory` | `check_environment_literals_and_account_context` | UT | [units/model-environment-reference-unit.checks.py](units/model-environment-reference-unit.checks.py#L22) | pytest / 1 | 環境名を含むscalar/JSONの保存値と選択scope、account参照・traceの保持 |
| `existing-ut-inventory` | `check_retired_declarations_rejected` | UT | [units/model-environment-reference-unit.checks.py](units/model-environment-reference-unit.checks.py#L57) | pytest / 4 | refid非依存でscalar/JSONの旧環境宣言をreader・Review・trace・export比較で拒否、bytes不変 |

## Required reference input with pending observation

| ケース | 層 | ファイル | 実行 | 検証目的 |
| --- | --- | --- | --- | --- |
| `existing-ut-inventory` | `check_pending_reference_is_required_input` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L365) | pytest / 1 | 保存済みResource URIは観測値が未配備でも必須入力として保持し、空値・未確定literalは拒否、入力不変 |

| `candidate-model/repair` | `check_repair_invalid_model` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1947) | pytest / 40 | 不正な参照・形式・identity・重複の修正保存、IMPORT固定値変更、候補検証・権限・scope・競合・rollback、Git baseline Model展開なし | Added |

## 残存UTの登録整合

既存の未登録UTを実collectionと直接実行入口から補完する。テスト本体・実行入口は追加せず、pytestの展開数は収集結果、直接実行は既存呼出しを確認した1入口で登録する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `existing-ut-inventory` | `check_sdk_lifetime` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L33) | direct / 1 | sdk lifetime | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_failure_lifetimes` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L71) | direct / 1 | SDK/Schema/Catalog固有の失敗保持と新インスタンス再取得 | Future待機・BaseException制御は共通UTへ移管 |
| `existing-ut-inventory` | `check_full_validation_dependencies` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L106) | direct / 1 | full validation dependencies | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_stage_survival_and_definition_sources` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L142) | direct / 1 | stage survival and definition sources | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_validation_projection_scope` | UT | [units/aws_mapping_display-unit.checks.py](units/aws_mapping_display-unit.checks.py#L35) | pytest / 1 | validation projection scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unit_dispatch` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L201) | pytest / 15 | unit dispatch | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ci_workflow` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L287) | pytest / 1 | ci workflow | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_fixed_identity_anchors` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L226) | pytest / 1 | fixed identity anchors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_atomic_bytes` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L105) | pytest / 1 | atomic bytes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_atomic_failure` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L127) | pytest / 3 | all-stage-first failure and rollback before/after rename | 置換前後の障害注入を共通UTに集約 |
| `existing-ut-inventory` | `check_save_rollback_patch` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L177) | pytest / 1 | save rollback patch | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_operation_catalog_arrays` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L680) | pytest / 6 | model operation catalog arrays | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_batch_model_operation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1170) | pytest / 1 | batch model operation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_intermediate_source_context` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1184) | pytest / 2 | intermediate source context | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_explicit_reference_operation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1224) | pytest / 6 | explicit reference operation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_effective_reference_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1291) | pytest / 2 | effective reference identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_local_reference_effective_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1314) | pytest / 1 | local reference effective identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_stack_reference_usage_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1326) | pytest / 1 | stack reference usage identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_target_diagnostics` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1347) | pytest / 2 | reference target diagnostics | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_issues_never_waive_delete_reference_safety` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1599) | pytest / 2 | issues never waive delete reference safety | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_publication_verifies_only_acquisition_selected_additions` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1697) | pytest / 1 | publication verifies only acquisition selected additions | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_existing_hyphenated_fixed_id_cannot_receive_rows` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1707) | pytest / 1 | existing hyphenated fixed id cannot receive rows | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_refactor_json_value_structure` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1859) | pytest / 22 | refactor json value structure | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_exact_reference` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L127) | pytest / 44 | exact reference | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_guardduty_bucket_reference_contract` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L145) | pytest / 1 | guardduty bucket reference contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_no_guessed_or_foreign_identity` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L173) | pytest / 1 | no guessed or foreign identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ambiguous_and_wrong_explicit_link` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L184) | pytest / 1 | ambiguous and wrong explicit link | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_publication_mixed_array_and_physical_value` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L198) | pytest / 1 | publication mixed array and physical value | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_observed_and_reused_index` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L215) | pytest / 1 | observed and reused index | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_pending_explicit_reference_after_destroy` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L231) | pytest / 9 | pending explicit reference after destroy | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_append_only_and_later_import` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L256) | pytest / 1 | append only and later import | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selected_new_import_can_resolve_only_its_declared_producer` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L271) | pytest / 1 | selected new import can resolve only its declared producer | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_declared_identifier_forms` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L310) | pytest / 4 | declared identifier forms | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_import_compact_display_and_create_guards` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L318) | pytest / 1 | import compact display and create guards | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_markdown_roundtrip_keeps_physical_values` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L348) | pytest / 3 | markdown roundtrip keeps physical values | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_mixed_literals_cannot_hide_behind_observations` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L373) | pytest / 1 | mixed literals cannot hide behind observations | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_role_arn_requires_account_and_explicit_path` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L384) | pytest / 2 | role arn requires account and explicit path | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_guardduty_role_acquired_value_consistency` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L394) | pytest / 1 | guardduty role acquired value consistency | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_import_reference_observation_sync_remains_guarded` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L423) | pytest / 1 | import reference observation sync remains guarded | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_design_link_validation_uses_physical_identity` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L450) | pytest / 4 | design link validation uses physical identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unknown_link_like_aws_data_is_not_inferred` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L477) | pytest / 1 | unknown link like aws data is not inferred | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_packed_variable_roundtrip_and_tamper` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L486) | pytest / 1 | packed variable roundtrip and tamper | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_packed_pipeline_configuration_roundtrip` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L503) | pytest / 1 | packed pipeline configuration roundtrip | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_native_cloudtrail_all_bucket_display` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L545) | pytest / 1 | native cloudtrail all bucket display | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_native_array_literals_cannot_evade_matching_model` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L558) | pytest / 1 | native array literals cannot evade matching model | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unobserved_link_requires_typed_target` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L577) | pytest / 5 | unobserved link requires typed target | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unobserved_structured_links_and_strict_import` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L596) | pytest / 4 | unobserved structured links and strict import | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_observed_comparison_in_design_and_import` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L639) | pytest / 2 | observed comparison in design and import | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unobserved_local_and_identity_self_links` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L653) | pytest / 1 | unobserved local and identity self links | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_design_pending_observation_retains_target_guard` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L668) | pytest / 3 | design pending observation retains target guard | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_saved_import_impact_analysis` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L705) | pytest / 2 | saved import impact analysis | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_preserved_analysis_cache_boundary` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L722) | pytest / 2 | preserved analysis cache boundary | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_impact_keeps_invalid_reference_diagnostics` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L741) | pytest / 4 | impact keeps invalid reference diagnostics | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_analysis_permission_restores_after_exception_and_foreign_scope` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L759) | pytest / 1 | analysis permission restores after exception and foreign scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_review_runs_saved_reference_impact` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L776) | pytest / 2 | review runs saved reference impact | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_preserved_read_does_not_authorize_writes` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L792) | pytest / 1 | preserved read does not authorize writes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_configuration_index_reuses_scans_and_keeps_raw_fields` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L802) | pytest / 1 | configuration index reuses scans and keeps raw fields | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_configuration_index_preserves_exception_priority` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L833) | pytest / 1 | configuration index preserves exception priority | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_observation_index_keeps_every_legacy_prefix` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L848) | pytest / 1 | observation index keeps every legacy prefix | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_parse` | UT | [units/json-format.checks.py](units/json-format.checks.py#L32) | pytest / 4 | parse | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_errors` | UT | [units/json-format.checks.py](units/json-format.checks.py#L45) | pytest / 12 | errors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_overflow_only` | UT | [units/json-format.checks.py](units/json-format.checks.py#L52) | pytest / 3 | model overflow only | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_output_bytes_and_hashes` | UT | [units/json-format.checks.py](units/json-format.checks.py#L60) | pytest / 1 | output bytes and hashes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_isolated_imports_and_standalone_audit` | UT | [units/json-format.checks.py](units/json-format.checks.py#L79) | pytest / 4 | isolated imports and standalone audit | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_success_invalidation_and_scope` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L31) | pytest / 1 | success invalidation and scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_strict_documents_repeat_failure` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L62) | pytest / 6 | strict documents repeat failure | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_no_kms_still_parses_malformed_rows` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L74) | pytest / 1 | no kms still parses malformed rows | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_service_reuse_and_direct_call_diagnostics` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py) | pytest / 1 | 同一service内の成功再利用、失敗の再検査とResource別check ID付き同一原因の診断 | 既存UT |
| `existing-ut-inventory` | `check_snapshots` | UT | [units/model-identity.checks.py](units/model-identity.checks.py#L69) | direct / 1 | snapshots | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_cfn_and_outputs` | UT | [units/model-identity.checks.py](units/model-identity.checks.py#L116) | direct / 1 | cfn and outputs | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selection_order_findings_and_fresh_calls` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py) | pytest / 1 | 所有順・辞書分離・新規呼出しの最新入力とResource別check ID付きmapping診断 | 既存UT |
| `existing-ut-inventory` | `check_catalog_failure_precedes_owner` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L109) | pytest / 1 | catalog failure precedes owner | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_first_owner_exception_precedes_resource_checks` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L125) | pytest / 1 | first owner exception precedes resource checks | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_zero_resources_never_classified` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L136) | pytest / 1 | zero resources never classified | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selected_mutation_is_isolated` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L150) | pytest / 1 | selected mutation is isolated | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_leaf_preservation` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L60) | pytest / 1 | reference leaf preservation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_typed_findings` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L75) | pytest / 1 | typed findings | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_incomplete_references_keep_known_records` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L85) | pytest / 1 | incomplete references keep known records | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_analysis_keeps_invalid_source_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L100) | pytest / 1 | reference analysis keeps invalid source error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deleted_target_retains_before_value` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L109) | pytest / 1 | deleted target retains before value | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_replace_keeps_snapshot_and_reports_impact` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L124) | pytest / 1 | replace keeps snapshot and reports impact | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_view_retained_but_io_still_fails` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L147) | pytest / 1 | reference view retained but io still fails | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_completion_only_waives_reference_not_run` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L180) | pytest / 1 | completion only waives reference not run | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_json_leaf_warning_keeps_sibling_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L196) | pytest / 1 | json leaf warning keeps sibling error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_json_cli_warning_success` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L206) | pytest / 1 | json cli warning success | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_generation_metadata_reaches_findings` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L217) | pytest / 1 | generation metadata reaches findings | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_bucket_missing_source_and_real_errors` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L244) | pytest / 1 | bucket missing source and real errors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_link_display_and_readback_classification` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L263) | pytest / 1 | link display and readback classification | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_independent_model_validation` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L307) | pytest / 4 | independent model validation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_generation_warning_keeps_independent_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L321) | pytest / 1 | generation warning keeps independent error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unavailable_service_keeps_source_errors_and_no_cache` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L348) | pytest / 2 | unavailable service keeps source errors and no cache | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_warning_only_completion_and_literal_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L372) | pytest / 2 | model warning only completion and literal error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_document_uses_authoritative_json` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L390) | pytest / 1 | model document uses authoritative json | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_analysis_generation_keeps_independent_checks` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L413) | pytest / 2 | analysis generation keeps independent checks | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_shared_snapshot_parses_each_producer_once_and_rechecks_permission` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L445) | pytest / 1 | shared snapshot parses each producer once and rechecks permission | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_cross_environment_direct_link_preserves_scope_and_dependency` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L470) | pytest / 1 | cross environment direct link preserves scope and dependency | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_preserves_order_and_all_candidates` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L532) | pytest / 1 | usage index preserves order and all candidates | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_skips_accumulated_direct_links` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L570) | pytest / 1 | usage index skips accumulated direct links | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_retains_conflicting_direct_links` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L583) | pytest / 6 | usage index retains conflicting direct links | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_keeps_producer_order_and_io_errors` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L625) | pytest / 1 | usage index keeps producer order and io errors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_is_invocation_local` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L651) | pytest / 1 | usage index is invocation local | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_standalone_contract` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L63) | pytest / 1 | standalone contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_preserves_producers_and_equal_renderings` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L77) | pytest / 2 | preserves producers and equal renderings | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_rejects_unsafe_candidates` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L88) | pytest / 18 | rejects unsafe candidates | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_json_positions` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L144) | pytest / 2 | json positions | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_route_table_pair_example` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L160) | pytest / 1 | route table pair example | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_guarded_save` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py) | pytest / 9 | Model保存の権限・scope・競合・一回使用 | 既存UT |
| `existing-ut-inventory` | `check_final_candidate_uses_latest_base` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L275) | pytest / 1 | final candidate uses latest base | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_additional_boundaries` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L309) | pytest / 5 | additional boundaries | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_one_way_model_contract` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L328) | pytest / 1 | one way model contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selected_model_row_consumption` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L395) | pytest / 1 | selected model row consumption | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_target_candidates` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L57) | pytest / 8 | reference target candidates | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_stack_target_identity` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L91) | pytest / 3 | stack target identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_fixed_ownership_and_invocation_isolation` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L71) | pytest / 1 | fixed ownership and invocation isolation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_lazy_whole_model_parse_and_error_order` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L88) | pytest / 1 | lazy whole model parse and error order | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_explicit_mapping_uniqueness_and_no_name_inference` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L110) | pytest / 1 | explicit mapping uniqueness and no name inference | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ten_deletions` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L56) | pytest / 2 | ten deletions | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_contract_rejects_unscoped_deletion` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L74) | pytest / 6 | contract rejects unscoped deletion | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_and_detach_normalization` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L94) | pytest / 1 | deletion and detach normalization | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_final_rejects_unrequested_changes` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L105) | pytest / 6 | final rejects unrequested changes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_related_detach_and_two_consumers` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L125) | pytest / 1 | related detach and two consumers | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_remaining_reference_is_warning` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L149) | pytest / 1 | remaining reference is warning | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_fifth_save_failure_retains_first_four` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L165) | pytest / 2 | fifth save failure retains first four | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_finalize_rejects_incomplete_leaves` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py#L48) | pytest / 1 | finalize rejects incomplete leaves | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_related_retarget` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L199) | pytest / 1 | related retarget | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_one_parent_merge_and_failed_candidate_repair` | IT | [integrations/worktree-model-operation.checks.py](integrations/worktree-model-operation.checks.py#L44) | pytest / 1 | 複数serviceの削除Transaction、失敗candidate保持・修復・1 Merge・cleanup | 統合境界のみ |
| `existing-ut-inventory` | `check_batch_operation_contract` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L227) | pytest / 1 | batch operation contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_idle_git_paths_and_state` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L262) | pytest / 6 | idle git paths and state | 既存テストの登録漏れ補完・本体変更なし |

## Shared Framework references

Framework seedと全体・部分コピー専用helperを撤去。実リポジトリのFrameworkを `definition_root` / `mapping_alias` / `mappings_for` と既存 `definitions_root` 引数で読み取り、Model・Task・IaC入力・Outputだけを独立workspaceへ配置する。pytestは `shared_framework` と `project_workspace` / `managed_project_workspace` を使用する。残る4 seedは可変Projectデータ専用で、runnerのInventory・完了Receipt・到達性検証を維持する。

Humanが明示許可した例外として `integrations/sync-existing-files.checks.py` の配布機能ITのみ実Frameworkをコピーする。テストfixtureのFrameworkコピーやsymlink/hardlinkは使用しない。Mapping/Schema読取例外は実ソースへの読取境界で検証し、定義ファイルを書き換えない。

## JSON settings without Resource markup

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `json-settings::values` | `check_json_settings` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L38) | pytest / 1 | document/inline JSONのResourceリンク拒否、escaped Pointer、URLとJSON外部リンク保持、identifierメタデータ再利用、物理値非解決 | Model |
| `json-settings::boundaries` | `check_json_boundaries` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L70) | pytest / 1 | 共通候補/独立Model検証の拒否、View Projectionの生成継続と正本不変 | Model |

import-references のSubnet配列とCodePipeline Configuration生成fixtureは確認済みliteralを使用する。ConfigurationのProjectNameは既存外部name参照とJSON Pointerで追跡し、IMPORTがリンク要求warningを出さず取得値の相違は拒否することを確認。入口/展開数は維持。

## Read-only implement preflight boundaries

| ID | Check | Layer | Source | Execution / cases | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `implement-preflight::authority` | `check_preflight_without_write_authority` | UT | [units/task-operation-scope-unit.checks.py](units/task-operation-scope-unit.checks.py) | pytest / 4 | No Task or restricted Task; one/multiple explicit Stacks; CLI PASS/FAIL; ordinary mapping, observation writes and destroy stay strict; no writes or extra template reads | Synthetic Model/IaC |
| `implement-preflight::mapping` | `check_preflight_uses_shared_selected_mapping` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py) | pytest / 5 | Selected-Stack validation without scope lookup; formal type, duplicate ownership, IMPORT mapping and unresolved Condition failures; unselected Stack inputs not read | Existing mapping fixture |

Existing `check_command_io_budget` retains one Task catalog read and one read per contract,
and now checks the deliberate unowned resource diagnostic rather than a Validation scope
failure. Existing `check_implementation_preflight_prompt` covers section-based readings,
no-diff/no-contract sequencing, centralized Skill routing and operation-limited Sandbox
approval instructions. The existing Markdown reference/anchor audit checks all new links.

Mapping I/O measurements use the existing read-only input context explicitly.
Both public and unwrapped paths retain the five-expansion budget and nested reuse
limit; changed-input and changed-authority checks remain outside that context.

## Static Parameter Export scaffold mapping

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `static-export-handle::check_static_exports_share_mapping_and_skip_observed` | `check_static_exports_share_mapping_and_skip_observed` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L143) | pytest / 1 | 論理ID非依存、通常/implementation一致、直接・cached observed同期の除外 | Model |
| `static-export-handle::check_static_export_decoded_fixture` | `check_static_export_decoded_fixture` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L168) | pytest / 1 | 独立YAMLのParameter直接Export再現、共有decoderと両モード一致 | Model |
| `static-export-handle::check_static_export_rejects_resource_configuration` | `check_static_export_rejects_resource_configuration` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L196) | pytest / 1 | Properties・Condition・DependsOn・Metadata・Policy属性の拒否 | Model |
| `static-export-handle::check_static_export_requires_direct_parameter_exports` | `check_static_export_requires_direct_parameter_exports` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L209) | pytest / 1 | 空Outputs・未宣言Parameter・式Value・Export不備の拒否 | Model |
| `static-export-handle::check_static_export_rejects_dependencies_and_unknown_expressions` | `check_static_export_rejects_dependencies_and_unknown_expressions` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L237) | pytest / 1 | Ref/GetAtt/Sub・未使用分岐/変数・依存・未知式・Transformの拒否 | Model |
| `static-export-handle::check_static_export_requires_sole_resource` | `check_static_export_requires_sole_resource` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L266) | pytest / 1 | WaitCondition参照・他Resource混在・通常未対応Resourceの拒否 | Model |
| `static-export-handle::check_static_export_preserves_explicit_mapping_checks` | `check_static_export_preserves_explicit_mapping_checks` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L284) | pytest / 1 | 明示管理維持、重複・formal Type・CREATE制約と両モード一致 | Model |
| `static-export-handle::check_static_export_preserves_removal_guards` | `check_static_export_preserves_removal_guards` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L306) | pytest / 1 | 削除対象の対応付けとcached同期の削除保護を維持 | Model |


## Deploy SDK boundaries and common decoder

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-sdk::boundary-sharing` | `check_boundary_sharing` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py#L64) | pytest / 5 | inline/large/artifact/shared bucket: independent delivery/Create/Execute boundaries | Offline fake SDK |
| `deploy-sdk::object-outcomes` | `check_conditional_put_outcomes` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py#L189) | pytest / 4 | conditional PUT, fresh HEAD, 412/409/timeout/403 | Offline fake SDK |
| `deploy-sdk::deletion-evidence` | `check_deletion_evidence` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py#L149) | pytest / 5 | Delete/Snapshot/Retain/skipped/unknown preserve identifiers correctly | Execution evidence |
| `deploy-sdk::initialization` | `check_client_concurrency` | UT | [units/aws-client.checks.py](units/aws-client.checks.py#L44) | pytest / 1 | context isolation and serialized Session/client initialization | Fake Session |
| `deploy-sdk::pagination` | `check_complete_pages` | UT | [units/aws-client.checks.py](units/aws-client.checks.py#L98) | pytest / 6 | complete inventories and invalid-token rejection | SDK pages |
| `deploy-sdk::decoder` | `check_scalars_and_intrinsics` | UT | [units/cloudformation-format.checks.py](units/cloudformation-format.checks.py#L30) | pytest / 1 | isolated CFn loader, JSON/YAML, intrinsics and existing scalar semantics | Source text/bytes |
| `boolean-literal::valid` | `check_boolean_literal` | UT | [units/cloudformation-format.checks.py](units/cloudformation-format.checks.py#L20) | pytest / 8 | Model booleanの大文字・小文字・混合表記をPython boolへ変換 | 合成リテラル |
| `boolean-literal::invalid` | `check_invalid_boolean_literal` | UT | [units/cloudformation-format.checks.py](units/cloudformation-format.checks.py#L25) | pytest / 15 | yes/no・数値・空白・JSON文字列・非文字列をValueErrorで拒否 | 合成リテラル |
| `sub-escaping::syntax` | `check_sub_variable_syntax` | UT | [units/cloudformation-format.checks.py](units/cloudformation-format.checks.py) | pytest / 34 | 通常変数の制限維持、エスケープリテラル受理、不完全・入れ子拒否、文字列とマップ形式 | 合成文字列 |
| `sub-escaping::evaluation-comparison` | `test_escaped_policy_variables_in_sub_evaluation_and_comparison` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 3 | IAM変数保持、ImportValueマップ、Model/IaC一致、タグ名とパス差異、未解決は比較不能 | 合成Modelと固定Framework |
| `sub-escaping::policy-json` | `check_escaped_policy_sub_variables` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 2 | PolicyDocument共通チェック、未解決式保持、ImportValueを含む置換結果 | 合成PolicyDocument |
| `boolean-literal::comparison` | `BooleanValueTests.test_login_profile_boolean_comparison_and_issue_summary` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | IAM.Userの6ケースでModel検証とmatched/difference・errorゼロ・Issue件数を確認 | 合成Model/IaCのみ |
| `boolean-literal::types` | `BooleanValueTests.test_other_types_and_union_conversion_stay_unchanged` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 文字列・数値・JSON・複数型・型未確定の既存変換を保持 | 合成型スキーマ |
| `boolean-literal::references` | `BooleanValueTests.test_boolean_model_reference_and_document_bypass_literal_conversion` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | boolean型でもmodelRef・JSON document・Ref/GetAtt/Sub/Joinの処理を保持 | 合成参照 |


## Deploy controller correctness and durable resume (1023v2)

従来の SDK/request・scheduler・session差替え・repair/bootstrap判定の10関数は、assertionを保持して `units/deploy-runtime-unit.checks.py` へ移動した。上の旧ケースIDから移動先を追跡できる。新ITは実controller入口、target/Task/CFN読込、guard、SDK wrapper、scheduler、session再読込、observed公開を通す。AWS置換はSDK client取得境界だけとし、observed失敗は対象ファイルI/Oにだけ注入する。子プロセス間の共有はsession/intentとcontroller外のfake AWS JSONに限る。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-v2::selected-parent` | `check_selected_parent` | UT | [units/deploy-observed-unit.checks.py](units/deploy-observed-unit.checks.py#L62) | pytest / 14 | direct/true/false/nested/nonselected/inactive/missing parent, both integrated kinds | synthetic Models |
| `deploy-v2::scope-discovery` | `check_discovery_defers_semantics` | UT | [units/deploy-observed-unit.checks.py](units/deploy-observed-unit.checks.py#L83) | pytest / 1 | raw discovery, related validation and corrupt input rejection | synthetic Models |
| `deploy-v2::cleanup-boundary` | `check_cleanup_refreshes_create_boundary` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py#L247) | pytest / 14 | rollback/delete-intent, current object, encryption/policy/KMS/Export value/producer change and unchanged continuation | delivery state |
| `deploy-v2::profile` | `check_effective_default_profile` | UT | [units/aws-client.checks.py](units/aws-client.checks.py#L162) | pytest / 1 | real SDK provider chain, private config and synthetic credentials | offline SDK |

| `deploy-v2::sdk-shapes` | `check_sdk_arguments_and_pages` | UT | [units/aws-client.checks.py](units/aws-client.checks.py#L198) | pytest / 1 | real SDK request/response schema and pagination | botocore Stubber |

| `deploy-v2::durable-delivery-reset` | `check_cleanup_delivery_evidence_is_durable` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py#L275) | pytest / 1 | cleanup reset saves existing evidence atomically, repaired input replans | saved state |


## Deploy observed publication plans and controller Remove resume

Task fixtureは独立した通常Gitとtask_contract.startで開始・選択し、可変Projectを通常repositoryへ置く。Framework定義は共有参照する。UTは計画照合の純粋判定、ITは実保存・journal/rollback・生成・session再読込・別プロセス再開を検証する。pytest receiptは既存run_it.pyが収集する。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `observed-resume::classification` | `check_classification` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L39) | pytest / 8 | exact before/after, no-op, journal-only mixed state, third bytes and file set rejection | manifests |
| `observed-resume::execution` | `check_execution_identity` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L50) | pytest / 5 | successful original Stack/ChangeSet/digest/token binding | execution evidence |
| `observed-resume::journal` | `check_journal_ownership` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L64) | pytest / 7 | own originals, complete restoration, unrelated receipt and third bytes rejection | journal records |
| `observed-resume::plan` | `check_plan_validation` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L110) | pytest / 13 | Task/extra identity field/evidence/manifest/candidate/desired/unrelated bytes/file set/Allowed paths/stage/original-set/manifest-set checks | isolated bytes |
| `observed-resume::intent-io` | `check_intent_save_failure` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L146) | pytest / 1 | failed intent persistence leaves Model untouched | session I/O |
| `observed-resume::peer-barrier` | `check_pending_plan_drained_peer_barrier` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L198) | pytest / 1 | saved plan finishes before drained peers synchronize | scheduler state |
| `observed-resume::first-error` | `check_original_failure_retained` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 4 | Generation待ちと共存するObserved保存/Guard失敗で最初の原因と最新復旧原因/履歴を保持 | 拡張 |

| `observed-resume::task-bytes` | `check_exact_task_bytes_bound` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L173) | pytest / 1 | pending plan binds full contract bytes in addition to the existing normalized session identity | Task text |

observed-resume UTはCIで毎回実行する。IT runnerとGitHub Actionsの入口は維持する。

| `observed-resume::direct-snapshot` | `check_direct_writer_keeps_noop_source_snapshot` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L158) | pytest / 1 | direct sync retains every selected source snapshot, including unchanged candidates | observation inputs |

## External deploy repair handoff

実Task/Worktree・検証loop・commit/ff-only統合・同一session受理を既存controller ITで検証する。AWSはSDK client取得境界の有限fake、障害注入は既存I/O・process境界のみ。正式ITのreceiptは既存run_it.pyから取得し、未実行をPASSにしない。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `external-repair::round-trip` | `check_external_implement_round_trip` | IT | [integrations/worktree-deploy-repair.checks.py](integrations/worktree-deploy-repair.checks.py) | pytest / 2 | 管理worktree固有の依存indexを準備し、normalの実CLI修復とmerge直後中断から再開。Fake AWS待機なし・有界poll・Patch復元 | 統合境界のみ |
| `external-repair::base-sync` | `check_sync_base_preserves_candidate` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L65) | direct / 1 | 実GitのBase更新と未commit候補の保持・同期後統合 | 統合境界のみ |
| `external-repair::failure-classes` | `check_failure_classes` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py#L116) | pytest / 6 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::status-helpers-preserve-task-identity` | `check_status_helpers_preserve_task_identity` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py#L156) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |

| `external-repair::unexecuted-shell` | `check_unexecuted_shell_recovery` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py#L345) | pytest / 12 | Original ownership/live identity, protection, no execution, failed ChangeSet, empty inventory and interrupted cleanup; no invented rollback | Offline AWS operation boundary |


| `external-repair::cross-task-workflow` | `check_old_workflow_registry_is_ignored` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L93) | direct / 1 | 複数実Worktree間で未完Deploy ledger・budget・所有権を保持 | 統合境界のみ |


| `import-worktree::properties-boundary` | `check_properties_import_git_boundary` | IT | [integrations/import-cli.checks.py](integrations/import-cli.checks.py#L83) | pytest / 5 | HEAD invalidation, separate CLI process and source/receipt/display os._exit(17) recovery, moved intact from properties publication matrix | Issue 14 |

## Issue 14: Import IT responsibility reduction

`import-model` は **29登録関数・37 pytest条件**（変更前47関数・104条件）。67条件を削減した。
件数は登録と収集の値であり、実行成功や性能の証拠ではない。目標約35条件より2条件多いが、
保存中raceの外部編集保持、bind/replace、Mixed Add/Refresh成功/失敗を独立して残す。
Production Import・runner・Receipt照合・Git/Worktree分離の実装は変更しない。

### IT削除と既存保証の対応

以下の旧名は削除理由の記録で、現在の登録・実行入口ではない。
UT略記: M=[import-model-unit](units/import-model-unit.checks.py)、A=[import-approval-unit](units/import-approval-unit.checks.py)、R=[import-references-unit](units/import-references-unit.checks.py)。
UTにはIT用Publication helper・Acquire→Publish全体・Full fixtureを移植していない。

| 削除した旧IT | 判断・直接呼出関数/既存UT | 残した代表ITと失われない保証 |
|---|---|---|
| `check_quicksight_normalization` (1)、`check_registry_services` (1) | M::check_adapter_inventory_normalization がimport_context/inventory/normalize_recordsを直接検証。QuickSight Name=identity・Account引数だけ同UTへ補完 | check_generic_acquisition_roundtrip、check_logs_roundtripが取得証跡→Review→Publish接続を維持 |
| `check_inventory_parent_references` (1)、`check_mapping_preservation` (1) | 同M UTに7 Subnetの親VpcIdとConfig未取得property除外を補完。型付きConfig値は既存assertion | check_managed_resource_additionで親参照の実保存・再読込を維持 |
| `check_cli_faults` (1、内部5入力) | M::check_adapter_inventory_normalizationにContext.verifyのAccountMismatch/AccessDenied、M::check_inventory_status_and_partial_retentionにinventoryの不正3応答を補完 | check_partial_acquisition_cannot_completeで失敗Inventoryと未完了Receiptの連携、check_evidence_and_display_recoveryで保存前不変を維持 |
| `check_existing_resource_selection_rejected` (2) | M::check_existing_resource_action_rejectedがselection_recordsのupdate/add拒否を既存4条件で保証 | check_foreign_source_writes_rejected、check_properties_import_acquire_review_publishで保存前拒否の実境界を維持 |
| `check_add_identity_boundary` (4) | M::check_duplicate_add_uses_baselineがLogs/VPC・observed隠し・CREATE/IMPORTの8条件を既存保証。新規追加はM::check_new_resource_and_explicit_dispositions | check_logs_roundtripの新Logs保存、check_managed_resource_additionのSubnet参照保存を維持 |
| `check_unacquired_property_rejection` (1) | M::check_unacquired_and_create_protection、check_overwrite_does_not_grant_unrelated_edits。新規Resourceの取得値不一致だけcheck_new_resource_and_explicit_dispositionsへ補完 | check_properties_import_acquire_review_publishで保存前拒否・正本不変を維持 |
| `check_fixed_identity_rejection` (1) | M::check_invalid_candidates、check_binding_identity_and_addition、check_overwrite_does_not_grant_unrelated_editsがanchor/logicalId/Mode/Rowの同一関数判定を既存保証 | 実bind/replace後の非選択Resource・保存結果はcheck_user_selected_overwrite_publication |
| `check_native_types_preserved` (1) | M::check_shared_property_typed_preservation、check_native_equality_and_singleton。integer 90とstring "90"のtyped_row/typed_equal照合のみcheck_typed_property_valuesに補完 | check_logs_roundtripで取得integerの正本/表示を維持 |
| `check_exact_scope` (1、内部2拒否) | M::check_foreign_candidate_scope、A::check_acquisition_identity_boundary / check_output_contract_scopeが直接検証 | check_foreign_source_writes_rejectedとcheck_gitless_guard_boundariesの実保存拒否を維持 |
| `check_external_reference_preservation` (1) | M::check_shared_source_preservation_boundary、A::check_unselected_reference_changes_are_not_reviewed_as_selectedがverify_values/build_reviewで未選択変更拒否。R::check_no_guessed_or_foreign_identityも参照推測を拒否 | check_reference_publicationが参照宣言保存/再読込とproducer不変を維持 |
| `check_partial_reflection` (1) | A::check_unanswered_review_cannot_be_approvedがreview_bindingで未回答を保存権限にしない | check_partial_acquisition_cannot_completeの実未完了Receiptを維持 |
| `check_single_acquisition` (1)、`check_create_definition_reuse` (1)、`check_yaml_candidate_edit` (1) | UT追加なし。同じ保存結果のassertionをcheck_logs_roundtripへ集約 | 再取得呼出禁止・元canonical値/CREATE・追加IMPORT・候補bytes=保存bytesを同一正常Publicationで照合 |
| `check_saved_display_recovery_needs_no_new_approval` (1) | UTへ移動しない。重複する実Recoveryを一本化 | check_evidence_and_display_recoveryで表示保存失敗後のModel/Receipt保持、recover_displayの実復旧とread_acquisition/import_context禁止を維持 |
| `check_candidate_review_mismatch_rejected_without_host` (4) | A::check_changed_review_needs_new_review、check_same_value_reference_meaning_is_boundは既存。A::check_preflight_before_any_saveへ候補value/target/resource/referenceの4不足条件のみ補完、publish_editはMock | check_properties_import_acquire_review_publishのReview改ざん拒否とcheck_publication_transaction_without_hostの候補raceを維持 |

### 不足した単体判定だけを既存UTへ補完

`acquisition_fixture()` のAction引数4種類と省略時refresh・既定Resource、Identity/before・非破壊性は既存import-approval-unit内の直接UTで保証する。model-properties-v2 ITのReview operation一致assertionは維持する。

| Requirement | Case | Layer | File | Mode / Count | Verification | Reason |
|---|---|---|---|---|---|---|
| `import-fixture::actions` | `check_acquisition_fixture_actions` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L714) | pytest / 1 | add/refresh/bind/replace伝播、既定refresh/007、Identity/before、入力不変 | Issue 14残存回帰 |

1024v9の責務移管では既存suiteに4関数を追加し、既存関数の不足parameterも合わせ32条件だけ増やした。上記Action伝播の回帰UTは別途1関数・1条件。
`check_it_focused_fixture_isolation` は合成fileを使ってコピー関数を直接呼び、Import fixtureやPublicationを実行しない。

| Requirement | Case | Layer | File | Mode / Count | Verification | Reason |
|---|---|---|---|---|---|---|
| `import-current::inputs` | `check_publication_current_inputs` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L355) | pytest / 6 | 保存前callbackを直接呼びReview/draft/acquisition/Task/source-setの変更拒否、正本不変・output guard未呼出 | No Publication |
| `import-current::identity` | `check_acquisition_identity_boundary` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L391) | pytest / 9 | read_acquisitionを直接呼びhead/base/Task/scope/root/dryRun/期限/statusを照合 | Sealed reader Mock |
| `import-current::output-scope` | `check_output_contract_scope` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py#L415) | pytest / 7 | record_outputsを直接呼びAllowed/scope/target/source/view/consumer拒否 | Contract snapshot Mock |
| `import-current::focused-fixture` | `check_it_focused_fixture_isolation` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L463) | pytest / 1 | 既存FullとFocusedのparts/階層、独立書込、共有seed不変、linkなし | Authored seed only |

### Parameterized ITの縮小

| IT | 条件数 前→後 | 除いた入力条件・UTの責務 | 統合固有のため維持した保証 |
|---|---:|---|---|
| check_properties_import_acquire_review_publish | 11→2 | none→logs roundtrip、source→source race、task→gitless guard、candidate→A preflight、source-set→A current inputs、model-io→source rollback、display-io→display recovery、bind/replace→overwrite IT | Review改ざん保存前拒否、finish_import後Receipt失敗の正本Rollback/Receipt除去 |
| check_publication_transaction_without_host | 10→2 | 正常/Receipt/Display失敗は代表ITと重複。Review/draft/acquisition/Taskの保存直前再確認はA::check_publication_current_inputs。期限はA::check_expiry_and_digest_tampering / check_acquisition_identity_boundary | record_outputs後のcandidate/正本race。実保存境界と外部編集保持はUTで代替しない |
| check_reference_publication | 7→3 | literal/no producerとabsentはR::check_exact_reference / check_unobserved_local_and_identity_self_links、mismatch/ambiguousはR::check_ambiguous_and_wrong_explicit_link / check_observed_comparison_in_design_and_import。incoming診断はR::check_saved_import_impact_analysis | 正常参照保存/JSON Pointer再読込・表示復旧、保存中producer raceのRollback、Review後producer変更拒否。producer読込/API回数assertionを保持 |
| check_user_selected_overwrite_publication | 6→2 | refresh正常はMixed/definition switch、action別dry-runはM::check_selected_overwrite / A::check_explicit_bind_preserves_identityと共通dry-run ITの組合せで保証 | bind/replace両方の実Publication・再読込・Review操作一致・未選択/他環境保持 |
| check_first_resource_uses_existing_source_format | 4→2 | missingと他環境あり/なしの直積だけ削除。初回入口の2保存経路と他環境不変を独立して保証するためのUT追加は不要 | 空入口/他環境なし、入口欠落/他環境あり。v2保存/再読込、他環境不変。templateの有無を検証しているとは扱わない |
| check_approval_bound_save_guard | 5→1 | source hashはM::check_acquired_plan_completion。Task/worktree/risk digestはM::check_external_completion_proofへ不足3条件のみ追加、構造/期限はA::check_review_binding_integrity_without_host | 実Receiptと保存後候補bytesの不一致をrequire_import_changesで拒否 |
| check_gitless_guard_boundaries | 7→2 | head/baseはA::check_acquisition_identity_boundary、Allowed/scope/targetはA::check_output_contract_scope。checkpointの競合は既存A::check_checkpoint_rejects_stale_or_competing_answers | Task変更拒否と実Publish後のScope外ソース変更拒否。実HEADはimport-cliのGit境界のみ |
| check_foreign_source_writes_rejected | 5→1 | stg part、dev別Service/part、templateはM::check_foreign_candidate_scopeのcandidate_sources直接呼出（dev part/templateの2不足条件を追加） | stg候補をpublish_edit前に拒否、全ファイル不変 |
| check_managed_resource_addition | 3→1 | VPC既知/不明はM::check_authored_vpc_append_candidate、unknown判定はM::check_unknown_identity_does_not_block_add | Subnetの実追加と親VPC参照、全既存Resource/他サービス/環境不変 |
| check_mixed_add_refresh_single_publication | 2→2 | 削除なし | 実一括保存・再読込と部分保存失敗Rollbackの両方を維持 |

全18削除関数・67削除条件の台帳。表中の集約先は現在存在する関数で、削除名への実行リンクを残さない。
CLI parser/別プロセス証跡・実Git/強制終了復旧は [import-cli](integrations/import-cli.checks.py) の3登録関数・7条件、
実managed所有者境界は [import-worktree-contract](integrations/import-worktree-contract.checks.py) の2登録関数・3条件、
Model-onlyのleaf保存/journal/batchは [model-operation-publication](integrations/model-operation-publication.checks.py) の3登録関数・8条件に任せる。
import-modelにはそれらの実操作を追加しない。PopenでGit起動を拒否し、worktree fixtureの非ロードassertionを保持する。

### Fixtureと検証範囲

`populate()` のFull契約はそのまま。新しい `populate_focused()` は既存共有seedの指定file/treeと親だけをcopytreeで複製する。
Import fixtureのFocusedはproject.json、dev対象Service入口/partsのみ。必要なTaskは既存APIで登録し、Validation scopeも存在するdevのみ。
共有seed生成は増やさず、symlink/hardlinkは使わない。既存呼出元はFullのままで、import-modelからだけ明示選択する。
`check_it_focused_fixture_isolation` UTはparts/親階層、Full既存契約、不要Service/環境除外、別Service選択、書込可能・独立性、共有seed不変を検証する。

Fullはlogs roundtrip、8 VPC、Subnet追加、shared property、foreign candidate、bind/replace、incoming replace、初回Resource、definition switch、gitless guard、snapshotに保持。
参照ITはCloudTrail/S3の2サービスを明示構築する。Focusedの保証範囲縮小をFullの正本bytes比較・非選択Resource・他環境不変で補う。
単一Serviceケースが不要な6 Serviceとstg Modelを複製しなくなることは構造から確認できるが、コピー回数・時間削減は推測値を記載しない。

ローカルでは関連UT、変更Pythonの構文、pytest収集、登録/件数/Receipt契約の静的照合、削除関数参照、diffのみ検証する。
import-model/import-cli/Worktree/Full IT、cProfile、性能用追加実行は行わない。
10秒未満と削減対象UT+IT合計時間の非悪化は、公式Framework ITの同一依存・同一runner条件のbaseline_ref比較で判定する。
手動baselineのreachability未検証/fixture比較不能の制限は既存runnerの表示に従う。CI未実施・待機をPASSや性能達成と扱わない。

| Requirement | Case | Layer | File | Mode / Count | Verification | Reason |
|---|---|---|---|---|---|---|
| `import-gitless::guards` | `check_gitless_guard_boundaries` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L743) | pytest / 2 | Task変更拒否と実Publish後のScope外ソース変更拒否、Gitなし | Issue 14 |
| `import-gitless::snapshot` | `check_repository_snapshot_detects_real_changes` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L767) | pytest / 1 | Model/Taskの追加・削除・comment編集とbaseline不変 | Issue 14 |
| `import-worktree::contract` | `check_import_managed_contract_boundaries` | IT | [integrations/import-worktree-contract.checks.py](integrations/import-worktree-contract.checks.py#L89) | pytest / 1 | 実Worktree間の取得証跡所有権分離と正規publication/Receipt接続 | 統合境界のみ |
| `model-worktree::source-context` | `check_model_source_context_worktree_boundary` | IT | [integrations/import-worktree-contract.checks.py](integrations/import-worktree-contract.checks.py#L95) | pytest / 2 | 実管理Worktreeのsource保存・所有者変更時の保存拒否・Base bytes保持 | 統合境界のみ |

## LLM diagnosis relations and mechanical retry boundaries

| ID | Function | Kind | Location | Entry / count | Responsibility | Scope |
|---|---|---|---|---|---|---|

## Observed generated-file resume protection

| Origin | Function | Layer | Source | Execution | Coverage | Fixture |
| --- | --- | --- | --- | --- | --- | --- |
| `observed-views::classification` | `check_generated_classification` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L223) | pytest / 11 | before/after candidates, exact bytes, empty vs absent, added/deleted artifacts, unexplained partial state and missing evidence | isolated files |
| `observed-views::journal` | `check_generated_journal` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L270) | pytest / 6 | owned generated transaction, missing-file originals, third bytes, foreign/incomplete journal and receipt | journal records |
| `observed-views::snapshot` | `check_generated_plan_snapshot` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L301) | pytest / 1 | pin views and actual JSON selection before fallible generation; empty vs absent and unexpected file evidence | raw snapshot |

## Resource impact 1023v5

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `resource-impact::addition` | `check_resource_addition` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L267) | direct / 1 | 同Serviceの別logicalId追加と新Consumer、Task基準Snapshot | Resource impact |

| `resource-impact::changes` | `check_resource_changes` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L293) | direct / 1 | 更新・削除・旧新参照・Resource連鎖・複数Service和集合 | Resource impact |
| `resource-impact::semantics` | `check_semantic_boundaries` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L323) | direct / 1 | コメント・表示・採番・Observed・project変更 | Resource impact |
| `resource-impact::fallback` | `check_stack_context_and_fallback` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L361) | direct / 1 | Stack・Context・不明参照・不正旧Model修復 | Resource impact |
| `resource-impact::internal-ids` | `check_internal_ids_and_comments` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py#L40) | pytest / 1 | Resource/Row/Reference番号・表示と意味的差分 | Resource impact |
| `resource-impact::cycles` | `check_minimal_fallback_and_cycles` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py#L54) | pytest / 1 | Resource/Service境界と循環停止 | Resource impact |
| `resource-impact::invalid` | `check_invalid_baseline_and_counter` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py#L67) | pytest / 1 | 不正旧Modelと不明採番の局所fallback | Resource impact |

既存 `units/import-model-unit.checks.py::check_repair_invalid_model` は旧Snapshotのraw差分取得を許可し、変更後だけの `load_model`、旧syntax/identity/encoding不正の修復、権限・scope・race・rollback・anchor拒否の全40展開を維持する。旧Modelを完全検証することを要求しない。

`integrations/sync-model.checks.py::check_integrated_validator` の2展開はImpact再計算3回の旧期待を、共通Snapshotによる計算1回の期待へ変更。生成・入力比較各1回を保持し、候補品質Gateは呼ばず、明示的content Acceptanceのみ保存後に独立実行する。

| `resource-impact::design-source` | `check_design_requires_changed_authority` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py#L79) | pytest / 1 | 共通Impactがあってもproject変更だけでdesign Taskを許可しない | Resource impact |

## Shared sealed evidence

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `sealed-evidence::legacy_bytes` | `check_legacy_bytes` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L25) | pytest / 1 | 現行HMAC-SHA256の固定ベクトルとdigest | evidence |
| `sealed-evidence::rejected_envelopes` | `check_rejected_envelopes` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L41) | pytest / 8 | 改ざん・別鍵・不正envelope拒否 | evidence |
| `sealed-evidence::store_and_key` | `check_store_and_key` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L64) | pytest / 1 | 保存先互換・root分離・32byte鍵 | evidence |
| `sealed-evidence::symlink_rejection` | `check_symlink_rejection` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L83) | pytest / 3 | receipt・鍵・保存先symlink拒否 | evidence |
| `sealed-evidence::private_permissions` | `check_private_permissions` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L110) | pytest / 1 | 所有者と権限 | evidence |
| `sealed-evidence::atomic_failure` | `check_atomic_failure` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L130) | pytest / 1 | atomic失敗時の旧証拠保持 | evidence |
| `sealed-evidence::ownership` | `check_ownership` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py#L28) | pytest / 5 | Worktree正本とTask所有確認 | evidence |
| `sealed-evidence::dependency_boundaries` | `check_dependency_boundaries` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py#L142) | pytest / 1 | 共通証拠とWorktreeの依存分離 | evidence |

## Shared Python requirements synchronization

既存worktree Python UTを拡張する。既存の初期構築・symlink・失敗復旧・実venv/並列Create ITは維持する。細かい同期分岐は合成共有ディレクトリとmock metadata/pipで検証し、実ネットワークやAWSは使用しない。

| Case | Class | Location | Conditions | Responsibility |
|---|---|---|---|---|
| `check_dependency_sync` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 6 | 同一hashは子process/pipなし、追加/不一致のみinstall、旧hashなし/既存一致はhashのみ |
| `check_added_dependency` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 1 | primaryへの追加を検出、旧Worktreeの同一pin subsetを許可、巻き戻しなし |
| `check_worktree_requirement_conflict` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 2 | 旧pin/Worktree独自依存はpip前に明示拒否 |
| `check_sync_failure_retry` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 2 | install/verify失敗でhash無効、詳細診断、環境保持と再検証 |
| `check_parallel_dependency_sync` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 1 | 共有lockで待機し取得後再確認、同期installは1回 |
| `check_requirement_metadata_probe` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 1 | metadata queryの実コード、不足/不一致の名前・要求/実version |
| `check_runtime_dependency_sync` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 1 | runtimeから同期、通常経路は子processなし、管理外は同期なし |
| `check_changed_requirements_during_sync` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 1 | 同期中のrequirements変更ではhash公開しない |
| `check_requirement_pins_reject_unsupported` | UT | [worktree Python](units/worktree_python-unit.checks.py) | 3 | 非exact pin/重複/間接requirementsを拒否 |

`check_shared_symlinks` は適用hashとatomic temporary markerのsymlink拒否も検証する（計7条件）。`support/worktree_test_policy.py` の専用Worktreeケース登録を同時更新する。

共有requirementsを置く2つの手動構築IT fixtureはFramework定義一式も初期配置する。部分的なframework/scriptsだけで定義rootを誤選択し、owners.jsonが欠落する状態を作らない。

## Worktree dependency separation (master 1024v2)

| 分類 | 旧依存 / 対象 | 現在の検証責務 |
|---|---|---|
| A | worktree_task / worktree_python / guard / managed Import boundary | 所有・Task基準・専用Python・create/merge/finalize/cleanup・中断復旧を専用ケースで検証 |
| A | Deploy managed delivery 2条件、Delete parent integration | 実checkpoint→child登録→static検証→親FF→cleanupとその証跡・再開を専用ITへ移動。normal/mergeの異なる統合境界を保持し、Deleteは失敗修復に一本化 |
| B | Model properties/repair、Impact、CloudFormation deploy/destroy、group05、JSON hash、explicit values、Import process 5条件、Deploy request/acceptance/retry/CFN cleanup 13条件 | `repository_fixtures`の通常Git候補へ変更。実Task・Model・生成・保存・rollback・プロセス終了/復旧を保持 |
| D | Git init/commit/diff、Reviewの公開worktreeフィールド、Framework参照整合性 | 通常Git・証跡データの検証でありLifecycleではないため保持 |

Importの所有境界は `check_import_managed_contract_boundaries` の別Worktree拒否、
retarget `guarded_save[wrong-owner]` は共有factoryの `check_ownership` と
`check_model_source_context_worktree_boundary[owner]` に責務を集約する。
HEAD/Task変更、未承認パス、scope/target、非選択データ、保存前後byte、no-opとrollbackの業務assertionは保持する。
`check_git_baseline_fail_closed` のreader委譲はsync UT、NUL/Git失敗はgit-changes UT、managed/unborn/故障基準はWorktree guard UT。
controllerの通常cleanupと外部修復後cleanupは、末尾の6フロー構成で同一の整合した復旧フローへ統合する。

`support/worktree_test_policy.py` はレビュー済みの専用ケースを関数単位で固定し、
UT/IT/supportのImport・動的loader・Mock対象を推移的に調べる。改名だけでは許可しない。
非専用pytestと公式IT runnerは実行時にもGit worktree変更、Lifecycle CLI、管理領域への書込みを拒否する。
通常Gitとproductionによるread-only discoveryは許可する。別プロセスの業務fixtureも通常Gitと
publication能力だけを渡し、管理状態を生成・Mockしない。既存の唯一のIT runnerと完了receiptを使用する。

| Origin | Case | Class | Location | Entry / conditions | Responsibility | Scope |
|---|---|---|---|---|---|---|
| `worktree-separation::candidate` | `check_model_finalize_cannot_bypass_candidate` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py#L63) | pytest / 2 | retarget/Delete承認による最終候補検証迂回を拒否 | Worktree integration |
| `worktree-separation::baseline` | `check_git_baseline_fail_closed` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py#L83) | pytest / 1 | managed基準・unborn・故障伝播 | Worktree integration |
| `worktree-separation::policy` | `check_repository_policy` | UT | [units/worktree-test-policy-unit.checks.py](units/worktree-test-policy-unit.checks.py#L23) | pytest / 1 | 全UT/IT/supportの非専用依存0 | Recurrence |
| `worktree-separation::dependencies` | `check_direct_and_indirect` | UT | [units/worktree-test-policy-unit.checks.py](units/worktree-test-policy-unit.checks.py#L34) | pytest / 5 | 直接/間接/Mock/dynamic fixture依存とLifecycle形状のfixtureを拒否 | Recurrence |
| `worktree-separation::rename` | `check_filename_grants_no_authority` | UT | [units/worktree-test-policy-unit.checks.py](units/worktree-test-policy-unit.checks.py#L43) | pytest / 1 | 改名による許可拡大を拒否 | Recurrence |
| `worktree-separation::runtime` | `check_runtime_guard` | UT | [units/worktree-test-policy-unit.checks.py](units/worktree-test-policy-unit.checks.py#L48) | pytest / 1 | 実操作・管理書込禁止と通常Git許可 | Recurrence |


追加の責務分割：ImportのHEAD/CLI/source/receipt/display crash 5条件は通常Gitの `import-cli` へ移動。
Worktree deliveryは2条件を保持し、controller request/acceptance/retryの組み合わせは末尾の対応表に従って直接UTへ集約する。業務fixtureは通常Gitの実commit/hashと署名付き外部結果を供給し、
worktree所有登録/配送の能力境界だけを置換する。Managed stateやLifecycleのMockは作らない。
実static FAIL→修正→PASSとcheckpoint/create/重複child拒否/FF/cleanupは専用側で引き続き検証する。

全assert文のASTを変更前後で照合し、削除したassert式は0件。所有者ケースは上記の専用側へ集約し、
業務parameter matrixのLifecycle条件だけを移動する。実行時guardはworker threadも対象にし、
静的依存違反をpytest/公式ITの実行前に拒否する。旧baseline計測には現行policyを強制しない。


## Task Contract snapshots / master-1024v3

`units/task-snapshot-unit.checks.py` uses three synthetic Tasks and counts Task byte/text
reads and directory enumeration. Its 20 conditions cover explicit selection (including
intentional isolation from unrelated malformed Tasks), implicit/catalog reuse, immutable
worker transfer with independent memo state, live content/status/newline/selector/catalog
changes, cache publication rejection, Task update invalidation, mutation I/O budgets and
Deploy session and publication suites retain their safety assertions. No Git/worktree
integration or live AWS operation is used by the new suite.

## AWS Profile / Identity common authority

Profile/Accountの判定条件は `units/aws-identity-unit.checks.py` だけで管理する。
共通判定の失敗は `utils.aws.identity.IdentityError`（ValueError派生）を直接伝播する。
各機能UTは元の例外オブジェクトの同一性とCLIでの捕捉を確認し、
DeployContextError/Blocked/AcquisitionErrorへのIdentity例外ラップを行わない。
STS不一致の `AccountMismatch` コードは共通例外が所有し、既存レポート分類を維持する。
既存UTの入口は削除せず、check-deploy-contextとvalidation topologyの不正入力表
（Profile各8、execution account各9、計34展開）を削除した。通常Account不正1入力、
AWS Client内のDeploy Profile選択/競合2条件、ImportのAccount不一致1条件も移管した。
Deploy CLIの競合判定は共通関数のMock拒否へ置換した。
SDK環境由来認証識別、cache、Session再開、alias/suffix/Region/engine、Importの承認と証跡は維持する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `aws-identity::valid-profile` | `check_valid_profile` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L28) | pytest / 5 | Profile形式 | Pure |
| `aws-identity::invalid-profile` | `check_invalid_profile` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L34) | pytest / 14 | 不正型/空/空白/UNSET/改行/NUL、明示値/設定/Import例外でも拒否 | Pure |
| `aws-identity::selection` | `check_profile_selection` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L53) | pytest / 4 | 設定/明示/一致/default chain | Pure |
| `aws-identity::conflict` | `check_profile_conflict` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L57) | pytest / 1 | 設定と明示Profile競合 | Pure |
| `aws-identity::import` | `check_import_selection` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L66) | pytest / 4 | Import専用no-profile、設定不変 | Pure |
| `aws-identity::valid-account` | `check_valid_account` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L73) | pytest / 2 | ASCII 12桁 | Pure |
| `aws-identity::invalid-account` | `check_invalid_account` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L79) | pytest / 12 | 不正Account、明示execution key不正のfallback禁止 | Pure |
| `aws-identity::execution` | `check_execution_account` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L94) | pytest / 2 | execution優先、未指定時resource、STS一致 | Pure |
| `aws-identity::sts-mismatch` | `check_sts_mismatch` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py#L100) | pytest / 5 | STS不一致/欠落/不正型 | Pure |
| `aws-identity::context` | `check_identity_delegation_and_sts_reuse` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L76) | pytest / 1 | Context比較委譲、IdentityError同一性、検証済みAccount返却、STS transport再利用、拒否後resource API禁止 | Mock |
| `aws-identity::multi-target` | `check_all_target_profiles_precede_aws` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L96) | pytest / 1 | 全Targetの事前判定、拒否時CLI/SDK session未実行 | Mock |
| `aws-identity::import-boundary` | `check_import_profile_mode_delegation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1105) | pytest / 1 | Import例外引渡し、設定不変、STS維持 | Mock |
| `aws-identity::preparation` | `check_identity_failure_precedes_preparation` | UT | [units/deploy_preparation-unit.checks.py](units/deploy_preparation-unit.checks.py#L100) | pytest / 1 | 共通判定委譲と準備/AWS前の拒否 | Mock |
| `aws-identity::runtime` | `check_runtime_identity_delegation` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L914) | pytest / 1 | 共通Profile保存、IdentityError同一性、connection作成前の拒否 | Mock |

既存 `integrations/model-test.checks.py::check` にSTS実transport 1回の確認を追加。
共通例外と関数は `model.audit.definitions()` で依存順に埋め込み、既存の隔離Python
単独実行（Framework/PyPI importなし）を維持する。新しいIT入口は追加しない。


## Single-flight common contracts

Future実行制御の重複検証を `aws_definitions.checks.py` と
`aws_mapping-unit.checks.py` から専用UTへ移管。呼び出し元はProvider・依存関係・
Document所有権・失敗保持を検証し、共通UTはEvent/Barrierで待機を同期する。

| Source | Check | Kind | Current location | Entry / cases | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `single-flight` | `check_waiters_share_one_flight` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L81) | pytest / 6 | 同一キーのload一回、成功/例外共有、BaseException通知と再送出、保持/破棄 | 共通UTへ集約 |
| `single-flight` | `check_different_keys_load_in_parallel` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L107) | pytest / 1 | 異なるキーのload並列性 | 共通UT |
| `single-flight` | `check_failure_policy_and_retry` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L116) | pytest / 2 | 失敗保持/破棄後再試行、破棄時ロック | 共通UTへ集約 |
| `single-flight` | `check_eviction_preserves_replacement` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L140) | pytest / 1 | 失敗したFutureと異なる現行Futureは削除しない | 共通UT |
| `single-flight` | `check_lookup_hit_precedes_future_access` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L156) | pytest / 2 | Noneを含むlookup成功、Future検索前の復帰 | 共通UT |
| `single-flight` | `check_lookup_miss_and_future_access_are_atomic` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L168) | pytest / 2 | lookupとFuture検索/登録が一回のロック取得内 | 共通UT |
| `single-flight` | `check_four_argument_api_and_success_cache` | UT | [units/lazy_definitions-unit.checks.py](units/lazy_definitions-unit.checks.py#L189) | pytest / 1 | 4引数互換、loadはロック外、成功キャッシュ | 共通UT |
| `single-flight-mapping` | `check_alias_transition_races` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L492) | pytest / 2 | Provider取得とalias登録/解除の競合安全性 | Mapping固有UT |
| `single-flight-mapping` | `check_provider_failure_lifetime` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L524) | pytest / 1 | Provider生成失敗はroot単位で保持 | Mapping固有UT |

既存 `check_shared_documents` は共有解析失敗の再試行後も既存ProviderのDocument/runtime失敗が
保持されることを追加確認。既存 `integrations/model-test.checks.py::check` は生成したstandalone
engineから `load_once` を実行し、未埋込ヘルパーに依存しないことと4引数互換を確認する。

## Worktree IT runtime reduction (master 1024v4)

ITは実Git/Worktree、CLI接続、永続化、プロセス間排他、失敗復旧を担当する。
条件網羅は既存UTへ集約する。skip/xfail、同等の重いケースへの移動、receipt判定の緩和は行わない。
対象5 suiteは29関数/38入口から27関数/29入口へ削減。direct入口内のfixture反復も別途削減した。
入口数は実行時間ではなく、時間の30%以上削減目標はFramework ITでの同条件実測待ち。

| 対象 | 旧 → 現在 | 削除・統合理由 / 既存UT |
|---|---|---|
| finalize line endings | 12 → 2 | CRLF実反映とstaged末尾空白拒否だけをITに保持 |
| incomplete / safety | 6 → 1 | status/setupはWorktree guard UT、予期しないHEADは既存prepare拒否UT |
| approved Model reads | 11 → 2 | Import UT `check_external_completion_proof`（署名/期限/Task/Base/Scope）、取得plan完了判定UT |
| Human approval | 4 → 1 | Worktree guard UTの承認・status判定、実MergeとFAIL保持はIT |
| candidate staleness | 5 → 1 | Worktree model guard UTがBase/HEAD/Task/dirty/完了中変更を拒否 |
| Model operation | 6 → 1 | Import UT `check_model_operation_preserves_consumers` / `check_model_operation_rejects_unproved_changes`、Deleteは専用IT |
| Model refactor | 2 → 1 | Base更新統合のみ。Import UT `check_refactor_rejects_changes` / `check_value_preserving_detach_and_single_deletions`を再利用 |
| merge retry | 3 → 2 | empty重複を削除。正常/emptyは`check_success_and_empty`が保持 |
| collisions / Base | 3 Git fixture → 1 | Base選択はguard UT、Branch/Path/stale保護を1 fixtureで検証 |
| directory layout | 2 Git fixture → 1 | ignore契約を保持。共通loadの不正path 5条件はguard UT（CLI掛合せは廃止） |
| metadata | 4 Git fixture → 1 | Symlink位置3条件はguard UT、複数Worktree・状態/Lockを保持 |
| ahead / conflict | 2 → 1 | 通常Base更新はsync/retry/refactorと重複。実競合復旧を保持 |
| real loop | 2 Worktree / 2 Loop → 1 / 1 | 実Loop失敗→suspend接続だけ。成功Mergeと承認は各固有IT |
| Python decoding / global wrapper | 8子Python / 1 Git fixture → 0 / 0 | IT関数を廃止。既存Python UTへ8 Mock条件とwrapper検証を統合 |
| Python setup | 5 Git fixture / 7 Create → 1 / 1 | 入力/失敗種類はPython UT。実install失敗後の永続状態と復旧のみ |
| real venv reuse | 3 Create → 2 | 実venv生成・再利用・wrapper/CLI・cleanup後共有環境保持 |
| parallel setup | thread fixture + process fixture → process fixtureのみ | 独立2プロセスの実Lock競合を明示確認。timeout/Lock保持はUT |
| Python symlink | 共有path + unknown + 4位置 → 共有pathのみ | 外部FS保持をIT、位置/marker判定はPython UT |
| Import contract / source context | 5 + 4 → 1 + 2 | 別Worktree所有権、publication接続、source保存/owner拒否。Task変更は既存snapshot UT |
| parent Delete | 2 → 1 | 失敗candidate保持→修復の経路が単一正常Merge/cleanupも検証 |
| Deploy repair | normal/mergeの2条件を維持 | master既存のsleep注入を再利用。1 invoke最大100回で停止、poll/終了・Patch復元を検証 |

Fake AWSの実5秒待機はmasterですでに除去済み。本変更による追加の実測短縮とは扱わない。
Python環境ITの実venv生成は2回（venv/独立process各1）を維持。通常Model guard 1回とDeploy repair 2回も維持し、対象全体の5回をMockへ置換しない。
Worktree本体のGit fixture展開は68→23、Python環境は10→4（AST上のloop展開数、実行時間ではない）。
Refactorの重複incoming CLI起動4回、decodingの子Python8回を削除。
証跡/値/条件と実統合の組合せを削減したため、それらの組合せ固有の不具合は単体境界と固有ITの合成保証となる。
ローカルは関連短時間UT・構文・公式inventory/責務登録静的確認のみ。対象IT実行・全UT/IT・時間実測はしない。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `worktree-runtime::check_output_decoding` | `check_output_decoding` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L100) | pytest / 8 | output decoding | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_wrapper_launcher` | `check_wrapper_launcher` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L115) | pytest / 1 | wrapper launcher | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_runtime_registration` | `check_runtime_registration` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L133) | pytest / 9 | runtime registration | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_setup_failure_recovery` | `check_setup_failure_recovery` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L161) | pytest / 6 | setup failure recovery | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_setup_lock_timeout` | `check_setup_lock_timeout` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L189) | pytest / 1 | setup lock timeout | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_shared_symlinks` | `check_shared_symlinks` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L207) | pytest / 5 | shared symlinks | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_shared_completion` | `check_shared_completion` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py#L226) | pytest / 4 | shared completion | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_integration_status` | `check_integration_status` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L375) | pytest / 6 | integration status | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_finalize_requires_setup` | `check_finalize_requires_setup` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L388) | pytest / 2 | finalize requires setup | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_base_selection` | `check_base_selection` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L409) | pytest / 6 | base selection | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_lifecycle_layout` | `check_lifecycle_layout` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L420) | pytest / 5 | lifecycle layout | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_metadata_symlinks` | `check_metadata_symlinks` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L432) | pytest / 3 | metadata symlinks | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_candidate_staleness` | `check_candidate_staleness` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py#L120) | pytest / 5 | candidate staleness | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_acquired_plan_completion` | `check_acquired_plan_completion` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L777) | pytest / 3 | acquired plan completion | 不足判定のみ追加・ITの入力反復を廃止 |
| `worktree-runtime::check_controller_sleep_injection` | `check_controller_sleep_injection` | UT | [units/cloudformation-deploy-unit.checks.py](units/cloudformation-deploy-unit.checks.py#L162) | pytest / 1 | controller sleep injection | 不足判定のみ追加・ITの入力反復を廃止 |

## Single-file staging and publication

Common byte, error, cleanup, collision and creation-mode checks live in the existing
`file_operations-unit` suite. Cache retains best-effort save and corruption checks;
Deploy retains signed intent/ledger recovery. Model retains journal ordering and its
existing interruption, publication-lock and multi-file rollback integration cases.
`atomic_files` keeps its consumed-stage rollback distinction and all-stage-first order.
The duplicate primitive rollback case in task_contract IT is removed; its assertions
are covered by file_operations check_atomic_failure and check_batch_stages_before_publish.
Controller fixtures inject session save faults through the shared API and rename faults
through os.replace, without depending on temporary filenames.

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `single-file::stage-publish` | `check_stage_and_publish` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L30) | pytest / 2 | UTF-8, exact newlines, binary, unique sibling stages, no fsync | Synthetic files |
| `single-file::failure` | `check_single_failure` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L55) | pytest / 4 | Open/write/fsync/replace failures preserve destination and clean stages | Injected I/O errors |
| `single-file::fsync-newlines` | `check_single_fsync_and_default_newlines` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L69) | pytest / 1 | One requested fsync and platform newline translation | Synthetic text |
| `single-file::collision` | `check_stage_collision` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L79) | pytest / 1 | Exclusive creation retries without clobbering another stage | Fixed UUID collision |
| `single-file::permissions` | `check_single_permissions` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L90) | pytest / 2 | 0600 and 0666-and-umask creation, also when replacing | POSIX modes; Windows skipped |
| `single-file::batch-order` | `check_batch_stages_before_publish` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L155) | pytest / 1 | All stages precede publish; rollback adds no fsync | Synthetic two-file batch |
| `single-file::journal-order` | `check_journal_precedes_publication` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L66) | pytest / 1 | Durable journal precedes Model write; journal failure stops publication | Synthetic journal |
## KMS recorded ARN history through Export/Import

`reference-evidence-unit.checks.py` は既存36条件に以下150条件を追加。Framework定義とModel保存形式は変更せず、合成Producer/Consumerと保存済み観測だけで検証する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `kms-proof::recorded` | `test_kms_recorded_arn_export_import` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L394) | pytest / 40 | 4受信Property・通常/Multi-Region Key・GetAtt/Sub/Joinで保存Observed単独はuncompared、Export診断保持・authority不変 | KMS ARN |
| `kms-proof::identifier` | `test_kms_arn_requires_recorded_key_id` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L413) | pytest / 11 | 欠落・未設定・PENDING_DEPLOY・不正形式・固定Model ARNからの逆推論禁止 | KMS ARN |
| `kms-proof::observation-only` | `test_kms_arn_identifier_evidence_comes_from_observation_only` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L422) | pytest / 1 | desiredやIaCにKeyIdがあっても観測の代用にしない | KMS ARN |
| `kms-proof::context` | `test_kms_arn_uses_only_producer_context` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L436) | pytest / 9 | ProducerのPartition/Region/Account欠落・不正・不一致、Consumer contextへのfallback禁止 | KMS ARN |
| `kms-proof::mismatch` | `test_kms_conflicting_recorded_identifier_is_uncompared` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L454) | pytest / 1 | 観測不整合を誤matched/確定differenceにしない | KMS ARN |
| `kms-proof::correspondence` | `test_kms_recorded_arn_preserves_correspondence_and_handoff` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L465) | pytest / 9 | Resource/Stack欠落・重複対応・型違い・Condition/Transform・IMPORT handoff・重複Property・置換先 | KMS ARN |
| `kms-proof::expression` | `test_kms_expression_cannot_bypass_allowed_forms` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L502) | pytest / 4 | Ref/Sub/JoinでKeyId/AliasArnをKeyArn限定契約へ持ち込めない | KMS ARN |
| `kms-proof::declaration` | `test_kms_declared_literal_cannot_bypass_allowed_forms` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L511) | pytest / 3 | saved_literalのliteral/Ref/Expression経路でも禁止形式拒否 | KMS ARN |
| `kms-proof::priority` | `test_key_arn_does_not_override_alias_only_service_contract` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L526) | pytest / 2 | Glue/CodePipelineのAliasArn専用KMS_FORMS優先を維持 | KMS ARN |
| `kms-proof::forms` | `test_kms_existing_service_form_matrix` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L541) | pytest / 64 | 4サービス×KeyId/KeyArn/AliasName/AliasArnの全16組合せ、既存形式・同一性の契約 | KMS ARN |
| `kms-proof::unresolved` | `test_kms_unresolved_expressions_do_not_gain_symbolic_equality` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L553) | pytest / 1 | 未解決の同一Expression/未対応Intrinsicを誤matchedにしない | KMS ARN |
| `kms-proof::diagnostics` | `test_kms_derived_producer_diagnostics_are_unique` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L560) | pytest / 1 | 導出診断を追加した後も同じProducer/attributeを重複しない | KMS ARN |
| `kms-proof::rows` | `test_kms_runner_reports_uncompared_with_recorded_proof` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L570) | pytest / 4 | 4受信Propertyのrow比較で保存Observed単独をuncomparedとし、recorded_observed診断を保持 | KMS ARN |

## Deploy controller processing reduction (1024v4)

旧66条件の主要assertionと削減後の保証先を以下に記録する。ITの配置変更でUT化せず、直接関数呼出しだけをUTへ補強する。controllerは6関数6入口、小型ITは1関数1入口とする。ITは静的確認のみで、実行・収集・計測しない。

| 旧controller条件（件数） | 主要assertion / 保証先 |
| --- | --- |
| orders_and_observed (1)、group_delivery成功 (1) | `check_ordered_delivery_and_observed`: Order 10配送完了→Create、First/Second SUCCESS・実Model反映→Third Create、全Stack各1 Create/Execute、Model/Markdown/JSON整合。historical metricsはhandoff UTへ |
| group_delivery失敗 (1) | `check_delivery_failure_stops_execution`: 実SDK wrapperのAccessDenied→終了2、Create/Executeなし。細分条件はSDK `check_conditional_put_outcomes`、runtime `check_delivery_encryption` |
| approval_resume (1)、subprocess_execution_resume (2)、remove_controller_process_resume (7) | 承認・受理直後process death・Remove positiveは `check_approved_remove_recovers_without_duplicate_execute`。ReadTimeout/JSON再構成はruntime `check_execute_timeout_keeps_evidence`。Retain/skipped/complete/missing/SnapshotはSDK `check_deletion_evidence`、token/StackId/physical不一致は `check_deletion_event_identity` |
| input_guard_drains_peer (1) | runtime `check_guard_failure_drains_accepted_peer`: guard実例外→新規停止・受理済peer drain |
| observed_io_resume (1)、observed_publication_process_resume (8)、observed_drains_peer_then_resumes (1) | design I/O/複数peer/後続Order停止は `check_observed_failure_drains_peers_and_resumes`、実Model-partial起動時復旧は `check_pending_observed_recovers_before_model_load`。plan保存失敗は `check_intent_save_failure`、Model/generation I/Oは `check_finish_io_failure`、committed段階は `check_finish_committed_stages`、session同期失敗は `check_session_sync_failure_drains_and_resumes`。生成物journalは小型 `check_generated_journal_recovery_uses_observed_owner`。一般的process death/atomic rollbackは既存 `model-properties-v2.checks.py::check_managed_properties_save[process-death] と model_templates.checks.py::check_transactions` のpublication IT（下記参照） |
| generated_external_change_rejected (9)、generated_change_during_publication (1) | observed-resume `check_generated_classification`（JSON削除補強）、`check_generated_journal`、`check_generated_plan_snapshot`。公開途中の外部変更は既存 `sync-model.checks.py::check_input_mutation` / `check_publication_boundary` / `check_publication_rechecks_excluded_outputs` のinput snapshot/publication IT。controller往復の重複を削除 |
| observed_external_change_rejected (11) | observed-resume `check_classification`、`check_plan_validation`、`check_execution_identity`、`check_journal_ownership`、`check_exact_task_bytes_bound`、`check_owned_resume_boundaries`。IaC入力変更・Task/targetのguardは既存runtime `check_session_cli`。署名evidence/approval/pending改変はhandoff `check_signed_protected_fields` |
| legacy_session_without_observed_plan (2) | observed-resume `check_session_without_plan_and_signed_removal`: 正当なplanなしsessionと署名済plan除去を区別 |
| cleanup_and_repair_process_resume (1)、external_repair_cleanup_recovery (1) | `check_external_repair_cleanup_resumes`: 元の失敗証跡・DELETE_INTENT・単一Delete・成功Stack保護・再実行・公開・結果再適用 |
| bootstrap_process_resume (2) | 既存runtime `check_secret_runtime_bootstrap`: JSON保存session再読込、同token/単一PUT、外部AWSCURRENT競合 |
| external_repair_resumption (12) | request/accept前後はhandoff `check_issue_request_stability` / `check_accept_protects_success_and_retries`、未実行decode/validate/create/reviewは `check_unexecuted_exception_to_diagnosis`、shared-successはaccept UT。repeat/new-problem/regressionは既存 `check_problem_sequences` とcause/relation UT。通常Git receipt境界はcleanup controller IT。専用Worktree normal/mergeのcheckpoint/child/validation/merge/cleanup/親再開および追加assertionを維持 |

66条件 = 1+1+1+1+2+7+1+1+8+1+9+1+11+2+1+1+2+3+12。以下の登録件数はソースのASTから静的確認した値であり、今回ITを収集して得た値ではない。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `deploy-reduction::ordered_delivery_and_observed` | `check_ordered_delivery_and_observed` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py#L103) | pytest / 1 | 同Order配送、実Observed barrier、3Stack単一実行と最終Model/文書/JSON | 接続境界 |
| `deploy-reduction::delivery_failure_stops_execution` | `check_delivery_failure_stops_execution` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py#L125) | pytest / 1 | SDK client境界のAccessDeniedが後段実行を停止 | 接続境界 |
| `deploy-reduction::approved_remove_resumes_without_duplicate_execute` | `check_approved_remove_recovers_without_duplicate_execute` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py#L139) | pytest / 1 | 承認保持、Execute受理中断と別process再開、削除証拠とPENDING_DEPLOY | 接続境界 |
| `deploy-reduction::pending_observed_recovers_before_model_load` | `check_pending_observed_recovers_before_model_load` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py#L201) | pytest / 1 | 実Model部分書込/journal/pending planからcontroller起動時復旧 | 接続境界 |
| `deploy-reduction::generated_journal_recovery_uses_observed_owner` | `check_generated_journal_recovery_uses_observed_owner` | IT | [integrations/deploy-observed-recovery.checks.py](integrations/deploy-observed-recovery.checks.py#L42) | pytest / 1 | 所有者検証→実lock/生成物復元、Model/plan/evidence保持 | 接続境界 |
| `deploy-reduction::deletion_event_identity` | `check_deletion_event_identity` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py#L305) | pytest / 4 | 上の旧条件・主要assertion対応表を参照 | 直接関数・小fixture |
| `deploy-reduction::execute_timeout_keeps_evidence` | `check_execute_timeout_keeps_evidence` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L1947) | pytest / 1 | SDK wrapperのReadTimeout分類・証拠を実JSONへ保存、再構成後のIN_PROGRESS→SUCCESSを実pollで処理し単一Executeと最終保存を確認 | 直接関数・小fixture |
| `deploy-reduction::guard_failure_drains_accepted_peer` | `check_guard_failure_drains_accepted_peer` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L1976) | pytest / 1 | 上の旧条件・主要assertion対応表を参照 | 直接関数・小fixture |
| `deploy-reduction::real_input_failure_details` | `check_real_input_failure_details` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py#L1991) | pytest / 2 | 上の旧条件・主要assertion対応表を参照 | 直接関数・小fixture |
| `deploy-reduction::finish_io_failure` | `check_finish_io_failure` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L450) | pytest / 2 | 実行証拠付きplanを保持し、PREPAREDのModel I/O失敗でgenerationなし、MODEL_PUBLISHEDのgeneration I/O失敗でModel再公開・生成物公開なし | 直接関数・小fixture |
| `deploy-reduction::session_sync_failure_drains_and_resumes` | `check_session_sync_failure_drains_and_resumes` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py#L533) | pytest / 1 | 上の旧条件・主要assertion対応表を参照 | 直接関数・小fixture |

| controller suite内の処理 | 1024v4設計値 | 再構成後の静的呼出構造 |
|---|---:|---:|
| full seed / Project全生成 / Git init | 各66 | 各6（6フローにつき1回） |
| 初期Gitコマンド | 330 | 30（seed内5 × 6） |
| Python子process | 100 | 7（Remove 2、Observed peer resume 1、Model partial 2、cleanup 2） |
| 小型IT / 新規UTに追加するPython子process | — | 0 |

controllerの親process invokeは6回（正常1・配送失敗1・承認待ち1・Observed I/O失敗1・外部修復初回1・完了後結果再適用1）。子process invoke7回と合わせ13回。各責務の再開のみ残し、細かな条件の往復は直接UTへ集約した。seedの初期sync(write=True)6回とは別に、完了内容を検証するsync(False)は正常と必要な復旧の5フローで各1回を保持する。外部修復receiptの通常Git provenance操作とWorktree専用処理はこの初期Git数に含めない。

これは実処理回数の設計値であり実測時間・速度倍率ではない。既存sleep無効化を新たな削減に算入しない。将来の正式CIでcontroller単独60秒目標と、関連UT・小型ITを含めた合計を計測する。今回IT未実行・未収集、CI未起動、60秒未計測。


## Deploy Framework digest removal

## Project Framework scan removal

Framework更新検知専用の `check_module_keys`（1 UT、Project入力の変更）を削除。
永続PASS保存のOSError/JSON bytes専用UT（1）を廃止し、実行寿命の検証へ変更。
ITの `check_single_target_cache` / `check_template_consumers`（2ケース）は呼出元所有Cache / 変更のないinput_context内で再利用し、ディスクPASS削除を廃止。
`check_task_service_validation`（1ケース）から別processの永続PASS再利用条件1個と実行1回を削除し、.lock保護は既存fresh/profile実行で確認する。
関連ITは既存のModel/参照/生成連携を保持し、新規ITなし。Framework配布・import安全性ITは別責務として保持。

| Source | Entry | Kind | Location | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `project-cache::lifetime` | `check_cache_lifetime` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L106) | pytest / 1 | Framework全件探索禁止、実行内共有、実行を跨ぐPASS失効、実行終了後のPASS失効 | Validation Cache |
| `project-generation::common` | `check_snapshot_project_common_inputs` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L262) | pytest / 2 | common選択の再利用、Framework/配布README非登録、Project変更/削除の最終照合・sealed bytesと外部変更保持 | Generation |
| `repair-snapshot::paths` | `check_validation_snapshot_project_paths` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py#L687) | pytest / 2 | Git管理されたルート.lockファイル/配下とFrameworkを除外し、tracked/untracked・欠落・通常Hash変更検知と禁止パス拒否を維持 | Repair Snapshot |
| `project-validation::common` | `check_common_cache_guard` | UT | [units/validation_checks/runner.py](units/validation_checks/runner.py#L120) | direct / 1 | 実Validatorのcommon初回/最終各1回、同一input_contextのCatalog PASS再利用 | Runner |

## Issue 19: Issues Scan responsibility boundaries

24旧入口（20 pytest + 4 direct）を6 pytestフローに統合する。フルScanはPython内9回から1回へ、別processのCLI Scanは1回から0回へ。例外6種類は依存先を置き換えたrunner UTで確認する。ITは本番のScan/Lint/Comparison/Saveを高速化目的で置き換えない。通常は1 Stack・1 Service・partsなし、cross-serviceだけ2 Stackを使う。Git初期化/commit/revision取得は行わない。CLIのscan exit契約は既存 `integrations/issues_api_only.checks.py::main_checks` / `cli_exit` に集約する。

### Active registrations

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `issues19::check_scan_publish_mismatch` | `check_scan_publish_mismatch` | IT | [integrations/issues_scan.checks.py](integrations/issues_scan.checks.py) | pytest / 1 | 実Scan→実Lint→JSON Artifact→review→Save→Report/Detail、一度だけ実行・再集計/再比較/再Lint禁止・入力変更後も既存Reviewで保存 | 統合 |
| `issues19::check_save_scope_and_rollback` | `check_save_scope_and_rollback` | IT | [integrations/issues_scan.checks.py](integrations/issues_scan.checks.py) | pytest / 1 | 全Target Snapshot保存・部分Scope拒否・2出力目replace後失敗で原子的Rollback | 統合 |
| `issues19::check_detail_cli` | `check_detail_cli` | IT | [integrations/issues_scan.checks.py](integrations/issues_scan.checks.py) | pytest / 1 | 小さい保存Artifact→Detail CLI→filter/paginationのJSON一致 | 統合 |
| `issues19::check_cloudtrail_comparison` | `check_cloudtrail_comparison` | IT | [integrations/issues_scan.checks.py](integrations/issues_scan.checks.py) | pytest / 1 | 実Model/CFn読込→EventSelectors親子所属と重複要素→matched | 統合 |
| `issues19::check_cross_service_reference` | `check_cross_service_reference` | IT | [integrations/issues_scan.checks.py](integrations/issues_scan.checks.py) | pytest / 1 | 2 Stackで共有Templateを一度decode、独立parameter評価・実KMS/Logs Model→Export/Import→Reference・正本非変更 | 統合 |
| `issues19::check_condition_provenance` | `check_condition_provenance` | IT | [integrations/issues_scan.checks.py](integrations/issues_scan.checks.py) | pytest / 1 | 実Condition/parameter-file→行/key/source付き診断→Report/Summary/Detail | 統合 |
| `issues19::check_scan_exception_classification` | `check_scan_exception_classification` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 7 | scan exception classification、RuntimeErrorと既存診断保持、IaCのNOT_RUN/未検証記録 | 未保証分のみ小入力へ移設 |
| `issues19::check_save_authority_rejections` | `check_save_authority_rejections` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 5 | save authority rejections | 未保証分のみ小入力へ移設 |
| `issues19::check_causal_report_grouping` | `check_causal_report_grouping` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | causal report grouping | 未保証分のみ小入力へ移設 |
| `issues19::check_model_part_bytes_and_legacy_rows` | `check_model_part_bytes_and_legacy_rows` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | model part bytes and legacy rows | 未保証分のみ小入力へ移設 |
| `issues19::check_missing_template_report` | `check_missing_template_report` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | missing template report | 未保証分のみ小入力へ移設 |
| `issues19::test_receiver_contracts` | `test_receiver_contracts` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L700) | pytest / 46 | receiver contracts | 未保証分のみ小入力へ移設 |
| `issues19::test_glue_connection_name` | `test_glue_connection_name` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L732) | pytest / 14 | glue connection name | 未保証分のみ小入力へ移設 |
| `issues19::test_formal_return_attributes` | `test_formal_return_attributes` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L763) | pytest / 5 | formal return attributes | 未保証分のみ小入力へ移設 |
| `issues19::test_glue_secret_identity` | `test_glue_secret_identity` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L778) | pytest / 3 | glue secret identity | 未保証分のみ小入力へ移設 |
| `issues19::test_action_context_requires_own_codecommit_contract` | `test_action_context_requires_own_codecommit_contract` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L789) | pytest / 6 | action context requires own codecommit contract | 未保証分のみ小入力へ移設 |
| `issues19::test_eventbridge_literal_requires_exact_lambda_identity` | `test_eventbridge_literal_requires_exact_lambda_identity` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L814) | pytest / 13 | eventbridge literal requires exact lambda identity | 未保証分のみ小入力へ移設 |
| `issues19::test_symbolic_setting_classification` | `test_symbolic_setting_classification` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L849) | pytest / 9 | symbolic setting classification | 未保証分のみ小入力へ移設 |
| `issues19::test_model_policy_links_bind_but_raw_intrinsics_do_not` | `test_model_policy_links_bind_but_raw_intrinsics_do_not` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L885) | pytest / 5 | model policy links bind but raw intrinsics do not | 未保証分のみ小入力へ移設 |
| `issues19::test_managed_policy_attachment_edges` | `test_managed_policy_attachment_edges` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L910) | pytest / 4 | managed policy attachment edges | 未保証分のみ小入力へ移設 |
| `issues19::test_inline_policy_ownership` | `test_inline_policy_ownership` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L934) | pytest / 5 | inline policy ownership | 未保証分のみ小入力へ移設 |
| `issues19::test_quicksight_api_group_principal` | `test_quicksight_api_group_principal` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L954) | pytest / 27 | quicksight api group principal | 未保証分のみ小入力へ移設 |
| `issues19::test_flowlog_resource_type_context` | `test_flowlog_resource_type_context` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1037) | pytest / 5 | flowlog resource type context | 未保証分のみ小入力へ移設 |
| `issues19::test_security_group_ref_requires_vpc` | `test_security_group_ref_requires_vpc` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1051) | pytest / 6 | security group ref requires vpc | 未保証分のみ小入力へ移設 |
| `issues19::test_cloudtrail_membership_comparison` | `test_cloudtrail_membership_comparison` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1063) | pytest / 5 | cloudtrail membership comparison | 未保証分のみ小入力へ移設 |
| `issues19::test_export_isolation_and_substitution_failures` | `test_export_isolation_and_substitution_failures` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1093) | pytest / 6 | export isolation and substitution failures | 未保証分のみ小入力へ移設 |
| `issues19::test_unknown_reference_property_never_infers_from_name` | `test_unknown_reference_property_never_infers_from_name` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1130) | pytest / 8 | unknown reference property never infers from name | 未保証分のみ小入力へ移設 |
| `issues19::test_codebuild_secret_context` | `test_codebuild_secret_context` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1139) | pytest / 4 | codebuild secret context | 未保証分のみ小入力へ移設 |
| `issues19::test_policy_statement_bijection` | `test_policy_statement_bijection` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1156) | pytest / 7 | policy statement bijection | 未保証分のみ小入力へ移設 |
| `issues19::test_nested_diagnostics_retain_format_and_failures` | `test_nested_diagnostics_retain_format_and_failures` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1211) | pytest / 2 | 確定差分とネスト診断・参照失敗・位置・秘匿化を併存 | 未保証分のみ小入力へ移設 |
| `issues19::test_naming_materials_mode_and_root_targets` | `test_naming_materials_mode_and_root_targets` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1377) | pytest / 1 | naming materials mode and root targets | 未保証分のみ小入力へ移設 |
| `issues19::test_stack_partition_and_noecho` | `test_stack_partition_and_noecho` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1410) | pytest / 6 | stack partition and noecho | 未保証分のみ小入力へ移設 |
| `issues19::test_inactive_inline_policy_provenance` | `test_inactive_inline_policy_provenance` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1432) | pytest / 1 | inactive inline policy provenance | 未保証分のみ小入力へ移設 |
| `issues19::test_inline_policy_document` | `test_inline_policy_document` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1448) | pytest / 3 | inline policy document | 未保証分のみ小入力へ移設 |
| `issues19::test_grouped_parent_reference` | `test_grouped_parent_reference` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1464) | pytest / 1 | grouped parent reference | 未保証分のみ小入力へ移設 |
| `issues19::test_run_mode_classification` | `test_run_mode_classification` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1479) | pytest / 4 | run mode classification | 未保証分のみ小入力へ移設 |
| `issues19::test_import_failure_cause_requires_unique_path` | `test_import_failure_cause_requires_unique_path` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1499) | pytest / 3 | import failure cause requires unique path | 未保証分のみ小入力へ移設 |

CloudFormation共通入力判定は `units/cloudformation-inputs-unit.checks.py` へ移管した。strict parameterの型/制約/不正入力・permissive loader保持、Condition組合せ/不明/循環/型を専用UTだけで検証する。`units/comparison_core-unit.checks.py` にはComparison固有のprovenance/default/pseudo/秘匿値と評価接続を残す。Condition定義は `support/cloudformation_inputs_fixtures.py` を共有し、同じ判定assertionを複製しない。既存CloudTrail行順/不足/重複、配列構築、型付き等値、Symbolic String評価のassertionも維持する。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `cloudformation-inputs::parameters` | `check_parameters` | UT | [units/cloudformation-inputs-unit.checks.py](units/cloudformation-inputs-unit.checks.py#L25) | pytest / 1 | 旧Comparison共通判定を移管: 6型/default/明示値、12制約拒否、5不正入力、非厳格値保持 | 小入力/Mock読込 |
| `cloudformation-inputs::conditions` | `check_conditions` | UT | [units/cloudformation-inputs-unit.checks.py](units/cloudformation-inputs-unit.checks.py#L60) | pytest / 1 | 旧Comparison共通判定を移管: false 4件、true 2件、不明/循環/非boolean/未対応拒否4件 | 共有Condition定義 |
| `cloudformation-inputs::identity` | `check_import_order_and_blocked_identity` | UT | [units/cloudformation-inputs-unit.checks.py](units/cloudformation-inputs-unit.checks.py#L75) | pytest / 5 | AWS SDK/Comparison/Deploy/Import/Validationの独立import順序とBlocked同一性、旧モジュール非読込 | 独立Python process |

### 旧24入口のassertion対応

次表は実行登録ではなく保証の対応表。複数責務を含む旧入口はassertion群ごとに維持/移設/重複削除を分ける。旧関数名の互換aliasやdecoratorは残さない。

| 旧入口 | Assertion群の分類と移設先・既存保証 |
|---|---|
| `naming_target_scope_cases` | UT移設: materialへのroot Name選択とnested除外は `test_naming_materials_mode_and_root_targets`。重複削除: path/pattern判定そのものは既存 `model-validations-unit::check_naming_target_paths`。 |
| `checks` | IT維持: Scan/Lint/naming/Artifact/Save・非blocking差分・入力変更後の既存Review保存は `check_scan_publish_mismatch`、共有decode/独立Stack評価は `check_cross_service_reference`、全Target scope/rollbackは `check_save_scope_and_rollback`。UT移設: strict/missing/template report、CRLF入口/parts・位置/row indexは `check_model_part_bytes_and_legacy_rows` / `check_missing_template_report`、入力変更許容・review/Task拒否・現run IaC置換はIssues UT。重複削除: typed/Tags/secretはcomparison_core、通常比較の変更保護は `check_comparison_input_tracking_is_report_only`、最新Snapshot/独立Human情報は `check_snapshot_replaces_inventory`、OSErrorのstaging/replaceはfile_operations UT。 |
| `resource_cases` | UT移設: IMPORT/Terraform/未宣言Stackは `test_run_mode_classification`。重複削除: duplicate/type/explicit CFn identityは `test_issues_iac::ExplicitIdentityTests`、Ref/GetAtt/recorded/PENDING/handoffはreference-evidence UT、Select/Splitはcomparison_core。 |
| `extended_cases` | UT移設: inline childの所属/欠落/多重/JSONエラー/配列順は `test_inline_policy_ownership` / `test_inline_policy_document`、独立KMS Aliasのimplicit parentReferenceは `test_grouped_parent_reference`、IMPORT実名/CREATE必須名はnaming UT、NoEcho/partitionは `test_stack_partition_and_noecho`。重複削除: singleton schema arrayは `test_receiver_contracts` と既存型判定、Fn/NoValueは既存test_issues_iac/core、Properties parserはmodel_design UT、View driftはissues_scan ITとissues_scan-unitのView障害判定、CLI Scan exit=0はissues_api_only IT。 |
| `check_nested_membership` | 重複削除: 既存 `comparison_core-unit` のexplicit/implicit配列構築・順序/重複と `test_issues_iac::test_formal_pipeline_membership_and_configuration_context` の親子context/独立property比較に集約。 |
| `check_cloudtrail_membership` | IT維持: 実Model/TemplateのEventSelectors比較は `check_cloudtrail_comparison`。UT移設: 親移動/重複不足/余分parent/type変更・不完全配列と独立IsLogging差分は `test_cloudtrail_membership_comparison`。重複削除: 行順不変/不足・重複rowは既存comparison_core。 |
| `check_condition_diagnostics` | IT維持: parameter-file→false→行/key/cause→集計/Report/Detailは `check_condition_provenance`。UT移設: true/default/And/Or/Not/If/Sub・missing/cycle/non-boolean/unknown・NoEcho/名前secret/numeric・Region/StackName provenanceはcomparison_core、inline child条件は `test_inactive_inline_policy_provenance`、偽resultのproven cause拒否は `check_causal_report_grouping`。 |
| `check_scan_workflow` | UT移設: 例外7種類のcategory/途中5レコード保持/末尾incomplete/summary/report/group membership/全channel masking/reference warningは `check_scan_exception_classification`。IT維持: 旧directの結合経路は7フローへ、sequential_reportsのCLI mergeは `check_cli_save_results`。 |
| `check_summary_detail_cli` | IT維持: `check_detail_cli`。重複削除: 1000件pagination/全ID/未表示分の取得は既存 `check_summary_scale`、CLIには3件だけ使用。 |
| `check_arn_array_reference_forms` | UT移設: `test_managed_policy_attachment_edges` / `test_unknown_reference_property_never_infers_from_name` / `test_formal_return_attributes`、一要素arrayの受信側属性は `test_receiver_contracts`。重複削除: 型付きidentity/Arn form/不明anchor/PENDINGは既存reference-evidence/test_issues_iacとreceiver UTへ集約。 |
| `check_eventbridge_reference_literals` | UT移設: partition/region/account/qualifier/service/name/別resource/属性/欠落/inactive対応は `test_eventbridge_literal_requires_exact_lambda_identity`。重複削除: 順序/多重度/selected subset/maskingはcomparison_coreと既存reference-evidence、S3 literalはissues_policy_equivalence IT。 |
| `check_glue_connection_names` | UT移設: `test_glue_connection_name` にscalar/Fn入力・別名/未解決/自己参照/相互循環/stray Name・Sub置換を小入力化。重複削除: 他サービスの明示Name/Subは既存 `test_issues_iac::test_codecommit_name_uses_only_explicit_repository_name`。 |
| `check_added_reference_properties` | UT移設: receiving property全件・formal producer/attribute・wrong type/anchor/IMPORTは `test_receiver_contracts`、SecurityGroup VpcIdは `test_security_group_ref_requires_vpc`、FlowLog contextは `test_flowlog_resource_type_context`、API-only QuickSight Groupのidentity/Arn構築/不正/未確定/禁止mode/Permissions順序は `test_quicksight_api_group_principal`。重複削除: KMS形式matrixとrecorded evidenceは既存reference-evidence、generic array順序/重複はcomparison_core。 |
| `check_aws_standard_comparison` | UT移設: inverse policy role edge/disabled/missing/unresolvedは `test_managed_policy_attachment_edges`、Secret Type/context/selectorは `test_codebuild_secret_context`、Statement全単射/不明と確定差分は `test_policy_statement_bijection` / `test_unordered_augmenting_paths`。重複削除: mixed PLAINTEXT/SECRETS_MANAGER/属性は既存 `test_issues_iac::test_resource_attributes_and_codebuild_plaintext_prohibition`、Sub/Fnは既存IntrinsicWarningTests、IAM Action/Policyの実結合はissues_policy_equivalence IT。 |
| `check_comparison_repair` | UT移設: strict typed/default/invalid/supplied/duplicate/permissive parameterはcomparison_core、partitionとsecret取得は `test_stack_partition_and_noecho`。IT維持: cross-service real bindingは `check_cross_service_reference`。重複削除: ServiceRoleとRoleNameは既存reference contract、explicit IDがない場合の候補探索禁止/duplicate/typeはtest_issues_iac。 |
| `check_local_reference` | IT維持: `check_cross_service_reference`。UT移設: healthy Export/unknown/conditional output/不正export name/名前cycleと再探索禁止は `test_export_isolation_and_substitution_failures`。重複削除: recorded declaration/権威不変/未観測・import cycle/duplicate/inactive/wrong contextは既存reference-evidence/test_issues_iac、deployでsymbolicを許可しない境界はcomparison_core。 |
| `check_symbolic_string` | UT移設: 実setting categoryとbound symbolic対不明/型不正は `test_symbolic_setting_classification`、Model linkのbindingと未binding intrinsic警告は `test_model_policy_links_bind_but_raw_intrinsics_do_not`。重複削除: Select/Split/Join/Sub・型/境界/操作/identity・deploy modeは既存comparison_core、未解決intrinsicの独立比較はtest_issues_iac。 |
| `check_reference_property_contract` | IT維持: CloudTrail/linkとcross-service読込は代表ITへ。UT移設: CodeCommit ActionTypeId全条件/欠落/wrong producerは `test_action_context_requires_own_codecommit_contract`、formal return属性は `test_formal_return_attributes`。重複削除: CodeCommit Name/Ref vs GetAtt/明示名literalはtest_issues_iac、indexed action context/順序は同既存UTとcomparison_core、QuickSight unsupported Refはissues_ref_returns IT。 |
| `check_reference_diagnostics` | UT移設: 実parentへのreference diagnostic/format/identity/child failureと秘匿化は `test_nested_diagnostics_retain_format_and_failures`。重複削除: Athena/KMS form全matrixは既存reference-evidence、Summary/Detail制限とredactionは `check_summary_scale` / `check_mismatch_rendering`、実service比較はissues_failed_services IT。 |
| `check_reference_identity_report` | IT維持: real KMS Export/Importは `check_cross_service_reference`。UT移設: cached Exportの障害隔離は `test_export_isolation_and_substitution_failures`、現run report置換は `check_snapshot_replaces_inventory`。重複削除: identity/forms/recorded/unproven優先順位は既存reference-evidence/test_issues_iac、Reportの全件所属/ID・欠落cause分類はsummary UTと `check_causal_report_grouping`。 |
| `check_action_report` | UT移設: direct/cascade同cause grouping・別path/parameter/不明causeの分離・独立setting ID/duplicatesは `check_causal_report_grouping`、cause単一性の証明は `test_import_failure_cause_requires_unique_path`。重複削除: 大量レコード保持/順序/ID/秘匿化/対象scope/未表示件数は既存 `check_summary_scale` / `check_mismatch_rendering`。 |
| `check_mismatch_display` | IT維持: `check_scan_publish_mismatch`。重複削除: NoEcho display side-channel/型/Tags/長文/ID/summary/detail/annotationsは既存 `check_mismatch_rendering` / `check_summary_scale` とstack NoEcho UT。 |
| `check_state_report` | IT維持: 全Target current snapshot/部分scope拒否/実2出力Rollbackは `check_save_scope_and_rollback`。UTは `check_atomic_rollback` と `check_snapshot_replaces_inventory`。重複削除: OSError staging/replace/afterは既存file_operations UT。 |
| `check_glue_secret_reference` | UT移設: Glue/Secret Ref/GetAtt正式属性とwrong Arnは `test_formal_return_attributes`、同名別Secretとnested ConnectionInput比較は `test_glue_secret_identity`、Glue名/自己参照は `test_glue_connection_name`。重複削除: IAM Policy内のsecret同一性は既存test_issues_iacのcontextとreference contract。 |

### Designサービス固定定義Registry

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `design-definitions::values` | `check_values` | UT | [units/design-definitions-unit.checks.py](units/design-definitions-unit.checks.py#L74) | direct / 1 | 移動前の31 Policy形式・参照・非表示・Name Tag・Packed定義を完全維持 | 固定baseline |
| `design-definitions::duplicates` | `check_duplicates` | UT | [units/design-definitions-unit.checks.py](units/design-definitions-unit.checks.py#L87) | direct / 1 | Pendingを含む7集合すべての重複登録を拒否 | 小型定義 |
| `design-definitions::registration` | `check_registration` | UT | [units/design-definitions-unit.checks.py](units/design-definitions-unit.checks.py#L99) | direct / 1 | 25サービスの明示登録・決定順・純粋データ依存 | 固定定義module |
| `design-layout::import-order` | `check_import_order` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L74) | pytest / 14 | Layout・Policy・EC2 SG・Model表示/検証/描画/変更比較・共通Array/Subnet・5サービスの先頭importで循環初期化を検出 | 独立Python process |
| `design-layout::import-pending` | `check_import_pending_reference` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L79) | pytest / 1 | 許可3PropertyとPending完全一致、未登録Property・Backtick・literal/link拒否 | 小型入力、Model UTの重複したliteral/link判定を移管 |

## Incomplete Model settings and confirmed IaC differences

| Case ID | Function | Layer | Source | Execution / Count | Contract | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| `incomplete::missing-structure` | `test_incomplete_codebuild_missing_structure` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1189) | pytest / 2 | 属性未指定KMS.Aliasを含む変数・親欠落をdifference一件と未比較一件で保持 | CodeBuild合成 |
| `incomplete::presence-siblings` | `test_incomplete_setting_presence_and_siblings` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1248) | pytest / 14 | 既知兄弟差分・追加IaC許容・存在不明・null/false/空値・NoValue・Conditionを分離 | 共通設定比較 |
| `incomplete::all-failed` | `test_all_children_failed_preserve_parent_and_categories` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1304) | pytest / 2 | 全子準備失敗でも親存在確認、errorとuncomparedの区別、matched防止 | 共通設定比較 |
| `incomplete::processing-errors` | `test_preparation_error_retains_confirmed_difference` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1363) | pytest / 5 | 値準備の実例外と確定欠落を併存 | 例外分類 |
| `incomplete::artifact` | `check_incomplete_setting_artifact` | IT | [integrations/issues_failed_services.checks.py](integrations/issues_failed_services.checks.py#L186) | direct / 1 | 合成Model読込→比較→集計→artifact詳細→iac-issues、位置・秘匿化・件数・欠落表示 | Frameworkのみ |
| `incomplete::json-children` | `test_incomplete_json_preserves_declared_children` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1324) | pytest / 8 | JSON全体行の子参照失敗でもフィールド・要素・値差分とPointerを保持、require_valueは失敗を返す | 共通設定比較 |

## Issue #20 check-model-aws responsibility separation

既存UTのRegistry構造・Mapping baseline（aws_mapping-unit）、Profile/Account判定
（aws-identity-unit）、SDK接続分離/ページング（aws-client）、正規化/集計
（check-model-aws-unit）は既存の検証先を維持する。本番コード、runner、receipt、CIは変更しない。

| 旧assertion群 | 現在の検証先 | 保証 |
| --- | --- | --- |
| service_checks 全Resource/Field/Identity/trace | check_service_adapters | 52 Adapter Type、全supported Mapping、ID/ARN/Name、実fetch、27サービス×4状態。SDK schemaから応答を生成 |
| identity_registry_checks | check_identity_registry | Registry優先、欠落/None、存在確認後Name選択、禁止API、Stack未対応 |
| check_cli_service_names | check_cli_service_names (UT) | 4コマンド×2 pagination引数 |
| cli_checks error/引数/cache/redaction | check_cli_errors | CLI例外4種、AWSエラー2種、禁止API、Unicode、pagination cache/失敗 |
| cli_checks end-to-end | cli_checks (IT) | Model→CLI→Context→比較、profile/region/owner/JSON、STSとcache |
| batch_checks missing/invalid/duplicate selector | check_batch_selectors | missing入口、8不正selector、all、inventory/CLI/coverage重複排除 |
| batch_checks SDK integration | batch_checks (IT) | 複数Service/Target、各Target独立Session/Context/STS、成功維持と失敗優先順位、coverage再読込 |
| common_checks 入力/identity/API account/変換/Stack状態 | check_context_branches | 未定義Mapping、UNSET、影響key集約、禁止API、実行account、API owner、session失敗、配列parse、Stack3状態 |
| common_checks split/SDK/reference/paginator | common_checks (IT) | split Model source、SDK Stubber、cache/trace、実paginator成功/後続失敗、IAM/KMS/export参照 |
| association_checks tag/stage/partial/IMPORT | check_association_values | Key/Value結合、stage曖昧性、部分失敗と集約、IMPORT比較 |
| association_checks KMS parent | association_checks (IT) | 2 Resource間parentReferenceとSDK応答の結合 |
| stack_checks 状態/name/error9条件 | check_stack_states | trace、metadata、cache、allowlistも旧assertionを維持 |
| stack_checks Model/CLI接続 | stack_checks (IT) | Stack Model→Context→CLI応答→比較/local metadata |
| cfn_identity_checks / fixture_coverage | 同名IT | Stack instanceごとのRef解決、全Mapping/Model再読込、consumer条件付き実行 |
| 新Fixture | check_schema_rejections / check_context_isolation_and_cache | 不正API/入力/応答拒否、未知FieldはMISSING、Context分離、schema再利用、cache/trace、応答の独立性、接続変更拒否 |

重複削除: SDK経路による同一batchのdirect反復と重複selector反復、association末尾の
ROLLBACK_COMPLETE（check_stack_statesと同一判定）、CLIのdifference（全Adapter4状態）。account/profile拒否のtransport未実行保証と
CLI/coverageの重複selectorはcheck_cli_errors / check_batch_selectorsへ移管。

IT pytest条件数18→8（check_domains 9→7、CLI名8→UT、consumer 1維持）、
IT direct登録9→7。対象check-model-aws UT条件数5→22（既存UT19、新Adapter1、Fixture2）。
内部の全52 Type/全Field/Identity/27×4条件は1 Adapter入口の中で全件実行する。
新Fixtureはboto3 Client/Sessionを生成せず、immutable SDK Service Modelだけ実行内再利用する。
実SDK paginatorの挙動は軽量Fixtureで代替せずITに残す。10秒達成は後続同条件CIで判定する。

| Source | Case | Layer | Location | Mode / count | Responsibility | Origin |
| --- | --- | --- | --- | --- | --- | --- |
| `issue20::check_cli_service_names` | `check_cli_service_names` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L116) | pytest / 8 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_stack_states` | `check_stack_states` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L129) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_identity_registry` | `check_identity_registry` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L165) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_cli_errors` | `check_cli_errors` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L193) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_batch_selectors` | `check_batch_selectors` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L252) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_context_branches` | `check_context_branches` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L299) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_association_values` | `check_association_values` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py#L379) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_service_adapters` | `check_service_adapters` | UT | [units/check-model-aws-adapter-unit.checks.py](units/check-model-aws-adapter-unit.checks.py#L40) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_schema_rejections` | `check_schema_rejections` | UT | [units/check-model-aws-fixture-unit.checks.py](units/check-model-aws-fixture-unit.checks.py#L29) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |
| `issue20::check_context_isolation_and_cache` | `check_context_isolation_and_cache` | UT | [units/check-model-aws-fixture-unit.checks.py](units/check-model-aws-fixture-unit.checks.py#L48) | pytest / 1 | 上記対応表の保証 | Issue #20移管/fixture契約 |

| `issue-18` | `check_snapshot_guards` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L864) | pytest / 8 | 通常TaskのHEAD/index/lock変更拒否・Issue変更許容・Windows runner保護 | Fake境界で確認 |
| `issue-18` | `check_log_directory_rejected` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L911) | pytest / 1 | 通常TaskのHEAD/index/lock変更拒否・Issue変更許容・Windows runner保護 | Fake境界で確認 |

## Issue 18 Blueprint Loopの検証責務

ITは10関数・21条件から7関数・7条件へ再構成。外側Loop CLIは38回から7回、Sync CLIは2回から0回。stagedの子Loopは別に旧3回→2回。未解決indexは実Git `index_tree` の直接検証を保持する。実行時間は正式CIで確認する。

| 旧ケース・assertion（変更前の行） | 変更後の検証先 | 対応 |
|---|---|---|
| `check_running_and_interruption:69` history[0]['jobs'] == 1 and history[0]['python_version'] == sys.version | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:70` history[0]['hash_seed'] == environment.get('PYTHONHASHSEED') | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:71` next((event for event in history if event['event'] == 'step_start'))['command'] == command | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:72` any((event['event'] == 'heartbeat' for event in history)) | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:73` 'RUNNING slow.py' in output.getvalue() | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:74` 'before wait' in (logs / '01-slow.py.log').read_text(encoding='utf-8') | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:75` history[-1]['status'] == 'pass' | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:76` history[-1]['duration_seconds'] >= 0.15 | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:78` running['pid'] > 0 | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:89` [event['status'] for event in ended] == ['error', 'pass'] | UT `blueprint-loop-unit::check_process_interruption` | 不足OSErrorのみ統合 |
| `check_running_and_interruption:90` ended[0]['error'] == 'cannot start' | UT `blueprint-loop-unit::check_process_interruption` | 不足OSErrorのみ統合 |
| `check_running_and_interruption:91` events(logs)[-1]['status'] == 'fail' | UT `blueprint-loop-unit::check_process_interruption` | 不足OSErrorのみ統合 |
| `check_running_and_interruption:67` MODULE.run_commands(root, [command], environment, logs, heartbeat_seconds=0.03) == 0 | IT `check_running_and_interruption` | 維持 |
| `check_running_and_interruption:87` MODULE.run_commands(root, [command, command], environment, logs) == 1 | UT `blueprint-loop-unit::check_process_interruption` | 不足OSErrorのみ統合 |
| `check_deploy_scope_isolation:172` result.returncode != 0 and 'outside Deployment scope' in result.stdout | IT `check_deploy_scope_isolation` | 維持 |
| `check_deploy_scope_isolation:173` 'invalid CloudFormation parameter JSON' not in result.stdout | IT `check_deploy_scope_isolation` | 維持 |
| `check_deploy_scope_isolation:175` result.returncode != 0 and 'invalid CloudFormation parameter JSON' in result.stdout | IT `validation_checks/scope::check_deployment_iac_scope`（Scope/JSON）、UT `blueprint-loop-unit::check_unit_dispatch`（2種diff・CRLF設定）、IT `worktree_task`（実Git whitespace） | 重複削除 |
| `check_deploy_scope_isolation:188` result.returncode != 0 and 'FAIL git-diff-check' in result.stdout | IT `validation_checks/scope::check_deployment_iac_scope`（Scope/JSON）、UT `blueprint-loop-unit::check_unit_dispatch`（2種diff・CRLF設定）、IT `worktree_task`（実Git whitespace） | 重複削除 |
| `check_deploy_scope_isolation:182` result.returncode != 0 and 'FAIL git-diff-check' in result.stdout | IT `validation_checks/scope::check_deployment_iac_scope`（Scope/JSON）、UT `blueprint-loop-unit::check_unit_dispatch`（2種diff・CRLF設定）、IT `worktree_task`（実Git whitespace） | 重複削除 |
| `check_deploy_scope_isolation:184` result.returncode != 0 and 'FAIL git-diff-check' in result.stdout | IT `validation_checks/scope::check_deployment_iac_scope`（Scope/JSON）、UT `blueprint-loop-unit::check_unit_dispatch`（2種diff・CRLF設定）、IT `worktree_task`（実Git whitespace） | 重複削除 |
| `check_deploy_scope_isolation:186` result.returncode != 0 and 'FAIL git-diff-check' in result.stdout | IT `validation_checks/scope::check_deployment_iac_scope`（Scope/JSON）、UT `blueprint-loop-unit::check_unit_dispatch`（2種diff・CRLF設定）、IT `worktree_task`（実Git whitespace） | 重複削除 |
| `_callback_check_task_service_validation_run:195` 'START validate-blueprint.py' in result.stdout | IT `_callback_check_task_service_validation_run` | 維持 |
| `_callback_check_task_service_validation_run:196` 'validation scope: dev/123456789012/logs' in result.stdout or result.returncode != 0 | IT `check_task_service_validation`（正常接続）＋UT `check_unit_dispatch`（fresh/profile、cache/workerオプション）＋IT `validation_scope`（scope mismatch / 対象外不正入力） | 重複削除 |
| `_callback_check_task_service_validation_run:197` 'START git-diff-check' in result.stdout | IT `_callback_check_task_service_validation_run` | 維持 |
| `_callback_check_task_service_validation_run:198` 'framework regression: skipped' in result.stdout | IT `_callback_check_task_service_validation_run` | 維持 |
| `_callback_check_task_service_validation_run:199` 'START blueprint-loop-unit.checks.py' not in result.stdout | IT `check_task_service_validation`（正常接続）＋UT `check_unit_dispatch`（fresh/profile、cache/workerオプション）＋IT `validation_scope`（scope mismatch / 対象外不正入力） | 重複削除 |
| `check_task_service_validation:239` result.returncode == 0 | IT `check_task_service_validation` | 維持 |
| `check_task_service_validation:275` result.returncode == 0 and 'PASS (0 framework regression scripts)' in result.stdout | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:280` fresh.returncode == 0 and '1 executed, 0 reused; workers: 1' in fresh.stdout | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:281` list((tmp_path / 'logs').glob('*/validate-blueprint.prof')) | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:283` any((Path(file).name == 'sync_runtime.py' for file, _, _ in pstats.Stats(str(profile)).stats)) | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:289` tasks.status(active.read_text()) == 'suspend' | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:297` result.returncode != 0 and 'changed design path is outside validation scope' in result.stdout | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:311` result.returncode == 0 | IT `check_task_service_validation` | 維持 |
| `check_task_service_validation:315` result.returncode != 0 and 'generated Markdown is stale' in result.stdout | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:316` design.read_text(encoding='utf-8') == good_design | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:320` result.returncode != 0 and 'ec2' in result.stdout | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:321` 'Validation: all' in result.stdout and 'framework regression: skipped' in result.stdout | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:330` result.returncode == 0 | IT `check_task_service_validation` | 維持 |
| `check_task_service_validation:331` not subprocess.check_output(['git', 'diff', '--', str(design.relative_to(root))], cwd=root) | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_task_service_validation:332` design.read_text(encoding='utf-8') == good_design | UT `sync-model-unit::check_readonly_stale_views`（一致・不一致・無書込）＋IT `validation_scope`（対象外不正入力 / allの対象選択）＋UT `check_unit_dispatch`（all伝達） | 重複削除 |
| `check_parallel_and_selection:355` output.getvalue().index('diagnostic-a') < output.getvalue().index('diagnostic-b') | IT `check_parallel_and_selection` | 維持 |
| `check_parallel_and_selection:359` parallel == events(logs)[-1]['failed_steps'] == ['a.checks.py'] | IT `check_parallel_and_selection`（同期・失敗集約）、UT `check_parallel_interruption` / `check_process_interruption`（停止）、UT `check_unit_dispatch`（選択） | 重複削除 |
| `check_parallel_and_selection:354` MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=2) == 1 | IT `check_parallel_and_selection` | 維持 |
| `check_parallel_and_selection:358` MODULE.run_commands(root, commands, MODULE.utf8_environment(), logs, jobs=1) == 1 | IT `check_parallel_and_selection`（同期・失敗集約）、UT `check_parallel_interruption` / `check_process_interruption`（停止）、UT `check_unit_dispatch`（選択） | 重複削除 |
| `_callback_check_staged_snapshot_git_only:365` command[0] == 'git' | UT `blueprint-loop-unit::check_snapshot_guards`（Windows / HEAD / index / .lock別条件）＋IT `check_staged_snapshot`（実Git stale / write-tree拒否） | 細分条件はFake UTへ統合 |
| `check_staged_snapshot:417` result.returncode == 0 and '日本語 snapshot' in result.stdout | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:418` 'snapshot regression assertion executed' not in result.stdout | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:419` 'PASS (0 framework regression scripts)' in result.stdout | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:420` index.read_bytes() == saved_index | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:421` active.read_text(encoding='utf-8') == 'dirty workspace contract' | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:423` metadata['base'] == base and metadata['source_unchanged'] | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:450` result.returncode == 1 and 'HEAD/index/.lock changed' in result.stdout | IT `check_staged_snapshot` | 維持 |
| `check_staged_snapshot:458` result.returncode == 1 and 'snapshot is stale' in result.stdout | UT `blueprint-loop-unit::check_snapshot_guards`（Windows / HEAD / index / .lock別条件）＋IT `check_staged_snapshot`（実Git stale / write-tree拒否） | 細分条件はFake UTへ統合 |
| `check_staged_snapshot:466` result.returncode != 0 and 'START validate-blueprint.py' not in result.stdout | UT `blueprint-loop-unit::check_snapshot_guards`（Windows / HEAD / index / .lock別条件）＋IT `check_staged_snapshot`（実Git stale / write-tree拒否） | 細分条件はFake UTへ統合 |
| `check_staged_snapshot:441` 'current runner and regression guard' in str(error.value) | UT `blueprint-loop-unit::check_snapshot_guards`（Windows / HEAD / index / .lock別条件）＋IT `check_staged_snapshot`（実Git stale / write-tree拒否） | 細分条件はFake UTへ統合 |
| `check_regression_authorization:500` len(run.call_args.args[1]) == 3 | UT `blueprint-loop-unit::check_regression_authorization` / `check_unit_dispatch` | 失敗のみ移管、成功重複削除 |
| `check_regression_authorization:504` len(run.call_args.args[1]) == 4 | UT `blueprint-loop-unit::check_regression_authorization` / `check_unit_dispatch` | 失敗のみ移管、成功重複削除 |
| `check_regression_authorization:492` CLI.main() == 130 | UT `blueprint-loop-unit::check_regression_authorization` / `check_unit_dispatch` | 失敗のみ移管、成功重複削除 |
| `check_regression_authorization:498` CLI.main() == 0 | UT `blueprint-loop-unit::check_regression_authorization` / `check_unit_dispatch` | 失敗のみ移管、成功重複削除 |
| `check_regression_authorization:502` CLI.main() == 0 | UT `blueprint-loop-unit::check_regression_authorization` / `check_unit_dispatch` | 失敗のみ移管、成功重複削除 |
| `check_regression_authorization:488` CLI.main() == 2 | UT `blueprint-loop-unit::check_regression_authorization` / `check_unit_dispatch` | 失敗のみ移管、成功重複削除 |
| `check_failure_suspension:546` result.returncode == 1 and 'Task suspended' in result.stdout | IT `check_failure_suspension` | 維持 |
| `check_failure_suspension:548` tasks.status(text) == 'suspend' and 'schema mismatch' in text | IT `check_failure_suspension`（実Validator失敗・他Task保持）＋既存IT `task_contract::check_suspend_and_resume`（resume / 複数理由） | 重複削除 |
| `check_failure_suspension:549` (root / other).read_bytes() == untouched | IT `check_failure_suspension` | 維持 |
| `check_failure_suspension:550` 'PASS own.checks.py' in result.stdout | IT `check_failure_suspension`（実Validator失敗・他Task保持）＋既存IT `task_contract::check_suspend_and_resume`（resume / 複数理由） | 重複削除 |
| `check_failure_suspension:554` tasks.status((root / first).read_text()) == 'running' | IT `check_failure_suspension`（実Validator失敗・他Task保持）＋既存IT `task_contract::check_suspend_and_resume`（resume / 複数理由） | 重複削除 |
| `check_failure_suspension:558` result.returncode == 0 | IT `check_failure_suspension` | 維持 |
| `check_failure_suspension:559` tasks.status((root / first).read_text()) == 'running' | IT `check_failure_suspension`（実Validator失敗・他Task保持）＋既存IT `task_contract::check_suspend_and_resume`（resume / 複数理由） | 重複削除 |
| `check_failure_suspension:567` result.returncode == 1 and tasks.status(text) == 'suspend' | IT `check_failure_suspension`（実Validator失敗・他Task保持）＋既存IT `task_contract::check_suspend_and_resume`（resume / 複数理由） | 重複削除 |
| `check_failure_suspension:568` 'own.checks.py' in text and 'missing required field' in text | IT `check_failure_suspension`（実Validator失敗・他Task保持）＋既存IT `task_contract::check_suspend_and_resume`（resume / 複数理由） | 重複削除 |
| `check_failure_suspension:569` (root / other).read_bytes() == untouched | IT `check_failure_suspension` | 維持 |
| `check_startup_diagnostics:678` (details['step'], details['api']) == expected[phase] | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:679` details['cwd'] == str(root) | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:680` details['location']['line'] > 0 and details['location']['filename'] | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:681` 'Traceback (most recent call last)' in details['traceback'] | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:682` str(Path(MODULE.__file__)) in details['traceback'] | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:696` tasks.status(text) == 'suspend' and str(directory / 'startup-error.json') in text | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:697` (root / other).read_bytes() == untouched | IT `check_startup_diagnostics` | 維持 |
| `check_startup_diagnostics:675` CLI.main() == 2 | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:684` details['errno'] == 22 and details['winerror'] == 87 | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:685` details['filename'] == '日本語-input' | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:687` details['command'] == ['git', 'config', '--get', 'core.whitespace'] | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:689` details['returncode'] == 7 | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:691` details['command'][:3] == [sys.executable, '-X', 'utf8'] | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_startup_diagnostics:694` history[-1]['event'] == 'error' | UT `blueprint-loop-unit::check_startup_diagnostics`（全11条件、実diagnostics/Task、subprocessのみFake） | 移管 |
| `check_workflow:714` normal.returncode != 0 and 'AssertionError: normal check body reached' in normal.stderr | IT `check_workflow`（-O失敗・後続・ログ）、UT `check_it_assertion_guards`（静的全走査・最適化拒否）、UT `check_unit_dispatch`（複数実行でも既存ログ不変）、UT `check_log_directory_rejected` | 重複削除 |
| `check_workflow:734` result.returncode != 0 | IT `check_workflow` | 維持 |
| `check_workflow:735` 'AssertionError: assertions must run' in result.stdout | IT `check_workflow` | 維持 |
| `check_workflow:736` 'validate-blueprint.py, a.checks.py' in result.stdout | IT `check_workflow` | 維持 |
| `check_workflow:737` (root / 'continued').read_text(encoding='utf-8') == 'yes' | IT `check_workflow` | 維持 |
| `check_workflow:740` startup[0]['event'] == 'directory_created' | IT `check_workflow` | 維持 |
| `check_workflow:741` {'task.contract.read', 'git.config', 'commands.prepare', 'utf8.subprocess', 'utf8.output', 'utf8.cleanup', 'stdout.print', 'stdout.flush', 'timing.open'} <= {event['step'] for event in startup if event['event'] == 'end'} | IT `check_workflow` | 維持 |
| `check_workflow:745` history[0]['event'] == 'loop_start' and history[0]['step_count'] == 5 | IT `check_workflow` | 維持 |
| `check_workflow:747` [event['returncode'] for event in ended] == [1, 1, 0, 0, 0] | IT `check_workflow` | 維持 |
| `check_workflow:748` all((event['duration_seconds'] >= 0 for event in ended)) | IT `check_workflow` | 維持 |
| `check_workflow:749` history[-1]['event'] == 'loop_end' and history[-1]['status'] == 'fail' | IT `check_workflow` | 維持 |
| `check_workflow:750` history[-1]['failed_steps'] == ['validate-blueprint.py', 'a.checks.py'] | IT `check_workflow` | 維持 |
| `check_workflow:751` all(('timestamp' in event for event in history)) | IT `check_workflow` | 維持 |
| `check_workflow:752` 'AssertionError' in (failed_directory / '02-a.checks.py.log').read_text(encoding='utf-8') | IT `check_workflow` | 維持 |
| `check_workflow:757` result.returncode == 0 | IT `check_workflow` | 維持 |
| `check_workflow:758` 'PASS (2 framework regression scripts)' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:760` len(directories) == 2 | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:761` events((directories - {failed_directory}).pop())[-1]['status'] == 'pass' | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:762` events(failed_directory)[-1]['status'] == 'fail' | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:764` rejected.returncode != 0 and 'outside the repository' in rejected.stderr | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:780` result.returncode == 0 and 'PASS (0 framework regression scripts)' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:784` result.returncode == 0 and 'Validation: active scope' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:788` result.returncode == 0 and 'PASS (2 framework regression scripts)' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:794` not MODULE.framework_changed({'model/dev/cde/ec2.properties', 'docs/designs/dev/cde/ec2.md', 'tasks/example.md'}) | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:798` result.returncode == 0 and 'PASS (0 framework regression scripts)' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:799` not (root / 'continued').exists() | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:804` result.returncode == 0 | IT `check_workflow` | 維持 |
| `check_workflow:805` model.read_bytes() == b'design change\r\nCRLF line\r\n' | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:808` result.returncode == 0 | IT `check_workflow` | 維持 |
| `check_workflow:812` result.returncode != 0 and 'indent with spaces' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:817` result.returncode != 0 and 'FAIL git-diff-check' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:821` result.returncode != 0 and 'FAIL git-diff-check' in result.stdout | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:825` result.returncode and 'validation scope missing' in result.stderr | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:826` set(log_parent.glob('blueprint-loop-*')) == before | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:829` result.returncode and 'validation scope missing' in result.stderr | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:830` set(log_parent.glob('blueprint-loop-*')) == before | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `check_workflow:709` rejected.returncode != 0 and 'Focused checks require assertions' in rejected.stderr | IT `check_workflow`（-O失敗・後続・ログ）、UT `check_it_assertion_guards`（静的全走査・最適化拒否）、UT `check_unit_dispatch`（複数実行でも既存ログ不変）、UT `check_log_directory_rejected` | 重複削除 |
| `check_workflow:793` MODULE.framework_changed({path}) | UT `check_unit_dispatch`（full/task/local/all・diff 2種・CRLF）、UT `check_changed_paths_error`（Framework選択）、UT `validation_scope-unit::check_active_scope`（不完全scope拒否） | 重複削除 |
| `_snapshot_evidence_pack:846` command[:2] in (['git', 'pack-objects'], ['git', 'index-pack']) | UT `blueprint-loop-unit::check_import_snapshot_evidence`（finally 0/1）＋`import-model-unit::check_snapshot_proof_resigning_and_cleanup` | finally境界のみ移管 |
| `check_import_snapshot_evidence:874` MODULE.staged_snapshot(root, args, directory, MODULE.utf8_environment()) == result | UT `blueprint-loop-unit::check_import_snapshot_evidence`（finally 0/1）＋`import-model-unit::check_snapshot_proof_resigning_and_cleanup` | finally境界のみ移管 |
| `check_import_snapshot_evidence:876` not sealed_evidence.evidence_store(snapshot, create=False).exists() | UT `blueprint-loop-unit::check_import_snapshot_evidence`（finally 0/1）＋`import-model-unit::check_snapshot_proof_resigning_and_cleanup` | finally境界のみ移管 |
| `check_import_snapshot_evidence:877` import_guard.proof_path(root).read_bytes() == saved | UT `blueprint-loop-unit::check_import_snapshot_evidence`（finally 0/1）＋`import-model-unit::check_snapshot_proof_resigning_and_cleanup` | finally境界のみ移管 |
| `check_import_snapshot_evidence:878` not (root / '.blueprint').exists() and (not (snapshot / '.blueprint').exists()) | UT `blueprint-loop-unit::check_import_snapshot_evidence`（finally 0/1）＋`import-model-unit::check_snapshot_proof_resigning_and_cleanup` | finally境界のみ移管 |

`--profile`は本番callbackがprofileを書き出すことをUTで確認する。旧ITのSync内部ファイル名への依存は、CLIの統合契約ではないため再追加しない。Cache内容・無効化は既存 `validation_cache-unit` とIT `validation_scope::check_single_target_cache` が保証する。

通常系・失敗系は同じ `generated_policy` bundleを独立コピーする。ModelとMarkdownは同じModel reader/renderから構築し、本番Validatorを通す。Frameworkのコピー・改変は行わない。

既存design-definitions UTのassertion guardをモジュール先頭へ移動し、全チェックの静的guard検証を通す。定義値・検証assertionは保持する。

## Issue 15 Sync Model ITの責務再編

旧25関数・67 pytest条件のAssertionを下表で分類する。Human指定のmaster（43bee83）はすでに20関数・27条件へ再編済みであり、旧件数を現在の1024v9の実数とは扱わない。現行20関数・28条件。
対象UT3ファイルの合計は84→137条件（sync 34→69、model_design 46→59、validation_cache 4→9）。
ケース数は静的展開数であり、IT PASS・速度改善の実測ではない。
新しいfixture/共通module/runnerは追加せず、本番SyncとFramework定義は変更しない。
UTはGit init/commit・実Sync・全Model生成・全Frameworkコピーを行わない。

| 旧IT関数 | 旧→現IT条件 | 判断 | 実際のAssertion・既存UT・移管先・維持する接続保証 |
|---|---|---|---|
| `check_input_mutation` | 12 → 0 | UTへ移管 | GenerationInputs::check_snapshot_conflict（entry/part/独立other-modelのchange/delete、重複しない追加先）、check_snapshot_project_common_inputs（project change/delete）。旧other-modelはpartと同一、addのentry/other-model/projectは同一追加先なので統合。公開拒否と成果物保持はpublication_boundary等で実接続を維持。 |
| `check_internal_sync_isolation` | 4 → 1 | UT＋代表IT | 引数Scope/--all×jobs=1/4はcheck_internal_sync_selection。memo/heartbeat/ContextVarは既存check_internal_sync_concurrent_output、check_resource_row_scope_restoration。実target並列・成功失敗成功・親Context保護はITに維持。 |
| `check_integrated_validator` | 2 → 2＋失敗IT 1 | 責務分離 | Snapshotはcheck_guard_snapshot_candidates、Cacheは既存check_cache_inputs/check_cache_lifetime＋check_service_cache_invalidation、Git正味差分/permission/Acceptanceは既存check_final_git_paths/check_scope_git_collection/check_result_reuse_is_scoped、Task境界はcheck_planned_outputs_and_boundary、欠落入力はcheck_missing_validation_inputs。正常生成→保存→Acceptanceはinitial=False/Trueを維持。更新はMarkdownだけの公開と旧bytes、新規はMarkdown/JSONの欠落から生成とoriginals=Noneを確認。保存失敗→Acceptance不成立は別IT。 |
| `check_stage_candidate_isolation` | 6 → 1 | 直接判定＋接続IT | modelはcheck_candidate_model_metadata、names/schema/overviewはcheck_candidate_design_diagnostics（Schema単体だけでなく実Table ValidatorのMaxSessionDuration診断まで確認）、policyのStatement欠落拒否は既存policy_tables-unit::check_lossless_generation（既存check_required_resource_names等を重複追加しない）。Stage内Modelのservice不整合とリンク破損を同じ代表ITでそれぞれassertし、正常な元Modelへのfallback禁止と元Model/成果物保持を確認。正常Stage/CFnの別ITを維持。 |
| `check_stage_definition_errors` | 4 → 0 | UTへ移管 | check_definition_read_errorsがfresh Schema/Mapping/naming/layout readerに読取例外を注入。Framework定義は変更せず、例外伝播/Findingsへの記録を検証。 |
| `check_publication_boundary` | 6 → 1 | 差分種類をUT集約 | project/part/consumer/extra/taskのbytes・ファイル集合差分はsnapshot UT＋既存check_retained_common_key。実source変更の公開拒否・旧成果物/外部変更保護はIT。 |
| `check_publication_rechecks_excluded_outputs` | 6 → 2 | 差分種類をUT集約 | source/taskの細分化はsnapshot/contract UT、全no-op/Markdownだけ変更で公開対象外JSONも再照合する2つの接続境界は維持。 |
| `check_changed_sidecar_publication` | 3 → 1 | 差分判定はUT | stale/missingはcheck_sidecar_output_difference＋check_service_cache_invalidation、実JSON-only公開はModelのPolicy Id更新で保証。 |
| `check_unchanged_sidecar_path_safety` | 1 → 0 | UTへ移管 | check_snapshot_symlink_safetyで同じGenerationInputs読取APIのsymlink拒否・親種類の競合・外部bytes保護。 |
| `check_unchanged_sidecar` | 2 → 2 | IT維持 | 全no-op/Markdownだけ変更の実Publication・JSON未再保存とmtime。末尾の重複read-only SyncはCLI write/checkとnormal_writerに統合。 |
| `check_unchanged_sidecar_validation` | 1 → 1 | IT維持 | 候補生成失敗時はno-opでも公開しない、全旧成果物を保持。 |
| `check_changed_sidecar_publication_rollback` | 2 → 2 | IT維持 | 変更済JSONの復元と、公開対象外JSONの外部書込保持は別障害境界。失敗後の実保存成功は保持し、末尾の重複read-only Syncだけ統合。 |
| `check_failure_counts` | 1 → 0 | UTへ移管 | 旧17モデル×extra_inputs/read-writeの実SyncとMock rendererを廃止。check_failure_countsが実report_generationで8成功/9又は11失敗/診断件数とWARN分離の4組を検証。部分成功の実接続はmultiple_targets_barrier/required_preflightで保持。 |
| `check_workflow` | 1 → 0 | UTへ移管/既存保証 | expanded_design・VPC/Subnet/S3表示・JSON raw digestはcheck_expanded_design_and_json_digest、Stack表/No/Order/commentは既存check_stack_policy、Scopeは選択UT、Missing authorityはcheck_invalid_model/check_missing_validation_inputs/check_generation_input_failures＋scope/Stage UT。実生成はnormal_writer/CLIを維持。 |
| `check_required_preflight` | 1 → 1 | 細分化は直接UT | 空Type4種/正常Type/暗黙BucketPolicy親はcheck_required_datasource_type、既存Pending UTを再利用。Model品質検証で必須Propertyを検出し、生成時は品質検証を行わず、構造不備時の既存出力保持・複数Service部分成功をITで確認する。 |
| `check_required_property_parents` | 1 → 1 | 細分化は直接UT | check_required_property_parents UTでConnectionInput/CatalogId欠落・boolean型・正常親推論をModel/Table両方で検証。実Glue生成とTable Validationの正常接続はIT。 |
| `check_normal_writer_contents` | 1 → 1 | IT維持/統合 | 候補の各Validator handler回数、生成/照合1回、no readback・実保存内容は維持。旧output compatibilityのstdout/progressも同じ実生成で検証。 |
| `check_generation_output_compatibility` | 1 → 0 | 既存ITへ統合 | normal_writerでstdout/progress、unchanged_sidecarで既存bytes、two_consumer_cliでread/write同値。2回の重複Syncを廃止。 |
| `check_multiple_targets_barrier` | 5 → 5 | IT維持 | none/input/candidate/io/rollbackを維持。candidateとlate I/Oの部分成功、rollback不能Journal保持→実lock復旧を別々にassert。 |
| `check_incoming_reference_models` | 2 → 1 | 直接判定＋IT | read-onlyのincoming除外はcheck_stage_dependency_selectionをread/writeに拡張。実write側のincoming Model配置とlink readerへの受渡しはIT。 |
| `check_stage_definition_sources` | 1 → 1 | IT維持 | 最小Stageの定義source共有、実生成bytesと元入力不変。 |
| `check_stage_cloudformation_definitions` | 1 → 1 | IT維持 | Stage Stackの候補正本とValidator→IaC metadata接続、古い保存Stackへのfallback拒否。 |
| `check_publication_lock_wait` | 1 → 1 | IT維持 | 実lock競合・再入と通知接続。 |
| `check_two_consumer_cli` | 1 → 1 | IT維持 | 複数環境CLI write/check・スコープ拒否・出力/完了数の実接続。 |
| `check_internal_sync_real_diagnostics` | 1 → 1 | IT維持 | 実Runner→Validatorへのconsumer不足/生成drift診断と復旧。 |

旧check_input_mutationの全12展開と移管先（各差分の例外・入力Snapshot保持・外部変更保持、公開拒否後の出力保持を分担）:

| 旧filename / mutation | 判定AssertionのUT | 実Syncの接続保証 |
|---|---|---|
| entry / change, delete | check_snapshot_conflict[entry-change/delete] | check_publication_boundaryがValidation後の変更を拒否し、Markdown/JSONと外部変更を保持 |
| part / change, delete | check_snapshot_conflict[part-change/delete] | 同上。Stageへの入力受渡しはcheck_stage_definition_sources |
| other-model / change, delete | 旧入力はpartと同一。上記partに包含し、check_snapshot_conflict[other-model-change/delete]で独立Modelも追加保証 | 同上 |
| project / change, delete | check_snapshot_project_common_inputs[change/delete]が実common_inputs登録・sealed bytes・外部変更保持を検査 | 同上 |
| part / add | check_snapshot_conflict[part-add]の未記録ファイル集合差分 | 同上 |
| entry, other-model, project / add | 旧3条件は同じModel追加先。check_snapshot_conflict[other-model-add]へ統合 | 同上 |

Publicationのsidecar/taskのchange/addはcheck_snapshot_conflict、Taskのselector/状態/境界は既存task-contract/validation_cache UTに対応する。Sidecarのstale/missingはcheck_sidecar_output_differenceで判定し、実JSON-only更新はcheck_changed_sidecar_publication、新規の欠落Markdown/JSON公開はcheck_integrated_validator[True]で接続を保持する。note=False/Trueの全no-op/Markdown変更の除外出力再確認とRollbackは各2条件、multiple_targets_barrierの5障害境界はそのまま維持する。

Cacheは現行PassCacheの呼出し内限定仕様を維持する。旧67条件版で別Validatorの生成回数を1とするAssertionは修正済みであり、今回その修正を再実装しない。Cache ITの反復は削除し、check_cache_lifetimeの同一context共有/fresh/別context独立と、service keyの正本/Markdown/Sidecar/追加ファイル変更・削除を直接UTに集約した。候補CheckResultのscope/candidate/FAIL/NOT_RUNとAcceptanceへの再利用は既存check_result_reuse_is_scopedが所有する。

実stageの元定義共有・CFn接続・cold workerの直列/並列同値、CLI write/check、候補Validation、Publication、Rollback/Recoveryを残す。28条件は26前後の目安より2多い。新規生成と既存更新の入力欠落/公開対象/originals、およびValidator保存失敗→Acceptance拒否は独立した接続保証なので維持する。

### 現行IT登録

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `sync-15::check_stage_definition_sources` | `check_stage_definition_sources` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L96) | pytest / 1 | 元Framework定義を共有した最小stage・同一生成bytes・元定義不変 | 統合境界 |
| `sync-15::check_stage_candidate_isolation` | `check_stage_candidate_isolation` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L204) | pytest / 1 | 実stageのModel不整合と壊れたリンクを個別に検出し、元の正常Model/成果物を保持・stage絶対パスを診断に漏らさない | 統合境界 |
| `sync-15::check_stage_cloudformation_definitions` | `check_stage_cloudformation_definitions` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L230) | pytest / 1 | Stage Stack正本・生成・候補Validator・IaCへのmetadata受渡し、古い保存Stackへのfallback禁止 | 統合境界 |
| `sync-15::check_publication_boundary` | `check_publication_boundary` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L300) | pytest / 1 | 候補Validation後の入力変更を公開前に拒否し、Markdown/JSONと外部変更を保護 | 統合境界 |
| `sync-15::check_normal_writer_contents` | `check_normal_writer_contents` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L327) | pytest / 1 | 実生成/照合各1回・品質Gate呼出し0・Markdown/JSON内容・stdoutとprogress接続 | 統合境界 |
| `sync-15::check_unchanged_sidecar` | `check_unchanged_sidecar` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L369) | pytest / 2 | 全no-op/Markdownだけ変更の2境界、候補Validation維持・JSON再保存なし・bytes/mtime保護 | 統合境界 |
| `sync-15::check_changed_sidecar_publication` | `check_changed_sidecar_publication` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L390) | pytest / 1 | 表示に影響しないPolicy Idだけの更新を実公開し、Markdownは不変・JSON内容は正しい | 統合境界 |
| `sync-15::check_publication_rechecks_excluded_outputs` | `check_publication_rechecks_excluded_outputs` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L412) | pytest / 2 | 全no-op/Markdownだけ変更の2境界で、公開対象外Sidecarの競合を拒否・外部変更保持 | 統合境界 |
| `sync-15::check_changed_sidecar_publication_rollback` | `check_changed_sidecar_publication_rollback` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L441) | pytest / 2 | JSON公開後のMarkdown途中失敗の復元／未変更JSONへの外部書込を巻き戻さない独立2境界、再保存成功 | 統合境界 |
| `sync-15::check_unchanged_sidecar_validation` | `check_unchanged_sidecar_validation` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L467) | pytest / 1 | no-opでも候補生成失敗時は公開せず、元Markdown/JSONを保持 | 統合境界 |
| `sync-15::check_incoming_reference_models` | `check_incoming_reference_models` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L485) | pytest / 1 | 実Stageがincoming文書とその正本Modelを配置してリンク検証に渡す | 統合境界 |
| `sync-15::check_required_preflight` | `check_required_preflight` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L510) | pytest / 1 | 独立Model品質検証で必須Property不備を検出、生成は品質preflightなし、構造不備で既存成果物・Model保持、独立Serviceは保存 | 統合境界 |
| `sync-15::check_required_property_parents` | `check_required_property_parents` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L569) | pytest / 1 | Glueの実Sync生成から実Table Validatorへの必須親Property接続、親行の捏造なし・正本保持 | 統合境界 |
| `sync-15::check_publication_lock_wait` | `check_publication_lock_wait` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L630) | pytest / 1 | 実lock競合・再入可能性とprogressのlock-wait通知 | 統合境界 |
| `sync-15::check_two_consumer_cli` | `check_two_consumer_cli` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L649) | pytest / 1 | 2環境の実CLI write/check・保存bytes・不正Scope拒否・診断チャネルと完了数 | 統合境界 |
| `sync-15::check_internal_sync_isolation` | `check_internal_sync_isolation` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L740) | pytest / 1 | 実Runnerの2 target並列barrier・成功→失敗→成功の再取得、親memo/ContextVar/progress/保存bytes保護 | 統合境界 |
| `sync-15::check_internal_sync_real_diagnostics` | `check_internal_sync_real_diagnostics` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L769) | pytest / 1 | consumer不足・古い生成物の実Runner診断をValidatorに伝達し、復元後に成功 | 統合境界 |
| `sync-15::check_integrated_validator` | `check_integrated_validator` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L818) | pytest / 2 | 実Validatorから生成・照合・Publication・独立Acceptance3件までの新規/更新の正常接続、originals=None/旧bytes・JSON生成/未再保存・正本保護 | 統合境界 |
| `sync-15::check_integrated_validator_publication_failure` | `check_integrated_validator_publication_failure` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L876) | pytest / 1 | 実Validatorの部分書込失敗・Rollback・Acceptance不成立、正本と旧Markdown/JSON保持 | 統合境界 |
| `sync-15::check_multiple_targets_barrier` | `check_multiple_targets_barrier` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L951) | pytest / 5 | 正常/入力競合/候補不採用/後続I/O/復元不能の独立5境界。部分成功、Recovery Journal保持と次lock時復旧 | 統合境界 |

### 新規UT登録

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `sync-15::check_snapshot_symlink_safety` | `check_snapshot_symlink_safety` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L798) | pytest / 2 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_internal_sync_selection` | `check_internal_sync_selection` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L832) | pytest / 4 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_failure_counts` | `check_failure_counts` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 8 | 成功/失敗/NOT_RUN件数、独立エラー優先、診断と保存済み参照WARNの分離 | 既存UT更新 |
| `generation-publication::issues` | `check_integrated_generation_with_issues` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 8 | Issue有無×正常/部分失敗/NOT_RUN/共通整合性失敗。候補生成検証はMock、実publication・成功保存・失敗View保持・Issue原文保全を検証 | 追加 |
| `sync-15::check_guard_snapshot_candidates` | `check_guard_snapshot_candidates` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L882) | pytest / 1 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_definition_read_errors` | `check_definition_read_errors` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L907) | pytest / 4 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_sidecar_output_difference` | `check_sidecar_output_difference` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L930) | pytest / 2 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_missing_validation_inputs` | `check_missing_validation_inputs` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L948) | pytest / 2 | Model欠落/View欠落のScope拒否・非生成・入力不変 | ITから移管 |
| `sync-15::check_expanded_design_and_json_digest` | `check_expanded_design_and_json_digest` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1028) | pytest / 1 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_required_datasource_type` | `check_required_datasource_type` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1162) | pytest / 5 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_required_property_parents` | `check_required_property_parents` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1189) | pytest / 4 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_candidate_model_metadata` | `check_candidate_model_metadata` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1227) | pytest / 1 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_candidate_design_diagnostics` | `check_candidate_design_diagnostics` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1234) | pytest / 1 | Resource名不整合・実Table ValidatorのSchema違反・Overview欠落を直接検証 | ITから移管 |
| `sync-15::check_service_cache_invalidation` | `check_service_cache_invalidation` | UT | [units/validation_cache-unit.checks.py](units/validation_cache-unit.checks.py#L220) | pytest / 5 | 直接APIの判定・変換（上表の移管対応） | ITから移管 |
| `sync-15::check_generation_input_failures` | `check_generation_input_failures` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L970) | pytest / 2 | 不正Model/正本なし文書のprepare_generation失敗分類と既存成果物保持（実生成なし） | ITから移管 |
| `sync-15::check_implicit_grouped_required_property` | `check_implicit_grouped_required_property` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1179) | pytest / 1 | 暗黙BucketPolicy親の必須Property判定 | ITから移管 |

既存check_snapshot_project_common_inputsはproject change/deleteの2条件、check_stage_dependency_selectionはread/writeの2条件へ拡張。check_snapshot_conflictはraw競合/不存在/sealの1条件と差分/集合変更12条件を同じ既存UTへ集約し、旧check_snapshot_input_differencesは削除した。移動した全Assertionは維持し、Taskの変更/追加は手動のread/selectに頼らずconstructorの自動登録を検証する。Sync UTは開始時29関数68条件から28関数69条件となる。不足していたread-onlyのView欠落拒否だけをcheck_missing_validation_inputsへ1条件追加し、既存のModel欠落拒否と区別する。どちらも非生成・入力不変を確認し、重複条件は追加しない。

ローカルでは関連UT・構文・ASTのparameter展開数・登録・既存PytestReceipt/reachability契約だけを確認する。IT本体・Full IT・cProfile・時間計測は実行しない。既存Framework ITでPASSと実時間を確認するまで10秒以下の達成は未確認。

既存Runner UT `blueprint-loop-unit::check_it_inventory` のincoming IT登録期待値も2→1へ更新し、receipt/reachability実装とpytest入口は変更しない。

## Common Model Reference nodes

| Requirement | Function | Layer | Source | Mode / cases | Responsibility | Notes |
|---|---|---|---|---|---|---|
| `model-reference::round-trip` | `main` | IT | [integrations/model-reference-nodes.checks.py](integrations/model-reference-nodes.checks.py#L24) | direct / 1 | Cross-service properties → JSON View/Markdown generation → artifact rendering; Resource links and Consumer logical references unchanged; Pending projects to PENDING_DEPLOY, unresolved retains its declaration; both round-trip as Views | Authored synthetic fixture |

`units/model-reference-nodes-unit.checks.py` owns strict syntax, target-local uniqueness/cache,
producer/attribute contracts, logical comparison with Ref/GetAtt/Export, ambiguity and missing
producers, missing parent settings despite unknown children, policy forms and IMPORT protection,
all display fallbacks, graph/incoming references, explicit Retarget preservation and deletion refusal.
The same UT owns CodePipeline CodeCommit/CodeBuild/S3 Action contracts, exact JSON and indexed-row
context isolation, typed Configuration reconstruction and display, and the connected comparison path.
Context-dependent CodeBuild variables and CloudTrail DataResources use the same traversal checks.
Existing Markdown-link, external metadata and service-specific equivalence tests remain with their
existing owners because they test independent contracts rather than typed-node duplicates.

## Partial IaC evaluation errors and confirmed differences

| Case ID | Function | Layer | Source | Execution / Count | Contract | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| `iac-partial::siblings` | `test_iac_partial_errors_preserve_known_fields` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1534) | pytest / 12 | Select・不正If・Joinの実評価errorとImage/Type差分、Model未比較・参照理由・位置を併存。既知兄弟一致でもmatched禁止 | 合成CodeBuild |
| `iac-partial::selection` | `test_iac_partial_selective_extra_fields` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1567) | pytest / 4 | selectiveの追加設定を評価せず、exactの存在未確定と指定フィールド一致・不一致を分離 | 共通設定比較 |
| `iac-partial::array-presence` | `test_iac_partial_array_presence` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1587) | pytest / 9 | フィールド・要素・識別子error、Condition存在不明、NoValue、null/false/空文字/空配列と確定兄弟差分を分離 | 合成配列 |
| `iac-partial::membership` | `test_iac_partial_keyed_and_conditional_membership` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1628) | pytest / 6 | keyed配列の識別不明・確定差分・不足数・重複・NoValue、選択済If内の子errorを保持 | 共通membership |
| `iac-partial::cardinality` | `test_iac_partial_array_cardinality` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1668) | pytest / 12 | 順序・multisetと重複を維持し、不明要素による存在数の上下限と位置対応を保守的に比較 | 純粋比較 |
| `iac-partial::diagnostics` | `test_iac_partial_error_keeps_reference_diagnostics` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1678) | pytest / 1 | IaC子errorが別の未解決参照診断を消さない | 共通設定比較 |
| `iac-partial::artifact` | `check_iac_partial_error_artifact` | IT | [integrations/issues_failed_services.checks.py](integrations/issues_failed_services.checks.py#L233) | direct / 1 | 合成Model→比較→集計→artifact→iac-issuesでImage/Type・差分1/未比較1/error1・位置・マスキングを確認 | Frameworkのみ |
| `iac-partial::error-unknown` | `test_iac_partial_error_and_unknown_condition` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1694) | pytest / 2 | 同時に発生するIaC実errorとCondition未解決を保持し、既知兄弟の一致・不一致を判定 | 共通設定比較 |

## Common receiving-reference contract audit

`units/reference-contract-audit-unit.checks.py` owns the full current static contract matrix
(115 Producer/attribute/receiving-property combinations across 89 entries), applying the
Resolver, typed normalization, final symbolic comparison, wrong Producer/attribute and
IMPORT rejection together. Context/Action contracts are covered jointly with the existing
`model-reference-nodes-unit.checks.py`; SSM.Parameter applicability is explicitly unsupported.
No old service-specific tests or CodePipeline acceptance checks are duplicated or removed.

| Case | Function | Layer | Entry | Runtime | Guarantees | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `reference-audit::static` | `test_registered_contract_route` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L102) | pytest / 115 | Shared contract/Resolver/typed comparison, wrong attributes/Producer and IMPORT protection for every static declaration | Authored temporary Models |
| `reference-audit::context` | `test_context_never_guesses` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L81) | pytest / 3 | Wrong/missing CloudTrail Type and unknown CodeBuild Type cannot produce confirmed references | Synthetic JSON |
| `reference-audit::flow-resolver` | `test_flowlog_nested_context` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L88) | pytest / 1 | VPC context and rejection of another ResourceType | Synthetic Models |
| `reference-audit::catalog` | `test_catalog_and_context_boundaries` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L141) | pytest / 1 | Every registered schema and context choice is inspected; SSM is unsupported | Framework schemas |
| `reference-audit::display` | `test_common_markdown_projection_and_restoration` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L162) | pytest / 9 | Glue maps, CodeBuild variables, Subnet/SG arrays; unknown/pending/observed display, exact source rows and tamper rejection | Synthetic Models |
| `reference-audit::prefix` | `test_cloudtrail_object_prefix_semantics` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L197) | pytest / 3 | S3 object slash/prefix cannot equal a bucket ARN; sibling Lambda remains isolated | Synthetic references |
| `reference-audit::settings` | `test_setting_attributes_and_consumers` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L217) | pytest / 4 | Secret Name/Id, Event Rule Name/RuleName and Alias Arn with receiving restrictions | Synthetic Models |
| `reference-audit::flow-comparison` | `test_flowlog_comparison_and_validation` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L240) | pytest / 4 | Split ResourceType reaches validation and comparison; unsupported types remain unverified | Synthetic Models |
| `reference-audit::arrays` | `test_array_elements_and_scalar_array_boundary` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L265) | pytest / 2 | Scalar reference cannot replace an array; elements require correct attributes | Synthetic Models |
| `reference-audit::malformed` | `test_malformed_display_objects` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L282) | pytest / 3 | Projection does not permit malformed objects or elements | Synthetic rows |
| `reference-audit::expression` | `test_unknown_expression_operand_never_matches` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L287) | pytest / 1 | Identical expression spelling cannot hide an unresolved operand | Symbolic values |
| `reference-audit::unsupported` | `test_unsupported_ssm_and_name_id_equivalence` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L293) | pytest / 1 | Unsupported SSM cannot be authorized by a receiving contract; Secret Name and Id are not automatically equivalent | Synthetic Models |
| `reference-audit::split-context` | `test_cloudtrail_split_context` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L310) | pytest / 2 | S3/Lambda split Type/Values rows use the same context boundary | Synthetic Models |
| `reference-audit::plaintext` | `test_codebuild_plaintext_and_missing_sibling_type` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py#L326) | pytest / 1 | PLAINTEXT Resource reference is rejected; missing sibling Type remains unproven | Synthetic JSON |

## SQS Queue named ARN comparison (1024v12)

| ID | Case | Layer | Source | Runner / count | Responsibility | Fixture |
| --- | --- | --- | --- | --- | --- | --- |
| `sqs-arn::match` | `test_sqs_policy_named_arn_match` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1732) | pytest / 1 | Queue/Rule ARN一致、Model権威不変 | 合成CREATE Queue/Rule/QueuePolicy |
| `sqs-arn::difference` | `test_sqs_policy_proven_difference_is_sqs_specific` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1741) | pytest / 5 | QueueName/partition/region/accountはSQSだけを変更しRule一致を確認、SourceArn差分はQueue一致を確認、個別診断と全体判定・マスキング | 合成PolicyDocument |
| `sqs-arn::name-proof` | `test_sqs_unproven_names` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1767) | pytest / 12 | 明示名欠落・不正・未確定・長さ超過はuncompared | 合成Queue |
| `sqs-arn::name-boundary` | `test_sqs_explicit_name_boundaries` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1781) | pytest / 3 | 1/80文字・FIFO接尾辞込み80文字 | 合成Queue |
| `sqs-arn::context` | `test_sqs_arn_context_requires_proof` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1790) | pytest / 18 | partition/region/accountの欠落・空・placeholder・型・形式不正はSQS個別証明でもuncompared | 合成実行context |
| `sqs-arn::shared-regression` | `test_existing_named_arn_context_guards` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1809) | pytest / 1 | 比較器から共通ARN組立への接続とcontext欠落時のproof境界 | 形式・context組合せはarn-values-unitへ移管 |
| `sqs-arn::correspondence` | `test_sqs_arn_correspondence_and_mode_guards` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1820) | pytest / 9 | formal type/Stack/Logical ID/一意性/Model/Condition/Transform/IMPORTの証明不足 | 合成Resource対応 |
| `sqs-arn::attributes` | `test_sqs_queue_url_is_not_getatt_arn` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1845) | pytest / 1 | Ref QueueUrl/GetAtt Arnを区別、IMPORTの推測禁止 | 合成Queue |
| `sqs-arn::errors` | `test_sqs_reference_processing_errors_propagate` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1859) | pytest / 3 | ARN評価のI/O/Value/Type実例外は上位へ伝搬 | 合成処理障害 |
| `sqs-arn::recorded-errors` | `test_recorded_reference_processing_errors_are_not_missing_proof` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py#L1875) | pytest / 6 | 記録識別子・保存宣言検証の実例外は証明不能と区別 | 合成VPC・catalog read障害 |
| `sqs-arn::artifact` | `sqs_policy_artifact_checks` | IT | [integrations/issues_policy_equivalence.checks.py](integrations/issues_policy_equivalence.checks.py#L142) | direct / 1 | 比較器→artifact保存再読込→detail/集計/表示のmatched/difference/uncompared/error整合、SQS単独region差分とRule一致、ARN/accountマスク | 一時合成projectのみ |

## Shared AWS reference and expression safety

All patterns use the common evaluator and authored temporary Models. An incomplete Export search retains its cached candidates and failures but cannot prove uniqueness.

| Case ID | Function | Layer | Suite | Execution / Count | Coverage | Origin |
| --- | --- | --- | --- | --- | --- | --- |
| `aws-reference::test_proven_arns_and_both_comparison_directions` | `test_proven_arns_and_both_comparison_directions` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 60 | proven arns and both comparison directions | Synthetic Models and Framework schemas |
| `aws-reference::test_model_nodes_before_common_intrinsic_evaluation` | `test_model_nodes_before_common_intrinsic_evaluation` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 240 | model nodes before common intrinsic evaluation | Synthetic Models and Framework schemas |
| `aws-reference::test_derived_model_attribute_does_not_authorize_getatt` | `test_derived_model_attribute_does_not_authorize_getatt` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 4 | derived model attribute does not authorize getatt | Synthetic Models and Framework schemas |
| `aws-reference::test_formal_ref_and_getatt_semantics` | `test_formal_ref_and_getatt_semantics` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 10 | formal ref and getatt semantics | Synthetic Models and Framework schemas |
| `aws-reference::test_generated_ids_remain_uncompared` | `test_generated_ids_remain_uncompared` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 8 | generated ids remain uncompared | Synthetic Models and Framework schemas |
| `aws-reference::test_producer_proof_cannot_be_replaced_by_a_matching_name` | `test_producer_proof_cannot_be_replaced_by_a_matching_name` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 7 | producer proof cannot be replaced by a matching name | Synthetic Models and Framework schemas |
| `aws-reference::test_arn_contract_inventory_covers_every_derivable_type` | `test_arn_contract_inventory_covers_every_derivable_type` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | arn contract inventory covers every derivable type | Synthetic Models and Framework schemas |
| `aws-reference::test_kms_attributes_in_compound_strings_are_not_property_form_equivalence` | `test_kms_attributes_in_compound_strings_are_not_property_form_equivalence` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | kms attributes in compound strings are not property form equivalence | Synthetic Models and Framework schemas |
| `aws-reference::test_invalid_intrinsics_cannot_match` | `test_invalid_intrinsics_cannot_match` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 8 | invalid intrinsics cannot match | Synthetic Models and Framework schemas |
| `aws-reference::test_unresolved_nodes_keep_their_pointer_and_context` | `test_unresolved_nodes_keep_their_pointer_and_context` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | unresolved nodes keep their pointer and context | Synthetic Models and Framework schemas |
| `aws-reference::test_export_evidence_composes_with_sub_and_join` | `test_export_evidence_composes_with_sub_and_join` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 6 | export evidence composes with sub and join | Synthetic Models and Framework schemas |
| `aws-reference::test_symbolic_token_boundaries_do_not_prove_string_inequality` | `test_symbolic_token_boundaries_do_not_prove_string_inequality` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | symbolic token boundaries do not prove string inequality | Synthetic Models and Framework schemas |
| `aws-reference::test_missing_identity_never_uses_a_generated_name` | `test_missing_identity_never_uses_a_generated_name` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 60 | missing identity never uses a generated name | Synthetic Models and Framework schemas |
| `aws-reference::test_explicit_context_and_creation_names_must_agree` | `test_explicit_context_and_creation_names_must_agree` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 4 | explicit context and creation names must agree | Synthetic Models and Framework schemas |
| `aws-reference::test_import_name_cannot_depend_on_a_resource` | `test_import_name_cannot_depend_on_a_resource` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | import name cannot depend on a resource | Synthetic Models and Framework schemas |
| `aws-reference::test_pseudo_parameters_and_formal_escaping` | `test_pseudo_parameters_and_formal_escaping` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | pseudo parameters and formal escaping | Synthetic Models and Framework schemas |
| `aws-reference::test_qualifiers_keys_and_literal_affixes_remain_part_of_the_value` | `test_qualifiers_keys_and_literal_affixes_remain_part_of_the_value` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 60 | qualifiers keys and literal affixes remain part of the value | Synthetic Models and Framework schemas |
| `aws-reference::test_unresolved_expression_is_not_equal_to_itself` | `test_unresolved_expression_is_not_equal_to_itself` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 9 | unresolved expression is not equal to itself | Synthetic Models and Framework schemas |
| `aws-reference::test_template_cannot_supply_aws_generated_return_values` | `test_template_cannot_supply_aws_generated_return_values` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 3 | template cannot supply aws generated return values | Synthetic Models and Framework schemas |
| `aws-reference::test_sub_arn_uses_contract_even_with_a_spoofed_template_field` | `test_sub_arn_uses_contract_even_with_a_spoofed_template_field` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 60 | sub arn uses contract even with a spoofed template field | Synthetic Models and Framework schemas |
| `reference-audit::returns` | `test_all_aws_return_contracts_are_explicit_and_schema_supported` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py) | pytest / 1 | Every pinned ResourceType: read-only/GetAtt and derived attributes, Ref setting types, no primaryIdentifier guessing | Framework schemas |

## Confirmed Model Reference values

- `units/arn-values-unit.checks.py`: 38 synthetic cases own shared ARN assembly, defaults,
  invalid components, required context, S3 context independence and generated-ID evidence.
  `reference-evidence-unit::test_existing_named_arn_context_guards` retains one comparison
  wiring case; its repeated assembly/context combinations now belong to the common UT.
- `units/model-reference-values-unit.checks.py`: 15 synthetic cases own desired S3 resolution
  without observed, rename propagation through the existing Graph, ListQuarantine display,
  unresolved generated KMS identifiers, explicit pending, duplicate/missing/invalid/conflicting
  producers, two policy references and JSON-string resolution, content equality and immutable authority,
  all unresolved pointers, explicit unknown optional properties versus absence defaults, and batch
  service isolation with saved-view retention.
- Existing typed-node tests retain canonical design JSON preservation; pipeline display now
  expects confirmed desired Name without observed and rejects contradictory observed Name.
  Existing Model Reference IT remains one focused offline round-trip case.


## Shared Reference contract completion

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `reference-shared::apigateway-reference-unit.checks.py:test_public_domain` | `test_public_domain` | UT | [units/apigateway-reference-unit.checks.py](units/apigateway-reference-unit.checks.py) | pytest / 3 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::apigateway-reference-unit.checks.py:test_unproven_domain` | `test_unproven_domain` | UT | [units/apigateway-reference-unit.checks.py](units/apigateway-reference-unit.checks.py) | pytest / 6 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_compound_values_do_not_replace_producer_proof_with_equal_names` | `test_compound_values_do_not_replace_producer_proof_with_equal_names` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 2 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_evaluated_names_keep_producer_identity_in_sub_and_join` | `test_evaluated_names_keep_producer_identity_in_sub_and_join` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_generated_arn_identity_is_symbolic_and_template_ids_are_not_evidence` | `test_generated_arn_identity_is_symbolic_and_template_ids_are_not_evidence` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 44 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_kms_alias_forms_and_expressions_are_symmetric` | `test_kms_alias_forms_and_expressions_are_symmetric` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 2 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_kms_generated_key_arn_compares_by_identity_in_allowed_forms` | `test_kms_generated_key_arn_compares_by_identity_in_allowed_forms` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 2 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_multiple_references_preserve_order_attribute_and_affixes` | `test_multiple_references_preserve_order_attribute_and_affixes` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_nested_split_select_uses_sub_join_semantics` | `test_nested_split_select_uses_sub_join_semantics` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_opaque_ref_keeps_its_full_return_identity` | `test_opaque_ref_keeps_its_full_return_identity` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 26 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::aws-reference-expressions-unit.checks.py:test_same_producer_different_attributes_cannot_be_proven_by_equal_template_fields` | `test_same_producer_different_attributes_cannot_be_proven_by_equal_template_fields` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 1 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::network-firewall-unit.checks.py:test_rule_group_type` | `test_rule_group_type` | UT | [units/network-firewall-unit.checks.py](units/network-firewall-unit.checks.py) | pytest / 2 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::network-firewall-unit.checks.py:test_unproven_rule_group_type` | `test_unproven_rule_group_type` | UT | [units/network-firewall-unit.checks.py](units/network-firewall-unit.checks.py) | pytest / 6 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::reference-contract-audit-unit.checks.py:test_inventory_is_exactly_the_supported_framework_types` | `test_inventory_is_exactly_the_supported_framework_types` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py) | pytest / 1 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::reference-contract-audit-unit.checks.py:test_inventory_return_and_arn_contracts` | `test_inventory_return_and_arn_contracts` | UT | [units/reference-contract-audit-unit.checks.py](units/reference-contract-audit-unit.checks.py) | pytest / 178 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::reference-evidence-unit.checks.py:test_cached_exports_are_bound_to_the_consumer_scope` | `test_cached_exports_are_bound_to_the_consumer_scope` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::reference-evidence-unit.checks.py:test_saved_literal_evidence_is_checked_in_both_directions` | `test_saved_literal_evidence_is_checked_in_both_directions` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 3 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |
| `reference-shared::reference-evidence-unit.checks.py:test_shared_recorded_arn_proof` | `test_shared_recorded_arn_proof` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 28 | Shared return, ARN, intrinsic and Producer proof regression | Synthetic inputs and pinned Framework contracts |

## Framework IT to UT migration (74252f5 baseline)

Baselineは76 suite・313登録・431条件。実行条件数とAssertion地点数は異なる。

Phase 1ではMapping Fake比較、Macie Schemaと表示、QuickSight往復、回帰認証の異常条件を既存UTへ移管。Runtime discovery/read不変性は既存Model Templatesのcreation/layout/snapshot ITが所有し、Loader破損/読取失敗はModel Files UTが所有する。PassCacheの単体入力条件はUT、Producer partsとConsumer依存・環境隔離はAttribute Reference ITへ移す。

Service契約は既存Model Parameter Inputs UTでサービスごとの小さい合成Resourceを使用する。全typed seed生成と13連続呼出しを廃止し、6 Producerの保存済み依存とConsumer非書換だけを同名ITに残す。共通unknown field/Row欠落/重複JSONはmodel-format-v2とmodel_parameter_inputsの既存UTへ集約する。

### Phase 0–5の確定構造

元データは開始時commit `74252f50d16ea252b66ab5bfddd477e6861fa0ac`。参考1024v12の312/430に対し、実コードは313登録/431条件だった。
最終ITは68 suite・236登録・311条件（補助登録込み）。
最終所有先の全ファイル/関数の存在を静的確認する。登録到達性/完了Receiptの最終証拠は公式CIに委ねる。

- 8 suite削除: aws_mapping_compare、design_catalog、quicksight-display、regression_guard、runtime-model、validation_cache、design_document、route53-import-expression。
- `service_contracts.py`の13補助登録を廃止。9 serviceと共通責務の値判定は既存Model Parameter Inputs UT、Logs scalarは同UT、6 Producer保存/参照は既存同名ITへ分離。連続呼出し専用のcheck/check_fixturesを削除。
- Validator補助17登録のうち10を既存Unit aggregatorへ移管し、7をITに保持。未インストールTerraformを正常returnで完了扱いにせず、実CLIがなければ明示FAILにする。
- Model Impactの同じSetting/Name→incoming集合を重ねたcheck_import_scopeを廃止。実Git Snapshot/Task接続は残す。baselineを読まない6経路のGit初期化を削除（cyclesは実Snapshotを保持）。
- `parameter_cases.py`はAthena/S3とSQS/contextの2統合経路だけが利用。CodeCommit spelling、SecurityHub scalar、DataZoneの固定Fixture件数、共通未知field/重複/欠落条件を繰り返さない。
- 元Model Design 7関数の構成とAssertion predicateは維持（CIの実エラー表示だけを追加）。Worktree専用Fixtureを業務ITへ再導入しない。
- 旧ITの期待値2箇所は現実装と既存UTに合わせて補正した。custom EventBusが証明可能ならdefault-bus ARNはFalse、KMS KeyArn未証明の例外理由は`KMS ARN requires a proven KeyId`。Production比較ロジックは変更しない。

異なる異常入力によるPublication遮断・Rollback/Recovery、別プロセスのimport/排他、実Task/複数Model参照は、入力だけのUTと同一保証と扱わない。

### 分割で追加した既存UT内の検証

| Case ID | Function | Layer | Source | Execution / Count | Contract | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| `it-ut-migration::cloudformation-deploy-unit.checks::check_deployment_input_conditions` | `check_deployment_input_conditions` | UT | [units/cloudformation-deploy-unit.checks.py](units/cloudformation-deploy-unit.checks.py#L182) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::design_layout-unit.checks::check_config_firehose_references` | `check_config_firehose_references` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L1104) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::issues_api_only-unit.checks::check_api_record_classification` | `check_api_record_classification` | UT | [units/issues_api_only-unit.checks.py](units/issues_api_only-unit.checks.py#L52) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::lambda_permission-unit.checks::check_permission_inputs` | `check_permission_inputs` | UT | [units/lambda_permission-unit.checks.py](units/lambda_permission-unit.checks.py#L46) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model-format-v2.checks::check_context_topology_inputs` | `check_context_topology_inputs` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L711) | pytest / 4 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_design-unit.checks::check_rotation_inputs` | `check_rotation_inputs` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L1269) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_files-unit.checks::check_saved_anchor_inputs` | `check_saved_anchor_inputs` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L103) | pytest / 5 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_files-unit.checks::check_resource_reading_inputs` | `check_resource_reading_inputs` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L128) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_files-unit.checks::check_part_boundaries` | `check_part_boundaries` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py#L286) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_kms` | `check_kms` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L168) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_security_group` | `check_security_group` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L180) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_route53` | `check_route53` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L189) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_iam` | `check_iam` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L205) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_s3` | `check_s3` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L222) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_glue` | `check_glue` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L229) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_lambda` | `check_lambda` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L246) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_eventbridge` | `check_eventbridge` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L262) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_codepipeline` | `check_codepipeline` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L288) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_responsibilities` | `check_responsibilities` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L307) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::model_parameter_inputs-unit.checks::check_log_group_native_scalars` | `check_log_group_native_scalars` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L329) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::policy_tables-unit.checks::check_iam` | `check_iam` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py#L119) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::producer-identifier-reference-unit.checks::check_producer_name_conditions` | `check_producer_name_conditions` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L134) | pytest / 7 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::producer-identifier-reference-unit.checks::check_identifier_value_conditions` | `check_identifier_value_conditions` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L159) | pytest / 4 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::producer-identifier-reference-unit.checks::check_link_reference_ignores_name_rows` | `check_link_reference_ignores_name_rows` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L169) | pytest / 3 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::producer-identifier-reference-unit.checks::check_context_and_stack_declarations` | `check_context_and_stack_declarations` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py#L188) | pytest / 6 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::resource_mode-unit.checks::check_resource_mode_conditions` | `check_resource_mode_conditions` | UT | [units/resource_mode-unit.checks.py](units/resource_mode-unit.checks.py#L82) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::security_group_tables-unit.checks::check_table_conditions` | `check_table_conditions` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#L146) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::task::check_task_type_inputs` | `check_task_type_inputs` | UT | [units/validation_checks/task.py](units/validation_checks/task.py#L262) | direct_group / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::validation_scope-unit.checks::check_unknown_scope_inputs` | `check_unknown_scope_inputs` | UT | [units/validation_scope-unit.checks.py](units/validation_scope-unit.checks.py#L70) | pytest / 3 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::validation_scope-unit.checks::check_invalid_design_artifact` | `check_invalid_design_artifact` | UT | [units/validation_scope-unit.checks.py](units/validation_scope-unit.checks.py#L81) | pytest / 1 | 入力/Schema/比較/診断 | 合成値/小Fixtureのみ |
| `it-ut-migration::ReferenceValueTests::test_kms_forms_and_arn_values` | `ReferenceValueTests.test_kms_forms_and_arn_values` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | unittest / 1 | ARN/Expression/Action比較の直接入力矩形 | 一時in-memory Comparison |
| `it-ut-migration::ReferenceValueTests::test_policy_action_and_expression_values` | `ReferenceValueTests.test_policy_action_and_expression_values` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | unittest / 1 | ARN/Expression/Action比較の直接入力矩形 | 一時in-memory Comparison |

### 残存IT全Suiteの統合境界

| Suite | 残す固有保証 |
| --- | --- |
| [attribute-reference-resolution.checks.py](integrations/attribute-reference-resolution.checks.py) | 保存Producer/Consumer→参照解決/Trace/PassCache、相互参照・Stack・partsと環境隔離 |
| [auxiliary-model-dependencies.checks.py](integrations/auxiliary-model-dependencies.checks.py) | 補助Model参照→依存列挙→生成Stage入力・Source Snapshot |
| [aws_mapping.checks.py](integrations/aws_mapping.checks.py) | 保存Config→SDK Adapter→Mapping Comparison→Import正規化→Design表示 |
| [aws_mapping_display.checks.py](integrations/aws_mapping_display.checks.py) | 保存Logs/CodeCommit Model→実Renderer→Validator、Model bytes保持 |
| [blueprint-loop.checks.py](integrations/blueprint-loop.checks.py) | 実CLI→Task/Validation scope→検証コマンド・ログ/終了状態 |
| [bound-anchor-name-change.checks.py](integrations/bound-anchor-name-change.checks.py) | 保存済みProducer anchor/name変更→Consumer参照・Sync、元参照値不変 |
| [bound-stack-name-change.checks.py](integrations/bound-stack-name-change.checks.py) | 保存Stack name変更→Producer/Consumer依存→Sync、placement不変 |
| [check-model-aws.checks.py](integrations/check-model-aws.checks.py) | Orchestrator→SDK/CLI transport→Adapter/Mapping→Comparison、全service配線とbatch |
| [cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py) | 実Observed collector/Adapter→Task guard→Publication/生成物、失敗時bytes保護 |
| [cloudformation-destroy.checks.py](integrations/cloudformation-destroy.checks.py) | Destroy Controller→Session/Task→Observed初期化・保存・再実行 |
| [cloudformation-naming.checks.py](integrations/cloudformation-naming.checks.py) | 保存Stack/Model→実Template/Parameter読取→Export/Import式とModel名の整合 |
| [cloudtrail-input-reference.checks.py](integrations/cloudtrail-input-reference.checks.py) | 保存S3/KMS/CloudWatch Producer→CloudTrail参照、依存とConsumer不変 |
| [compact-model-sources.checks.py](integrations/compact-model-sources.checks.py) | Publication lock/transaction→raw bytes/派生値→rollback、独立環境保存 |
| [comparison_core.checks.py](integrations/comparison_core.checks.py) | 独立OSプロセスのimport順序/禁止I/O/共有型identity、Orchestratorの実module接続 |
| [deploy-controller.checks.py](integrations/deploy-controller.checks.py) | Controller→複数Stack/配送/Task/Observed、排出・中断・再開と実永続状態 |
| [deploy-observed-recovery.checks.py](integrations/deploy-observed-recovery.checks.py) | 実journalとObserved owner→Recovery→新規検証/Publication |
| [deploy_preparation.checks.py](integrations/deploy_preparation.checks.py) | 実準備CLI→契約/入力fingerprint→登録/Controller起動境界、生成物保護 |
| [design_layout.checks.py](integrations/design_layout.checks.py) | 保存Config/ServiceRole Model→Reference読取→実Markdown/Validatorの接続 |
| [eventbridge-producer-name-reference.checks.py](integrations/eventbridge-producer-name-reference.checks.py) | 保存Producer→EventBridge name参照・変更依存とConsumer不変 |
| [export-design-pdf.checks.py](integrations/export-design-pdf.checks.py) | 実Design/Pandoc/PDF変換→リンク/成果物、実OSプロセス |
| [framework-input-isolation.checks.py](integrations/framework-input-isolation.checks.py) | 実消費側TaskとFramework定義rootの別コンテキスト・Validator呼出し隔離 |
| [glue_datazone_catalog.checks.py](integrations/glue_datazone_catalog.checks.py) | 保存Glue/DataZone Model→Sync→実Design/JSON/Validator、再同期不変 |
| [group-03-input-references.checks.py](integrations/group-03-input-references.checks.py) | 複数サービスの保存Producer/Consumer→Source依存・参照値不変 |
| [human-inputs-group-05.checks.py](integrations/human-inputs-group-05.checks.py) | 実Git/Task→複数環境Model edit→Publication/再読込、非選択値とno-op保持 |
| [import-cli.checks.py](integrations/import-cli.checks.py) | 実Import CLI→Git/Task境界→Review/保存/終了コードと変更検知 |
| [import-model.checks.py](integrations/import-model.checks.py) | Acquire/Review/Task→Publication/再読込、rollback/recoveryと他Resource/環境保持 |
| [import-worktree-contract.checks.py](integrations/import-worktree-contract.checks.py) | 実Worktree/Task変更権限→Model Source/Import契約境界 |
| [issues-lint.checks.py](integrations/issues-lint.checks.py) | 実CLI/比較器→Lint入力/終了コード、原本保護と複数service境界 |
| [issues_api_only.checks.py](integrations/issues_api_only.checks.py) | 実Model/IaC→Comparison→集計/Issue CLIとexit、API-only代表経路 |
| [issues_failed_services.checks.py](integrations/issues_failed_services.checks.py) | 実Model/IaC/Export→Comparison→理由/位置/マスク付きIssue artifact |
| [issues_policy_equivalence.checks.py](integrations/issues_policy_equivalence.checks.py) | 実Model Policy/IaC/Import→比較/集計→保存artifact/detail/レポート |
| [issues_ref_returns.checks.py](integrations/issues_ref_returns.checks.py) | 実Model/IaC/Export/Import→Ref返却型の解決→Issue判定 |
| [issues_scan.checks.py](integrations/issues_scan.checks.py) | 実Scan/CLI→複数service/Adapter/Scan成果物/保存、失敗や参照警告を保持 |
| [model-document-sources.checks.py](integrations/model-document-sources.checks.py) | 実管理Task edit→Model/JSON内容→保存、他環境・Consumer不変 |
| [lambda-input-reference.checks.py](integrations/lambda-input-reference.checks.py) | 保存Producer→Lambda入力のcross-file解決・依存とConsumer不変 |
| [lambda_permission.checks.py](integrations/lambda_permission.checks.py) | 実Model→roundtrip/Sync→Permission生成、親子保存と不正候補時の旧View保護 |
| [model-input-context-digest.checks.py](integrations/model-input-context-digest.checks.py) | project execution account→保存JSON参照/内容/Source依存、明示候補以外の値不変 |
| [model-operation-publication.checks.py](integrations/model-operation-publication.checks.py) | 実Model-only操作→Task/Publication→最終参照検証、失敗/非選択bytes保持 |
| [model-properties-v2.checks.py](integrations/model-properties-v2.checks.py) | 実CLI/Task/Git→Model edit/Observed→Publication/Recovery、隔離されたstandalone audit |
| [model-reference-nodes.checks.py](integrations/model-reference-nodes.checks.py) | 保存Producer/Consumer→実JSON/Markdown生成→再読込、AWS JSON境界遮断 |
| [model-test.checks.py](integrations/model-test.checks.py) | 実Model→standalone監査Python生成→埋込Adapter/比較、独立OSで実行・ログ保存 |
| [model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py) | 実生成候補→保存Validator→共通check到達、失敗伝播・定義共有/workerとpublication scope |
| [model_design.checks.py](integrations/model_design.checks.py) | 既存7関数を維持。実Model→生成/Validator/保存、複数service失敗と正本保持 |
| [model_files.checks.py](integrations/model_files.checks.py) | 実CLI read/find/resource/trace→入口/parts→Task隔離、Publication cache失効・stale input拒否 |
| [model_impact.checks.py](integrations/model_impact.checks.py) | 保存された複数Modelグラフ→実Git Snapshot/Task差分→依存Scope、Consumer/他環境不変 |
| [model_parameter_inputs.checks.py](integrations/model_parameter_inputs.checks.py) | 明示環境Model→Sync/保存参照、KMS Alias/Secret/6 ProducerとConsumer不変 |
| [model_templates.checks.py](integrations/model_templates.checks.py) | 環境別保存Model→parts/依存Graph→Sync、実transaction/rollback/recoveryと入力変更停止 |
| [policy_tables.checks.py](integrations/policy_tables.checks.py) | 実policy_tables CLI→Markdown修復と元JSON artifact bytes保持 |
| [producer-identifier-reference.checks.py](integrations/producer-identifier-reference.checks.py) | 保存Producer observed ID→Consumer identifier参照→依存Snapshot、保存値不変 |
| [producer-name-reference.checks.py](integrations/producer-name-reference.checks.py) | 保存producer raw name/JSON→Consumer参照→変更新規読取と依存Hash |
| [raw-bucket-name-reference.checks.py](integrations/raw-bucket-name-reference.checks.py) | 保存S3 name→複数Consumer・raw/URI参照、環境隔離/依存・元値保持 |
| [resource_mode.checks.py](integrations/resource_mode.checks.py) | 保存ResourceMode→実Sync/Validator→stale View拒否/修復、Model bytes保持 |
| [rotation_schedule.checks.py](integrations/rotation_schedule.checks.py) | 保存Secret/Rotation/KMS→roundtrip/Sync→Design生成、親子変更・失敗保護 |
| [s3-bound-anchor.checks.py](integrations/s3-bound-anchor.checks.py) | 保存S3 binding/anchor→実生成/再同期→name表示と元参照保持 |
| [security-group-input-reference.checks.py](integrations/security-group-input-reference.checks.py) | 保存VPC/SG Producer→Consumer参照/Source依存→Hash変更、環境隔離 |
| [security_group_tables.checks.py](integrations/security_group_tables.checks.py) | 保存SG/Stack Model→実metadata読取/Renderer→タグ復元、正本bytes保持 |
| [service-parameter-inputs.checks.py](integrations/service-parameter-inputs.checks.py) | 保存Athena/S3・SQS/project context→参照依存/明示候補、他環境と元bytes保持 |
| [sync-existing-files.checks.py](integrations/sync-existing-files.checks.py) | 実Sync CLI/保存API→既存改行/ファイル、途中失敗時rollbackと入力保護 |
| [sync-model.checks.py](integrations/sync-model.checks.py) | 既存Stage/Task→候補Validator→Publication/Acceptance、複数service・sidecar・Recovery |
| [task_contract.checks.py](integrations/task_contract.checks.py) | 実atomic replaceと並行readerのstart/complete/suspend/resume、別TaskのIssue保存併存 |
| [used-definition-inputs.checks.py](integrations/used-definition-inputs.checks.py) | 実使用Framework定義→Source Snapshot→生成Stage、入力変更時の公開停止 |
| [validate-blueprint.checks.py](integrations/validate-blueprint.checks.py) | 実Task/別OS module import/Terraform CLI→Validator補助の統合dispatch |
| [validation_scope.checks.py](integrations/validation_scope.checks.py) | 実Git/複数環境service→並列Validator/Cache→生成scope・変更検知とCLI遮断 |
| [worktree-deploy-repair.checks.py](integrations/worktree-deploy-repair.checks.py) | 実Worktree親子→修復request/result→親への統合・再開・cleanup |
| [worktree-model-operation.checks.py](integrations/worktree-model-operation.checks.py) | 実WorktreeのModel-only契約→操作/最終検証→統合/cleanup |
| [worktree_python.checks.py](integrations/worktree_python.checks.py) | 実venv生成/再利用・別OSの初期化排他/安全なcleanup |
| [worktree_task.checks.py](integrations/worktree_task.checks.py) | 実Git/Worktree→契約/commit/rebase/ff merge→再検証/cleanup、衝突・途中失敗と保護 |

### Phase進捗・検証記録

| Phase | 実装結果 | 検証 |
| --- | --- | --- |
| 0 | 313登録・431条件を再確認。最終所有先と統合境界を整理 | 所有先の静的存在確認。実行到達性はCIで検証 |
| 1 | 6指定Suiteとservice_contractsを分離、不要IT/Helper削除 | 関連UT PASS後に全UT再検証 |
| 2 | Referenceの異常入力を共通UTに集約、保存/参照/依存Hash・他環境不変をITに保持 | 関連UT PASS後に全UT再検証 |
| 3 | Design/Model/Comparison/Deploy/Validationの入力矩形を既存UTへ移管、間接呼出し解消 | 関連UT PASS後に全UT再検証 |
| 4 | 残存68Suiteの境界を上表に明記、不要な準備・同一条件の繰返しを除去 | Git/Worktree/Publication/Recoveryの実経路はCIで検証 |
| 5 | 台帳/Receipt Inventory、構造規約、Ruff、pytest収集と全UT | 最終検証結果はPR/タスク報告に記録 |
| 6 | 既存Framework IT workflowを使用。新Runner・分類方式・互換Wrapperなし | 公式CI #137でUT 90/90・IT 68/68 PASS。10秒目標は未達 |

ローカル開始時UTは90 suite中89 PASS/1 FAIL（53.819秒）。既存model-reference-display-unitのAssertion Guard欠落を修正した。
この開始時測定は正常baselineではなく、公式CIの同条件Before測定でもない。ローカルITと性能測定は実行しない。

最終ローカル証跡: UT 90 suite PASS (56.140秒)、Ruff/構造規約/Inventory/Assertion Guard PASS、pytest 3,111条件収集、Framework Validator 611 checks PASS。
開始時commitの[公式CI #133](https://github.com/wwalpha/ai-driven-infra-blueprints/actions/runs/40108331559)はUT 122.6秒でFAILし、Assertion Guard違反でIT開始前に停止していたため、BeforeのIT/合計時間は未計測。
今回の公式CIは[PR #30](https://github.com/wwalpha/ai-driven-infra-blueprints/pull/30)で確認する。

公式CI初回#134ではUT 2 suiteとIT 4 suiteがFAIL。Python 3.12で必要な既存BoundCallbackを復元し、SGのjson importを修正、実Terraform CLI 1.16.1を既存workflowに準備する。
ManagedPolicyNameの明示証明は現行ARN契約/既存UTに合わせ、Ref return ITの古い未証明期待を補正した。Model DesignのPrincipal.AWS拒否Assertionは保持し、失敗内容を表示して再調査する。
局所再検証は関連UT 380条件PASS、Framework Validator 611 checks PASS。公式CIの再検証が完了するまでPhase 6は未完了。

公式CI再検証#135は全UT PASS（117.4秒）、IT 67/68 PASS・Model Design 1件FAIL（IT runner全体188.158秒）。
残るKMSケースはTyped Reference付き旧Viewが変更Modelと不一致のため、account検証より前に正しく停止していた。
同じ7関数のまま、まずstale View拒否と元Markdown/JSON/Model保持を検証し、その後に未検証Rendererで整合する不正Fixtureを用意して既存Principal.AWS拒否・write/read-only両方の保存保護Assertionへ到達させる。Productionの検証を無効化せず、元Assertionも削除しない。

最終監査で、validation_cacheの旧2行が同じCase IDを使う点を照合し、Producer入力6地点の所有先を移管後Attribute Reference ITへ正した。
Runtime Modelの列挙/読取/Hash/環境隔離は個別の既存IT/UT所有先を記載。入口を全削除した後の空列挙だけを既存Model Files UTへ追加して取りこぼしを防いだ（13条件PASS）。
CI #136は全UT PASS（183.6秒）、IT 67/68 PASS。stale Viewの入口はwriteであり、read-onlyは先にPrincipal.AWS検証へ進むことを実測し、Fixtureの事前確認をwriteへ修正した。7ケースの元拒否Assertionは維持する。

公式CI [#137](https://github.com/wwalpha/ai-driven-infra-blueprints/actions/runs/40117696173)は実装候補 `455b13f50f02a8118ac55f7ba56adcb7c311cae2` でUT 90/90・IT 68/68 PASS、236登録のReceipt到達性エラー0。UT 137.7秒、IT runner本体236.702秒、UT＋IT 374.402秒（準備時間を除く）。IT 10秒目標は未達で、正常Beforeの欠落により改善率は判定しない。
QuickSightの既存UT行と移管元行が同じ所有関数を重複登録していたため、既存UT行だけを残した。最終Headの公式結果はPR checksで確認する。

最新ローカル基準e91ea79のReference契約と統合する際は、同Taskの全UT/台帳追加を保持する。移管UTのImportValue Fixtureは実Outputs経由のscope付き索引を使用し、KMSの生成ID未証明拒否も現行共通契約の理由で確認する。Productionの変更は継承のみで、今回Taskからは編集しない。

## Issue Skill入力・Git変更監視の廃止

| ID | Function | Kind | Source | Mode / Count | Guarantee | Provenance |
| --- | --- | --- | --- | --- | --- | --- |
| `issues-change::comparison` | `check_comparison_input_tracking_is_report_only` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | Issue入力追跡で再読込/hash比較なし・通常比較の矛盾hash拒否を維持 | Issue変更監視廃止 |
| `issues-change::missing-producer` | `ModelDependencyTests.test_missing_producer_dependency` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | unittest / 1 | 欠落ProducerをNoneで追跡し出現時に通常比較は矛盾拒否、Issueはハッシュなしで継続 | 通常比較のModel依存追跡回帰 |
| `issues-change::existing-producer` | `ModelDependencyTests.test_existing_producer_dependency` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | unittest / 1 | 既存依存の矛盾拒否、再読込・同一バイト二重ハッシュなし、Issueはパスのみ | 通常比較のModel依存追跡回帰 |
| `issues-change::scan-inputs` | `check_scan_accepts_input_changes` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 3 | Scan中のMarkdown/Model/IaC変更で監視停止・再Scanなし | 通常比較のModel依存追跡回帰 |
| `issues-change::lint` | `check_lint_jobs_accept_changed_dependencies` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 3 | lintジョブ間の依存ファイル/集合/選択変更を許容・監視フィールドなし | Issue変更監視廃止 |
| `issues-change::git` | `check_issue_task_ignores_other_task_git_changes` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L522) | pytest / 1 | 実GitでHEAD前進・Model staged・IaC dirty・untrackedとIssue完了・他Task変更を集計しない | Issue変更監視廃止 |
| `issues-change::loop` | `check_issue_loop_has_no_git_change_checks` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L81) | pytest / 1 | Issue loopで変更ファイル収集/差分チェックなし・通常Validatorは実行 | Issue変更監視廃止 |
| `issues-change::authority` | `check_save_authority_limits_real_destinations` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 4 | 実Issue契約のreport保存先のみ許可・別名/親経路/Humanファイル包括権限の拒否 | Issue変更監視廃止 |
| `issues-live::authority` | `check_save_authority_ignores_cached_task` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 7 | 実Taskの古い外側cacheを保持し、最新status・Allowed/Modified paths・scope・typeで保存/拒否、拒否時atomic未実行と既存report不変 | v1026v4 |
| `issues-live::selection` | `check_save_authority_reselects_live_task` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 3 | 環境変数・API・暗黙選択の変更をLive認可へ反映 | v1026v4 |
| `issues-live::cli` | `check_save_cli_keeps_publication_scan_and_pending_validation_separate` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 12 | 実Task/Scan/Review保存、CLI・環境変数・暗黙選択、保存前後の選択変更でも認可Task名の案内とprocessing終了コードを維持 | v1026v4 |
| `issues-change::mechanical-contracts` | `check_mechanical_accepts_contract_catalog_changes` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | Issue機械診断中の他Task追加で停止しない | Issue変更監視廃止 |
| `issues-change::validation-contracts` | `check_issue_validation_ignores_contract_catalog_changes` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#L562) | pytest / 1 | Issue ValidatorのTask一覧変更許容・実Acceptance検証・PASS cacheなし | Issue変更監視廃止 |

## Reference comparison residual safety (1025v2)

既存の178型監査台帳・ARN契約・Sub/Join比較を再利用する。保存Observedは履歴値であり物理同一性を証明しない。同一Producer/属性と、scope・一意性が証明された同一Export/変換式は論理同一性として比較する。Selectの具体値評価はbounds未証明のまま停止する。

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `reference-residual::observed` | `test_replacement_and_old_observed_cannot_prove_physical_identity` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | VPC CIDR変更と旧ObservedはArn/Sub/Join/Split/Selectと逆方向でuncompared、論理同一性を維持 | Synthetic Models |
| `reference-residual::eventbus` | `test_eventbridge_bus_name_arn_and_proven_reference` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 8 | 省略/default/custom名・ARN・Ref/GetAtt/Subから正しいRule ARN | Synthetic Models |
| `reference-residual::eventbus-invalid` | `test_eventbridge_unproven_or_conflicting_bus_is_uncompared` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 14 | scope不一致・不正ARN・欠落・循環・未証明参照をuncompared | Synthetic Models |
| `reference-residual::route53` | `test_route53_composite_export_uses_shared_nested_setting_comparison` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | ネストしたRoute53 settingの同一Export比較と異なる変換のuncompared | Synthetic Models |
| `reference-residual::export-expression` | `test_export_retains_symbolic_dns_expression_and_transform` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 8 | 同一scope/Export/変換のみmatched、Select boundsとProducer/属性/由来を保持 | Synthetic Models |
| `reference-residual::export-invalid` | `test_symbolic_export_keeps_scope_uniqueness_and_invalid_input_guards` | UT | [units/aws-reference-expressions-unit.checks.py](units/aws-reference-expressions-unit.checks.py) | pytest / 8 | Export不在・重複・探索不完全・scope不一致・範囲外・不正式の拒否 | Synthetic Models |

## ARN構築式の正規化とKMS参照同一性

共通の構造・Producer・スコープ組合せはarn-projection UTに集約し、既存Evidence UTにはImportValue/Export/Refの接続回帰のみ追加する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `arn-projection::symbolic` | `test_projection_and_symbolic_comparison` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 6 | AliasName/KeyIdのSub/Join/入れ子射影、未確定KeyIdの論理比較と文字列の証拠不足、非破壊 | Synthetic Models |
| `arn-projection::receivers` | `test_projection_only_uses_registered_receiving_forms` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 5 | KMS_FORMSの全受取プロパティと対象外経路の既存動作 | Synthetic Models |
| `arn-projection::shape` | `test_unproven_shape_or_scope_never_falls_back` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 6 | 余計な接頭辞/接尾辞とpartition/region/account不一致は一致へ昇格しない | Synthetic Models |
| `arn-projection::producer` | `test_different_producers_with_equal_names_cannot_match` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 1 | 同名Aliasでも別Producerの直接/構築式はdifference | Synthetic Models |
| `arn-projection::owning-context` | `test_projection_uses_producer_context_without_borrowing_consumer_context` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 3 | Consumerと異なるProducer所属スコープのみを使用 | Synthetic Models |
| `arn-projection::saved-evidence` | `test_saved_reference_evidence_is_checked_before_projection` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 1 | 保存参照宣言を既存Evidenceへ渡し、未証明参照を昇格しない | Synthetic Models |
| `arn-projection::attribute` | `test_key_and_alias_arn_are_different` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 1 | KeyArnとAliasArnの混同をdifference | Synthetic Models |
| `arn-projection::scope` | `test_producer_scope_requires_the_owning_stack` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 10 | Producer/Stack/型/一意性/Condition/Transform/CREATE/確定pseudoの証明必須 | Synthetic Models |
| `arn-projection::unresolved` | `test_incomplete_or_unregistered_expressions_are_uncompared` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 7 | 未解決/未知/Select/Split/複数Producer/未登録属性は推測で一致しない | Synthetic Models |
| `arn-projection::existing` | `test_existing_reference_and_literal_results` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 4 | 直接参照・Sub/JoinのARN参照・正常文字列ARNを維持 | Synthetic Models |
| `arn-projection::getatt` | `test_alias_arn_projection_does_not_authorize_getatt` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 1 | AliasArn導出とCFn未対応GetAttを分離 | Synthetic Models |
| `arn-projection::shared` | `test_normalizer_reuses_a_non_kms_shape_without_enabling_a_service` | UT | [units/arn-projection-unit.checks.py](units/arn-projection-unit.checks.py) | pytest / 1 | サービス非依存の正規化は既存ARN_SHAPESを再利用 | Fixed contracts |
| `arn-projection::pipeline` | `test_alias_arn_sub_import_ref_pipeline_preserves_export_evidence` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 1 | Model AliasArn→Sub→ImportValue→Export→Ref AliasName→matchedとExport証跡維持 | Synthetic Models |

## IMPORT参照のPENDING_DEPLOY正常除外

既存の6分類と参照契約検証を利用する。PENDING_DEPLOYはexcludedであり、Issue・未比較・partialには含めない。分類行の専用件数はIssue分類とは分離し、同じConsumer/Producer原因の親子伝播を重複排除する。通常Markdownは件数のみ、Artifactと明示detail CLIは原因を保持する。他のdeferred状態は既存判定を維持する。

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `import-wait::category` | `test_normal_wait` | UT | [units/import-reference-deferred-unit.checks.py](units/import-reference-deferred-unit.checks.py) | pytest / 3 | pending_deployだけexcluded・構造化cause種類、他2状態deferred | Synthetic observations |
| `import-wait::failures` | `test_other_failures_are_not_normal_waits` | UT | [units/import-reference-deferred-unit.checks.py](units/import-reference-deferred-unit.checks.py) | pytest / 1 | 既存エラー分類・6分類・不正cause拒否 | Synthetic exceptions |
| `import-wait::authority` | `test_phase_selection_uses_authoritative_observations` | UT | [units/import-reference-deferred-unit.checks.py](units/import-reference-deferred-unit.checks.py) | pytest / 3 | observed正本で状態選択・形式検証維持 | Synthetic observations |
| `import-wait::propagation` | `test_import_wait_propagates_without_parent_issue` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 15 | link/JSON/modelRef/intrinsicの原因保持・Issue 0・pendingだけpartialなし | Synthetic Models |
| `import-wait::invalid` | `test_import_invalid_contract_or_identifier_stays_an_issue` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 16 | pendingでも欠落・曖昧・型/属性/Consumer違反を除外しない、不正観測値もIssue | Synthetic Models |
| `import-wait::siblings` | `test_import_wait_preserves_known_json_difference` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 8 | JSON/配列の一部除外と独立差分の保持、通常詳細に除外子を混入しない | Synthetic Models |
| `import-wait::actual` | `test_actual_wait_retains_pointer_and_known_siblings` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 6 | IaC側の構造化原因・Pointer・独立差分を維持 | Synthetic evaluator |
| `import-wait::resource` | `test_resource_failure_uses_shared_classification` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 5 | Resource例外も共有分類を利用 | Synthetic comparison |
| `import-wait::operands` | `test_deferred_intrinsic_does_not_hide_other_operand_failures` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | pending/unobservedが他operandの不正参照・式違反を隠さない | Synthetic intrinsic |
| `pending-excluded::report` | `check_pending_deploy_is_count_only_exclusion` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 2 | 1/2件の専用分類行・Issue 0・通常詳細なし・Artifact/明示detail原因保持 | Synthetic records |
| `pending-excluded::status` | `check_pending_deploy_does_not_change_comparison_status` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 6 | pending単独/一致/差分/未比較/エラー/他deferredの全体判定・Issue件数分離 | Synthetic records |
| `pending-excluded::dedup` | `check_pending_deploy_parent_child_count_and_issue_separation` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | 親子同原因を1件・別Consumerを独立集計・CFn非対応とIssue分類を維持 | Synthetic records |
| `import-wait::artifact` | `check_artifact_v5_rejects_invalid_indexes` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 24 | deferred/excludedのcause/category/count/index整合性検証、旧分類互換なし | Synthetic Artifact |

## CodeBuild PLAINTEXT Resource link prohibition

| Case | UT | Count | Responsibility |
| --- | --- | --- | --- |
| Model policy | `units/codebuild-plaintext-unit.checks.py::test_model_policy` | 18 | CREATE/IMPORT; literal ARN/URL strings pass; every producer kind, missing target and structured reference are blocking errors |
| Exact variable context | `test_exact_sibling_type_and_continuation` | 2 | Repeated/indexed rows use their own Name/Type; real presentation validation and unrelated invalid literals do not hide policy errors |
| Independent ownership | `test_prohibited_link_preserves_resource_ownership_error` | 1 | A prohibited link does not exclude its Resource from ownership validation |
| Policy identity | `test_policy_diagnostic_identity_preserves_model_ids` | 2 | Markdown and repeated/indexed Model policy errors retain the existing Model diagnostic ID; other Resources and unrelated errors remain separate |
| JSON context | `test_container_references_use_exact_context` | 2 | Value/document structured and Markdown references use their own array object's Type |
| Display restoration | `test_markdown_rejects_plaintext_link` | 4 | Explicit/missing PLAINTEXT marker rejects links in CREATE/IMPORT |
| Non-PLAINTEXT | `test_non_plaintext_round_trip` | 2 | PARAMETER_STORE/SECRETS_MANAGER display round trip is preserved |
| Issues connection | `test_scan_save_owns_codebuild_and_deduplicates` | 18 | Model-only, Markdown-only and combined policy errors; one/two variables and independent ownership errors; readable/unreadable Markdown and typed IAM.Role; scan/save twice retains Issue IDs and counts, independent S3 comparison/lint, CLI artifact v5 and strict generation rejection |
| Structured display | `test_structured_reference_display_is_rejected` | 2 | Symbolic typed rows remain visible; independent Model validation rejects PLAINTEXT references in CREATE/IMPORT |
| Valid producers | `test_non_plaintext_model_links_pass` | 2 | Authoritative Model passes correct SSM.Parameter/SecretsManager.Secret links |

Existing partial-comparison UTs retain confirmed sibling differences and reject matches for prohibited references. Their comparison rejection reason is PLAINTEXT prohibition; authoritative Model validation owns the blocking ordinary Issue.

## Design table expansion dependency isolation

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `design-expansion::independence` | `check_expansion_failure_preserves_raw_and_independent_resources` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py) | pytest / 1 | Valid CodeBuild PASS; PLAINTEXT cause retained, no derived Variables/Subnets/Id errors, raw failures and independent catalog/schema failures remain; blocked scope recorded | Synthetic Markdown |
| `design-expansion::stages` | `check_expansion_dependency_boundaries` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py) | pytest / 6 | Model reference tables, display expansion and hidden-row projection: input ERROR versus unresolved-reference warning, raw continuation, no identity misclassification or processing error | Synthetic exceptions |
| `design-expansion::child-projection` | `check_grouped_projection_failure_stops_dependent_schema` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py) | pytest / 1 | Child projection failure blocks dependent grouped schema and identifier checks | Synthetic KMS |
| `design-expansion::child-expansion` | `check_grouped_expansion_failure_has_no_derived_errors` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py) | pytest / 1 | Actual grouped child expansion violation retains its cause without secondary schema or identifier errors | Synthetic KMS |
| `design-expansion::horizontal-raw` | `check_horizontal_raw_checks_survive_reference_failure` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py) | pytest / 1 | Horizontal Security Group cell structure and CIDR checks continue when Model reference validation fails | Synthetic Security Group |
| `design-expansion::processing` | `check_unexpected_expansion_exception_is_processing` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py) | pytest / 1 | Unexpected RuntimeError remains a processing failure | Synthetic exception |

| `design-expansion::model-resources` | `test_model_reference_failure_keeps_independent_schema_and_valid_resource` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 1 | Model policy failure is isolated; independent typed Resource schema errors and healthy Resource identifier checks remain | Synthetic Models/Markdown |
| `design-expansion::saved-raw` | `test_scoped_generation_failure_keeps_saved_raw_and_schema` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 2 | Real scoped generation failure preserves saved raw H1 checks, independent schema errors and incomplete semantic checks | Synthetic Models/Markdown |
| `design-expansion::raw-unavailable` | `test_generation_failure_unreadable_raw_is_not_run` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 2 | Missing and invalid UTF-8 saved Markdown retain raw NOT_RUN reasons without processing errors | Synthetic Models/Markdown |
| `design-expansion::normal-typed` | `test_scoped_normal_typed_reference_checks_raw_once` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 2 | Resolved and CREATE PENDING_DEPLOY references preserve completion policy and execute raw checks once | Synthetic Models/Markdown |
| `design-expansion::invalid-target` | `test_missing_typed_target_is_model_error_not_reference_wait` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 1 | A missing typed target remains MODEL_NEEDS_FIX, never a completable reference wait | Synthetic Models/Markdown |
| `design-expansion::mixed-issues` | `test_issues_retains_mixed_causes_and_resource_dependencies` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 1 | Actual Issues scan retains policy/schema/raw causes, Resource NOT_RUN and aggregate FAIL without derived or processing errors | Synthetic Models/Markdown |
| `design-expansion::model-display-match` | `test_recovery_rejects_independent_markdown_tampering` | UT | [units/codebuild-plaintext-unit.checks.py](units/codebuild-plaintext-unit.checks.py) | pytest / 1 | Recovery refuses mismatched independent Model displays and continues the remaining matched Resource | Synthetic Models/Markdown |
| `design-expansion::grouped-models` | `check_grouped_resource_recovery_keeps_parent_and_children_together` | UT | [units/model-reference-display-unit.checks.py](units/model-reference-display-unit.checks.py) | pytest / 2 | Existing renderer binds each complete parent/child group; malformed child and tampered sibling displays cannot bypass typed validation | Synthetic Models/Markdown |

The existing CodeBuild scan/save UT also checks Issues v5 ordinary policy errors, aggregate FAIL, incomplete NOT_RUN checks, no derived catalog/identifier errors and no policy processing errors. Generation failures retain FAIL independently from saved raw validation and per-Resource semantic NOT_RUN; pure reference waits retain their existing completion policy.

## desired直接値PENDING_DEPLOYの正常除外

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `direct-pending::cause` | `test_direct_pending_deploy_cause` | UT | [units/import-reference-deferred-unit.checks.py](units/import-reference-deferred-unit.checks.py) | pytest / 2 | 直接値専用Blocked原因・対象property・excluded分類、コード表記の正規化 | Synthetic desired values |
| `direct-pending::schema` | `test_direct_pending_deploy_cause_schema` | UT | [units/import-reference-deferred-unit.checks.py](units/import-reference-deferred-unit.checks.py) | pytest / 5 | 不正phase・欠落/空/型違いproperty・余剰fieldの拒否 | Synthetic causes |
| `direct-pending::document` | `test_pending_deploy_in_document_is_unchanged` | UT | [units/import-reference-deferred-unit.checks.py](units/import-reference-deferred-unit.checks.py) | pytest / 1 | document内文字列は直接値の専用除外へ変えない | Synthetic document |
| `direct-pending::route53` | `test_route53_direct_pending_deploy_classification` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 12 | dev/stg cde Resource003 DNSNameの除外1件・Issue0、未確定4値と通常差分の維持 | Synthetic Models/IaC |
| `direct-pending::siblings` | `test_direct_pending_deploy_preserves_sibling_comparison` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 8 | 同Resourceの2直接値を2件、親内/別親の一致・差分・真の未比較を維持 | Synthetic Models/IaC |
| `direct-pending::actual` | `test_direct_pending_deploy_retains_actual_sibling_failures` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 2 | 除外先IaC未解決値の無視と別propertyの未解決参照維持 | Synthetic Models/IaC |
| `direct-pending::reports` | `check_direct_pending_deploy_reports_and_dedup` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 2 | 異property独立件数・親子重複排除・IMPORT件数維持・Artifact v5・issues/reportのIssue0 | Synthetic records |
| `direct-pending::artifact` | `check_direct_pending_deploy_artifact_rejects_invalid_causes` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 8 | 原因schema・分類・除外件数の不整合を拒否、互換分岐なし | Synthetic Artifact v5 |

## Immutable issues Snapshot v5

旧inventory merge・旧ID/Service block/Human文面保持・continuing/resolved/unverified状態遷移・
verification_targets復元・resolved互換ProjectionのUTを削除した。部分結果を追記する旧CLIと
そのITも削除した。現行のSnapshot/Human/coverage/publication契約は以下で検証する。
比較器・Gateの共通Markdown分類・lint/秘匿化の既存UT/ITは維持する。

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `issues-snapshot::check_snapshot_replaces_inventory` | `check_snapshot_replaces_inventory` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 1 | 旧Markdownを読まない全置換、決定性、immutable値、解消後の最新Snapshot | Synthetic v5 |
| `issues-snapshot::check_review_additions_have_stable_ids_and_save` | `check_review_additions_have_stable_ids_and_save` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 1 | 機械16件＋Review9件の一意ID、元入力・機械ID不変、順序・再実行・Scan日時に依存しないID、IDコメントと両レポートの実保存 | Synthetic v6 |
| `issues-snapshot::check_review_duplicate_ids_rejected_before_rendering` | `check_review_duplicate_ids_rejected_before_rendering` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 2 | Review内重複と機械ID衝突を描画前に拒否し、既存の両レポートを保持 | Synthetic v6 |
| `issues-snapshot::check_human_exception_and_conflict` | `check_human_exception_and_conflict` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 1 | Human v2読取・2レポートのみ保存・Human原文保持、例外除外と矛盾時のIssue/未検証保持 | Synthetic v5 |
| `issues-snapshot::check_exclusion_scope` | `check_exclusion_scope` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 15 | Human id/Service/Resource/Property/Rule/診断ID/根拠/例外の一致、欠落・wildcard・公開アクセス誤除外拒否 | Synthetic v5 |
| `issues-snapshot::check_human_contract_refuses_unsupported_records` | `check_human_contract_refuses_unsupported_records` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 7 | v2のみ読取、旧field/version・欠落fact・wildcard・空Rule/条件・不正例外を拒否し原文保持 | Synthetic v5 |
| `issues-snapshot::check_incomplete_is_not_pass` | `check_incomplete_is_not_pass` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 4 | 処理エラー/未検証Service/LLM未確認をPASSにしない | Synthetic v5 |
| `issues-snapshot::check_partial_scope_refused` | `check_partial_scope_refused` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 5 | 部分Service/欠落結果/重複/理由欠落/Target未確定で保存拒否 | Synthetic v5 |
| `issues-snapshot::check_atomic_rollback` | `check_atomic_rollback` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 4 | 両Markdownのreplace前後失敗をrollbackしHuman原文保持 | Synthetic v5 |
| `issues-snapshot::check_review_rejects_incomplete_and_old_inputs` | `check_review_rejects_incomplete_and_old_inputs` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 9 | Scan/context/全材料review/診断網羅と旧Artifact/旧cleanup field拒否 | Synthetic v5 |
| `issues-snapshot::check_explicit_human_file_and_service_discovery` | `check_explicit_human_file_and_service_discovery` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 1 | 必須Human file/strict YAML/ModelとViewのTarget membership | Synthetic v5 |
| `issues-snapshot::check_reviewed_sources_are_not_reread` | `check_reviewed_sources_are_not_reread` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 1 | Scan後の入力変更を監視せずScan時根拠行のまま保存・Git非参照 | Synthetic v5 |
| `issues-snapshot::check_snapshot_rejects_invalid_current_values` | `check_snapshot_rejects_invalid_current_values` | UT | [units/issues-snapshot-unit.checks.py](units/issues-snapshot-unit.checks.py) | pytest / 11 | 範囲外診断/IaC、timezone、根拠path/line、未確認Service、不正・重複機械IDとReview入力IDの保存前拒否 | Synthetic v6 |

| `resource-impact::routes` | `check_task_snapshot_routes` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py#L425) | direct / 1 | 実managed保存・Candidate・stage/commit・最終Validation・Snapshot/graph回数 | Resource impact |
| `deploy-runtime::issues` | `check_mutation_and_recovery_with_issues` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py) | pytest / 1 | mutation継続・Issue警告なし・recovery継続、入力guard/危険rollback状態は停止 | Mock SDK / real guards |

| `report-task::git` | `check_report_commit_independence` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py) | pytest / 3 | Report-only保存は他TaskのGit変更を保持し、通常Taskは変更範囲を検証 | Synthetic Git |
| `generation-model::guards` | `check_generation_preserves_model_guards` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 3 | IssueがあってもAllowed paths・Validation scope・参照整合性エラーは拒否 | Synthetic Models |

## v1025v12 Validation / Issue Scan regression

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `validation-diagnostics::link-artifact-collection` | `check_artifact_differences` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 4 | 表の品質検証に依存しないJSONリンク収集の完了、正常参照・欠落・未参照の区別 | Synthetic Markdown/JSON |
| `validation-diagnostics::scoped-orphans` | `check_scoped_orphans_without_markdown` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 6 | Markdownに依存しない全体/単一/複数Scope列挙、別Markdownによる所有誤判定とScope外JSON混入の防止、所有不明judgments | Synthetic JSON |
| `validation-diagnostics::unavailable-orphans` | `check_unavailable_services_still_scan_orphans` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 1 | 親子ValidatorでMarkdown欠落時も孤立JSONを検出、未検証情報を保持 | Synthetic JSON |
| `validation-diagnostics::invalid-links` | `check_invalid_json_links_continue_without_external_reads` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 4 | サービス外/リポジトリ外/絶対/外部symlinkの配置違反、正常参照継続、外部ファイル非読込、正常索引への不正パス非登録 | Synthetic Markdown/JSON |
| `validation-diagnostics::child-correspondence` | `check_child_validator_keeps_diagnostic_correspondence` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 1 | 親子統合で診断IDと表示エラー対応を維持、独立した文字列エラーを保持 | Synthetic Findings |
| `validation-diagnostics::scan-correspondence` | `check_scan_artifact_keeps_diagnostics_and_incomplete_metadata` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 8 | 同文/ラッパー/親子伝搬/独立同文/ReferenceDiagnostic/PLAINTEXTで二重Issueを防止、v5と未検証metadataを保持 | Existing UT extended |

## Deploy lazy inputs and session Model reuse

The former whole-target digest/observed-baseline UTs are replaced by scoped revision,
publication and cache checks; no whole-target Model scan is an acceptance condition.
Existing Deploy handoff tests retain shared-input/SUCCESS protection; observed-resume
checks retain exact journals, CAS, partial publication and execution/approval evidence.

| Case ID | Function | Kind | File | Runner / Cases | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-lazy::bounded-100` | `check_100_stacks_bounded` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 2 | 100 Stacks, first-slot failure, concurrency 1/3, no pending decode/delivery | Added |
| `deploy-lazy::model-once` | `check_model_load_once_parallel_and_observed` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | 100 concurrent requests, one source parse/check, incremental observations, no recheck | Added |
| `deploy-lazy::owners` | `check_index_owners_duplicate_and_unknown` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Unique, absent and duplicate owner discovery without inference | Added |
| `deploy-lazy::input-revision` | `check_claim_immutable_inputs_and_no_eager_decode` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Pin only claimed input hashes; reject changed IaC before use | Added |
| `deploy-lazy::observed-authority` | `check_observed_patch_rejects_authority_changes` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 3 | Reject desired, display and unrelated-byte changes | Replaces eager baseline tests |
| `deploy-lazy::success-resume` | `check_resume_skips_success_and_dependency_unknown` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | SUCCESS never starts twice; pending dependencies stay explicitly unloaded | Added |
| `deploy-lazy::desired-once` | `check_reference_dependent_validation_invalidated_after_observed` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Same-generation reuse; full reference-dependent check invalidation after observed deltas | Added |
| `deploy-lazy::cas` | `check_observed_publication_rejects_conflict` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Real observed writer rejects concurrent bytes before publishing | Added |
| `deploy-lazy::stack-delivery` | `check_stack_metadata_defers_delivery_model` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Stack/generated metadata equality needs no delivery Model; ordinary generation retains delivery validation | Added |
| `deploy-lazy::index-publication` | `check_index_delta_retarget_delete_and_invalid_unrelated` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Observed index patch without reparse, retarget/delete maintenance, invalid unrelated authority excluded | Added |
| `deploy-lazy::mapping-denial` | `check_owner_ambiguity_blocks_mapping` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Absent/duplicate owners cannot produce an observed mapping | Added |
| `deploy-lazy::cache-authority` | `check_cache_permission_and_input_revision` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Distinct permission context, reused checked snapshot, changed revision rejection | Added |
| `deploy-lazy::generation-stage` | `check_generation_stage_reuses_checked_model` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 1 | Reuse checked authority for byte-identical generation-stage copies; reject modified candidate bytes | Added |

## Partial reference snapshots

| Case ID | Function | Layer | File | Mode / count | Coverage | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `sqs-partial::producer` | `check_other_group_producer` | UT | [units/sqs-partial-reference-unit.checks.py](units/sqs-partial-reference-unit.checks.py) | pytest / 1 | 別グループQueueの参照をQueuePolicy部分表示で解決 | 追加 |
| `sqs-partial::deleted` | `check_deleted_candidate_producer` | UT | [units/sqs-partial-reference-unit.checks.py](units/sqs-partial-reference-unit.checks.py) | pytest / 1 | 候補削除済みQueueを旧ディスクModelから復活させない | 追加 |
| `sqs-partial::attribute` | `check_candidate_producer_attribute` | UT | [units/sqs-partial-reference-unit.checks.py](units/sqs-partial-reference-unit.checks.py) | pytest / 1 | 候補QueueNameからARNと表示リンクを解決、旧値を使用しない | 追加 |
| `sqs-partial::independent` | `check_unrelated_group_generation_failure` | UT | [units/sqs-partial-reference-unit.checks.py](units/sqs-partial-reference-unit.checks.py) | pytest / 1 | 完全候補の同型Resource件数による見出しを部分Viewでも維持し、無関係グループの全体表示失敗前後で正常QueuePolicyを検証 | 拡張 |
| `reference-values::partial-context` | `test_partial_json_reference_context` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 2 | JSON検証と投影の参照文脈分離、空候補からの旧Model補完禁止、未選択JSON非検証 | 追加 |

## v1026v1 Observed / Generation error classification

| Case ID | Function | Layer | File | Mode / count | Coverage | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-generation::phase-error` | `check_generation_error_retains_confirmed_observed` | UT | [units/deploy-generation-resume-unit.checks.py](units/deploy-generation-resume-unit.checks.py) | pytest / 6 | Generation実行/候補復旧/Guard例外の分類、Observed確定と両pending保持 | 拡張 |
| `deploy-generation::resume-only` | `check_generation_retry_does_not_repeat_observed` | UT | [units/deploy-generation-resume-unit.checks.py](units/deploy-generation-resume-unit.checks.py) | pytest / 1 | Generation再開成功時にObserved再保存なし、generationError解消 | 追加 |
| `deploy-generation::observed-history` | `check_generation_only_preserves_observed_history` | UT | [units/deploy-generation-resume-unit.checks.py](units/deploy-generation-resume-unit.checks.py) | pytest / 2 | Generation単独成功/失敗で既存Observedエラー履歴を保持 | 追加 |
| `worktree-runtime::observed-barrier` | `check_checkpoint_observed_barrier` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py) | pytest / 6 | Checkpointで同一Observed保護、Generationのみでも既存入力検証へ進む | 追加 |


## JSON派生ハッシュ削除とSnapshot cache

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot::rows` | `check_snapshot_row_index_and_mutable_entries` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py) | pytest / 1 | entries/固定行索引100回で構築1回、Candidate差分と旧入力保持、可変入力再読取、行の外部変更拒否、別呼出し分離 | 小さい辞書のみ |
| `snapshot::references` | `test_snapshot_reference_cache_and_unbound_inputs` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 2 | 固定/可変入力、参照100回の解決1/100回、派生hash禁止、参照なし、文書/Context/除外差分、返却結果隔離 | 既存小型Model |
| `snapshot::observed` | `test_reference_cache_observed_generation_and_invocation` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 1 | 他ServiceのObserved反映、保持Resolverの更新、UNRESOLVED→PENDING→RESOLVED、診断汚染防止、別呼出しで再解決 | 既存RunModelsと小型Model |
| `snapshot::candidate` | `test_reference_cache_candidate_and_rollback` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 1 | CandidateReadsの別Snapshotと元Snapshot復帰で診断混在なし | 既存CandidateReads |

旧 `check_json_hash_types` と専用再export helperは削除。共通JSON形式/ハッシュの契約は
既存 `json-format::check_output_bytes_and_hashes` に集約。旧派生hashの生成/trace/比較の
assertionは削除し、JSON/Markdown内容・構文・AWS文書検証・正本不変性を既存ケース内で維持。
既存文書編集ITの公開/no-op/環境間隔離とContext依存ITのProject変更検出は残す。
`test_generated_json_and_hash_keep_authority` は `test_generated_json_keeps_authority` へ改名。
`deploy-lazy::desired-once` は参照依存の全検証失効を確認し、Desired単独のPASS再利用とは扱わない。
正式ITは既存Framework ITのみで、新しいITケース・大規模fixtureは追加しない。

## Independent Deploy runs and unfinished operations

永続Session/Workflow/SAME-NEW/累積Budget/過去承認/旧形式復旧の専用ケースは廃止。AWS Token、現在ChangeSet承認、Secrets冪等性、Observed CAS/atomic publication、入力不変、worktree commit検証の安全性は既存UTを更新し、未完了Journal専用UTに集約する。ITはordered delivery、実process中断/publication復旧、単発Implement検証/統合に限定し、分岐組合せはUTに置く。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `independent-deploy::test_journal_excludes_history_and_approval_and_discards_success` | `test_journal_excludes_history_and_approval_and_discards_success` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_running_restart_observes_original_token_without_execute` | `test_running_restart_observes_original_token_without_execute` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_uncertain_operation_is_retained_without_new_token` | `test_uncertain_operation_is_retained_without_new_token` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_aws_success_before_observed_recovers_without_execute` | `test_aws_success_before_observed_recovers_without_execute` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_publication_recovery_failure_preserves_evidence` | `test_publication_recovery_failure_preserves_evidence` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_journal_tampering_and_redirects_are_rejected` | `test_journal_tampering_and_redirects_are_rejected` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_current_changeset_approval_is_not_restored` | `test_current_changeset_approval_is_not_restored` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_new_task_is_not_owned_by_unexecuted_old_changeset` | `test_new_task_is_not_owned_by_unexecuted_old_changeset` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_new_context_accepts_latest_iac_and_ignores_old_files` | `test_new_context_accepts_latest_iac_and_ignores_old_files` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_successful_stack_latest_iac_is_claimed_for_new_update` | `test_successful_stack_latest_iac_is_claimed_for_new_update` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_no_change_still_checks_all_four_kms_exports` | `test_no_change_still_checks_all_four_kms_exports` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::test_kms_four_exports_update_and_no_change_require_aws_facts` | `test_kms_four_exports_update_and_no_change_require_aws_facts` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::check_one_shot_request_requires_current_authority` | `check_one_shot_request_requires_current_authority` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 6 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::check_delivered_request_evidence_is_discarded` | `check_delivered_request_evidence_is_discarded` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 5 | 現在入力/未完了操作/単発修復の境界と過去状態非依存 | 追加 |
| `independent-deploy::recovery-guard` | `test_recovery_guard_preserves_current_task_target_and_model` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 4 | 復旧中のTask/target/Model変更を拒否 | 追加 |
| `independent-deploy::adoption-interruption` | `test_adoption_claim_failure_keeps_every_unprocessed_changeset` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 引き継ぎ中断で未処理ChangeSetの証跡を失わない | 追加 |
| `independent-deploy::terminal-output` | `test_terminal_output_failure_discards_execution_intent` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | AWS確定後のExport未反映は失敗報告しExecute意図を破棄 | 追加 |
| `independent-deploy::bootstrap-recovery` | `test_bootstrap_restart_restores_failure_and_only_current_owner` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 元Tokenの失敗eventとowner再取得、完了後Journal破棄 | 追加 |
| `independent-deploy::bootstrap-input-guard` | `test_recovery_mutation_guard_fixes_bootstrap_inputs` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 3 | 復旧mutation直前のconsumer/owner入力固定 | 追加 |
| `independent-deploy::observed-run-context` | `check_run_context_owns_observed_publication` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 2 | RunContextの新規/未完了Observed publication経路 | 追加 |
| `independent-deploy::waiting-generation` | `test_waiting_generation_recovers_scope_without_inheriting_completed_stacks` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 未公開の生成待ちを新実行へ再結合、過去Stack成功や未確定候補は引き継がない | 追加 |

## Modelを正本とする配列表示

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `array-projection` | `check_array_model_projection` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py) | pytest / 1 | 注釈なし生成、元JSON/コメント/順序不変、Model照合後の正式行、番号・要素・値・コメント・所属不正、Modelなしのエラー | 追加 |
| `array-compact-diagnostics` | `check_indexed_compact_variable_diagnostics` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py) | pytest / 1 | Model JSON復元を伴わない番号付き変数の既存生Markdown診断、0/先頭ゼロ/欠番とPLAINTEXTリンク拒否 | 追加 |



## Deploy repair discard interruption recovery

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `repair-discard::interruptions` | `check_discard_retries_every_interruption` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 26 | 検証前・rename前後・各Log/Validation/Result/Request/Failure削除・rmdir前後・一時証跡削除前後の例外/強制終了、再実行と二重削除防止 | Synthetic offline |
| `repair-discard::integrity` | `check_discard_rejects_unknown_or_changed_evidence` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 11 | 署名・残存内容・所有権・commit/requestId・不明ファイル・一時証跡欠落を安全停止 | Synthetic offline |
| `repair-discard::shared` | `check_discard_retry_preserves_shared_failure` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 2 | 無効化前/後に共有されたFailureと他Requestの保持 | Synthetic offline |
| `repair-discard::templates` | `check_failure_survives_new_task_and_templates_live_until_consumed` | UT | [units/deploy-temporary-unit.checks.py](units/deploy-temporary-unit.checks.py) | pytest / 4 | 未消費Failure保護、Cleanup途中/不明証跡でTemplate保持、完了後の回収 | Synthetic offline |


## Deploy recovery, OS locks and temporary inputs

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-recovery::test_new_task_recovers_original_execution_then_uses_latest_inputs` | `test_new_task_recovers_original_execution_then_uses_latest_inputs` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_foreign_destination_settles_aws_before_refusing_local_publication` | `test_foreign_destination_settles_aws_before_refusing_local_publication` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_unrelated_stack_operations_survive_recovery_and_new_run_saves` | `test_unrelated_stack_operations_survive_recovery_and_new_run_saves` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 2 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_changed_original_operation_proof_blocks_before_aws` | `test_changed_original_operation_proof_blocks_before_aws` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 5 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_signed_operation_must_match_execution_target` | `test_signed_operation_must_match_execution_target` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 3 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_unrelated_stack_requires_proved_dependency_boundary` | `test_unrelated_stack_requires_proved_dependency_boundary` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 5 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_process_kill_releases_lock_retains_original_journal_and_token` | `test_process_kill_releases_lock_retains_original_journal_and_token` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_lock_rejects_unsafe_files_without_unlinking` | `test_lock_rejects_unsafe_files_without_unlinking` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 3 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_partial_scope_keeps_atomic_plan_with_all_original_operation_proofs` | `test_partial_scope_keeps_atomic_plan_with_all_original_operation_proofs` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_peer_owners_keep_every_entry_when_new_operation_is_saved` | `test_peer_owners_keep_every_entry_when_new_operation_is_saved` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_unrelated_publication_blocks_only_shared_task_files` | `test_unrelated_publication_blocks_only_shared_task_files` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::test_existing_readable_lock_is_reused_without_unlink` | `test_existing_readable_lock_is_reused_without_unlink` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::check_current_task_reauthorizes_only_safe_signed_publication` | `check_current_task_reauthorizes_only_safe_signed_publication` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 9 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::check_unused_failure_cleanup_preserves_active_or_unknown_evidence` | `check_unused_failure_cleanup_preserves_active_or_unknown_evidence` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 10 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::check_owned_directory_cleanup` | `check_owned_directory_cleanup` | UT | [units/deploy-temporary-unit.checks.py](units/deploy-temporary-unit.checks.py) | pytest / 19 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |
| `deploy-recovery::check_controller_closes_lock_and_cleans_workdir_on_return_or_error` | `check_controller_closes_lock_and_cleans_workdir_on_return_or_error` | UT | [units/deploy-temporary-unit.checks.py](units/deploy-temporary-unit.checks.py) | pytest / 2 | Task独立復旧・元Token・OS排他・所有と参照に基づくCleanup | Synthetic offline / short process |


## Deploy Handoff scope and Task-independent cleanup

| Requirement | Test | Layer | Source | Cases | Responsibility | Environment |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-scope::handoff` | `check_handoff_scopes_current_failure_and_preserves_journal` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 15 | 同一/無関係/双方向・間接依存、Observed/Generationの競合・独立・不明Scope、元Journal保持 | Synthetic offline |
| `deploy-scope::locks` | `check_handoff_lock_order_fails_without_waiting_or_releasing_owner` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 2 | Journal→Repairの非待機排他と競合後再取得 | Synthetic offline |
| `deploy-scope::authentication` | `check_dependency_reader_uses_current_authentication` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 3 | alias/Account選択、現Target/STS認証、読取API限定 | Synthetic offline |
| `deploy-scope::dependency-graph` | `test_deploy_and_handoff_dependency_graph` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 8 | 共通Import/Export判定の双方向・間接依存、共通Producerのみの独立、取得不備の安全停止 | Synthetic offline |
| `deploy-scope::checkpoint` | `check_checkpoint_uses_scoped_barrier_under_ordered_locks` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py) | pytest / 4 | Checkpointの実変更範囲・Publication衝突、Journal/Repair排他、Commit前停止 | Synthetic offline |

## v1026v10 Change Validation residual regressions

| Case | Function | Layer | Location | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `change-residual::metadata-scope` | `check_unrelated_resource_identity_defect` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 4 | 未変更Resourceのcfn/deploymentEncryption/欠落・重複identityを品質検証せず、Fullでは検出 | Synthetic Models |
| `change-residual::changed-metadata` | `check_changed_resource_metadata_is_validated` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | 変更したResource metadataの不正は拒否 | Synthetic Models |
| `change-residual::dependency-states` | `check_dependency_discovery_and_broken_consumer` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 6 | missing/current/stale × typed/Markdown参照、Consumer完全探索・参照破壊FAIL・再読込なし・Deploy sealed条件維持 | Synthetic Models |
| `change-residual::dependency-empty` | `check_missing_index_without_consumer` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | indexなし・Consumerなしで正常更新 | Synthetic Models |
| `change-residual::dependency-reuse` | `check_current_index_reuses_unaffected_metadata` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | 5サービスの正常indexを再利用、変更Snapshotのみ解析、コメントのみは参照探索0、sealed index不変 | Synthetic Models |
| `change-residual::save-preparation` | `check_save_preparation_uses_change_validation` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 180 | 実prepare_editとpublication、Import/EditのRetentionInDays型不正拒否・既存別Resourceの不正リンク/型付き参照/metadata非阻害・Full呼出0 | Synthetic Models |
| `change-residual::same-resource` | `check_same_resource_old_metadata_does_not_block_property` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | 同一Resource内の未変更metadata不正と変更Propertyの分離 | Synthetic Models |
| `change-residual::incoming-save` | `check_save_preparation_rejects_incoming_reference_break` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | missing/stale indexから保存準備で既存Consumer破壊を拒否 | Synthetic Models |
| `change-residual::final-candidate` | `check_real_final_candidate_guard_never_calls_full` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | 実Git baselineで通常更新とImportの最終候補共通検証、不正変更拒否、Full呼出0 | Synthetic Models |
| `change-residual::occurrence-shape` | `check_shape_only_change_is_validated` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | valueShapeのみの変更をChange Planが選択し、共通literal検証へ接続。旧enum/階層条件はmodel-literal-values UTへ移管 | Synthetic Models |
| `change-residual::issue-full` | `check_issue_scan_explicitly_keeps_full` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | Issue ScanでFull Validationを呼び既存エラーを検出 | Synthetic Models |
| `change-residual::acquired-invalid` | `check_import_rejects_acquired_schema_violation_before_save` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py) | pytest / 1 | 取得・Reviewを通過する不正RetentionInDays列挙値も共通Change Validationで実保存前に拒否、Model/Receipt不変、Full呼出0 | Offline acquired fixture |
| `change-residual::import-index` | `check_import_refreshes_reference_metadata_without_full` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py) | pytest / 2 | 実Importでmissing/stale indexのmetadataを取得し正常保存、別targetの品質検証なし、Full呼出0 | Offline acquired fixture |

## Framework validation / Export throttling regressions

| Case | Function | Layer | Location | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `validation-result::lookup` | `check_result_lookup_is_candidate_and_scope_specific` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 1 | 未登録参照は無変更、scope/candidate分離、result生成動作維持 | Synthetic Findings |
| `validation-result::iac-stacks` | `check_iac_stack_lookup_and_file_fallback` | UT | [units/validation-diagnostics-unit.checks.py](units/validation-diagnostics-unit.checks.py) | pytest / 8 | IaCのみのStack参照でPASS維持、保存設計fallback、必要なNOT_RUN/FAILと入力不正FAILを保持 | Synthetic IaC/design |
| `exports-retry::continuation` | `check_export_throttling_retries_only_failed_page` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 4 | 明示4コードのみ同一NextToken/引数で再試行、成功ページ重複なし | Mock request/clock |
| `exports-retry::attempt-limit` | `check_export_throttling_attempt_limit` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 1 | 失敗ページ最大5request、指数バックオフ1/2/4/8秒、部分結果非返却 | Mock request/clock |
| `exports-retry::deadline` | `check_export_retry_shares_deadline` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 3 | 全ページ/試行共通60秒、待機前/再試行前/次ページの期限確認 | Mock request/clock |
| `exports-retry::non-throttling` | `check_export_non_throttling_is_not_retried` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 3 | AccessDenied/ValidationError/InvalidContinuationToken非再試行 | Mock AWS errors |
| `exports-retry::invalid-page` | `check_export_retry_retains_page_validation` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 4 | 再試行後も重複/数値/空Tokenと不正ページを拒否 | Mock pages |
| `exports-retry::operation-boundary` | `check_other_operations_do_not_retry_throttling` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 4 | list_importsと更新create/execute/delete非再試行 | Mock request |

## IMPORT共通Change Validation

| Case | Function | Layer | Location | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `change-save::prepare` | `check_prepare_save_change_validation` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 24 | 実prepare_editでIMPORT/EDIT共通検証、Name/PENDING_DEPLOY・PLAINTEXTリンク・依存Type変更・JSON参照・Modelツリー外リンク・不在Producerを拒否して旧bytes維持。正常更新・環境変数PENDING_DEPLOY・未変更既存ERROR/参照・コメント・Warning保持と保存、Full呼出禁止 | Synthetic Models / exact IMPORT read scope |
| `change-save::resource-contracts` | `check_prepare_save_resource_contracts` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 4 | IMPORT/EDITの正常Resource追加を保存、Producer削除で既存Consumerの参照契約を壊す変更を保存前に拒否。IMPORTのConsumer依存読取は権限を拡大せず共通差分抽出を使用 | Synthetic producer/consumer Models |
| `change-save::column-arrays` | `check_changed_column_array` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 3 | leaf/projectionのChange/Full入口が同じ共通検証へ接続。boolean/enum/深い階層の条件はmodel-literal-values UTへ移管 | Synthetic CloudTrail rows |


## Deploy CLI guidance and reading authority

共通Rules読取・案内は専用UTが所有する。呼出元UTは出力接続と既存終了コードのみ確認する。

| Case | Callable | Layer | Entrypoint | Runner / count | Contract | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-readings::snapshot` | `check_prompt_independent_snapshot_and_registration` | UT | [units/deploy-required-readings.checks.py](units/deploy-required-readings.checks.py) | pytest / 1 | Prompt変更/削除非依存、7本文/hash、登録再検証 | Added |
| `deploy-readings::missing-section` | `check_missing_rule_section_stops` | UT | [units/deploy-required-readings.checks.py](units/deploy-required-readings.checks.py) | pytest / 1 | 不明Rule節で停止 | Added |
| `deploy-readings::parser` | `check_rule_section_boundaries` | UT | [units/deploy-required-readings.checks.py](units/deploy-required-readings.checks.py) | pytest / 1 | 共通Markdown境界・重複検出をPreparation UTから移管 | Moved |
| `deploy-guidance::routes` | `check_controller_routes` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 12 | 完了/group/復旧/承認/認証/依存/作成/実行/Observed/生成/不明 | Added |
| `deploy-guidance::repair` | `check_repair_candidate_requires_structured_cause_and_authority` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 10 | 署名証拠の存在だけで修復案内しない | Added |
| `deploy-guidance::uncertain` | `check_unknown_execution_only_proposes_original_recovery` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 2 | 元操作Recoveryのみ、実Task/Target/Stack/Profileとshell quoting | Added |
| `deploy-guidance::exception` | `check_exception_routes_do_not_echo_secrets` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 7 | 段階/入力変更/秘密非出力/停止 | Added |
| `deploy-guidance::known-errors` | `check_known_error_details` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 5 | 型付き不足条件・Model対象・JSON位置・認証コードと秘密非出力 | Added |
| `deploy-guidance::diagnostic-filter` | `check_reference_diagnostics_filter_values` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | 診断のコード・対象・属性のみ採用し値・本文・不正pathは除外 | Added |
| `deploy-guidance::dependency-json` | `check_preparation_dependency_json` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | 実Preparation例外から依存不足をJSONへ伝播 | Added |
| `deploy-guidance::unknown-stop` | `check_unknown_error_fields_and_environment_fail_closed` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | 未知エラーと環境不明時はcommand=null | Added |
| `deploy-guidance::wrapper-environment` | `check_worktree_commands_reproduce_wrapper_environment` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py) | pytest / 1 | Controller・Recovery・Handoffをwrapper経由、cwd・PATH・Task・空白引数を再現 | Added |
| `deploy-guidance::wrapper-stop` | `check_worktree_command_unknown_environment` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py) | pytest / 5 | Python・PATH・PYTHONPATH・setup・依存不一致でcommand=null | Added |
| `deploy-guidance::pending` | `check_pending_failure_uses_type_not_prose` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | 曖昧文字列から操作を推測しない | Added |
| `deploy-guidance::help` | `check_cli_help_and_example_options` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 4 | 4 CLI Help実行と実在option | Added |
| `deploy-guidance::preparation-output` | `check_preparation_success_output` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 4 | 既存Preparation JSONと次操作 | Added |
| `deploy-guidance::exit-codes` | `check_preparation_and_handoff_keep_failure_exit_codes` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | Preparation=1/Handoff=2維持 | Added |
| `deploy-guidance::recovery-output` | `check_recovery_exit_reports_no_new_deploy` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 2 | 復旧だけの成功/停止と既存終了コード | Added |
| `deploy-guidance::controller-output` | `check_controller_final_json_keeps_state_and_exit_code` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 4 | state/metrics/repairFailure/終了コードとObserved/生成原因 | Added |
| `deploy-guidance::single-json` | `check_handled_controller_stop_prints_one_json` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | 外側例外処理がJSONを重複出力しない | Added |
| `deploy-guidance::structured-cause` | `check_structured_reference_cause_and_handoff_command` | UT | [units/deploy-cli-guidance.checks.py](units/deploy-cli-guidance.checks.py) | pytest / 1 | Reference分類と実親Task suspendコマンド | Added |

## v1026v12 Reference impact and dependency metadata reuse

| Case | Function | Layer | Location | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `change-impact::unrelated-reference` | `check_unrelated_reference_does_not_block_change` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 24 | 同一/別環境、missing/current/stale indexの既存Modelツリー外・無関係anchor・不正modelRef非阻害、Full品質検出は維持 | Synthetic Models |
| `change-impact::cross-environment` | `check_cross_environment_contract_is_selected` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 6 | 正当な環境間MarkdownのConsumer集合・変更契約を検証、Producer削除はERROR | Synthetic Models |
| `change-impact::revision-selection` | `check_index_revision_and_consumer_selection` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 3 | 5サービスのcurrent/stale/missing比較、必要Consumer集合・読込回数・診断再利用・Arn破壊停止・永続書込0 | Synthetic Models |
| `change-impact::snapshot-reuse` | `check_reference_metadata_reuses_immutable_snapshot` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | 同一Snapshot解析1回、新Snapshotは再解析 | Immutable synthetic snapshots |
| `change-impact::sealed-diagnostics` | `check_index_corruption_and_related_model` | UT | [units/deploy-lazy-inputs.checks.py](units/deploy-lazy-inputs.checks.py) | pytest / 16 | 署名・構造・membership・owner・診断の改変と旧schemaを拒否、Snapshot先読込/後読込の両方を検証 | Offline Deploy fixtures |

## Change Validation reference metadata isolation

| Case | Function | Layer | Location | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `reference-metadata::recovery` | `check_recovery_retains_every_candidate` | UT | [units/reference-metadata-unit.checks.py](units/reference-metadata-unit.checks.py) | pytest / 1 | Broken syntax, duplicate values, multiline typed references and partial diagnostics remain discoverable | Synthetic raw Models |
| `reference-metadata::partial-target` | `check_partial_target_filter` | UT | [units/reference-metadata-unit.checks.py](units/reference-metadata-unit.checks.py) | pytest / 7 | Shared conservative scope/logicalId filtering and impossible outside-tree links | Synthetic scopes |
| `reference-metadata::unknown-json` | `check_unreadable_json_is_not_an_empty_edge` | UT | [units/reference-metadata-unit.checks.py](units/reference-metadata-unit.checks.py) | pytest / 3 | Invalid/escaped JSON cannot silently erase candidate references | Synthetic scalar inputs |
| `reference-metadata::missing-part` | `check_missing_part_keeps_unknown_references` | UT | [units/reference-metadata-unit.checks.py](units/reference-metadata-unit.checks.py) | pytest / 1 | Missing part retains unknown cross-scope candidates | Synthetic raw Model index |
| `reference-metadata::index-shape` | `check_index_rejects_unproven_metadata` | UT | [units/reference-metadata-unit.checks.py](units/reference-metadata-unit.checks.py) | pytest / 2 | Deploy rejects old/unproven metadata; Change discovery refreshes it | Synthetic sealed index |
| `reference-metadata::save` | `check_broken_unrelated_model_save` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 18 | Real prepare_edit/publication permits unrelated broken syntax/outside links/partial links for missing/current/stale/old indexes; old-index rollback preserves sources | Synthetic Models and save authority |
| `reference-metadata::broken-consumer` | `check_broken_syntax_keeps_valid_incoming_reference` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | Broken syntax does not hide valid incoming contracts or type violations | Synthetic typed consumer |
| `reference-metadata::outside-quality` | `check_outside_link_still_fails_quality` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | Change rejects new invalid links and Full still detects existing invalid links | Synthetic Models |

## Comparison execution input reuse

These UTs exercise cache units and execution boundaries; existing generation/import ITs retain publication and integrated reference scenarios.

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `comparison-reuse::one_parse_for_raw_checked_and_layout` | `check_one_parse_for_raw_checked_and_layout` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 2 | one parse for raw checked and layout | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::reader_candidate_root_and_next_execution` | `check_reader_candidate_root_and_next_execution` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | reader candidate root and next execution | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::permission_checked_before_cached_source` | `check_permission_checked_before_cached_source` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | permission checked before cached source | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::index_checked_once_per_root_permission_and_execution` | `check_index_checked_once_per_root_permission_and_execution` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | index checked once per root permission and execution | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::worker_forks_share_snapshots_and_keep_private_tables` | `check_worker_forks_share_snapshots_and_keep_private_tables` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | worker forks share snapshots and keep private tables | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::stage_and_original_snapshots_remain_separate` | `check_stage_and_original_snapshots_remain_separate` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | stage and original snapshots remain separate | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::comparison_keeps_saved_bytes_and_still_reports_difference` | `check_comparison_keeps_saved_bytes_and_still_reports_difference` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | comparison keeps saved bytes and still reports difference | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::policy_batch_evaluates_documents_once` | `check_policy_batch_evaluates_documents_once` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | policy batch evaluates documents once | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::independent_comparison_scope_cleanup` | `check_independent_comparison_scope_cleanup` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 2 | independent comparison scope cleanup | Synthetic fixed bytes and Model snapshots |
| `comparison-reuse::update_reads_are_live_inside_input_context` | `check_update_reads_are_live_inside_input_context` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | 同一input_context内の作成・更新・削除をexists/parts/raw/checked読込に反映 | 通常更新の回帰 |
| `comparison-reuse::index_rebuild_is_live_inside_input_context` | `check_index_rebuild_is_live_inside_input_context` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | rebuild後のrevision・logicalIdとpublication読込 | 通常更新の回帰 |
| `comparison-reuse::explicit_read_context_keeps_its_snapshot` | `check_explicit_read_context_keeps_its_snapshot` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 2 | 明示FileReads/CandidateReadsの固定入力契約を保持 | 正本・候補の分離 |
| `comparison-reuse::cold_workers_share_one_read_parse_and_index` | `check_cold_workers_share_one_read_parse_and_index` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 2 | 未読Producerへ4worker同時参照、bytes/parse/index各1回、外部変更無視と次実行再取得 | recorder有無・可変Model表の分離 |
| `comparison-reuse::workers_share_inventory_and_retain_diagnostics` | `check_workers_share_inventory_and_retain_diagnostics` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | 未解析参照索引をworker間で1回構築し、個別metadataに診断を保持 | 診断省略なし |
| `comparison-reuse::inventory_distinguishes_changed_sets_and_candidates` | `check_inventory_distinguishes_changed_sets_and_candidates` | UT | [units/comparison-reuse-unit.checks.py](units/comparison-reuse-unit.checks.py) | pytest / 1 | 同一rootでも変更集合・Candidateの異なる索引を混在させない | 共通キャッシュ境界 |

## v1026v13 Export scope and dependency hint propagation

| Case | Function | Layer | Location | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `export-scope::saved-conflicts` | `check_controller_scopes_saved_hint_conflicts` | UT | [units/cloudformation-export-resolution.checks.py](units/cloudformation-export-resolution.checks.py) | pytest / 6 | Importなし・無関係ExportのProducer/Value矛盾は非阻害、必要Exportの矛盾はBLOCKED、ImportなしのExport APIは0回 | Synthetic offline |
| `export-scope::controller-proof` | `test_controller_passes_current_import_proof_to_independence` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 4 | delivery・Producer outputs・未完了Operationの既知ProducerはListExports 0回、未知だけ1回、同一境界Describe共有・次境界Value変更BLOCKED・無効Import除外 | Synthetic offline |
| `export-scope::hint-conflicts` | `test_planned_hints_cannot_override_unfinished_operation_evidence` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 2 | 今回予定Importと未完了OperationのProducer/Value矛盾はAWS読取前にBLOCKED | Synthetic offline |
| `export-scope::retained-proof` | `test_no_planned_imports_keep_unfinished_operation_export_proof` | UT | [units/deploy-operation-journal-unit.checks.py](units/deploy-operation-journal-unit.checks.py) | pytest / 1 | 今回Importなしでも未完了Operationの保存済みValueとAWS実値を比較してBLOCKED | Synthetic offline |

## Explicit Model literal shapes

配列形式の条件組合せは共通UTに集約する。呼出し元UTは保存・取得・Review・比較・変更選択への接続を検証する。ITの入力条件・ケース数は増やさず、既存の取得候補fixtureが取得レコードのvalueShapeを引き継ぐ。

| Case ID | Function | Level | Entrypoint | Mode / count | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `literal-shapes::normalize` | `test_normalize` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 9 | 親選択階層だけ展開し、配列leaf・空の親・末端選択・順序を保持 | Native values |
| `literal-shapes::hierarchy` | `test_invalid_hierarchy` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 5 | 不正親階層・形式・配列のないprojectionを拒否 | Native values |
| `literal-shapes::actions` | `test_actions` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 11 | leaf/projection成功、配列型・要素型・空・31件・余分/不足階層を拒否 | Pinned provider schema |
| `literal-shapes::deep-terminal` | `test_deep_projection_and_terminal_selection` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | 2階層と末端[]の意味を区別 | Pinned provider schema |
| `literal-shapes::columns` | `test_column_constraints` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 9 | Change UTからboolean/enum/階層の重複条件を移管 | Pinned provider schema |
| `literal-shapes::empty` | `test_empty_parent_uses_its_schema` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | 空leafと空親の異なるschema制約、件数、不正な末端パス | Synthetic schema |
| `literal-shapes::terminal` | `test_terminal_projection_constraints` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 10 | 既存比較UTから末端配列のJSON・要素型の重複条件を移管 | Pinned provider schema |
| `literal-shapes::items` | `test_provider_items` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 7 | 要素型/enum/pattern/数値/union/object/入れ子、$ref、minItems/maxItems | Synthetic schema |
| `literal-shapes::dynamic` | `test_dynamic_reference_in_array` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | 配列要素でもdynamic referenceの既存検証を維持 | Synthetic schema |
| `literal-shapes::decode` | `test_decoding_is_explicit` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | 文字列の見た目で形式を推測しない | Explicit row metadata |
| `literal-shapes::property` | `test_property_projection_retains_array_leaf_and_rejects_ambiguous_groups` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | 取得形式への比較投影、親子所属の推測を拒否 | Explicit rows |
| `literal-shapes::tree` | `test_projection_tree_retains_membership` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | SDK選択結果の階層を再構築、列の長さ不一致を拒否 | Native projection |
| `literal-shapes::conflicts` | `test_projection_row_conflicts` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 22 | 独立sibling・数値indexを区別し、共有配列の混在・重複projection・祖先構造衝突だけを拒否。両順序で衝突Propertyを特定 | Explicit rows |
| `literal-shapes::sibling-tree` | `test_projection_siblings_reconstruct` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 3 | VpcConfig siblingとCloudTrail多階層projectionを既存put_row/projectで再構築し、所属・配列順序を保持 | Native values |
| `literal-shapes::sibling-iac` | `test_projection_sibling_comparison` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 6 | validated_rowsとIaC比較への接続、衝突Subnetsだけを除外しVpcIdを保持。親/子Property選択にも診断が伝播 | Synthetic template |
| `literal-shapes::sibling-aws` | `check_projection_sibling_comparison` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py) | pytest / 2 | 同じVpcConfig ModelがAWS値に一致し、衝突時もVpcIdをdesign_unresolvedにしない | Offline acquired value |
| `literal-shapes::roundtrip` | `check_shape_round_trip_and_display` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 保存/再読込/runtimeで形式情報保持、表示列へ非出力 | Synthetic Model |
| `literal-shapes::import` | `check_import_array_leaf_comparison` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 2 | leaf/projection候補を取得値と比較 | Synthetic acquisition |
| `literal-shapes::invalid-metadata` | `check_invalid_shape_is_rejected` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | readerが未知valueShapeを拒否 | Synthetic Model |
| `literal-shapes::aws` | `check_explicit_array_shape_comparison` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py) | pytest / 2 | 共通parseと実比較処理でleaf/projectionが同じAWS投影に一致 | Offline acquired value |
| `literal-shapes::iac` | `test_parent_projection_comparison` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 2 | 1/2階層の投影をIaCとの共通比較で保持 | Synthetic template |
| `literal-shapes::terminal-caller` | `test_terminal_string_array_comparison` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | leaf/projection成功・差分・共通検証エラーの伝播 | Synthetic template |

| `indexed-properties::leaf` | `test_indexed_leaf_definition` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 3 | Indexed schema validation | Provider schemas |
| `indexed-properties::paths` | `test_definition_path_and_parents` | UT | [units/model-literal-values-unit.checks.py](units/model-literal-values-unit.checks.py) | pytest / 1 | Definition paths and invalid indexes | Provider schemas |
| `indexed-properties::mapping` | `check_indexed_mapping` | UT | [units/aws_mapping_display-unit.checks.py](units/aws_mapping_display-unit.checks.py) | pytest / 1 | Mapping lookup and indexed display | Mappings |
| `indexed-properties::validation` | `check_indexed_full_and_change_validation` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 2 | Full and Change schema checks | Synthetic Model |
| `indexed-properties::required` | `check_indexed_required_ancestors` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | Required ancestors and scoped changes | Synthetic Model |
| `indexed-properties::display` | `check_indexed_display` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py) | pytest / 1 | Preserve positions in display rows | Synthetic rows |

## Model authority and AWS JSON projection

Existing reference value/node/classification cases retain logical Model authority and Markdown
links while JSON Views expand confirmed values, project Pending to PENDING_DEPLOY and retain
unresolved declarations. Normal and strict View generation both preserve warnings and PASS
for reference waits; invalid references still fail only their service. Mixed/encoded values,
repeated generation and saved-artifact equality remain in those UTs. The existing 3-case
transaction IT verifies Stage/Publish and Markdown/JSON write rollback in pending and resolved
states. AWS execution input checks remain independent of JSON Views.

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `json-format::model-nodes` | `check_aws_boundary_rejects_model_nodes` | UT | [units/json-format.checks.py](units/json-format.checks.py) | pytest / 4 | Internal nodes and encoded JSON rejected in standalone and CFn contexts; CFn expressions retain their context | Synthetic JSON |
| `cloudformation-inputs::design-nodes` | `check_deploy_input_rejects_design_nodes` | UT | [units/cloudformation-inputs-unit.checks.py](units/cloudformation-inputs-unit.checks.py) | pytest / 6 | Strict/permissive decoded Templates, encoded JSON and Parameters reject design references before submission | Synthetic files |

| `design-json::conflicting-documents` | `test_conflicting_design_documents_fail_before_saving` | UT | [units/model-reference-classification-unit.checks.py](units/model-reference-classification-unit.checks.py) | pytest / 2 | Two Model documents claiming one artifact fail before save in both common generation paths; saved files/authority unchanged | Synthetic CREATE/IMPORT |
| `generated-json::nested` | `test_artifact_nested_and_encoded_references` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 2 | Normal/strict Artifact generation resolves Object/Array/encoded references without changing Model | Synthetic Models |
| `generated-json::pending-literal` | `test_artifact_literal_pending_is_view_warning` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 3 | Scalar/nested/encoded PENDING_DEPLOY generates a JSON View and retains its warning | Synthetic JSON |
| `generated-json::independent-save` | `check_pending_artifact_does_not_gate_model_save` | UT | [units/change-validation-unit.checks.py](units/change-validation-unit.checks.py) | pytest / 1 | Real prepare/publish saves Model with pending reference before and after JSON View projection; generated files remain unsaved | Authorized synthetic Model edit |

## Resource表示名のProjectionフォールバック

単独の無名Resourceは共通のType名表示を優先し、一覧・詳細・参照のAnchorを保持する。未確定Nameだけのfallbackは既存 `model-generation-validation-unit::test_unconfirmed_names_keep_anchor_and_model`、GROUPED・Policy・配列表示は既存 `model-reference-display-unit` / `model_design-unit` のケースを再利用し重複追加しない。

| Origin | Case | Level | Entry | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `projection-name::nameless` | `check_nameless_projection_display` | UT | [units/model-reference-display-unit.checks.py](units/model-reference-display-unit.checks.py) | pytest / 12 | GuardDuty.Detector/KMS.Key/SecurityHub.Hub/Macie.Session/EC2.EIP/SQS.QueuePolicy × CREATE/IMPORTのModelから一覧・詳細・hidden ID・Anchorを実生成。明示ラベル優先と同一Type複数件のlogicalId fallback | Synthetic Models |
| `projection-name::label` | `check_named_projection_fallback` | UT | [units/model-reference-display-unit.checks.py](units/model-reference-display-unit.checks.py) | pytest / 3 | 確定Nameがlabelに優先、未確定Nameの有効label保持、未確定labelとNameでlogicalId fallback、Model不変 | Synthetic SQS |
| `projection-name::reference` | `check_nameless_projection_reference` | UT | [units/model-reference-display-unit.checks.py](units/model-reference-display-unit.checks.py) | pytest / 4 | KMS→IAMの一覧・詳細・Policy内参照label一致、保存Anchor解決とMarkdown参照テーブル復元、PENDING_DEPLOY時の$modelRef宣言保持 | Synthetic KMS/IAM |
| `issues-iac::policy-integrity-selection` | `BooleanValueTests.test_policy_integrity_selection_scope` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | Role/User properties範囲、Full Scan、範囲外Ref非評価 | 合成Model/IaC |
| `issues-iac::duplicate-policy-cause` | `BooleanValueTests.test_duplicate_policy_issue_cause_and_evidence` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 重複名のみのIssue統合、独立差分と全証跡・分類保持 | 合成Model/IaC |

## PENDING_DEPLOY JSON Views

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `generated-json::vpc-view` | `test_vpc_json_view_and_saved_policy` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 3 | VpcId pending/resolved/unresolved, mixed confirmed reference, nested/encoded arrays, saved-policy equality and real mismatch, unchanged authority | Synthetic Models |
| `generated-json::pending-composite` | `test_pending_composite_view_is_not_a_physical_identifier` | UT | [units/model-reference-values-unit.checks.py](units/model-reference-values-unit.checks.py) | pytest / 4 | Join/Sub/nested Join/Select with Pending never assemble a false identifier, including encoded JSON | Synthetic JSON |

## IaC reference difference display

| Case ID | Function | Layer | File | Mode / count | Coverage | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `iac-reference-display::pipeline` | `test_iac_reference_display_pipeline_preserves_comparison_and_issues` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 3 | KeyIdとAliasNameの分離、記録Observed/未記録/pending、dataset/summary/detail伝搬、判定・分類・ID・原因・件数不変 | Added |
| `iac-reference-display::expressions` | `test_iac_reference_display_local_expression_and_cache` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 5 | 直接/ネスト/Sub/Join/SplitSelect、明示値の取得元、重複参照を1回解決、元値不変 | Added |
| `iac-reference-display::masking` | `test_iac_reference_display_retains_masks` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 5 | secret Property/環境変数/参照先、sensitive parameter、Expression内部のマスクをdetailまで保持 | Added |
| `iac-reference-display::failures` | `test_iac_reference_display_expected_failures_only` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | Producer/比較context欠落・Blockedを未解決表示、失敗キャッシュ、予期しないバグを伝播 | Added |
| `iac-reference-display::ordinary` | `test_iac_reference_display_preserves_nonreferences_and_missing` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 4 | 非参照値、参照を持たないExpression、MISSING表示を維持し解決を呼ばない | Added |
| `iac-reference-display::runner` | `test_iac_reference_display_runner_decisions_unchanged` | UT | [units/reference-evidence-unit.checks.py](units/reference-evidence-unit.checks.py) | pytest / 3 | runnerから差分だけを解決、matched/difference/uncomparedのレコード完全一致 | Added |

## Model Validation の責務分割

`model/validations/` の Full／Change 接続と各検証責務を確認する。
`check_service_scoped_naming`、`check_naming_target_paths`、`check_naming_coverage`、
`check_naming_edges` の８ケースと補助関数は `model_design-unit` から
`model-validations-unit` へ移管し、旧配置の重複を削除した。既存の命名仕様は変更しない。

| Module | 主な既存UTと専用の接続確認 |
| --- | --- |
| `full_inputs` | `model-input-selection-unit`、`deploy-lazy-inputs`：実行順序・診断集約・セッションキャッシュ |
| `change_inputs` | `change-validation-unit`：変更範囲・新規CREATE・保存時のFull非実行 |
| `structure` | `model-validations-unit::check_structure_order_and_short_circuit`：キー→Rowの順序と失敗時停止 |
| `naming` | 移管した８ケース、`resource_mode-unit`：対象パス・サービス限定読取・CREATE／IMPORT条件 |
| `schema` | `change-validation-unit`、`model-validations-unit::check_ordered_schema_diagnostic_contract`：必須属性・API・Literal・診断内容 |
| `json_settings` | `json-resource-arn-unit`、`model-validations-unit::check_json_adapter_order_and_reference_authority`：環境値→JSONの順序・文脈引渡し |
| `environment` | `environment_values-unit`：環境値・PENDING_DEPLOYの既存条件 |
| `references` | `model-reference-classification-unit`、`model-validations-unit::check_reference_adapter_preserves_context_and_warnings`：正本diagnoseの文脈・診断 |
| `policies` | `kms-validation-reuse-unit`、`model_design-unit::check_kms_policy_accounts`：成功結果再利用・失敗の再検査・既存例外 |
| `identity` | `model-identity`、`model_design-unit::check_cfn_identity_inputs`：Resource／CFn Identity・配置先 |
| `stacks` | `change-validation-unit`：変更Stack項目と一意性 |
| `presentation` | `model_design-unit`、`model-validations-unit::check_presentation_adapter_uses_canonical_scope`：表示検証・Model／ViewのScope |

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `model-validations::structure-imports` | `check_module_structure_and_imports` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 12 | 各モジュールの独立import・型注釈・docstring・関数内import／ネスト関数の禁止 | 合成入力・静的Framework |
| `model-validations::shared-rules` | `check_full_and_change_share_rules` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 6 | Full／Changeが同じ正本の関数を利用 | 関数同一性 |
| `model-validations::structure` | `check_structure_order_and_short_circuit` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 2 | キー→Row構造・失敗時停止 | Mock境界 |
| `model-validations::references` | `check_reference_adapter_preserves_context_and_warnings` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 1 | 正本diagnoseへのScope・入力・警告の接続 | 合成入力・Mock境界 |
| `model-validations::presentation` | `check_presentation_adapter_uses_canonical_scope` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 2 | Model／View入力から正しい表示Scopeとアンカーへ接続 | 合成入力・Mock境界 |
| `model-validations::json` | `check_json_adapter_order_and_reference_authority` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 2 | 環境値→JSONの順序・除外参照・authority・失敗伝播 | 合成入力・Mock境界 |
| `model-validations::diagnostic` | `check_ordered_schema_diagnostic_contract` | UT | [units/model-validations-unit.checks.py](units/model-validations-unit.checks.py) | pytest / 2 | Full／Changeの既存診断コード・check ID・件数・内容と保存境界 | 合成Model・既存schema |

## Issues Review progress

Progress mechanics reuse existing Naming/Human/diagnostic validators; business IT uses only synthetic temporary Scan artifacts and reports.

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `issues-review-progress::inventory_context_order_and_fetch_is_not_review` | `check_inventory_context_order_and_fetch_is_not_review` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | inventory context order and fetch is not review | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::batch_size_bytes_and_oversize_item` | `check_batch_size_bytes_and_oversize_item` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | batch size bytes and oversize item | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::invalid_batch_is_atomic_and_retryable` | `check_invalid_batch_is_atomic_and_retryable` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 11 | invalid batch is atomic and retryable | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::reordered_batch_results_and_human_context_references` | `check_reordered_batch_results_and_human_context_references` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | reordered batch results and human context references | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::invalid_shared_validation_never_advances_results` | `check_invalid_shared_validation_never_advances_results` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | invalid shared validation never advances results | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::retry_idempotence_overwrite_and_stale_batch` | `check_retry_idempotence_overwrite_and_stale_batch` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | retry idempotence overwrite and stale batch | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::scan_identity_mismatch_preserves_checkpoint` | `check_scan_identity_mismatch_preserves_checkpoint` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 4 | scan identity mismatch preserves checkpoint | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::checkpoint_corruption_rejected` | `check_checkpoint_corruption_rejected` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 8 | checkpoint corruption rejected | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::atomic_replace_failure_retains_valid_checkpoint` | `check_atomic_replace_failure_retains_valid_checkpoint` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | atomic replace failure retains valid checkpoint | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::owner_decision_dependency_and_existing_export` | `check_owner_decision_dependency_and_existing_export` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | owner decision dependency and existing export | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::unresolved_owner_creates_no_decision` | `check_unresolved_owner_creates_no_decision` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | unresolved owner creates no decision | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::incomplete_export_rejected_and_final_validation_used` | `check_incomplete_export_rejected_and_final_validation_used` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | incomplete export rejected and final validation used | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::duplicate_inventory_rejected` | `check_duplicate_inventory_rejected` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 4 | duplicate inventory rejected | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::cli_commands_external_paths_and_byte_limit` | `check_cli_commands_external_paths_and_byte_limit` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | cli commands external paths and byte limit | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::process_lock_serializes_checkpoint_updates` | `check_process_lock_serializes_checkpoint_updates` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 1 | process lock serializes checkpoint updates | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::scan_review_export_save_and_local_loop` | `check_scan_review_export_save_and_local_loop` | IT | [integrations/issues-review-progress.checks.py](integrations/issues-review-progress.checks.py) | pytest / 1 | scan review export save and local loop | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::process_exit_resume_from_checkpoint_and_save` | `check_process_exit_resume_from_checkpoint_and_save` | IT | [integrations/issues-review-progress.checks.py](integrations/issues-review-progress.checks.py) | pytest / 1 | process exit resume from checkpoint and save | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::large_review_complete_id_coverage_and_equivalent_reports` | `check_large_review_complete_id_coverage_and_equivalent_reports` | IT | [integrations/issues-review-progress.checks.py](integrations/issues-review-progress.checks.py) | pytest / 1 | large review complete id coverage and equivalent reports | Synthetic Scan / external checkpoint / existing Save |
| `issues-review-progress::invalid_scan_reports_explicit_error` | `check_invalid_scan_reports_explicit_error` | UT | [units/issues-review-progress-unit.checks.py](units/issues-review-progress-unit.checks.py) | pytest / 4 | malformed/non-object Scan fails explicitly | Synthetic external Scan |

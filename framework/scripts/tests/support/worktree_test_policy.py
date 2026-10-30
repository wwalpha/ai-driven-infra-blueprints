"""Responsibility registry and recurrence checks for test-only Worktree dependencies."""

import ast
import re
from contextlib import contextmanager
from pathlib import Path

# Reviewed Worktree responsibilities, not a filename convention. Exact cases are checked.
WORKTREE_CASES = {
    "units/deploy-worktree-unit.checks.py": (
        "check_snapshot_ignores_base_history",
        "check_unmanaged_mutation_is_rejected",
        "check_managed_task_authority",
        "check_mutation_rechecks_live_authority",
        "check_git_failure_preserves_stack_success",
        "check_resume_adopts_only_unchanged_successes",
        "check_completion_keeps_states_separate",
        "check_publication_requires_exact_saved_checkpoint",
        "check_final_completion_rechecks_saved_checkpoint_evidence",
        "check_stepwise_without_receipt_never_creates_checkpoint",
        "check_publication_guidance_only_offers_proven_git_retry",
        "check_claim_input_hash_still_blocks",
        "check_conflict_records_model_values",
        "check_startup_needs_only_standard_library",
        "check_progress_preserves_success_and_omits_unowned_fields",
        "check_progress_ignores_legacy_files_without_key",
        "check_reuse_keeps_exact_identity",
        "check_other_engine_retains_its_completion",
        "check_unfinished_progress_requires_original_journal",
    ),
    "integrations/deploy-worktree.checks.py": (
        "check_current_request_is_shared_without_history_or_duplicate_execute",
        "check_start_creates_and_reuses_official_worktree",
        "check_git_conflict_checkpoints_peers_and_recovers",
        "check_failed_snapshot_with_unstarted_stack_publishes",
        "check_controller_keeps_aws_success_after_rewrite_and_conflict",
        "check_interrupted_publication_retries_and_cleans",
        "check_stepwise_checkpoint_publication_isolation",
        "check_stepwise_final_contract_checkpoint",
        "check_task_completion_rechecks_checkpoint_receipts",
        "check_stepwise_success_while_peer_running",
    ),
    "units/worktree-guard-unit.checks.py": (
        "check_registered_guard_process",
        "check_prepare_rejects_before_git_write",
        "check_cli_failure_diagnostics",
        "check_cleanup_missing_worktree",
        "check_cleanup_stops_before_removal",
        "check_cleanup_preflight_diagnostics",
        "check_idle_git_paths_and_state",
        "check_repin_rejects_before_state_write",
        "check_integration_status",
        "check_finalize_requires_setup",
        "check_base_selection",
        "check_lifecycle_layout",
        "check_metadata_symlinks",
        "check_checkpoint_observed_barrier",
        "check_checkpoint_uses_scoped_barrier_under_ordered_locks",
    ),
    "units/worktree_python-unit.checks.py": (
        "check_worktree_commands_reproduce_wrapper_environment",
        "check_worktree_command_unknown_environment",
        "check_environment",
        "check_pdf_native_optional",
        "check_windows_exit_propagation",
        "check_output_decoding",
        "check_wrapper_launcher",
        "check_runtime_registration",
        "check_setup_failure_recovery",
        "check_setup_lock_timeout",
        "check_shared_symlinks",
        "check_shared_completion",
        "check_dependency_sync",
        "check_added_dependency",
        "check_worktree_requirement_conflict",
        "check_sync_failure_retry",
        "check_parallel_dependency_sync",
        "check_requirement_metadata_probe",
        "check_runtime_dependency_sync",
        "check_changed_requirements_during_sync",
        "check_requirement_pins_reject_unsupported",
    ),
    "units/worktree-model-guard-unit.checks.py": (
        "check_ownership",
        "check_finalize_rejects_incomplete_leaves",
        "check_model_finalize_cannot_bypass_candidate",
        "check_git_baseline_fail_closed",
        "check_candidate_staleness",
        "check_final_candidate_scope",
        "check_integration_detects_undeclared_paths",
    ),
    "integrations/worktree_task.checks.py": (
        "check_implement_rewritten_base_and_real_conflict",
        "check_sync_base_preserves_candidate",
        "check_old_workflow_registry_is_ignored",
        "check_success_and_empty",
        "check_finalize_line_endings",
        "check_incomplete_and_git_safety",
        "check_dirty_base_and_retry",
        "check_ahead_and_rebase_conflict",
        "check_collisions_and_base_selection",
        "check_directory_layout",
        "check_metadata_storage",
        "check_cleanup_failure_and_retry",
        "check_merge_retry_and_commit_failure",
        "check_human_approved_validation_failure",
        "check_real_loop_integration",
        "check_final_candidate_staleness",
        "check_approved_model_reads",
        "check_registered_normal_model_guard",
        "check_model_operation_integration",
        "check_model_refactor_integration",
        "check_framework_final_candidate",
    ),
    "integrations/worktree_python.checks.py": (
        "check_setup",
        "check_venv_fallback",
        "check_parallel_fallback",
        "check_symlink_safety",
    ),
    "integrations/import-worktree-contract.checks.py": (
        "check_import_managed_contract_boundaries",
        "check_model_source_context_worktree_boundary",
    ),
    "integrations/worktree-deploy-repair.checks.py": (
        "check_external_implement_round_trip",
        "check_merge_recovery",
    ),
    "integrations/worktree-deploy-checkpoint.checks.py": (
        "check_parallel_checkpoint_and_restart",
        "check_checkpoint_rejects_foreign_changes_and_preserves_success",
        "check_model_publication_interruption",
        "check_generation_wait_and_resume",
        "check_zero_difference_checkpoint",
    ),
    "integrations/worktree-model-operation.checks.py": (
        "check_one_parent_merge_and_failed_candidate_repair",
    ),
}
WORKTREE_SUPPORT = frozenset(
    {
        "support.worktree_task_fixtures",
        "support.worktree_python_fixtures",
        "support.worktree_deploy_fixtures",
    }
)
_active = None


def worktree_suite(path, tests):
    relative = Path(path).resolve().relative_to(tests.resolve()).as_posix()
    expected = WORKTREE_CASES.get(relative)
    if expected is None:
        return False
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("check_")
    } == set(expected)


def violations(tests):
    modules = {
        ".".join(p.relative_to(tests).with_suffix("").parts): p
        for p in tests.rglob("*.py")
    }
    edges, forbidden, errors = {}, {}, []
    for module, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(tests).as_posix()
        if relative in WORKTREE_CASES:
            cases = {
                n.name
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name.startswith("check_")
            }
            if cases != set(WORKTREE_CASES[relative]):
                errors.append(
                    relative + ": unreviewed Worktree responsibility/case change"
                )
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
                imports.update(
                    (node.module + "." if node.module else "") + a.name
                    for a in node.names
                )
            elif isinstance(node, ast.Dict):
                keys = {key.value for key in node.keys if isinstance(key, ast.Constant)}
                if {"task_file", "worktree"} <= keys:
                    imports.add("worktree_lifecycle_fixture")
            elif isinstance(node, ast.Call):
                call = ast.unparse(node.func)
                # Include dynamic fixture loaders and Mock targets, including aliased patch objects.
                if any(
                    part in call
                    for part in (
                        "patch",
                        "setattr",
                        "import_module",
                        "spec_from_file_location",
                    )
                ):
                    values = " ".join(ast.unparse(arg) for arg in node.args)
                    if re.search(
                        r"worktree_(?:state|task|python|runtime)|support[./]worktree_",
                        values,
                    ):
                        imports.add("worktree_mock_or_loader")
        edges[module] = {name for name in imports if name in modules}
        forbidden[module] = {
            name
            for name in imports
            if name.startswith("worktree_") or name in WORKTREE_SUPPORT
        }
    for module, path in modules.items():
        relative = path.relative_to(tests).as_posix()
        if (
            relative in WORKTREE_CASES
            or module in WORKTREE_SUPPORT
            or relative in {"conftest.py", "support/worktree_test_policy.py"}
        ):
            continue
        pending, seen = [module], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            bad = forbidden[current] | (edges[current] & WORKTREE_SUPPORT)
            if bad:
                errors.append(
                    relative
                    + ": Worktree dependency through "
                    + current
                    + ": "
                    + ", ".join(sorted(bad))
                )
            pending.extend(edges[current] - seen)
    return sorted(set(errors))


def forbidden_process(command):
    if not isinstance(command, (list, tuple)):
        return bool(
            re.search(
                r"git\s+worktree\s+(?:add|remove|move|prune|repair|lock|unlock)|worktree_task\.py",
                str(command),
            )
        )
    words = [str(word) for word in command]
    if any(
        Path(word).name == "worktree_task.py"
        or re.search(
            r"(?:import|from) (?:support\.)?worktree_(?:task|state|python|runtime)",
            word,
        )
        for word in words
    ):
        return True
    if not words or Path(words[0]).stem != "git" or "worktree" not in words:
        return False
    return any(
        word in {"add", "remove", "move", "prune", "repair", "lock", "unlock"}
        for word in words[words.index("worktree") + 1 :]
    )


def audit(event, args):
    suite = _active
    if suite is None:
        return
    if event == "subprocess.Popen" and forbidden_process(args[1]):
        raise AssertionError(
            suite + ": non-Worktree test attempted lifecycle subprocess"
        )
    if event in {"open", "os.mkdir", "os.remove", "os.rename", "os.rmdir"}:
        values = args[:2] if event == "os.rename" else args[:1]
        writing = (
            event != "open"
            or (isinstance(args[1], str) and any(c in args[1] for c in "wax+"))
            or isinstance(args[2], int)
            and args[2] & 3
        )
        if writing and any(
            isinstance(value, (str, bytes))
            and ".worktrees"
            in Path(value.decode() if isinstance(value, bytes) else value).parts
            for value in values
        ):
            raise AssertionError(suite + ": non-Worktree test wrote lifecycle storage")


@contextmanager
def ordinary_suite(path, tests):
    global _active
    previous = _active
    _active = None if worktree_suite(path, tests) else str(path)
    try:
        yield
    finally:
        _active = previous

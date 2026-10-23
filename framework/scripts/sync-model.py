#!/usr/bin/env python3
"""Generate detailed-design Markdown from authoritative service properties."""

import argparse
import hashlib
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context, copy_context
from functools import partial as _bind_framework_callback
from pathlib import Path

import import_guard as _imports_import_guard
import issue_gate as _imports_issue_gate
import model.impact as _imports_model_impact
import model.importing.scope as _imports_model_importing_scope
from sync_progress import consumers, diagnostics, output_file, phase, reported_main
from sync_runtime import generation_context, run_generation, sync
from validation_scope import active_scope


class ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        super()._print_message(message, output_file(error=file is not sys.stdout))


def _callback_run_invoke(argv, definitions_root, repository_root, /):
    output = io.StringIO()
    with diagnostics(output):
        try:
            code = main([*argv, '--repository-root', str(repository_root)], definitions_root=definitions_root)
        except SystemExit as error:
            code = error.code
    return code, output.getvalue()


def run(argv, *, repository_root, definitions_root=None):
    """Run the CLI logic with fresh invocation state and return code/diagnostics."""
    invoke = _bind_framework_callback(_callback_run_invoke, argv, definitions_root, repository_root)
    return Context().run(invoke)


def _callback_main_generate(args, definitions_root, groups, root, /, item):
    (environment, target), services = item
    try:
        sync(root, args.write, environment, target, services,
             jobs=args.jobs if len(groups) == 1 else 1, definitions_root=definitions_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return str(error)
    return None


@reported_main
def main(argv=None, *, definitions_root=None) -> int:
    parser = ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().resolve())
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--environment")
    parser.add_argument("--aws-account-id")
    parser.add_argument("--alias")
    parser.add_argument("--service", action="append", help="Exact design service ID (repeatable)")
    parser.add_argument("--scope", action="append", help="Exact environment/target/service selection (repeatable)")
    parser.add_argument("--all", action="store_true", help="Explicit full generation/validation")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 4), default=4, help="Read-only service/target validation workers")
    args = parser.parse_args(argv)
    selectors = bool(args.aws_account_id) + bool(args.alias)
    if (args.environment and selectors != 1) or (not args.environment and selectors):
        parser.error(
            "--environment must be used with exactly one of --aws-account-id or --alias"
        )
    if args.scope and (args.all or args.environment or selectors or args.service):
        parser.error("--scope cannot be combined with other target/service selectors or --all")
    try:
        root = args.repository_root.resolve()
        with generation_context(root, args.write, definitions_root):
            if args.all:
                if args.service or args.environment:
                    parser.error("--all cannot be combined with target/service selectors")
                return sync(root, args.write, jobs=args.jobs, definitions_root=definitions_root)
            contract_scope = active_scope(root)
            if args.scope:
                scope = set()
                for entry in args.scope:
                    parts = entry.split("/")
                    if len(parts) != 3 or any(not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", part) for part in parts):
                        raise ValueError("invalid generation scope: expected environment/target/service")
                    scope.add(tuple(parts))
                if contract_scope is not None and not scope <= contract_scope:
                    raise ValueError("requested services are outside active task validation scope")
            elif args.service:
                if not args.environment or any(not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", service) for service in args.service):
                    parser.error("--service requires a complete environment/target and valid service ID")
                scope = {(args.environment, args.alias or args.aws_account_id, service) for service in args.service}
                if contract_scope is not None and not scope <= contract_scope:
                    raise ValueError("requested services are outside active task validation scope")
            else:
                scope = contract_scope
                if scope is None:
                    return sync(root, args.write, args.environment, args.alias or args.aws_account_id, jobs=args.jobs, definitions_root=definitions_root)
                if args.environment:
                    scope = {item for item in scope if item[:2] == (args.environment, args.alias or args.aws_account_id)}
                if not scope:
                    raise ValueError("no service validation scope; specify environment/target/service")
            consumers(scope)
            changed_sources = _imports_import_guard.changed_sources
            scope_diagnostic = _imports_model_impact.scope_diagnostic
            task_impact = _imports_model_impact.task_impact
            changed = changed_sources(root) if (root / '.git').exists() else set()
            with phase("impact-scope"):
                impact = set(task_impact(root, changed).services)
            import_selection = _imports_model_importing_scope.selected
            impact_scope = contract_scope if import_selection(root) is not None else scope
            if impact_scope is None or not impact <= impact_scope:
                raise ValueError('include all affected Model services in generation/Validation scope: ' + scope_diagnostic(impact, scope))
            if args.write and import_selection(root) is None:
                require_import_changes = _imports_import_guard.require_import_changes
                require_no_issues = _imports_issue_gate.require_no_issues
                require_import_changes(root, changed, generation=True)
                require_no_issues(root, scope)
                return run_generation(root, scope, write=True, jobs=args.jobs, definitions_root=definitions_root)
            groups = {}
            for environment, target, service in sorted(scope):
                groups.setdefault((environment, target), []).append(service)
            generate = _bind_framework_callback(_callback_main_generate, args, definitions_root, groups, root)
            with phase("consumer-generation"):
                if len(scope) == 1:
                    failures = [error for item in groups.items() if (error := generate(item))]
                else:
                    with ThreadPoolExecutor(max_workers=min(args.jobs, len(groups))) as executor:
                        futures = [executor.submit(copy_context().run, generate, item) for item in groups.items()]
                        failures = [error for future in futures if (error := future.result())]
            if failures:
                raise ValueError("\n- ".join(failures))
            return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Design Markdown sync: FAIL\n- {error}", file=output_file(error=True))
        return 1


if __name__ == "__main__":
    if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
        import cProfile
        import pstats
        profile = cProfile.Profile()
        identity = hashlib.sha256("\0".join(sys.argv[1:]).encode()).hexdigest()[:12]
        try:
            raise SystemExit(profile.runcall(main))
        finally:
            profile.dump_stats(str(Path(directory) / f"sync-model-{identity}.prof"))
            pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(25)
    raise SystemExit(main())

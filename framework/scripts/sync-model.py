#!/usr/bin/env python3
"""Generate detailed-design Markdown from authoritative service properties."""

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import os
import re
import sys
from pathlib import Path
from sync_runtime import sync
from validation_scope import active_scope
from task_contract import DeferredExhausted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--import-markdown", action="store_true", help="Explicit one-time migration; requires a migration task and absent models")
    parser.add_argument("--environment")
    parser.add_argument("--aws-account-id")
    parser.add_argument("--alias")
    parser.add_argument("--service", action="append", help="Exact design service ID (repeatable)")
    parser.add_argument("--all", action="store_true", help="Explicit full generation/validation")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 4), default=4, help="Read-only service/target validation workers")
    args = parser.parse_args()
    selectors = bool(args.aws_account_id) + bool(args.alias)
    if (args.environment and selectors != 1) or (not args.environment and selectors):
        parser.error(
            "--environment must be used with exactly one of --aws-account-id or --alias"
        )
    try:
        root = args.repository_root.resolve()
        if args.all:
            if args.service or args.environment:
                parser.error("--all cannot be combined with target/service selectors")
            return sync(root, args.write, import_markdown=args.import_markdown, jobs=args.jobs)
        contract_scope = active_scope(root)
        if args.service:
            if not args.environment or any(not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", service) for service in args.service):
                parser.error("--service requires a complete environment/target and valid service ID")
            scope = {(args.environment, args.alias or args.aws_account_id, service) for service in args.service}
            if contract_scope is not None and not scope <= contract_scope:
                raise ValueError("requested services are outside active task validation scope")
        else:
            scope = contract_scope
            if scope is None:
                return sync(root, args.write, args.environment, args.alias or args.aws_account_id, args.import_markdown, jobs=args.jobs)
            if args.environment:
                scope = {item for item in scope if item[:2] == (args.environment, args.alias or args.aws_account_id)}
            if not scope:
                raise ValueError("no service validation scope; specify environment/target/service")
        groups = {}
        for environment, target, service in sorted(scope):
            groups.setdefault((environment, target), []).append(service)
        def generate(item):
            (environment, target), services = item
            try:
                sync(root, args.write, environment, target, args.import_markdown, services,
                     jobs=args.jobs if len(groups) == 1 else 1)
            except DeferredExhausted as error:
                return error
            except (OSError, ValueError, KeyError, TypeError) as error:
                return str(error)
            return None
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(groups))) as executor:
            failures = [error for error in executor.map(generate, groups.items()) if error]
        if failures:
            real_errors = [error for error in failures if not isinstance(error, DeferredExhausted)]
            if real_errors:
                raise ValueError("\n- ".join(real_errors))
            raise failures[0]
        return 0
    except DeferredExhausted as error:
        print(str(error))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Design Markdown sync: FAIL\n- {error}", file=sys.stderr)
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

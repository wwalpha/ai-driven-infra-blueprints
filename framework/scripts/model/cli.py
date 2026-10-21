#!/usr/bin/env python3
"""Properties Model command entrypoint; no persistent PYTHONPATH configuration."""
from pathlib import Path
import sys

if __name__ == '__main__' and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from model.cli import main
    raise SystemExit(main())

import argparse
import json
from model.sources import load_model, list_models
from validation_cache import input_scope


@input_scope
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['aws-compare']:
        from model.adapters.aws import main as compare
        return compare(argv[1:])
    if argv[:1] == ['import']:
        from model.importing.cli import main as importing
        return importing(argv[1:])
    if argv[:1] == ['audit']:
        from model.audit import main as audit
        return audit(argv[1:])
    if argv[:1] == ['observed']:
        from model.adapters.observed import main as observed
        return observed(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('aws-compare', help='compare saved Model with AWS (requires explicit AWS authorization)')
    commands.add_parser('import', help='acquire/review/publish/recover one explicitly selected service')
    commands.add_parser('observed', help='inspect offline CloudFormation identifier mappings before observation retrieval')
    commands.add_parser('audit', help='generate a standalone AWS audit without executing AWS')
    read = commands.add_parser('read')
    read.add_argument('model', type=Path)
    trace = commands.add_parser('trace')
    trace.add_argument('model', type=Path)
    trace.add_argument('key')
    edit = commands.add_parser('edit', help='publish one ordinary properties candidate under the selected Task')
    edit.add_argument('model', type=Path)
    edit.add_argument('--candidate', type=Path, required=True)
    edit.add_argument('--task-file', required=True)
    render = commands.add_parser('render')
    render.add_argument('model', type=Path)
    for name in ('resource', 'find'):
        command = commands.add_parser(name)
        command.add_argument('model', type=Path)
        command.add_argument('selector')
    incoming = commands.add_parser('incoming')
    incoming.add_argument('model', type=Path)
    incoming.add_argument('resource')
    listing = commands.add_parser('list')
    listing.add_argument('--repository-root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.command in {'read', 'trace', 'resource', 'find', 'render', 'incoming'}:
            from model.sources import scope_for
            from task_contract import task_path
            task_path(scope_for(args.model).root, required=False)
        if args.command == 'read':
            snapshot = load_model(args.model)
            result = {'scope': [snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service],
                      'authoritative': dict(snapshot.authoritative), 'files': [str(path) for path in snapshot.files],
                      'warnings': list(snapshot.warnings)}
        elif args.command == 'edit':
            from model.sources import scope_for, candidate_sources, edit_base, raw_model
            from model.adapters.task import source_write_context, edit_write_context
            from model.operations import prepare_edit, publish_edit
            from task_contract import selected_task, task_revision, model_operation
            scope = scope_for(args.model)
            with selected_task(scope.root, args.task_file):
                _, contract = task_revision(scope.root, args.task_file)
                operation = model_operation(contract)
                authority = source_write_context(scope.root, args.task_file) if operation is not None else edit_write_context(
                    scope.root, {(scope.environment, scope.target, scope.service)}, args.task_file)
                with authority as context:
                    reader = edit_base
                    if operation is not None:
                        reader = raw_model
                    snapshot = reader(scope.path, context.snapshot)
                    candidate, _ = candidate_sources(scope.root, args.candidate, snapshot)
                    paths = publish_edit(prepare_edit(snapshot, candidate, context), context)
            result = {'status': 'saved', 'paths': [str(path) for path in paths]}
        elif args.command == 'trace':
            from model.files import trace_model
            result = trace_model(args.model, args.key)
        elif args.command in {'resource', 'find'}:
            from model.files import read_resource, find_model
            selected = read_resource(args.model, args.selector) if args.command == 'resource' else find_model(args.model, args.selector)
            result = {key: [str(origin[0]), *origin[1:]] for key, origin in selected.items()}
        elif args.command == 'render':
            from model.render import render_model
            snapshot = load_model(args.model)
            result = {str(path): text for path, text in render_model(snapshot, None).items()}
        elif args.command == 'incoming':
            from dataclasses import asdict
            from model.references import incoming
            snapshot = load_model(args.model)
            warnings = []
            records = incoming(snapshot, args.resource, warnings=warnings)
            result = {'status': 'incomplete' if warnings else 'complete', 'warnings': warnings,
                      'references': [{'consumer': str(scope.path), **asdict(usage)} for scope, usage in records]}
        elif args.command == 'list':
            result = [str(scope.path) for scope in list_models(args.repository_root)]
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

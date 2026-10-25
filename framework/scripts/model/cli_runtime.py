"""Execute parsed Model commands; CLI help needs no editing/rendering runtime."""

import json
import sys
from dataclasses import asdict

import task_contract_core as _imports_task_contract
from task_contract_core import model_operation, selected_task, task_path
from utils.script_loader import module

import model.dependency_index as dependency_index
from model import prepare_edit, publish_edit, render_model
from model.files import find_model, read_resource, trace_model
from model.references import incoming as reference_incoming
from model.sources import (
    candidate_sources,
    edit_base,
    list_models,
    load_model,
    raw_model,
    scope_for,
)


def execute(args):
    try:
        root = (
            args.repository_root.resolve()
            if args.command in {"list", "index"}
            else scope_for(args.model).root
        )
        with _imports_task_contract.task_reads(root):
            if args.command in {
                "read",
                "trace",
                "resource",
                "find",
                "render",
                "incoming",
            }:
                task_path(scope_for(args.model).root, required=False)
            if args.command == "read":
                snapshot = load_model(args.model)
                result = {
                    "scope": [
                        snapshot.scope.environment,
                        snapshot.scope.target,
                        snapshot.scope.service,
                    ],
                    "authoritative": dict(snapshot.authoritative),
                    "files": [str(path) for path in snapshot.files],
                    "warnings": list(snapshot.warnings),
                }
            elif args.command == "edit":
                scope = scope_for(args.model)
                with (
                    selected_task(scope.root, args.task_file),
                    _imports_task_contract.task_reads(scope.root),
                ):
                    task = _imports_task_contract.task_snapshot(
                        scope.root, args.task_file, live=True
                    )
                    operation = model_operation(task.text)
                    task_adapter = module(
                        "model/adapters/task.py", "model.adapters.task"
                    )
                    authority = (
                        task_adapter.source_write_context(
                            scope.root, args.task_file, snapshot=task
                        )
                        if operation is not None
                        else task_adapter.edit_write_context(
                            scope.root,
                            {(scope.environment, scope.target, scope.service)},
                            args.task_file,
                            snapshot=task,
                        )
                    )
                    with authority as context:
                        reader = edit_base
                        if operation is not None:
                            reader = raw_model
                        snapshot = reader(scope.path, context.snapshot)
                        candidate, _ = candidate_sources(
                            scope.root, args.candidate, snapshot
                        )
                        paths = publish_edit(
                            prepare_edit(snapshot, candidate, context), context
                        )
                result = {"status": "saved", "paths": [str(path) for path in paths]}
            elif args.command == "trace":
                result = trace_model(args.model, args.key)
            elif args.command in {"resource", "find"}:
                selected = (
                    read_resource(args.model, args.selector)
                    if args.command == "resource"
                    else find_model(args.model, args.selector)
                )
                result = {
                    key: [str(origin[0]), *origin[1:]]
                    for key, origin in selected.items()
                }
            elif args.command == "render":
                snapshot = load_model(args.model)
                result = {
                    str(path): text
                    for path, text in render_model(snapshot, None).items()
                }
            elif args.command == "incoming":
                snapshot = load_model(args.model)
                warnings = []
                records = reference_incoming(snapshot, args.resource, warnings=warnings)
                result = {
                    "status": "incomplete" if warnings else "complete",
                    "warnings": warnings,
                    "references": [
                        {"consumer": str(scope.path), **asdict(usage)}
                        for scope, usage in records
                    ],
                }
            elif args.command == "index":
                result = {"indexedModels": len(dependency_index.rebuild(root))}
            elif args.command == "list":
                result = [
                    str(scope.path) for scope in list_models(args.repository_root)
                ]
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(
            json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

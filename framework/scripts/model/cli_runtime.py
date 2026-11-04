"""Execute parsed Model commands; CLI help needs no editing/rendering runtime."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import task_contract_core as _imports_task_contract
from task_contract_core import model_operation, selected_task, task_path
from utils.file_operations import atomic_files
from utils.script_loader import module
from utils.source_reads import FileReads

import model.dependency_index as dependency_index
from model import prepare_edit, publish_edit, render_model
from model.files import find_model, read_resources, trace_model
from model.format import owner, patch, validate_blocks
from model.identity import COUNTERS, allocate, preserve_allocation
from model.references import incoming as reference_incoming
from model.sources import (
    candidate_sources,
    edit_base,
    list_models,
    load_model,
    raw_model,
    safe,
    scope_for,
)


def allocate_candidate(args):
    scope = scope_for(args.model)
    directory = args.candidate.absolute()
    safe(Path(directory.anchor), directory)
    root = scope.root.resolve()
    if (
        directory.is_relative_to(root)
        or root.is_relative_to(directory)
        or any((path / ".git").exists() for path in (directory, *directory.parents))
    ):
        raise ValueError("Model properties candidate must be outside the repository")

    reads = FileReads()
    saved = reads.kind(scope.path) != "missing"
    before = raw_model(scope, reads) if saved else edit_base(scope.path, reads)
    _, candidate = candidate_sources(scope.root, directory, before)
    values, locations = validate_blocks(candidate.documents)
    keys = [f"desired.resource.{number}.logicalId" for number in args.resource]
    for number, key in zip(args.resource, keys, strict=True):
        if before.authoritative.get(key):
            raise ValueError("cannot reallocate a saved logicalId: " + number)
    allocated = allocate(values, args.resource)
    if saved:
        preserve_allocation(before.authoritative, allocated)

    owners = {owner(key, values): path for key, (path, _) in locations.items()}
    updates = {}
    for key in [*keys, COUNTERS]:
        path = owners.get(owner(key, values))
        if path is None:
            if len(candidate.parts) != 1:
                raise ValueError("split Model candidate needs a service block for " + key)
            path = candidate.parts[0]
        updates.setdefault(path, {})[key] = allocated[key]
    output = {
        directory / path.relative_to(scope.root): patch(candidate.documents[path], changes)
        for path, changes in updates.items()
    }
    if args.write_candidate:
        _, current = candidate_sources(scope.root, directory, before)
        if current.files != candidate.files:
            raise ValueError("Model candidate changed during allocation")
        reads.verify()
        atomic_files(output)
    return {
        "status": "updated" if args.write_candidate else "preview",
        "allocations": [
            {"resource": number, "logicalId": allocated[key]}
            for number, key in zip(args.resource, keys, strict=True)
        ],
        "lastAllocated": json.loads(allocated[COUNTERS]),
        "paths": [str(path) for path in output],
    }


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
            elif args.command == "allocate":
                result = allocate_candidate(args)
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
                    read_resources(args.model, args.selector)
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

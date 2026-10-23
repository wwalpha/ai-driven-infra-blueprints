"""Model dependencies from saved declarations and direct links, without regenerating values."""

from dataclasses import dataclass
from pathlib import Path

import import_guard as _imports_import_guard
import task_contract_core as _imports_task_contract
import utils.input_cache as _imports_validation_cache

import model.impact_changes as _imports_model_impact_changes
import model.impact_graph as _imports_model_impact_graph
import model.importing.scope as _dependency_model_importing_scope
import model.importing.scope as _imports_model_importing_scope
import model.importing.scope as import_scope
import model.operations as _imports_model_operations
import model.references as _dependency_model_references
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources


def dependencies(root, *, read_context=None, raw=False):
    readable = _imports_model_importing_scope.readable
    root = Path(root).absolute()
    reads = read_context or _dependency_model_sources._invocation_reads(root)
    allowed = readable(root)
    result = {}
    reader = _dependency_model_sources.load_model
    if raw:
        raw_model = _imports_model_sources.raw_model
        reader = raw_model
    for scope in _dependency_model_sources.list_models(root, reads):
        identity = scope.environment, scope.target, scope.service
        if allowed is not None and identity not in allowed:
            continue
        model = reader(scope, reads)
        result[identity] = {tuple(usage.producer_scope.split('/')) for usage in _dependency_model_references.usages(model, reads)
                            if usage.producer_kind != 'context'}
    return result


def _service_affected(root, changed, *, before=None, read_context=None, raw=False):
    """Include deleted scopes and incoming consumers; this grants no output/AWS rights."""
    root = Path(root)
    changed = {Path(path) for path in changed}
    if not any(path.parts[:1] == ('model',) or path == Path('project.json') for path in changed):
        return set()
    reads = read_context or _dependency_model_sources.FileReads()
    graph = dependencies(root, read_context=reads, raw=raw)
    if before is not None:
        for identity, producers in dependencies(before).items():
            graph.setdefault(identity, set()).update(producers)
    result = set()
    for path in changed:
        if path.parts[:1] == ('model',):
            scope = _dependency_model_sources.source_scope(root, root / path)
            result.add((scope.environment, scope.target, scope.service))
    if Path('project.json') in changed:
        result.update(graph)
    pending = set(result)
    while pending:
        incoming = {consumer for consumer, producers in graph.items() if consumer not in result and producers & pending}
        result.update(incoming)
        pending = incoming
    return result


@dataclass(frozen=True)
class Impact:
    services: frozenset
    changed_nodes: frozenset = frozenset()
    visited: frozenset = frozenset()
    reasons: tuple = ()


def analyze(root, changed, *, before=None, read_context=None, raw=False):
    """Keep source services for validation; propagate only their changed semantic nodes."""
    changed_nodes = _imports_model_impact_changes.changed_nodes
    node = _imports_model_impact_changes.node
    Graph = _imports_model_impact_graph.Graph
    models = _imports_model_impact_graph.models
    readable = _imports_model_importing_scope.readable
    selected = _imports_model_importing_scope.selected
    root = Path(root).absolute()
    changed = {Path(path) for path in changed}
    sources = {path for path in changed if path.parts[:1] == ('model',)}
    if not sources and Path('project.json') not in changed:
        return Impact(frozenset())
    if before is None or selected(root) is not None:
        return Impact(frozenset(_service_affected(root, changed, before=before, read_context=read_context, raw=raw)),
                      reasons=({'reason': 'IMPORT compatibility scope' if selected(root) is not None else
                                'no baseline: conservative service impact'},))
    reads = read_context or _dependency_model_sources._invocation_reads(root)
    allowed = readable(root)
    current = models(root, reads, raw=raw, allowed=allowed)
    old_reads = _dependency_model_sources._invocation_reads(Path(before))
    previous = models(before, old_reads, previous=True, allowed=allowed)
    scopes = set()
    for path in sources:
        scope = _dependency_model_sources.source_scope(root, root / path)
        scopes.add((scope.environment, scope.target, scope.service))
    graph = Graph()
    graph.include(previous, old_reads)
    graph.include(current, reads)
    seeds = changed_nodes(scopes, previous, current, graph.reasons)
    if Path('project.json') in changed:
        seeds.update(node(scope) for scope in previous.keys() | current.keys())
    visited = graph.traverse(seeds)
    return Impact(frozenset(scopes | {entry[:3] for entry in visited}), frozenset(seeds),
                  frozenset(visited), tuple(graph.reasons))


def affected(root, changed, *, before=None, read_context=None, raw=False):
    """Compatible service-set API; a versioned baseline enables Resource precision."""
    return set(analyze(root, changed, before=before, read_context=read_context, raw=raw).services)


def task_impact(root, changed=None, *, output=None, base=None, contract_file=None, read_context=None):
    """One Task baseline and Candidate overlay shared by save, generation and validation."""
    base_revision = _imports_import_guard.base_revision
    changed_sources = _imports_import_guard.changed_sources
    snapshots = _imports_import_guard.snapshots
    memo_table = _imports_validation_cache.memo_table

    CandidateReads = _imports_model_operations.CandidateReads

    root = Path(root).resolve()
    changed = changed_sources(root, changed, contract_file=contract_file)
    output = output or {}
    changed |= changed_sources(root, {p.relative_to(root).as_posix() for p in output})
    if not changed:
        return Impact(frozenset())
    reads = read_context or _dependency_model_sources._invocation_reads(root)
    candidates = CandidateReads(reads, output) if output else reads
    if not (root / '.git').exists() or import_scope.selected(root, contract_file=contract_file) is not None:
        return analyze(root, changed, read_context=candidates, raw=True)
    memo = memo_table()
    if base is None:
        task_path = _imports_task_contract.task_path
        selector = contract_file if contract_file is not None else task_path(root, required=False)
        baseline_key = (task_impact, 'baseline', root, selector)
        if memo is not None and baseline_key in memo:
            base = memo[baseline_key]
        else:
            base = base_revision(root, contract_file=contract_file)
            if memo is not None:
                memo[baseline_key] = base
    if base is None:
        return analyze(root, changed, read_context=candidates, raw=True)
    key = (task_impact, root, base, frozenset(changed), tuple(sorted(output.items())),
           _dependency_model_importing_scope.read_context(root), id(reads))
    if memo is not None and key in memo:
        return memo[key]
    with snapshots(root, base, {}) as (before, _):
        result = analyze(root, changed, before=before, read_context=candidates, raw=True)
    if memo is not None:
        memo[key] = result
    return result


def _lambda_scope_diagnostic_show_162(scopes):
    return ', '.join(('/'.join(entry) for entry in sorted(scopes))) or '(none)'


def scope_diagnostic(required, declared):
    required, declared = set(required), set(declared)
    show = _lambda_scope_diagnostic_show_162
    return ('required=[' + show(required) + ']; declared=[' + show(declared) +
            ']; declared-only=[' + show(declared - required) + ']')

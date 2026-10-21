"""Model dependencies from saved declarations and direct links, without regenerating values."""
from pathlib import Path

from model.references import usages
from model.sources import FileReads, list_models, load_model, source_scope, _invocation_reads


def dependencies(root, *, read_context=None):
    root = Path(root).absolute()
    reads = read_context or _invocation_reads(root)
    from model.importing.scope import readable
    allowed = readable(root)
    result = {}
    for scope in list_models(root, reads):
        identity = scope.environment, scope.target, scope.service
        if allowed is not None and identity not in allowed:
            continue
        model = load_model(scope, reads)
        result[identity] = {tuple(usage.producer_scope.split('/')) for usage in usages(model, reads)
                            if usage.producer_kind != 'context'}
    return result


def affected(root, changed, *, before=None, read_context=None):
    """Include deleted scopes and incoming consumers; this grants no output/AWS rights."""
    root = Path(root)
    changed = {Path(path) for path in changed}
    if not any(path.parts[:1] == ('model',) or path == Path('project.json') for path in changed):
        return set()
    reads = read_context or FileReads()
    graph = dependencies(root, read_context=reads)
    if before is not None:
        for identity, producers in dependencies(before).items():
            graph.setdefault(identity, set()).update(producers)
    result = set()
    for path in changed:
        if path.parts[:1] == ('model',):
            scope = source_scope(root, root / path)
            result.add((scope.environment, scope.target, scope.service))
    if Path('project.json') in changed:
        result.update(graph)
    pending = set(result)
    while pending:
        incoming = {consumer for consumer, producers in graph.items() if consumer not in result and producers & pending}
        result.update(incoming)
        pending = incoming
    return result

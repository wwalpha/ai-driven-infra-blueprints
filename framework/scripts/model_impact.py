"""Propagate Model changes only through changed active resource references."""
from pathlib import Path

from model_parameter_inputs import parameter_value
from model_templates import (_reference_inputs, json_text, model_paths, parse_template,
                             prepare_instances, service_source)
from validation_cache import memoized


@memoized
def references(path):
    _, inputs = _reference_inputs(path)
    definitions, _, observed, parameters, _, _ = inputs
    return {(item['id'], name): (item, spec)
             for item, definition in prepare_instances(definitions, parameters, observed)
             for name, spec in definition.parameters.items()
             if isinstance(spec, dict) and 'service' in spec}


def dependencies(root, *, active=True):
    # Callers end the input snapshot after writes; never expose the cached sets.
    from import_scope import selected, readable
    root = Path(root).resolve()
    scope = tuple(sorted(readable(root))) if selected(root) is not None else None
    return {entry: set(producers) for entry, producers in _dependencies(root, active, scope).items()}


@memoized
def _dependencies(root, active, scope):
    result = {}
    for path in model_paths(root):
        env, alias, _ = path.relative_to(root/'model').parts
        producers = None
        if active:
            try:
                producers = {spec['service'] for _, spec in references(path).values()}
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if producers is None:
            # Unknown baseline or invalid active inputs cannot prove a smaller scope.
            service_source(path)
            definitions, _ = parse_template(root/'model/templates'/alias/(path.stem+'.properties.tpl'))
            producers = {spec['service'] for definition in definitions.values()
                         for spec in definition.parameters.values() if isinstance(spec, dict) and 'service' in spec}
        result[(env, alias, path.stem)] = {(env, alias, service) for service in producers}
    return {entry: frozenset(producers) for entry, producers in result.items()}


def reference_results(root, entry, producers):
    path = root/'model'/entry[0]/entry[1]/(entry[2]+'.properties')
    registered, inputs = _reference_inputs(path)
    _, template, _ = registered
    definitions, _, _, parameters, bindings, _ = inputs
    result = {}
    for (identity, name), (item, spec) in references(path).items():
        if (*entry[:2], spec['service']) not in producers:
            continue
        selected = item['parameters'][name]
        if 'instance' in spec:
            producer = path.with_name(spec['service']+'.properties')
            _, source = _reference_inputs(producer)
            target = source[4]['instances'][spec['instance']]
            selected = [rid for rid in target['resources'].values()
                        if source[5][f'desired.resource.{rid}.resourceType'][2] == spec['resourceType']]
        value = parameter_value(template, item, name, parameters['instances'], bindings,
                                definitions, entry[0], {})
        result[(identity, name)] = json_text([spec['service'], selected, spec['resourceType'], spec.get('format'),
                                             spec.get('property'), value])
    return result


def propagate(root, result, pending, before=None):
    graph = dependencies(root, active=before is not None)
    if before is not None:
        for entry, producers in dependencies(before).items():
            graph.setdefault(entry, set()).update(producers)
    while pending:
        added = set()
        for consumer, producers in graph.items():
            if consumer in result or not producers & pending:
                continue
            changed = True
            if before is not None:
                try:
                    changed = reference_results(before, consumer, pending) != reference_results(root, consumer, pending)
                except (OSError, ValueError, KeyError, TypeError):
                    pass  # Missing, deleted, ambiguous or cyclic references remain validation targets.
            if changed:
                added.add(consumer)
        result.update(added)
        pending = added
    return result


def dependency_impact(root, changed, result, propagating, *, before=None):
    if Path('project.json') in changed:
        for path in model_paths(root):
            registered = service_source(path)
            definitions, _ = parse_template(registered[1])
            if any(isinstance(spec, dict) and spec.get('source') == 'consumer.executionAccountId'
                   for definition in definitions.values() for spec in definition.parameters.values()):
                entry = (*path.relative_to(root/'model').parts[:2], path.stem)
                result.add(entry); propagating.add(entry)
    if before is not None:
        # A deleted template/consumer must remain in the direct impact set.
        from model_templates import consumers
        for path in changed:
            if path.parts[:2] == ('model', 'templates') and len(path.parts) >= 4:
                result.update(consumers(before, path.parts[2], path.parts[3].removesuffix('.tpl').removesuffix('.properties')))
        return propagate(root, result, propagating | result, before)
    if not propagating:
        return result
    from import_guard import base_revision, snapshots
    from worktree_task import git
    if git(root, 'rev-parse', '--verify', 'HEAD', check=False).returncode:
        return propagate(root, result, propagating)
    base = base_revision(root)
    paths = sorted(map(str, changed))
    differences = git(root, 'diff', '--name-only', '--no-renames', '-z', base, '--', *paths).stdout
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z', '--', *paths).stdout
    if not differences and not untracked:
        return propagate(root, result, propagating)
    with snapshots(root, base, {}) as (previous, current):
        # A claimed change without a versioned diff cannot establish a safe baseline.
        known = any((previous/p).is_file() != (current/p).is_file() or
                    ((previous/p).is_file() and (previous/p).read_bytes() != (current/p).read_bytes())
                    for p in changed)
        if not known:
            return propagate(root, result, propagating)
        return dependency_impact(current, changed, result, propagating, before=previous)

"""Content guards shared by scan and publication; no comparison execution."""
import re
from validation_cache import digest_files, PassCache, recording_inputs

def live_common_key(cache):
    # A surrounding generation recorder must never turn the final guard into a memo read.
    with recording_inputs(None):
        return cache.common_key()


def selected_scope(environment, directory, services):
    values = [environment, directory, *services]
    if not services or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', value) for value in values):
        raise ValueError('explicit environment/target/services required')
    return {(environment, directory, service) for service in services}


def file_sets(comparison):
    roots = {path.with_suffix('') for path in comparison.inputs if path.suffix in {'.properties', '.md'} and path.is_relative_to(comparison.root / 'model')}
    roots.update(comparison.root / 'docs/designs' / comparison.environment / comparison.directory / service for service in comparison.services)
    return {path.relative_to(comparison.root).as_posix(): sorted(file.relative_to(comparison.root).as_posix() for file in path.rglob('*')
              if file.is_file() or file.is_symlink()) for path in roots}


def fingerprint(comparison, *, common_key):
    if getattr(comparison, 'stale_inputs', False):
        raise ValueError('stale scan: contradictory input observations')
    from .inputs import retain_reads
    reads = getattr(comparison, 'model_reads', None)
    if reads is not None:
        retain_reads(comparison)
    paths = sorted(path.relative_to(comparison.root).as_posix() for path in comparison.inputs)
    return {'paths': paths, 'digest': digest_files(comparison.root, comparison.inputs),
            'file_sets': file_sets(comparison), 'framework': common_key,
            'unreadable': getattr(comparison, 'unreadable_inputs', False) or bool(reads and reads.read_failures),
            'model_kinds': {p.relative_to(comparison.root).as_posix(): kind for p, kind in reads.kinds.items()
                            if p.is_relative_to(comparison.root)} if reads else {},
            'model_selections': [dict(base=base.relative_to(comparison.root).as_posix(), pattern=pattern,
                                    recursive=recursive, kinds=kinds,
                                    paths=[p.relative_to(comparison.root).as_posix() for p in paths])
                                 for (base, pattern, recursive, kinds), paths in reads.selections.items()
                                 if base.is_relative_to(comparison.root)] if reads else []}


def verify_inputs(root, artifact, *, cache=None, common=True):
    expected = artifact['fingerprint']
    if expected.get('unreadable'):
        raise ValueError('scan input freshness unprovable: input bytes could not be read')
    from generation_inputs import GenerationInputs
    for path, kind in expected.get('model_kinds', {}).items():
        if GenerationInputs.live_kind(root / path) != kind:
            raise ValueError('stale scan: Model input kind changed: ' + path)
    for selection in expected.get('model_selections', []):
        current = [p.relative_to(root).as_posix() for p in GenerationInputs.live_select(
            root / selection['base'], selection['pattern'], selection['recursive'], selection['kinds'])]
        if current != selection['paths']:
            raise ValueError('stale scan: Model input selection changed')
    if digest_files(root, [root / path for path in expected['paths']]) != expected['digest']:
        raise ValueError('stale scan: scoped model/IaC/parameter/reference input changed; rescan affected scope')
    for directory, files in expected['file_sets'].items():
        current = sorted(file.relative_to(root).as_posix() for file in (root / directory).rglob('*') if file.is_file() or file.is_symlink())
        if current != files:
            raise ValueError('stale scan: input file set changed')
    if cache is None:
        cache = PassCache(root)
        cache.common = live_common_key(cache)
        if cache.common != expected['framework']:
            raise ValueError('stale scan: framework/project input changed')
    verify_service_keys(root, artifact, cache=cache)
    if artifact.get("lint_dependencies"):
        from utils.cfn_lint import verify_dependencies
        verify_dependencies(artifact["lint_dependencies"], cwd=root)
    if common and live_common_key(cache or PassCache(root)) != expected['framework']:
        raise ValueError('stale scan: framework/project input changed')


def verify_service_keys(root, artifact, *, cache=None):
    supplied = cache is not None
    for entry, expected_key in artifact.get('service_keys', {}).items():
        if expected_key is None:
            continue
        if cache is None:
            cache = PassCache(root)
        if cache.service_key(tuple(entry.split('/'))) != expected_key:
            raise ValueError('stale scan: validation/reference dependency changed')
    if not supplied and cache is not None and live_common_key(cache) != cache.common:
        raise ValueError('stale scan: validation/reference dependency changed')



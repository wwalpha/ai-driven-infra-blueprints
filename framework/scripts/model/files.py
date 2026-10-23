"""Resource reads and source traces over the canonical Model reader."""

from pathlib import Path

from utils.input_cache import input_scope

import model.core as _imports_model_core
import model.format as _imports_model_format
import model.identity as resource_identity
import model.references as _imports_model_references
import model.sources as _dependency_model_sources
from model.core import entries, properties
from model.core import resource_row_index as resource_row_index


@input_scope
def read_model(path):
    return load_model(path).text


@input_scope
def trace_model(path, key):
    declarations = _imports_model_references.declarations
    snapshot = load_model(path)
    origin = key
    if key not in snapshot.authoritative:
        if key.startswith('observed.row.') and key.endswith(('.property', '.comment')):
            origin = key.replace('observed.', 'desired.', 1)
        elif key.endswith('.artifactSha256'):
            origin = key.removesuffix('artifactSha256') + 'document'
    file, line = snapshot.locations[origin]
    result = {'key': key, 'value': snapshot.values[key] if origin != key else snapshot.authoritative[key], 'file': str(file), 'line': line}
    if origin != key:
        result['derivedFrom'] = origin
    references = {identity: spec for identity, spec in declarations(snapshot.authoritative).items()
                  if spec['consumerKey'] == origin}
    if references:
        result['references'] = references
    return result


def service_model_path(path, base):
    return _dependency_model_sources.source_scope(base.parent, path).path


def model_file_contents(path, text, *, validate=True):
    """Initial layout only; ordinary edits use format.patch and retain existing parts."""
    validate_authority = _imports_model_core.validate_authority
    parse = _imports_model_format.parse
    split = _imports_model_format.split
    values = parse(text).values
    if validate:
        validate_authority(values)
    return split(path, values)


def resource_keys(text: str, selector: str, *, scope=None) -> set[str]:
    """Select one resource's display group and service-wide context without rewriting values."""
    values = properties(text)
    resources = dict(entries(values, "desired.resource."))
    matches = [identity for identity, resource in resources.items()
               if selector and selector in (identity, resource.get("logicalId"))]
    if len(matches) != 1:
        raise ValueError(f"resource selector must match exactly one fixed entry number or logicalId: {selector!r} ({len(matches)} matches)")
    anchors = resource_identity.anchor_index(values)
    neighbors = {identity: set() for identity in resources}
    for identity, resource in resources.items():
        if 'parentReference' not in resource:
            continue
        environment, target, service, logical = resource_identity.parse_reference(resource['parentReference'], scope)
        if scope is None or (environment, target, service) != (scope.environment, scope.target, scope.service):
            raise ValueError('grouped parent requires the same explicit service scope')
        match = resource_identity.select_anchor(anchors, logical, resource['parentReference'])
        if match is None:
            raise ValueError('grouped parent is absent: ' + identity)
        parent = match[0]
        neighbors[identity].add(parent)
        neighbors[parent].add(identity)
    selected = set()
    pending = matches[:]
    while pending:
        identity = pending.pop()
        if identity not in selected:
            selected.add(identity)
            pending.extend(neighbors[identity] - selected)
    prefixes = ("desired.service.", "display.service.", "desired.note.") + tuple(
        prefix for identity in selected for prefix in (
            f"desired.resource.{identity}.", f"display.resource.{identity}.",
            f"desired.row.{identity}-", f"observed.row.{identity}-",
        )
    )
    return {key for key in values if key.startswith(prefixes)}


@input_scope
def read_resource(model_path: Path, selector: str) -> dict[str, tuple[Path, int, str]]:
    """Return selected group keys with source locations/values; expansion errors propagate."""
    owner = _imports_model_format.owner
    loaded = load_model(model_path.absolute())
    keys = resource_keys(loaded.text, selector, scope=loaded.scope)
    selected = {owner(key, loaded.authoritative) for key in keys if key in loaded.authoritative}
    return {key: (*loaded.locations[key], value) for key, value in loaded.authoritative.items()
            if owner(key, loaded.authoritative) in selected}


@input_scope
def find_model(model_path: Path, query: str) -> dict[str, tuple[Path, int]]:
    """Return matching key locations using existing expanded values; no writes."""
    loaded = load_model(model_path.absolute())
    return {key: loaded.locations[key] for key, value in loaded.authoritative.items() if query in key + '=' + value}



def load_model(scope, read_context=None):
    return _dependency_model_sources.load_model(scope, read_context)


def model_parts(path, *, read_context=None):
    return _dependency_model_sources.model_parts(path, read_context=read_context)

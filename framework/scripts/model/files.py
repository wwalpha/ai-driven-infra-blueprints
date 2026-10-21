"""Resource reads and source traces over the canonical Model reader."""
from pathlib import Path
from model.sources import load_model, scope_for
from model.core import resource_row_index
from validation_cache import input_scope
from model.sources import model_parts, source_scope
from model.format import LIMIT as MAX_LINES


@input_scope
def read_model(path):
    return load_model(path).text


@input_scope
def trace_model(path, key):
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
    from model.references import declarations
    references = {identity: spec for identity, spec in declarations(snapshot.authoritative).items()
                  if spec['consumerKey'] == origin}
    if references:
        result['references'] = references
    return result


def service_model_path(path, base):
    return source_scope(base.parent, path).path


def model_file_contents(path, text, *, validate=True):
    """Initial layout only; ordinary edits use format.patch and retain existing parts."""
    from model.format import parse, split
    from model.core import validate_authority
    values = parse(text).values
    if validate:
        validate_authority(values)
    return split(path, values)


def resource_keys(text: str, selector: str) -> set[str]:
    """Select one resource's display group and service-wide context without rewriting values."""
    from model.core import LINK, entries, properties
    values = properties(text)
    resources = dict(entries(values, "desired.resource."))
    matches = [identity for identity, resource in resources.items()
               if selector and selector in (identity, resource.get("logicalId"), resource.get("cfn-logicalId"), resource.get("anchor"))]
    if len(matches) != 1:
        raise ValueError(f"resource selector must match exactly one number, cfn-logicalId, legacy logical ID or anchor: {selector!r} ({len(matches)} matches)")
    anchors: dict[str, list[str]] = {}
    for identity, resource in resources.items():
        if anchor := resource.get("anchor"):
            anchors.setdefault(anchor, []).append(identity)
    neighbors = {identity: set() for identity in resources}
    for identity, resource in resources.items():
        if "parentReference" not in resource:
            continue
        link = LINK.fullmatch(resource["parentReference"])
        parents = anchors.get(link.group(3), []) if link and not link.group(2) else []
        if len(parents) != 1:
            raise ValueError(f"invalid or ambiguous grouped parent: desired.resource.{identity}.parentReference")
        parent = parents[0]
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
    loaded = load_model(model_path.absolute())
    keys = resource_keys(loaded.text, selector)
    from model.format import owner
    selected = {owner(key, loaded.authoritative) for key in keys if key in loaded.authoritative}
    return {key: (*loaded.locations[key], value) for key, value in loaded.authoritative.items()
            if owner(key, loaded.authoritative) in selected}


@input_scope
def find_model(model_path: Path, query: str) -> dict[str, tuple[Path, int]]:
    """Return matching key locations using existing expanded values; no writes."""
    loaded = load_model(model_path.absolute())
    return {key: loaded.locations[key] for key, value in loaded.authoritative.items() if query in key + '=' + value}


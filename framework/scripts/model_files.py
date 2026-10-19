"""Read YAML service Model values, locate their sources or extract a resource."""

from __future__ import annotations
from validation_cache import input_is_file, input_is_symlink, input_select, input_text

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple
from validation_cache import input_scope, memoized
from import_scope import scoped_read


from model_sources import MAX_LINES, PART_LINES, INDEX_HEADER, PART_PREFIX, model_parts


class LoadedModel(NamedTuple):
    text: str
    values: dict[str, str]
    locations: dict[str, tuple[Path, int]]
    files: dict[Path, str]
    warnings: tuple = ()


@scoped_read
@memoized
def load_model(path: Path, _context=None) -> LoadedModel:
    from model_templates import source_paths, publication_lock, load_expansion
    paths = source_paths(path)
    if paths is None:
        raise ValueError(f'Model requires a YAML service source: {path}')
    with publication_lock(paths[0]):
        expanded = load_expansion(path)
        if expanded is None:
            raise ValueError(f'YAML Model inputs missing: {path}')
        text = ''.join(f'{key}={value}\n' for key, value in expanded.values.items())
        locations = {key: (Path(source["template"]), source["line"]) if "template" in source else (paths[2]/"observed.json", 1)
                     for key, source in expanded.provenance.items()}
        return LoadedModel(text, expanded.values, locations, expanded.files, expanded.warnings)


@input_scope
def read_model(path: Path) -> str:
    return load_model(path).text


def resource_row_index(values: dict[str, str]) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Index legacy IDs as well as numbered resources using the existing prefix rule.

    Ambiguous overlapping legacy identities are rejected, never split at first '-'.
    """
    from model_core import entries
    resources = dict(entries(values, "desired.resource."))
    index = {identity: [] for identity in resources}
    # A row's final segment is its row number; legacy resource IDs may contain '-'.
    for rid, row in entries(values, "desired.row."):
        owner = rid.rpartition("-")[0]
        if owner not in resources:
            raise ValueError(f"orphan desired row: {rid}")
        prefix, overlapping = owner, []
        while "-" in prefix:
            prefix = prefix.rpartition("-")[0]
            if prefix in resources:
                overlapping.append(prefix)
        if overlapping:
            raise ValueError(f"ambiguous legacy row ownership: {rid}: {overlapping + [owner]}")
        index[owner].append((rid, row))
    return index


def model_file_contents(path: Path, text: str, *, validate: bool = True) -> dict[Path, str]:
    from model_core import properties
    if validate:
        properties(text)
    lines = text.splitlines(keepends=True)
    if len(lines) <= MAX_LINES:
        return {path: text}
    output = {}
    index = [INDEX_HEADER]
    for start in range(0, len(lines), PART_LINES):
        part = path.with_suffix("") / f"part-{len(output) + 1:03d}.properties"
        output[part] = "".join(lines[start:start + PART_LINES])
        index.append(PART_PREFIX + part.relative_to(path.parent).as_posix())
    # ponytail: one index level; nested indexes if a service needs more than 599 parts.
    if len(index) > MAX_LINES:
        raise ValueError("service model requires more than 599 parts")
    output[path] = "\n".join(index) + "\n"  # Publish the index after its data files.
    return output


def service_model_path(path: Path, base: Path) -> Path:
    """Map a part back to its service entrance for scope and task boundaries."""
    relative = path.relative_to(base)
    if len(relative.parts) == 4 and relative.parts[0] not in {'parameters', 'templates'}:
        return base / relative.parent.with_suffix(".properties")
    return path


def resource_keys(text: str, selector: str) -> set[str]:
    """Select one resource's display group and service-wide context without rewriting values."""
    from model_core import LINK, entries, properties
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
    return {key: (*loaded.locations[key], value) for key, value in loaded.values.items() if key in keys}


@input_scope
@scoped_read
def trace_model(model_path: Path, key: str, _context=None) -> dict:
    """Return existing expansion provenance for one key; missing keys raise KeyError."""
    from model_templates import load_expansion
    from model_sources import source_paths, publication_lock
    path = model_path.absolute()
    location = source_paths(path)
    if location is None:
        raise ValueError(f'Model requires a YAML service source: {path}')
    with publication_lock(location[0]):
        expanded = load_expansion(path)
        if expanded is None:
            raise ValueError(f'YAML Model inputs missing: {path}')
        return dict(expanded.provenance[key])


@input_scope
def find_model(model_path: Path, query: str) -> dict[str, tuple[Path, int]]:
    """Return matching key locations using existing expanded values; no writes."""
    loaded = load_model(model_path.absolute())
    return {key: loaded.locations[key] for key, value in loaded.values.items() if query in key + '=' + value}


@input_scope
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="Logical model/<environment>/<target>/<service>.properties identifier; no file is stored")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--trace", help="Trace one generated key to template/parameter/observed authority")
    operation.add_argument("--find", help="Find a property key or identifier without printing whole files")
    operation.add_argument("--resource", help="Read one exact resource number, logical ID or anchor, including its display group and service notes")
    args = parser.parse_args()
    try:
        path = args.model.absolute()
        if args.trace is not None:
            import json
            print(json.dumps(trace_model(path, args.trace), ensure_ascii=False))
            return 0
        records = read_resource(path, args.resource) if args.resource is not None else find_model(path, args.find)
        for key, record in records.items():
            file, number = record[:2]
            value = '=' + record[2] if args.resource is not None else ''
            print(f'{file}:{number}: {key}{value}')
        return 0
    except (OSError, ValueError, IndexError, KeyError) as error:
        print(f"Service model files: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

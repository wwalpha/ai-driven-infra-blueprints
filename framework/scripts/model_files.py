"""Read YAML service Model values, locate their sources or extract a resource."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple
from validation_cache import memoized
from import_scope import scoped_read


MAX_LINES = 600
PART_LINES = 550
INDEX_HEADER = "# model-index: 1"
PART_PREFIX = "# part: "


def model_parts(path: Path, *, text: str | None = None) -> list[Path]:
    if path.is_symlink() or path.with_suffix("").is_symlink():
        raise ValueError(f"model files must not use symlinks: {path}")
    lines = (path.read_text(encoding="utf-8") if text is None else text).splitlines()
    indexed = bool(lines and lines[0] == INDEX_HEADER)
    if any(line.startswith(("# model-index:", PART_PREFIX)) for line in lines) and not indexed:
        raise ValueError(f"invalid model index: {path}")
    parts = []
    if indexed:
        if len(lines) > MAX_LINES or any(line.strip() and not line.startswith("#") for line in lines):
            raise ValueError(f"model index must contain comments only, at most {MAX_LINES} lines: {path}")
        for line in lines[1:]:
            if not line.startswith(PART_PREFIX):
                continue
            expected = f"{path.stem}/part-{len(parts) + 1:03d}.properties"
            if line.removeprefix(PART_PREFIX) != expected:
                raise ValueError(f"invalid or duplicate model part; expected {expected}: {path}")
            part = path.parent / expected
            if part.is_symlink() or not part.is_file():
                raise ValueError(f"missing or unsafe model part: {part}")
            parts.append(part)
        if not parts:
            raise ValueError(f"model index has no parts: {path}")
    extras = set(path.with_suffix("").rglob("*.properties")) - set(parts)
    if extras:
        raise ValueError(f"unlisted model parts: {sorted(str(part) for part in extras)}")
    return parts if indexed else [path]


class LoadedModel(NamedTuple):
    text: str
    values: dict[str, str]
    locations: dict[str, tuple[Path, int]]
    files: dict[Path, str]


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
        return LoadedModel(text, expanded.values, locations, expanded.files)


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
        text = read_model(path)
        from model_templates import load_expansion
        if args.trace is not None:
            import json
            expanded = load_expansion(path)
            print(json.dumps(expanded.provenance[args.trace], ensure_ascii=False))
            return 0
        loaded = load_model(path)
        keys = resource_keys(text, args.resource) if args.resource is not None else {k for k,v in loaded.values.items() if args.find in k + '=' + v}
        for key in loaded.values:
            if key in keys:
                file, number = loaded.locations[key]
                value = '=' + loaded.values[key] if args.resource is not None else ''
                print(f'{file}:{number}: {key}{value}')
        return 0
    except (OSError, ValueError, IndexError, KeyError) as error:
        print(f"Service model files: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

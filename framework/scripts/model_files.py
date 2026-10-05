"""Read one service model through its optional part index; split, locate or extract a resource."""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import re
import sys
from pathlib import Path
from typing import NamedTuple
from validation_cache import memoized
from task_contract import task_path, require_writable

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


@memoized
def load_model(path: Path) -> LoadedModel:
    """One validated parse with real part locations; immutable within input_scope."""
    from model_design import properties
    entrance = path.read_bytes().decode("utf-8")
    parts = model_parts(path, text=entrance)
    contents, files, locations = [], {path: entrance}, {}
    for part in parts:
        content = entrance if part == path else part.read_bytes().decode("utf-8")
        lines = content.splitlines()
        if part != path and (len(lines) > MAX_LINES or INDEX_HEADER in lines):
            raise ValueError(f"invalid or oversized model part: {part}")
        if part != parts[-1] and not content.endswith("\n"):
            raise ValueError(f"model part must end with a newline: {part}")
        files[part] = content
        contents.append(content)
        for number, line in enumerate(lines, 1):
            if line.strip() and not line.startswith("#"):
                key = line.partition("=")[0]
                if key in locations:
                    previous, previous_line = locations[key]
                    raise ValueError(f"invalid or duplicate model property: {part}:{number}: {key}; first at {previous}:{previous_line}")
                locations[key] = (part, number)
    text = "".join(contents)
    return LoadedModel(text, properties(text), locations, files)


def read_model(path: Path) -> str:
    return load_model(path).text


def resource_row_index(values: dict[str, str]) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Index legacy IDs as well as numbered resources using the existing prefix rule.

    Ambiguous overlapping legacy identities are rejected, never split at first '-'.
    """
    from model_design import entries
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


def model_file_contents(path: Path, text: str) -> dict[Path, str]:
    from model_design import properties
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
    if len(relative.parts) == 4:
        return base / relative.parent.with_suffix(".properties")
    return path


def resource_keys(text: str, selector: str) -> set[str]:
    """Select one resource's display group and service-wide context without rewriting values."""
    from model_design import LINK, entries, properties
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
    parser.add_argument("model", type=Path, help="Service entrance .properties file")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--split", action="store_true")
    operation.add_argument("--find", help="Find a property key or identifier without printing whole files")
    operation.add_argument("--resource", help="Read one exact resource number, logical ID or anchor, including its display group and service notes")
    args = parser.parse_args()
    try:
        path = args.model.absolute()
        text = read_model(path)
        parts = model_parts(path)
        if args.resource is not None:
            keys = resource_keys(text, args.resource)
            for part in parts:
                for number, line in enumerate(part.read_text(encoding="utf-8").splitlines(), 1):
                    if line.partition("=")[0] in keys:
                        print(f"{part}:{number}: {line}")
            return 0
        if args.find is not None:
            for part in parts:
                for number, line in enumerate(part.read_text(encoding="utf-8").splitlines(), 1):
                    if "=" in line and args.find in line:
                        print(f"{part}:{number}: {line.partition('=')[0]}")
            return 0
        # Splitting changes authoritative files only in an explicit design/migration scope.
        root = path.parents[3]
        if path.relative_to(root).parts[0] != "model" or len(path.relative_to(root).parts) != 4:
            raise ValueError("split input must be model/<environment>/<target>/<service>.properties")
        contract = task_path(root).read_text(encoding="utf-8")
        if not any(f"- Task type: `{kind}`" in contract.splitlines() for kind in ("design", "migration")):
            raise ValueError("splitting requires an explicit design or migration task")
        from validation_scope import active_scope
        from issue_gate import require_no_issues
        identity = tuple(path.relative_to(root / "model").with_suffix("").parts)
        scope = active_scope(root)
        if scope is not None and identity not in scope:
            raise ValueError("split service is outside active task validation scope")
        require_no_issues(root, {identity})
        output = model_file_contents(path, text)
        obsolete = set(parts) - output.keys() - {path}
        if "## Allowed paths\n" not in contract:
            raise ValueError("split task must declare Allowed paths")
        allowed = contract.split("## Allowed paths\n", 1)[1].split("\n## ", 1)[0]
        patterns = re.findall(r"^- `([^`]+)`$", allowed, re.MULTILINE)
        if any(not any(fnmatch.fnmatchcase(file.relative_to(root).as_posix(), pattern) for pattern in patterns)
               for file in set(output) | obsolete):
            raise ValueError("split output is outside active task Allowed paths")
        spec = importlib.util.spec_from_file_location("model_sync", Path(__file__).with_name("sync-model.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        require_writable(root, set(output) | obsolete)
        module.save_files(output)
        for part in obsolete:
            part.unlink()
        print(f"Service model split: PASS ({path}; {len(output)} files)")
        return 0
    except (OSError, ValueError, IndexError) as error:
        print(f"Service model files: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

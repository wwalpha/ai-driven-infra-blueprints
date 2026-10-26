"""Derived ownership/reference metadata, maintained by atomic Model publication."""

from contextlib import nullcontext

from utils.sealed_evidence import evidence_store, read_sealed, write_sealed

import model.change_scope as change_scope
import model.identity as identity
import model.importing.scope as import_scope
import model.sources as sources
from model.core import entries, structural_entries
from model.reference_nodes import nodes


def location(root):
    return evidence_store(root) / "model-dependencies.json"


def revision(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def inventory(root):
    result = {}
    for path in sorted((root / "model").rglob("*.properties")):
        sources.safe(root, path)
        result[path.relative_to(root).as_posix()] = revision(path)
    return result


def record(path, reads, *, quality=True):
    snapshot = sources.raw_model(path, reads)
    return snapshot_record(snapshot, quality=quality)


def reference_metadata(snapshot, *, strict=False):
    """Extract edges and retain incomplete references without running quality rules."""
    metadata = change_scope.metadata()
    cache = (
        metadata.setdefault("references", {})
        if metadata is not None
        and isinstance(snapshot.authoritative, sources.SnapshotValues)
        else {}
    )
    cache_key = id(snapshot.authoritative), strict
    if cache_key in cache:
        return cache[cache_key][1]
    links, logical, errors = set(), set(), {}
    for key, value in snapshot.authoritative.items():
        if key.startswith(("desired.row.", "desired.resource.")):
            diagnostics = []
            for token in identity.reference_tokens(value):
                try:
                    links.add(
                        "/".join(identity.parse_reference(token[0], snapshot.scope)[:3])
                    )
                except ValueError as error:
                    if strict:
                        raise
                    # Tokens already satisfy resource_link; only link_scope can reject them.
                    diagnostics.append(
                        {"message": str(error), "kind": "link", "outsideModel": True}
                    )
            # Raw snapshots already check declared JSON syntax; nodes distinguishes prose.
            logical.update(
                node.logical_id for node in nodes(value.strip("`"), errors=diagnostics)
            )
            if diagnostics and key.endswith(
                (".value", ".document", ".parentReference")
            ):
                errors[key] = diagnostics
        elif key.startswith("desired.reference.") and key.endswith(".producerScope"):
            links.add(value)
    result = links, logical, errors
    cache[cache_key] = snapshot.authoritative, result
    return result


def snapshot_record(snapshot, *, quality=True, errors=None):
    values, scope = snapshot.authoritative, snapshot.scope
    resources = [
        resource
        for _, resource in (entries if quality else structural_entries)(
            values, "desired.resource."
        )
    ]
    links, logical, diagnostics = reference_metadata(snapshot, strict=quality)
    if errors is not None:
        errors.update(diagnostics)
    return {
        "files": sorted(p.relative_to(scope.root).as_posix() for p in snapshot.files),
        "owners": [r["cfn-logicalId"] for r in resources if "cfn-logicalId" in r],
        "logical": [r["logicalId"] for r in resources if "logicalId" in r],
        "links": sorted(links),
        "typed": sorted(logical),
        "errors": diagnostics,
    }


def rebuild(root):
    """Explicit offline bootstrap; never called by Deploy or an observed writer."""
    root = root.resolve()
    with sources.publication_lock(root):
        before = inventory(root)
        reads = sources.FileReads()
        records = {
            path.relative_to(root).as_posix(): record(path, reads)
            for path in sources.model_paths(root, read_context=reads)
        }
        reads.verify()
        if inventory(root) != before:
            raise ValueError("Model dependency index inputs changed during build")
        write_sealed(
            root, location(root), {"version": 2, "files": before, "models": records}
        )
    return records


def load(root):
    root = change_scope.index_root(root)
    shared = sources.session_reads(root)
    with shared.lock if shared is not None else nullcontext():
        if shared is not None and shared.dependency_index is not None:
            return shared.dependency_index
        index = _load(root)
        if shared is not None:
            for key, snapshot in shared.models.items():
                if key[0] == "source":
                    verify_snapshot(index, snapshot, shared.revisions)
                    shared.index_checks[key] = snapshot.dependencies
            shared.dependency_index = index
        return index


def _load(root):
    path = location(root)
    if not path.is_file():
        raise ValueError(
            "Model dependency index missing; run offline before Deploy: "
            f"python framework/scripts/model/cli.py index --repository-root {root}"
        )
    index = read_sealed(root, path)
    validate(root, index)
    return index


def validate(root, index):
    if (
        not isinstance(index, dict)
        or index.get("version") != 2
        or not isinstance(index.get("files"), dict)
        or not isinstance(index.get("models"), dict)
    ):
        raise ValueError("invalid Model dependency index")
    for path, value in index["files"].items():
        if (
            not isinstance(path, str)
            or ".." in path.split("/")
            or not path.startswith("model/")
            or not isinstance(value, list)
            or len(value) != 5
            or any(type(item) is not int for item in value)
        ):
            raise ValueError("invalid Model dependency index file revision")
        sources.source_scope(root, root / path)
    entrances = {p for p in index["files"] if len(p.split("/")) == 4}
    if set(index["models"]) != entrances or any(
        not isinstance(entry, dict)
        or set(entry) != {"files", "owners", "logical", "links", "typed", "errors"}
        or any(
            not isinstance(items, list)
            or any(not isinstance(item, str) for item in items)
            or len(items) != len(set(items))
            for name, items in entry.items()
            if name != "errors"
        )
        or not valid_reference_errors(entry["errors"])
        or set(entry["files"])
        != {
            p
            for p in index["files"]
            if p == entrance or p.startswith(entrance.removesuffix(".properties") + "/")
        }
        for entrance, entry in index["models"].items()
    ):
        raise ValueError("Model dependency index has inconsistent source membership")


def valid_reference_errors(errors):
    return isinstance(errors, dict) and all(
        isinstance(key, str)
        and key.startswith(("desired.row.", "desired.resource."))
        and key.endswith((".value", ".document", ".parentReference"))
        and isinstance(diagnostics, list)
        and bool(diagnostics)
        and all(
            isinstance(error, dict)
            and isinstance(error.get("message"), str)
            and all(isinstance(field, str) for field in error)
            and all(
                type(value) is bool
                if field == "outsideModel"
                else isinstance(value, str)
                for field, value in error.items()
            )
            for error in diagnostics
        )
        for key, diagnostics in errors.items()
    )


def verify_snapshot(index, snapshot, revisions):
    """Check only a first-used service against the signed index, without disk reads."""
    relative = snapshot.scope.path.relative_to(snapshot.scope.root).as_posix()
    if index["models"].get(relative) != snapshot_record(snapshot) or any(
        index["files"].get(p.relative_to(snapshot.scope.root).as_posix())
        != revisions.get(p)
        for p in snapshot.files
    ):
        raise ValueError(
            "Model dependency index differs from checked Model: " + relative
        )


def update(root, changed, *, observed=False):
    """Called inside the Model transaction; an absent index stays absent until bootstrap."""
    if not location(root).is_file():
        return
    previous = load(root)
    index = {
        **previous,
        "files": dict(previous["files"]),
        "models": dict(previous["models"]),
    }
    scopes = {sources.source_scope(root, p).path for p in changed}
    reads = sources.FileReads()
    for path in changed:
        sources.safe(root, path)
        relative = path.relative_to(root).as_posix()
        if observed and relative not in index["files"]:
            raise ValueError(
                "observed Model is missing from dependency index: " + relative
            )
        if path.is_file():
            index["files"][relative] = revision(path)
        else:
            index["files"].pop(relative, None)
    for path in () if observed else scopes:
        relative = path.relative_to(root).as_posix()
        files = set(index["models"].get(relative, {}).get("files", ()))
        for changed_path in changed:
            if sources.source_scope(root, changed_path).path == path:
                changed_relative = changed_path.relative_to(root).as_posix()
                if changed_relative in index["files"]:
                    files.add(changed_relative)
                else:
                    files.discard(changed_relative)
        if path.is_file():
            entry = record(path, reads, quality=False)
            if set(entry["files"]) != files:
                raise ValueError(
                    "Model dependency index has inconsistent source membership"
                )
            index["models"][relative] = entry
        else:
            if files:
                raise ValueError("deleted Model still has indexed parts: " + relative)
            index["models"].pop(relative, None)
    if index == previous:
        return
    write_sealed(root, location(root), index)
    shared = sources.session_reads(root)
    if shared is not None:
        shared.dependency_index = index
        if not observed:
            shared.index_checks.clear()


def owners(root, environment, directory, identities):
    prefix = f"model/{environment}/{directory}/"
    return [
        root / path
        for path, entry in load(root)["models"].items()
        if path.startswith(prefix) and set(entry["owners"]) & set(identities)
    ]


def logical_models(root, environment, directory, logical, *, index=None):
    prefix = f"model/{environment}/{directory}/"
    return [
        sources.scope_for(root / path)
        for path, entry in (load(root) if index is None else index)["models"].items()
        if path.startswith(prefix) and logical in entry["logical"]
    ]


def consumers(root, scopes, identifiers, *, index=None):
    return [
        root / path
        for path, entry in (load(root) if index is None else index)["models"].items()
        if set(entry["links"]) & scopes
        or any(
            tuple(path.split("/")[1:3]) == identity[:2]
            and identity[-1] in entry["typed"]
            for identity in identifiers
        )
    ]


def change_snapshot(path, reads, metadata=None):
    metadata = metadata if metadata is not None else change_scope.metadata()
    snapshots = metadata.setdefault("snapshots", {}) if metadata is not None else {}
    if path not in snapshots:
        try:
            scope = sources.scope_for(path)
            with import_scope.read_consumers(
                {(scope.environment, scope.target, scope.service)}
            ):
                base = sources.edit_base(path, reads)
                # Text with no Model fields or reference tokens cannot declare an edge or owner.
                empty = not any(
                    "desired." in text or any(identity.reference_tokens(text))
                    for text in base.files.values()
                )
                snapshots[path] = base if empty else sources.raw_model(path, reads)
        except ValueError as error:
            raise ValueError(
                f"cannot read reference metadata: {path}: {error}"
            ) from error
    return snapshots[path]


def check_change_inventory(root, changed, *, reads=None):
    """Refresh only missing/stale reference metadata in this immutable read scope."""
    metadata = change_scope.metadata()
    if metadata is not None and root in metadata.get("indexes", {}):
        return metadata["indexes"][root]
    reads = reads or change_scope.inputs_for(root)[1] or sources.FileReads()
    primary = change_scope.index_root(root)
    previous = (
        read_sealed(primary, location(primary))
        if location(primary).is_file()
        else {"version": 2, "files": {}, "models": {}}
    )
    validate(primary, previous)
    current = inventory(root)
    # Register membership with the same input recorder used by publication.
    paths = sources.model_paths(root, read_context=reads)
    index = {"version": 2, "files": current, "models": {}}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        scope = sources.scope_for(path)
        entry = previous["models"].get(relative)
        files = {
            p
            for p in current
            if p == relative or p.startswith(relative.removesuffix(".properties") + "/")
        }
        if (
            entry is None
            or (scope.environment, scope.target, scope.service) in changed
            or files != set(entry["files"])
            or any(current[p] != previous["files"].get(p) for p in files)
        ):
            snapshot = change_snapshot(path, reads, metadata)
            entry = snapshot_record(snapshot, quality=False)
        if metadata is not None:
            metadata.setdefault("reference_errors", {})[path] = entry["errors"]
        index["models"][relative] = entry
    if metadata is not None:
        metadata.setdefault("indexes", {})[root] = index
    return index


def incomplete_reference_matches(scope, error, producer, logical=None):
    """Limit unknown typed targets to their lookup scope; outside links have no edge."""
    if error.get("outsideModel"):
        return False
    if producer[:2] != (scope.environment, scope.target):
        return False
    return (
        logical is None
        or not error.get("targetLogicalId")
        or error["targetLogicalId"] == logical
    )


def change_consumers(root, scopes, identifiers, changed, *, reads=None):
    metadata = change_scope.metadata()
    metadata = metadata if metadata is not None else {}
    with change_scope.change_reads(root, reads, metadata=metadata):
        index = check_change_inventory(root, changed, reads=reads)
    selected = set(consumers(root, scopes, identifiers, index=index))
    targets = (
        {
            (producer, logical)
            for value in scopes
            for producer in [tuple(value.split("/"))]
            for environment, target, logical in identifiers
            if producer[:2] == (environment, target)
        }
        if identifiers
        else {(tuple(value.split("/")), None) for value in scopes}
    )
    for path, fields in metadata.get("reference_errors", {}).items():
        scope = sources.scope_for(path)
        if any(
            incomplete_reference_matches(scope, error, producer, logical)
            for errors in fields.values()
            for error in errors
            for producer, logical in targets
        ):
            selected.add(path)
    return sorted(selected)

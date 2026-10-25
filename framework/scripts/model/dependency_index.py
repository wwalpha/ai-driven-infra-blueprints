"""Derived ownership/reference metadata, maintained by atomic Model publication."""

from contextlib import nullcontext

from utils.sealed_evidence import evidence_store, read_sealed, write_sealed

import model.identity as identity
import model.sources as sources
from model.core import entries
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


def record(path, reads):
    snapshot = sources.raw_model(path, reads)
    return snapshot_record(snapshot)


def snapshot_record(snapshot):
    values, scope = snapshot.authoritative, snapshot.scope
    resources = [resource for _, resource in entries(values, "desired.resource.")]
    links, logical = set(), set()
    for key, value in values.items():
        if key.startswith(("desired.row.", "desired.resource.")):
            for token in identity.reference_tokens(value):
                links.add("/".join(identity.parse_reference(token[0], scope)[:3]))
            for node in nodes(value.strip("`"), errors=[]):
                logical.add(node.logical_id)
        elif key.startswith("desired.reference.") and key.endswith(".producerScope"):
            links.add(value)
    return {
        "files": sorted(p.relative_to(scope.root).as_posix() for p in snapshot.files),
        "owners": [r["cfn-logicalId"] for r in resources if "cfn-logicalId" in r],
        "logical": [r["logicalId"] for r in resources if "logicalId" in r],
        "links": sorted(links),
        "typed": sorted(logical),
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
            root, location(root), {"version": 1, "files": before, "models": records}
        )
    return records


def load(root):
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
            "Model dependency index missing; run model/cli.py index offline before Deploy"
        )
    index = read_sealed(root, path)
    validate(root, index)
    return index


def validate(root, index):
    if (
        not isinstance(index, dict)
        or index.get("version") != 1
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
        or set(entry) != {"files", "owners", "logical", "links", "typed"}
        or any(
            not isinstance(items, list)
            or any(not isinstance(item, str) for item in items)
            or len(items) != len(set(items))
            for items in entry.values()
        )
        or set(entry["files"])
        != {
            p
            for p in index["files"]
            if p == entrance or p.startswith(entrance.removesuffix(".properties") + "/")
        }
        for entrance, entry in index["models"].items()
    ):
        raise ValueError("Model dependency index has inconsistent source membership")


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
            entry = record(path, reads)
            if set(entry["files"]) != files:
                raise ValueError(
                    "Model dependency index has inconsistent source membership"
                )
            index["models"][relative] = entry
        else:
            if files:
                raise ValueError("deleted Model still has indexed parts: " + relative)
            index["models"].pop(relative, None)
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


def logical_models(root, environment, directory, logical):
    prefix = f"model/{environment}/{directory}/"
    return [
        sources.scope_for(root / path)
        for path, entry in load(root)["models"].items()
        if path.startswith(prefix) and logical in entry["logical"]
    ]


def consumers(root, scopes, identifiers):
    return [
        root / path
        for path, entry in load(root)["models"].items()
        if set(entry["links"]) & scopes
        or any(
            tuple(path.split("/")[1:3]) == identity[:2]
            and identity[-1] in entry["typed"]
            for identity in identifiers
        )
    ]

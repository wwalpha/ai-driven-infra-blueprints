"""Derived ownership/reference metadata, maintained by atomic Model publication."""

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
    path = location(root)
    if not path.is_file():
        raise ValueError(
            "Model dependency index missing; run model/cli.py index offline before Deploy"
        )
    index = read_sealed(root, path)
    if index.get("version") != 1 or index.get("files") != inventory(root):
        raise ValueError(
            "Model dependency index stale; rebuild offline before observed synchronization"
        )
    entrances = {p for p in index["files"] if len(p.split("/")) == 4}
    if set(index.get("models", {})) != entrances or any(
        set(entry["files"])
        != {
            p
            for p in index["files"]
            if p == entrance or p.startswith(entrance.removesuffix(".properties") + "/")
        }
        for entrance, entry in index["models"].items()
    ):
        raise ValueError("Model dependency index has inconsistent source membership")
    return index


def update(root, changed, *, observed=False):
    """Called inside the Model transaction; an absent index stays absent until bootstrap."""
    if not location(root).is_file():
        return
    try:
        index = read_sealed(root, location(root))
    except (ValueError, OSError):
        if observed:
            raise
        return  # An invalid derived index must not prevent ordinary Model corrections.
    if index.get("version") != 1:
        if observed:
            raise ValueError("unsupported Model dependency index")
        return
    current = inventory(root)
    untouched = index["files"].keys() | current.keys()
    if any(
        index["files"].get(p) != current.get(p)
        for p in untouched
        if root / p not in changed
    ):
        if observed:
            raise ValueError("Model dependency index changed outside publication")
        return
    scopes = {sources.source_scope(root, p).path for p in changed}
    reads = sources.FileReads()
    for path in () if observed else scopes:
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            index["models"][relative] = record(path, reads)
        else:
            index["models"].pop(relative, None)
    index["files"] = current
    write_sealed(root, location(root), index)


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

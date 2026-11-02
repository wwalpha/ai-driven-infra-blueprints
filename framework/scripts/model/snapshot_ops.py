"""Purpose-specific transformations of existing Model snapshots."""

from copy import deepcopy
from dataclasses import replace
from types import MappingProxyType

from model.core import structural_entries
from model.sources import Scope, observed_snapshot


def rebase_snapshot(snapshot, source_root, root):
    if root == source_root:
        return snapshot
    result = {}
    for field in ("documents", "files", "dependencies"):
        result[field] = MappingProxyType(
            {
                root / p.relative_to(source_root)
                if p.is_relative_to(source_root)
                else p: value
                for p, value in getattr(snapshot, field).items()
            }
        )
    result["locations"] = MappingProxyType(
        {
            key: (root / path.relative_to(source_root), line)
            for key, (path, line) in snapshot.locations.items()
        }
    )
    result["parts"] = tuple(root / p.relative_to(source_root) for p in snapshot.parts)
    return snapshot._replace(
        scope=Scope(
            root,
            snapshot.scope.environment,
            snapshot.scope.target,
            snapshot.scope.service,
        ),
        **result,
    )


def reference_snapshot(snapshot, keys):
    values = snapshot.authoritative
    selected_rows = {
        key.split(".")[2] for key in keys if key.startswith("desired.row.")
    }
    selected = {
        key: value
        for key, value in values.items()
        if (
            not key.startswith(("desired.row.", "observed.row.", "desired.reference."))
            and not key.endswith(".parentReference")
            or key.startswith(("desired.row.", "observed.row."))
            and key.split(".")[2] in selected_rows
            or key in keys
        )
    }
    for identity, spec in structural_entries(values, "desired.reference."):
        if spec.get("consumerKey") in keys:
            selected.update(
                (key, value)
                for key, value in values.items()
                if key.startswith(f"desired.reference.{identity}.")
            )
    return snapshot._replace(authoritative=selected)


def update_observed_snapshot(snapshot, outputs):
    candidate = observed_snapshot(snapshot, outputs)
    dependencies = {
        **candidate.dependencies,
        **{
            p: text.encode("utf-8")
            for p, text in outputs.items()
            if p in candidate.dependencies
        },
    }
    return candidate._replace(dependencies=MappingProxyType(dependencies))


def copy_snapshot_warnings(snapshot):
    """Fork diagnostic dictionaries while retaining fixed inputs and authority."""
    return replace(snapshot, warnings=deepcopy(snapshot.warnings))

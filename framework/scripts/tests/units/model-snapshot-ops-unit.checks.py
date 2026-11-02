"""Compatibility checks for purpose-specific snapshot transformations."""

import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.model_cache import RunModels
from model.format import patch
from model.sources import raw_model
from support.model_v2_fixtures import format_fixture
from validation.change import reference_inputs

from model import (
    copy_snapshot_warnings,
    rebase_snapshot,
    reference_snapshot,
    update_observed_snapshot,
)


def check_rebase_paths_identity_and_errors(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    scope, _ = format_fixture(root)
    snapshot = raw_model(scope)
    external = tmp_path / "external"
    original = replace(
        snapshot,
        dependencies=MappingProxyType({scope.path: b"model", external: b"external"}),
    )
    new_root = tmp_path / "stage"
    moved = rebase_snapshot(original, root, new_root)
    assert rebase_snapshot(original, root, root) is original
    assert RunModels(root, {}).rebased(original, new_root) == moved
    assert moved.scope == replace(scope, root=new_root)
    assert (
        moved.authoritative is original.authoritative
        and moved.values is original.values
    )
    for name in ("documents", "files", "dependencies"):
        before = getattr(original, name)
        expected = {
            (new_root / p.relative_to(root) if p.is_relative_to(root) else p): v
            for p, v in before.items()
        }
        assert dict(getattr(moved, name)) == expected
        with pytest.raises(TypeError):
            getattr(moved, name)[external] = None
    assert dict(moved.locations) == {
        k: (new_root / p.relative_to(root), line)
        for k, (p, line) in original.locations.items()
    }
    assert moved.parts == tuple(new_root / p.relative_to(root) for p in original.parts)
    assert dict(original.dependencies) == {scope.path: b"model", external: b"external"}
    broken = replace(original, locations={"bad": (external, 1)})
    with pytest.raises(ValueError):
        rebase_snapshot(broken, root, new_root)


def check_reference_selection_and_source_unchanged(tmp_path):
    scope, values = format_fixture(tmp_path)
    snapshot = raw_model(scope)
    values.update(
        {
            "desired.row.007-002.parentReference": "exclude",
            "desired.row.007-003.value": "exclude",
            "observed.row.007-003.value": "exclude",
            "desired.reference.a.consumerKey": "desired.row.007-001.value",
            "desired.reference.a.text": "keep",
            "desired.reference.b.consumerKey": "desired.row.007-003.value",
            "desired.reference.b.text": "exclude",
            "desired.stack.001.name": "context",
        }
    )
    snapshot = replace(snapshot, authoritative=values)
    selected = reference_snapshot(snapshot, {"desired.row.007-001.value"})
    expected = {
        key: value
        for key, value in values.items()
        if not key.startswith(("desired.row.", "observed.row.", "desired.reference."))
    }
    expected.update(
        {
            key: value
            for key, value in values.items()
            if key.startswith(
                (
                    "desired.row.007-001.",
                    "observed.row.007-001.",
                    "desired.reference.a.",
                )
            )
        }
    )
    assert dict(selected.authoritative) == expected
    assert reference_inputs(snapshot, {"desired.row.007-001.value"}) == selected
    assert dict(snapshot.authoritative) == values
    selected_parent = reference_snapshot(
        snapshot, {"desired.row.007-002.parentReference"}
    )
    assert (
        selected_parent.authoritative["desired.row.007-002.parentReference"]
        == "exclude"
    )
    broken = replace(
        snapshot, authoritative={**values, "desired.reference.bad": "invalid"}
    )
    with pytest.raises(ValueError, match="invalid model entry"):
        reference_snapshot(broken, {"desired.row.007-001.value"})


def check_observed_dependencies_and_error_compatibility(tmp_path):
    scope, values = format_fixture(tmp_path)
    snapshot = raw_model(scope)
    extra = tmp_path / "dependency"
    snapshot = replace(
        snapshot,
        dependencies=MappingProxyType(
            {scope.path: scope.path.read_bytes(), extra: b"old"}
        ),
    )
    text = patch(snapshot.documents[scope.path], {"observed.row.007-001.value": "new"})
    updated = update_observed_snapshot(snapshot, {scope.path: text, extra: "updated"})
    assert updated.authoritative["observed.row.007-001.value"] == "new"
    assert dict(updated.dependencies) == {scope.path: text.encode(), extra: b"updated"}
    assert snapshot.authoritative == values
    assert snapshot.dependencies[extra] == b"old"
    assert updated.files[scope.path] == text
    with pytest.raises(TypeError):
        updated.dependencies[extra] = b"bad"
    invalid = patch(
        snapshot.documents[scope.path], {"desired.row.007-001.comment": "changed"}
    )
    with pytest.raises(ValueError):
        update_observed_snapshot(snapshot, {scope.path: invalid})


def check_warning_fork_preserves_inputs_and_isolates_diagnostics(tmp_path):
    scope, _ = format_fixture(tmp_path)
    snapshot = replace(raw_model(scope), warnings=({"details": ["original"]},))
    fork = copy_snapshot_warnings(snapshot)
    assert fork == snapshot and fork is not snapshot
    assert fork.dependencies is snapshot.dependencies
    assert fork.authoritative is snapshot.authoritative
    fork.warnings[0]["details"].append("local")
    assert snapshot.warnings == ({"details": ["original"]},)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))

"""Strict Issues artifact input boundary."""

import hashlib
import json
from copy import deepcopy

import pytest
from issues.cli import main
from issues.reader import read_review_json, read_scan_artifact
from issues.review_progress import ReviewController
from support.issues_scan_fixtures import snapshot_artifact


def test_scan_reader_integrity_and_raw_digest(tmp_path):
    data = snapshot_artifact(tmp_path / "repository")
    path = tmp_path / "scan.json"
    for raw in (json.dumps(data).encode(), json.dumps(data, indent=2).encode()):
        path.write_bytes(raw)
        loaded = read_scan_artifact(path)
        assert loaded.artifact == data
        assert loaded.raw_sha256 == hashlib.sha256(raw).hexdigest()
    broken = deepcopy(data)
    broken["overview"]["record_count"] = 1
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError):
        read_scan_artifact(path)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b'{"version":6,"version":6}',
        b'{"secret-marker":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e999}',
        b"\xff",
        b"[" * 2000,
    ],
)
def test_strict_rejection_does_not_echo_input(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError) as error:
        read_scan_artifact(path)
    assert "secret-marker" not in str(error.value)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("version", 6.0, "version"),
        ("version", True, "version"),
        ("version", 7, "version"),
        ("naming_context", [], "naming_context"),
        ("record_meta", None, "record_meta"),
    ],
)
def test_scan_fields(tmp_path, field, value, message):
    data = snapshot_artifact(tmp_path / "repository")
    if field == "record_meta":
        del data[field]
    else:
        data[field] = value
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_scan_artifact(path)


def test_review_json_strict(tmp_path):
    path = tmp_path / "review.json"
    path.write_text('{"x":1,"x":2}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_review_json(path)


def test_nested_types(tmp_path):
    data = snapshot_artifact(tmp_path / "repository")
    path = tmp_path / "scan.json"
    data["overview"]["records"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="overview.records"):
        read_scan_artifact(path)
    data = snapshot_artifact(tmp_path / "repository")
    data["iac_issues"] = [{"members": "secret-marker"}]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="iac_issues.members"):
        read_scan_artifact(path)


def test_invalid_scan_all_cli_entrypoints_preserve_files(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repository"
    root.mkdir()
    artifact = tmp_path / "scan.json"
    artifact.write_bytes(b'{"secret-marker":NaN}')
    state = tmp_path / "checkpoint.json"
    state.write_text("checkpoint", encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    for args in (
        ["detail", "--artifact", str(artifact), "--section", "ordinary"],
        ["save", "--artifact", str(artifact), "--review", str(review)],
        ["review", "init", "--artifact", str(artifact), "--state", str(state)],
    ):
        monkeypatch.setattr(
            "sys.argv", ["issues_scan.py", "--repository-root", str(root), *args]
        )
        assert main() == 2
        captured = capsys.readouterr()
        assert "secret-marker" not in captured.out + captured.err
        assert "Traceback" not in captured.err
        assert state.read_text(encoding="utf-8") == "checkpoint"
        assert list(root.iterdir()) == []


def test_checkpoint_rejects_changed_raw_bytes(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    data = snapshot_artifact(root)
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    state = tmp_path / "state.json"
    ReviewController(root, path, state).initialize()
    original = state.read_bytes()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(ValueError):
        ReviewController(root, path, state).initialize()
    assert state.read_bytes() == original

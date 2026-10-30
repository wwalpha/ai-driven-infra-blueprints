"""Strict Issues artifact input boundary."""

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issues.cli import main
from issues.reader import read_review_json, read_scan_artifact
from issues.review import IncompleteNamingScan
from issues.review_progress import ReviewController
from support.issues_scan_fixtures import snapshot_artifact, stamp_naming_scan
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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
    with pytest.raises(ValueError, match=r"iac_issues\[\].members"):
        read_scan_artifact(path)


@pytest.mark.parametrize(
    "collection,field",
    [
        ("service_results", "service"),
        ("service_results", "status"),
        ("record_meta", "record_id"),
        ("record_meta", "issue_id"),
        ("record_meta", "category"),
        ("iac", "service"),
        ("iac", "category"),
        ("iac_issues", "id"),
        ("iac_issues", "category"),
        ("iac_issues", "members"),
        ("iac_issues", "compact"),
        ("iac_issues", "compact.records"),
    ],
)
@pytest.mark.parametrize("missing", [True, False])
def test_required_nested_fields_rejected_everywhere(
    tmp_path, monkeypatch, capsys, collection, field, missing
):
    root = tmp_path / "repository"
    root.mkdir()
    record = dict(
        category="difference",
        service="s3",
        resource="1",
        property="S3.Bucket.X",
        reason="value mismatch",
        desired="a",
        actual="b",
        stack="S",
        iac={"path": "template.yaml"},
    )
    data = snapshot_artifact(root, records=[record])
    parent = data[collection][0]
    if field == "compact.records":
        parent = parent["compact"]
        key = "records"
    else:
        key = field
    if missing:
        del parent[key]
    else:
        parent[key] = (
            {"secret-marker-key": "secret-marker-value"}
            if key == "members"
            else ["secret-marker-value"]
        )
    data["secret-marker-key"] = "secret-marker-value"
    artifact = tmp_path / "scan.json"
    artifact.write_text(json.dumps(data), encoding="utf-8")
    state = tmp_path / "checkpoint.json"
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    files = [state, root / "issues.md", root / "iac-issues.md", root / "task.md"]
    for path in files:
        path.write_text("original", encoding="utf-8")
    before = {path: path.read_bytes() for path in files}
    diagnostic = f"{collection}[].{field}"
    kind = "missing required field" if missing else "invalid type at"
    with pytest.raises(ValueError) as error:
        read_scan_artifact(artifact)
    assert str(error.value) == f"Scan artifact: {kind} {diagnostic}"
    for args in (
        ["detail", "--artifact", str(artifact), "--section", "iac"],
        ["save", "--artifact", str(artifact), "--review", str(review)],
        ["review", "init", "--artifact", str(artifact), "--state", str(state)],
    ):
        monkeypatch.setattr(
            "sys.argv", ["issues_scan.py", "--repository-root", str(root), *args]
        )
        assert main() == 2
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert f"Scan artifact: {kind} {diagnostic}" in output
        assert "secret-marker" not in output and "Traceback" not in output
        assert {path: path.read_bytes() for path in files} == before


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


@pytest.mark.parametrize(
    "fault,diagnostic",
    [
        ("context", "invalid naming_context_id"),
        ("missing", "invalid or missing decision"),
        ("type", "invalid or missing decision"),
        ("item", "Naming item context ID mismatch"),
        ("evidence", "Naming decision does not match Scan evidence"),
    ],
)
def test_naming_diagnostics_all_cli_entrypoints_preserve_files(
    tmp_path, monkeypatch, capsys, fault, diagnostic
):
    root = tmp_path / "repository"
    root.mkdir()
    data = snapshot_artifact(root)
    data["naming"]["names"] = [
        dict(
            id="name-1",
            service="s3",
            resource="1",
            resourceType="S3.Bucket",
            property="S3.Bucket.BucketName",
            value="`bucket`",
            resourceMode="CREATE",
        )
    ]
    stamp_naming_scan(data)
    name = data["naming"]["names"][0]
    if fault == "context":
        data["naming_context_id"] = "secret-marker"
    elif fault == "missing":
        del name["decision"]
    elif fault == "type":
        name["decision"] = "secret-marker"
    elif fault == "item":
        name["naming_context_id"] = "secret-marker"
    else:
        name["decision"]["status"] = "secret-marker"
    artifact = tmp_path / "scan.json"
    artifact.write_text(json.dumps(data), encoding="utf-8")
    state = tmp_path / "checkpoint.json"
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    files = [state, root / "issues.md", root / "iac-issues.md", root / "task.md"]
    for path in files:
        path.write_text("original", encoding="utf-8")
    before = {path: path.read_bytes() for path in files}
    for args in (
        ["detail", "--artifact", str(artifact), "--section", "naming"],
        ["save", "--artifact", str(artifact), "--review", str(review)],
        ["review", "status", "--artifact", str(artifact), "--state", str(state)],
    ):
        monkeypatch.setattr(
            "sys.argv", ["issues_scan.py", "--repository-root", str(root), *args]
        )
        assert main() == 2
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "incomplete Naming Scan" in output
        assert diagnostic in output
        assert "rescan and Review" in output
        assert "secret-marker" not in output
        assert "Traceback" not in output
        assert {path: path.read_bytes() for path in files} == before


@pytest.mark.parametrize(
    "error",
    [
        ValueError("secret-marker"),
        IncompleteNamingScan(
            "incomplete Naming Scan: secret-marker; explicit rescan and Review required"
        ),
    ],
)
def test_unknown_validation_exception_is_sanitized(tmp_path, monkeypatch, error):
    data = snapshot_artifact(tmp_path / "repository")
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(
        "issues.reader.validate_artifact", lambda artifact: (_ for _ in ()).throw(error)
    )
    with pytest.raises(
        ValueError, match="^Scan artifact: invalid structure or integrity$"
    ):
        read_scan_artifact(path)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "nan",
        "infinity",
        "overflow",
        "nonobject",
        "version",
        "missing",
        "nested",
    ],
)
def test_invalid_inputs_do_not_leak_at_any_entrypoint(
    tmp_path, monkeypatch, capsys, fault
):
    root = tmp_path / "repository"
    root.mkdir()
    data = snapshot_artifact(root)
    data["secret-marker-key"] = "secret-marker-value"
    if fault == "version":
        data["version"] = "secret-marker-value"
    elif fault == "missing":
        del data["record_meta"]
    elif fault == "nested":
        data["overview"]["records"] = {"secret-marker-key": "secret-marker-value"}
    raw = json.dumps(data)
    if fault == "duplicate":
        raw = '{"secret-marker-key":1,"secret-marker-key":2}'
    elif fault in {"nan", "infinity", "overflow"}:
        raw = (
            '{"secret-marker-key":'
            + {"nan": "NaN", "infinity": "Infinity", "overflow": "1e999"}[fault]
            + "}"
        )
    elif fault == "nonobject":
        raw = '["secret-marker-value"]'
    artifact = tmp_path / "scan.json"
    artifact.write_text(raw, encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("original", encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    for args in (
        ["detail", "--artifact", str(artifact), "--section", "naming"],
        ["save", "--artifact", str(artifact), "--review", str(review)],
        ["review", "status", "--artifact", str(artifact), "--state", str(state)],
    ):
        monkeypatch.setattr(
            "sys.argv", ["issues_scan.py", "--repository-root", str(root), *args]
        )
        assert main() == 2
        captured = capsys.readouterr()
        assert "secret-marker" not in captured.out + captured.err
        assert "Traceback" not in captured.out + captured.err
        assert state.read_text(encoding="utf-8") == "original"
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


if __name__ == "__main__":
    raise SystemExit(run(__file__))
